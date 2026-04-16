try:
    from PyQt5 import QtWidgets, QtCore
except Exception:
    QtWidgets = None
    QtCore = None

from typing import Any, Dict, List
import queue
import threading
import json
import re
import concurrent.futures
import config_loader


def create_gui_pyqt(config_path: str) -> None:
    if QtWidgets is None:
        print("PyQt5 未安装。请通过 'pip install PyQt5' 安装后重试。")
        return

    # delay-import heavy application helpers to avoid circular import at module import time
    from map_poi_fetcher import (
        ensure_region_data,
        fetch_amap_subdistrict,
        get_task_area_summary,
        run_task,
        run_tasks,
        # log helpers
        load_logs,
        export_logs,
        PROVIDER_DISPLAY,
    )

    app = QtWidgets.QApplication([])
    win = QtWidgets.QMainWindow()
    win.setWindowTitle("POI 任务调度器 (PyQt5)")
    central = QtWidgets.QWidget()
    win.setCentralWidget(central)
    layout = QtWidgets.QVBoxLayout(central)

    # top: config path and save/load
    top_h = QtWidgets.QHBoxLayout()
    config_edit = QtWidgets.QLineEdit(config_path)
    top_h.addWidget(QtWidgets.QLabel("配置文件："))
    top_h.addWidget(config_edit)
    btn_load = QtWidgets.QPushButton("刷新配置")
    btn_save = QtWidgets.QPushButton("保存配置")
    top_h.addWidget(btn_load)
    top_h.addWidget(btn_save)
    layout.addLayout(top_h)

    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    layout.addWidget(splitter, 1)

    # left: task list and buttons
    left_w = QtWidgets.QWidget()
    left_l = QtWidgets.QVBoxLayout(left_w)
    task_list = QtWidgets.QListWidget()
    left_l.addWidget(task_list)
    hb = QtWidgets.QHBoxLayout()
    btn_add = QtWidgets.QPushButton("新增任务")
    btn_delete = QtWidgets.QPushButton("删除任务")
    btn_run = QtWidgets.QPushButton("运行选中任务")
    btn_run_all = QtWidgets.QPushButton("运行全部任务")
    btn_stop = QtWidgets.QPushButton("停止任务")
    btn_stop.setEnabled(False)
    hb.addWidget(btn_add)
    hb.addWidget(btn_delete)
    hb.addWidget(btn_run)
    hb.addWidget(btn_run_all)
    hb.addWidget(btn_stop)
    left_l.addLayout(hb)
    splitter.addWidget(left_w)

    # right: task editor + global settings + logs
    right_w = QtWidgets.QWidget()
    right_l = QtWidgets.QVBoxLayout(right_w)

    form = QtWidgets.QFormLayout()
    task_name_edit = QtWidgets.QLineEdit()
    form.addRow("任务名称：", task_name_edit)
    area_type_combo = QtWidgets.QComboBox()
    # 显示为中文/友好文本，内部使用映射保存为 'admin' / 'bbox'
    area_type_combo.addItems(["行政区", "BBox"])
    type_display_to_value = {"行政区": "admin", "BBox": "bbox"}
    type_value_to_display = {v: k for k, v in type_display_to_value.items()}
    form.addRow("选择模式：", area_type_combo)
    country_label = QtWidgets.QLabel("中华人民共和国")
    form.addRow("国家：", country_label)
    province_combo = QtWidgets.QComboBox()
    city_combo = QtWidgets.QComboBox()
    county_combo = QtWidgets.QComboBox()
    form.addRow("省份：", province_combo)
    form.addRow("城市：", city_combo)
    form.addRow("区/县：", county_combo)

    # Region tree: allow multi-select of provinces/cities/counties with parent-child checkbox behavior
    region_tree = QtWidgets.QTreeWidget()
    region_tree.setHeaderLabels(["地区 (多选)"])
    region_tree.setColumnCount(1)
    region_tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    region_tree.setUniformRowHeights(True)
    form.addRow("地区选择：", region_tree)

    bbox_left = QtWidgets.QLineEdit()
    bbox_bottom = QtWidgets.QLineEdit()
    bbox_right = QtWidgets.QLineEdit()
    bbox_top = QtWidgets.QLineEdit()
    form.addRow("BBox 左：", bbox_left)
    form.addRow("BBox 下：", bbox_bottom)
    form.addRow("BBox 右：", bbox_right)
    form.addRow("BBox 上：", bbox_top)

    save_task_btn = QtWidgets.QPushButton("保存任务")
    form.addRow(save_task_btn)

    def update_mode_ui():
        cur = area_type_combo.currentText()
        mode_val = type_display_to_value.get(cur, cur)
        is_admin = (mode_val == "admin")
        province_combo.setEnabled(is_admin)
        city_combo.setEnabled(is_admin)
        county_combo.setEnabled(is_admin)
        bbox_left.setEnabled(not is_admin)
        bbox_bottom.setEnabled(not is_admin)
        bbox_right.setEnabled(not is_admin)
        bbox_top.setEnabled(not is_admin)

    # Use a tab widget: Task 编辑页 和 全局设置页
    tabs = QtWidgets.QTabWidget()
    tab_task = QtWidgets.QWidget()
    tab_task_l = QtWidgets.QVBoxLayout(tab_task)
    tab_task_l.addLayout(form)
    tabs.addTab(tab_task, "任务编辑")

    # Global settings tab
    tab_global = QtWidgets.QWidget()
    tab_global_l = QtWidgets.QVBoxLayout(tab_global)
    glob_group = QtWidgets.QGroupBox("全局设置")
    glob_layout = QtWidgets.QFormLayout(glob_group)
    provider_combo = QtWidgets.QComboBox()
    # display Chinese names, map to internal provider keys
    provider_display_to_value = {"百度": "baidu", "高德": "gaode", "天地图": "tianditu"}
    provider_value_to_display = {v: k for k, v in provider_display_to_value.items()}
    provider_combo.addItems(list(provider_display_to_value.keys()))
    # resources: store as comma-separated keywords by default, but show a persistent JSON example below
    example_resources = ["gas_station", "service_area", "hospital", "repair_factory"]
    resources_edit = QtWidgets.QLineEdit(json.dumps(example_resources, ensure_ascii=False))
    resources_edit.setToolTip("输入资源关键字，支持 JSON 列表或逗号分隔的关键字；示例已填入并可复制")
    example_label = QtWidgets.QLabel(json.dumps(example_resources, ensure_ascii=False))
    # allow users to select/copy the example text
    try:
        example_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    except Exception:
        pass
    export_combo = QtWidgets.QComboBox()
    export_combo.addItems(["csv", "json", "excel"])
    concurrency_spin = QtWidgets.QSpinBox(); concurrency_spin.setRange(1, 32)
    province_expand_concurrency_spin = QtWidgets.QSpinBox(); province_expand_concurrency_spin.setRange(1, 64)
    province_expand_delay_spin = QtWidgets.QDoubleSpinBox(); province_expand_delay_spin.setRange(0.0, 60.0); province_expand_delay_spin.setSingleStep(0.1)
    page_spin = QtWidgets.QSpinBox(); page_spin.setRange(1, 100)
    check_interval_spin = QtWidgets.QSpinBox(); check_interval_spin.setRange(1, 1440)
    incr_check = QtWidgets.QCheckBox()
    sched_spin = QtWidgets.QSpinBox(); sched_spin.setRange(1, 365)
    glob_layout.addRow("提供商：", provider_combo)
    glob_layout.addRow("资源：", resources_edit)
    glob_layout.addRow("资源示例(JSON)：", example_label)
    glob_layout.addRow("导出格式：", export_combo)
    # Note: concurrency, paging and scheduler options moved to Advanced tab
    adv_note = QtWidgets.QLabel("并发/分页/调度设置已移至“高级设置”选项卡。点击高级设置进行配置。")
    try:
        adv_note.setWordWrap(True)
    except Exception:
        pass
    glob_layout.addRow(adv_note)
    tab_global_l.addWidget(glob_group)
    # Resources tree for multi-select resource types (parent select -> select children)
    resources_tree = QtWidgets.QTreeWidget()
    resources_tree.setHeaderLabels(["资源 (多选)"])
    resources_tree.setColumnCount(1)
    resources_tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    try:
        resources_tree.setUniformRowHeights(True)
    except Exception:
        pass
    tab_global_l.addWidget(QtWidgets.QLabel("资源树（若需要可直接勾选）"))
    tab_global_l.addWidget(resources_tree)
    # add explicit save button inside global tab
    btn_save_global = QtWidgets.QPushButton("保存全局设置")
    tab_global_l.addWidget(btn_save_global)
    # advanced save button will be created below and wired to the same save logic
    tabs.addTab(tab_global, "全局设置")

    # Advanced settings tab (for concurrency, paging and scheduler settings)
    tab_advanced = QtWidgets.QWidget()
    tab_adv_l = QtWidgets.QVBoxLayout(tab_advanced)
    adv_group = QtWidgets.QGroupBox("高级设置")
    adv_layout = QtWidgets.QFormLayout(adv_group)
    adv_layout.addRow("并发数：", concurrency_spin)
    adv_layout.addRow("省展开并发数：", province_expand_concurrency_spin)
    adv_layout.addRow("省展开延迟(秒)：", province_expand_delay_spin)
    adv_layout.addRow("分页限制：", page_spin)
    adv_layout.addRow("调度检查间隔(分钟)：", check_interval_spin)
    adv_layout.addRow("调度间隔(天)：", sched_spin)
    adv_layout.addRow("增量去重：", incr_check)
    tab_adv_l.addWidget(adv_group)
    btn_save_advanced = QtWidgets.QPushButton("保存高级设置")
    tab_adv_l.addWidget(btn_save_advanced)
    tabs.addTab(tab_advanced, "高级设置")

    right_l.addWidget(tabs)

    # logs
    logs = QtWidgets.QTextEdit(); logs.setReadOnly(True)
    right_l.addWidget(QtWidgets.QLabel("日志输出（实时摘要）"))
    right_l.addWidget(logs, 1)

    splitter.addWidget(right_w)

    # load config and region data
    cfg_path = config_edit.text()
    current_cfg = config_loader.load_config(cfg_path)
    region_data = ensure_region_data(cfg_path, current_cfg.get("api_keys", {}).get("gaode", ""))

    logs_queue: "queue.Queue[str]" = queue.Queue()
    # executor for PyQt GUI
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=int(current_cfg.get("max_concurrency", 1)))
    # running state and cooperative stop event
    task_running = False
    current_stop_event = None

    def append_log_msg(msg: str) -> None:
        # Called from main thread: also put into queue for consistency
        logs_queue.put(msg)

    def drain_logs() -> None:
        nonlocal task_running, current_stop_event
        try:
            while True:
                msg = logs_queue.get_nowait()
                # try to parse JSON messages and display friendly summaries for users
                try:
                    parsed = json.loads(msg)
                    if isinstance(parsed, dict):
                        ttype = parsed.get("type")
                        if ttype == "start_provider":
                            summary = f"开始任务: {parsed.get('task_name','')} · 提供商: {parsed.get('provider','')} · 关键词: {parsed.get('keyword','')}"
                            logs.append(summary)
                            continue
                        if ttype == "start_subtask":
                            lvl = parsed.get('level','')
                            if lvl == 'city':
                                summary = f"正在执行: {parsed.get('task_name','')} · 城市: {parsed.get('city','')} · 提供商: {PROVIDER_DISPLAY.get(parsed.get('provider'), parsed.get('provider',''))}"
                            elif lvl == 'county':
                                summary = f"正在执行: {parsed.get('task_name','')} · 区县: {parsed.get('county','')} (市: {parsed.get('city','')}) · 提供商: {PROVIDER_DISPLAY.get(parsed.get('provider'), parsed.get('provider',''))}"
                            else:
                                summary = f"正在执行子任务: {parsed.get('task_name','')} · 区域: {parsed.get('area','')} · 提供商: {PROVIDER_DISPLAY.get(parsed.get('provider'), parsed.get('provider',''))}"
                            logs.append(summary)
                            continue
                        if ttype == 'subtask_done':
                            summary = f"子任务完成: {parsed.get('task_name','')} · 已处理: {parsed.get('count',0)} 条（{parsed.get('province','')}{parsed.get('city','')}{parsed.get('county','')}）"
                            logs.append(summary)
                            continue
                        if ttype == 'subtask_failed':
                            summary = f"子任务失败: {parsed.get('task_name','')} · 区域: {parsed.get('province','')} {parsed.get('city','')} {parsed.get('county','')} · 错误: {parsed.get('message','') }"
                            logs.append(summary)
                            continue
                        if ttype == 'subtask_page':
                            # 每页请求的页码信息
                            pg = parsed.get('page')
                            keyword = parsed.get('keyword', '')
                            provider = parsed.get('provider', '')
                            try:
                                provider_name = PROVIDER_DISPLAY.get(provider, provider)
                            except Exception:
                                provider_name = provider
                            # 简短显示：提供商 · 关键词 · 页码
                            logs.append(f"{provider_name} · {keyword} · 第 {pg} 页")
                            continue
                        if ttype == 'summary_title':
                            # 三行摘要的第一行：标题
                            logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'summary_query':
                            # 三行摘要的第二行：查询/子任务信息
                            logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'summary_status':
                            # 三行摘要的第三行：状态/数量/错误
                            logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'task_done':
                            summary = f"任务完成: {parsed.get('task_name','')} · 总记录: {parsed.get('records',0)}"
                            logs.append(summary)
                            continue
                        if ttype == 'task_failed':
                            summary = f"任务失败: {parsed.get('task_name','')} · 错误: {parsed.get('message','')}"
                            logs.append(summary)
                            continue
                        if ttype == 'runner_done':
                            # background runner finished or stopped; restore UI state
                            task_running = False
                            current_stop_event = None
                            try:
                                btn_run.setEnabled(True)
                                btn_run_all.setEnabled(True)
                                btn_stop.setEnabled(False)
                            except Exception:
                                pass
                            logs.append("任务已停止或完成。")
                            continue
                        # fallback: if it looks like a final log entry
                        if parsed.get('task_name') and parsed.get('status'):
                            summary = f"{parsed.get('run_time','')} | 任务: {parsed.get('task_name','')} | 状态: {parsed.get('status','')} | 记录: {parsed.get('records','')} | {parsed.get('message','') }"
                            logs.append(summary)
                            continue
                except Exception:
                    pass
                logs.append(msg)
        except Exception:
            pass

    timer = QtCore.QTimer()
    timer.timeout.connect(drain_logs)
    timer.start(300)

    # --- Log Query tab: build UI elements but add to tab widget later ---
    # Filters
    log_date_from = QtWidgets.QDateEdit(); log_date_from.setCalendarPopup(True); log_date_from.setDate(QtCore.QDate.currentDate())
    log_date_to = QtWidgets.QDateEdit(); log_date_to.setCalendarPopup(True); log_date_to.setDate(QtCore.QDate.currentDate())
    log_task_filter = QtWidgets.QComboBox(); log_task_filter.addItem("全部")
    log_provider_filter = QtWidgets.QComboBox(); log_provider_filter.addItems(["全部", "百度", "高德", "天地图"])
    btn_query_logs = QtWidgets.QPushButton("查询日志")
    btn_export_filtered = QtWidgets.QPushButton("导出筛选结果")
    btn_export_all_logs = QtWidgets.QPushButton("导出全部日志")
    # Table
    log_table = QtWidgets.QTableWidget();
    log_table.setColumnCount(7)
    log_table.setHorizontalHeaderLabels(["任务名称", "运行时间", "区域", "提供商", "状态", "记录数", "消息"])
    log_table.horizontalHeader().setStretchLastSection(True)


    def refresh_task_list() -> None:
        task_list.clear()
        for t in current_cfg.get("tasks", []):
            text = f"{t.get('name')} | {get_task_area_summary(t)}"
            item = QtWidgets.QListWidgetItem(text)
            # make item checkbox-enabled for easy multi-selection
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            task_list.addItem(item)

    def get_checked_task_indices() -> List[int]:
        idxs: List[int] = []
        for i in range(task_list.count()):
            it = task_list.item(i)
            try:
                if it.checkState() == QtCore.Qt.Checked:
                    idxs.append(i)
            except Exception:
                pass
        return idxs

    def populate_log_task_filter():
        log_task_filter.clear()
        log_task_filter.addItem("全部")
        for t in current_cfg.get("tasks", []):
            log_task_filter.addItem(t.get("name", ""))

    def populate_region_tree():
        try:
            region_tree.clear()
            for prov, cities in region_data.items():
                prov_item = QtWidgets.QTreeWidgetItem([prov])
                prov_item.setFlags(prov_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                prov_item.setCheckState(0, QtCore.Qt.Unchecked)
                region_tree.addTopLevelItem(prov_item)
                if isinstance(cities, dict):
                    for city, counties in cities.items():
                        city_item = QtWidgets.QTreeWidgetItem([city])
                        city_item.setFlags(city_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                        city_item.setCheckState(0, QtCore.Qt.Unchecked)
                        prov_item.addChild(city_item)
                        if isinstance(counties, list):
                            for c in counties:
                                cname = c.get("name") if isinstance(c, dict) else str(c)
                                county_item = QtWidgets.QTreeWidgetItem([cname])
                                county_item.setFlags(county_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                                county_item.setCheckState(0, QtCore.Qt.Unchecked)
                                city_item.addChild(county_item)
                elif isinstance(cities, list):
                    for city in cities:
                        city_item = QtWidgets.QTreeWidgetItem([str(city)])
                        city_item.setFlags(city_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                        city_item.setCheckState(0, QtCore.Qt.Unchecked)
                        prov_item.addChild(city_item)

    def populate_resources_tree():
        try:
            resources_tree.clear()
            keys = list(current_cfg.get("keywords", {}).keys())
            if not keys:
                keys = ["gas_station", "service_area", "hospital", "repair_factory"]
            for k in keys:
                item = QtWidgets.QTreeWidgetItem([k])
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Unchecked)
                resources_tree.addTopLevelItem(item)
        except Exception:
            pass

    def propagate_check(item: QtWidgets.QTreeWidgetItem, col: int) -> None:
        try:
            state = item.checkState(col)
            # set all children to the same state
            def set_children(it):
                for i in range(it.childCount()):
                    ch = it.child(i)
                    ch.setCheckState(0, state)
                    set_children(ch)
            set_children(item)
            # propagate upwards
            parent = item.parent()
            while parent is not None:
                all_checked = True
                any_checked = False
                for i in range(parent.childCount()):
                    s = parent.child(i).checkState(0)
                    if s == QtCore.Qt.Checked:
                        any_checked = True
                    else:
                        all_checked = False
                if all_checked:
                    parent.setCheckState(0, QtCore.Qt.Checked)
                elif any_checked:
                    parent.setCheckState(0, QtCore.Qt.PartiallyChecked)
                else:
                    parent.setCheckState(0, QtCore.Qt.Unchecked)
                parent = parent.parent()
        except Exception:
            pass

    # wire tree signals
    try:
        region_tree.itemChanged.connect(propagate_check)
        resources_tree.itemChanged.connect(propagate_check)
    except Exception:
        pass

    def build_log_rows(logs_list: list) -> list:
        rows = []
        for entry in logs_list:
            task_name = entry.get("task_name", "")
            run_time = entry.get("run_time", "")
            area = entry.get("area", "")
            # provider: prefer explicit provider field, otherwise try to detect
            provider = entry.get("provider", "")
            if not provider:
                low = json.dumps(entry).lower()
                if "baidu" in low:
                    provider = "百度"
                elif "gaode" in low or "amap" in low:
                    provider = "高德"
                elif "tencent" in low:
                    provider = "腾讯"
            status = entry.get("status", "")
            records = entry.get("records", "")
            message = entry.get("message", "")
            rows.append((task_name, run_time, area, provider, status, records, message))
        return rows

    def query_logs_ui():
        try:
            all_logs = load_logs(current_cfg.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
            df = log_date_from.date().toString("yyyy-MM-dd")
            dt = log_date_to.date().toString("yyyy-MM-dd")
            task_sel = log_task_filter.currentText()
            prov_sel = log_provider_filter.currentText()
            filtered = []
            for e in all_logs:
                try:
                    rt = str(e.get("run_time", ""))[:10]
                except Exception:
                    rt = ""
                if df and rt and rt < df:
                    continue
                if dt and rt and rt > dt:
                    continue
                if task_sel and task_sel != "全部" and e.get("task_name") != task_sel:
                    continue
                if prov_sel and prov_sel != "全部":
                    # prefer explicit provider field in log entry
                    prov_field = e.get("provider")
                    if prov_field:
                        if prov_field != prov_sel:
                            continue
                    else:
                        low = json.dumps(e).lower()
                        key = "baidu" if prov_sel == "百度" else ("gaode" if prov_sel == "高德" else "tencent")
                        if key not in low:
                            continue
                filtered.append(e)
            rows = build_log_rows(filtered)
            log_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, val in enumerate(row):
                    item = QtWidgets.QTableWidgetItem(str(val))
                    log_table.setItem(i, j, item)
        except Exception as exc:
            append_log_msg(f"查询日志出错: {exc}")

    def export_logs_ui(filtered_only: bool):
        try:
            all_logs = load_logs(current_cfg.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
            if filtered_only:
                # reuse query to get filtered entries
                df = log_date_from.date().toString("yyyy-MM-dd")
                dt = log_date_to.date().toString("yyyy-MM-dd")
                task_sel = log_task_filter.currentText()
                prov_sel = log_provider_filter.currentText()
                filtered = []
                for e in all_logs:
                    try:
                        rt = str(e.get("run_time", ""))[:10]
                    except Exception:
                        rt = ""
                    if df and rt and rt < df:
                        continue
                    if dt and rt and rt > dt:
                        continue
                    if task_sel and task_sel != "全部" and e.get("task_name") != task_sel:
                        continue
                    if prov_sel and prov_sel != "全部":
                        low = json.dumps(e).lower()
                        key = "baidu" if prov_sel == "百度" else ("gaode" if prov_sel == "高德" else "tencent")
                        if key not in low:
                            continue
                    filtered.append(e)
                to_export = filtered
            else:
                to_export = all_logs
            # ask user for save path
            path, _ = QtWidgets.QFileDialog.getSaveFileName(win, "导出日志", "logs_export.csv", "CSV 文件 (*.csv);;JSON 文件 (*.json)")
            if not path:
                return
            exported = export_logs(to_export, path)
            append_log_msg(f"已导出日志: {exported}")
        except Exception as exc:
            append_log_msg(f"导出日志失败: {exc}")

    def update_provinces():
        province_combo.clear(); province_combo.addItems(sorted(region_data.keys()))

    def update_cities():
        prov = province_combo.currentText()
        city_combo.clear()
        if prov and prov in region_data:
            # add '全部' option to allow fetching entire province/city
            city_combo.addItem("全部")
            city_combo.addItems(sorted(region_data[prov].keys()))

    def update_counties():
        prov = province_combo.currentText(); cit = city_combo.currentText()
        county_combo.clear()
        # if user selected '全部' for city, show only '全部' to represent whole-city fetch
        if prov and cit == "全部" and prov in region_data:
            county_combo.addItem("全部")
            return
        if prov and cit and prov in region_data and cit in region_data[prov]:
            counties = region_data[prov][cit]
            if not counties:
                # try fetch
                fetched = fetch_amap_subdistrict(current_cfg.get("api_keys", {}).get("gaode", ""), prov, cit)
                if fetched:
                    region_data.setdefault(prov, {})[cit] = fetched
                    counties = fetched
            # add '全部' option to allow fetching entire city when desired
            county_combo.addItem("全部")
            # region_data entries may be dicts with name/adcode or plain names
            names = []
            for c in (counties or []):
                if isinstance(c, dict):
                    names.append(c.get("name", ""))
                else:
                    names.append(str(c))
            county_combo.addItems([n for n in names if n])

    selected_task_index = None

    def load_task(idx: int) -> None:
        try:
            t = current_cfg.get("tasks", [])[idx]
        except Exception:
            return
        task_name_edit.setText(t.get("name", ""))
        # map stored internal value ('admin'/'bbox') to display text
        stored_atype = t.get("area_type", "admin")
        area_type_combo.setCurrentText(type_value_to_display.get(stored_atype, stored_atype))
        province_combo.setCurrentText(t.get("admin_region", {}).get("province", ""))
        update_cities()
        # map empty-string (saved meaning '全部') to display value '全部'
        city_val = t.get("admin_region", {}).get("city", "") or "全部"
        city_combo.setCurrentText(city_val)
        update_counties()
        county_val = t.get("admin_region", {}).get("county", "") or "全部"
        # if stored config only has adcode, try to map to name
        if county_val == "" and t.get("admin_region", {}).get("adcode"):
            ac = t.get("admin_region", {}).get("adcode")
            # try lookup
            try:
                prov = t.get("admin_region", {}).get("province", "")
                cit = t.get("admin_region", {}).get("city", "")
                if prov and cit and prov in region_data and cit in region_data[prov]:
                    for entry in region_data[prov][cit]:
                        if isinstance(entry, dict) and str(entry.get("adcode")) == str(ac):
                            county_val = entry.get("name", "")
                            break
            except Exception:
                pass
        county_combo.setCurrentText(county_val)
        bbox_left.setText(str((t.get("bbox") or {}).get("left", "")))
        bbox_bottom.setText(str((t.get("bbox") or {}).get("bottom", "")))
        bbox_right.setText(str((t.get("bbox") or {}).get("right", "")))
        bbox_top.setText(str((t.get("bbox") or {}).get("top", "")))
        # update enabled/disabled widgets based on loaded mode
        try:
            update_mode_ui()
        except Exception:
            pass
        # 不在主面板日志输出区显示历史日志（历史日志请使用“日志查询”选项卡查看）
        # record which task index is currently loaded in the editor
        nonlocal selected_task_index
        selected_task_index = idx

    def on_task_selected():
        idx = task_list.currentRow()
        if idx >= 0:
            load_task(idx)


    def save_config_ui():
        nonlocal executor
        # write global settings into current_cfg and save
        try:
            # map displayed provider name back to internal key
            cur_prov_display = provider_combo.currentText()
            current_cfg["provider"] = provider_display_to_value.get(cur_prov_display, cur_prov_display)
            # resources: accept JSON list or comma/Chinese-comma separated keywords
            raw = resources_edit.text().strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    current_cfg["resources"] = [str(x).strip() for x in parsed if str(x).strip()]
                else:
                    raise ValueError("not a list")
            except Exception:
                parts = [p.strip() for p in re.split(r"[,，]", raw) if p.strip()]
                current_cfg["resources"] = parts
            current_cfg["export_format"] = export_combo.currentText()
            current_cfg["province_expand_concurrency"] = int(province_expand_concurrency_spin.value())
            current_cfg["province_expand_delay_seconds"] = float(province_expand_delay_spin.value())
            current_cfg["default_page_limit"] = int(page_spin.value())
            # scheduler settings are nested under 'scheduler'
            sched = current_cfg.setdefault("scheduler", {})
            sched["check_interval_minutes"] = int(check_interval_spin.value())
            current_cfg["incremental"] = bool(incr_check.isChecked())
            current_cfg["schedule_interval_days"] = int(sched_spin.value())
            current_cfg["max_concurrency"] = int(concurrency_spin.value())
            config_loader.save_config(config_edit.text(), current_cfg)
            # recreate executor if changed
            try:
                new_max = int(current_cfg.get("max_concurrency", 1))
                if getattr(executor, "_max_workers", None) != new_max:
                    try:
                        executor.shutdown(wait=False)
                    except Exception:
                        pass
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=new_max)
            except Exception:
                pass
            append_log_msg("已保存配置")
            try:
                QtWidgets.QMessageBox.information(win, "保存配置", "全局设置已保存并生效。")
            except Exception:
                pass
        except Exception as e:
            append_log_msg(f"保存配置失败: {e}")

    def save_task():
        try:
            name = task_name_edit.text().strip()
            if not name:
                append_log_msg("任务名称不能为空")
                return
            # map display text to internal value
            atype_display = area_type_combo.currentText()
            atype = type_display_to_value.get(atype_display, atype_display)
            task: Dict[str, Any] = {"name": name, "enabled": True, "area_type": atype}
            if atype == "bbox":
                task["bbox"] = {"left": float(bbox_left.text() or 0), "bottom": float(bbox_bottom.text() or 0), "right": float(bbox_right.text() or 0), "top": float(bbox_top.text() or 0)}
                task["admin_region"] = {"country": country_label.text(), "province": "", "city": ""}
            else:
                # map UI '全部' selection to empty string in saved config to indicate whole-city/whole-province
                prov = province_combo.currentText()
                city = city_combo.currentText()
                county = county_combo.currentText()
                if city == "全部":
                    city = ""
                if county == "全部":
                    county = ""
                admin = {"country": country_label.text(), "province": prov, "city": city, "county": county}
                # if we have region_data with adcodes, try to attach adcode for precise queries
                try:
                    if prov and city and prov in region_data and city in region_data[prov]:
                        entries = region_data[prov][city]
                        if entries:
                            for entry in entries:
                                name = entry.get("name") if isinstance(entry, dict) else entry
                                if name == county and isinstance(entry, dict):
                                    admin["adcode"] = entry.get("adcode", "")
                                    break
                except Exception:
                    pass
                task["admin_region"] = admin
                task["bbox"] = None
            # collect selected resources from resources_tree if any, else parse resources_edit
            sel_resources = []
            try:
                for i in range(resources_tree.topLevelItemCount()):
                    it = resources_tree.topLevelItem(i)
                    if it.checkState(0) == QtCore.Qt.Checked:
                        sel_resources.append(it.text(0))
            except Exception:
                pass
            if not sel_resources:
                try:
                    sel_resources = json.loads(resources_edit.text()) if resources_edit.text() else []
                except Exception:
                    sel_resources = [p.strip() for p in re.split(r"[,，]", resources_edit.text()) if p.strip()]
            task["resources"] = sel_resources
            # collect selected regions from region_tree; if multiple regions selected, create multiple tasks
            selected_regions = []
            try:
                def collect_leaves(item):
                    out = []
                    if item.childCount() == 0:
                        out.append(item)
                    else:
                        for j in range(item.childCount()):
                            out.extend(collect_leaves(item.child(j)))
                    return out

                for pi in range(region_tree.topLevelItemCount()):
                    pitem = region_tree.topLevelItem(pi)
                    if pitem.checkState(0) == QtCore.Qt.Checked:
                        # collect all leaf descendants
                        leaves = collect_leaves(pitem)
                        for leaf in leaves:
                            path = []
                            cur = leaf
                            while cur is not None:
                                path.insert(0, cur.text(0))
                                cur = cur.parent()
                            # path may be [prov, city, county] or [prov, city]
                            pr = path[0] if len(path) > 0 else ""
                            ct = path[1] if len(path) > 1 else ""
                            co = path[2] if len(path) > 2 else ""
                            selected_regions.append({"country": country_label.text(), "province": pr, "city": ct, "county": co})
                    else:
                        # check partially checked nodes: inspect children
                        for ci in range(pitem.childCount()):
                            c = pitem.child(ci)
                            if c.checkState(0) != QtCore.Qt.Unchecked:
                                leaves = collect_leaves(c)
                                for leaf in leaves:
                                    if leaf.checkState(0) == QtCore.Qt.Checked:
                                        path = []
                                        cur = leaf
                                        while cur is not None:
                                            path.insert(0, cur.text(0))
                                            cur = cur.parent()
                                        pr = path[0] if len(path) > 0 else ""
                                        ct = path[1] if len(path) > 1 else ""
                                        co = path[2] if len(path) > 2 else ""
                                        selected_regions.append({"country": country_label.text(), "province": pr, "city": ct, "county": co})
            except Exception:
                selected_regions = []

            tasks_to_add = []
            if selected_regions:
                for idx_r, reg in enumerate(selected_regions):
                    tcopy = dict(task)
                    tcopy["admin_region"] = reg
                    # if multiple regions, append region text to name to disambiguate
                    if len(selected_regions) > 1:
                        tcopy["name"] = f"{tcopy['name']} ({reg.get('province','')}/{reg.get('city','')}/{reg.get('county','')})"
                    tasks_to_add.append(tcopy)
            else:
                tasks_to_add.append(task)
            # prefer the task index that was loaded into the editor; fall back to currentRow
            nonlocal selected_task_index
            idx = selected_task_index if selected_task_index is not None else task_list.currentRow()
            tasks = current_cfg.setdefault("tasks", [])
            if idx < 0:
                tasks.extend(tasks_to_add)
            else:
                # replace the single selected row with first task, append remaining after it
                tasks[idx] = tasks_to_add[0]
                if len(tasks_to_add) > 1:
                    for extra in tasks_to_add[1:]:
                        tasks.insert(idx + 1, extra)
            config_loader.save_config(config_edit.text(), current_cfg)
            refresh_task_list()
            append_log_msg(f"已保存任务: {task['name']}")
        except Exception as e:
            append_log_msg(f"保存任务失败: {e}")

    def add_task_ui():
        task_name_edit.setText(f"新任务_{len(current_cfg.get('tasks', []))+1}")

    def delete_task_ui():
        checked = get_checked_task_indices()
        if checked:
            # delete in reverse order to keep indices valid
            try:
                names = []
                for idx in sorted(checked, reverse=True):
                    names.append(current_cfg.get("tasks", [])[idx].get("name"))
                    del current_cfg["tasks"][idx]
                config_loader.save_config(config_edit.text(), current_cfg)
                refresh_task_list()
                append_log_msg(f"已删除任务: {', '.join(names)}")
            except Exception as e:
                append_log_msg(f"删除任务失败: {e}")
            return
        # fallback to single selection deletion
        idx = task_list.currentRow()
        if idx < 0:
            return
        try:
            t = current_cfg.get("tasks", [])[idx]
            del current_cfg["tasks"][idx]
            config_loader.save_config(config_edit.text(), current_cfg)
            refresh_task_list()
            append_log_msg(f"已删除任务: {t.get('name')}")
        except Exception as e:
            append_log_msg(f"删除任务失败: {e}")

    def worker_run_task(t: Dict[str, Any], stop_event) -> None:
        def push_progress(obj: Dict[str, Any]) -> None:
            try:
                logs_queue.put(json.dumps(obj, ensure_ascii=False))
            except Exception:
                pass
        try:
            res = run_task(t, current_cfg, mode="manual", progress_callback=push_progress, stop_event=stop_event)
            logs_queue.put(json.dumps(res, ensure_ascii=False))
        except Exception as e:
            logs_queue.put(f"任务运行失败: {e}")
        finally:
            try:
                logs_queue.put(json.dumps({"type": "runner_done"}, ensure_ascii=False))
            except Exception:
                pass

    def display_task_logs(task_name: str) -> None:
        try:
            logs.clear()
            all_logs = load_logs(current_cfg.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
            found = False
            for entry in all_logs:
                if entry.get("task_name") == task_name:
                    logs.append(json.dumps(entry, ensure_ascii=False))
                    found = True
            if not found:
                logs.append(f"未找到任务 '{task_name}' 的执行日志。")
        except Exception as e:
            logs.append(f"读取日志失败: {e}")

    def run_selected_ui():
        nonlocal task_running, current_stop_event
        if task_running:
            append_log_msg("已有任务正在执行，不能重复启动。")
            return
        checked = get_checked_task_indices()
        # create new stop event for this run
        ev = threading.Event()
        task_running = True
        current_stop_event = ev
        try:
            btn_run.setEnabled(False)
            btn_run_all.setEnabled(False)
            btn_stop.setEnabled(True)
        except Exception:
            pass
        if checked:
            for idx in checked:
                try:
                    t = current_cfg.get("tasks", [])[idx]
                except Exception:
                    continue
                try:
                    executor.submit(worker_run_task, t, ev)
                except Exception:
                    threading.Thread(target=worker_run_task, args=(t, ev), daemon=True).start()
            return
        idx = task_list.currentRow()
        if idx < 0:
            logs_queue.put("请先选择任务。")
            task_running = False
            current_stop_event = None
            try:
                btn_run.setEnabled(True)
                btn_run_all.setEnabled(True)
                btn_stop.setEnabled(False)
            except Exception:
                pass
            return
        t = current_cfg.get("tasks", [])[idx]
        try:
            executor.submit(worker_run_task, t, ev)
        except Exception:
            threading.Thread(target=worker_run_task, args=(t, ev), daemon=True).start()

    def worker_run_all(stop_event):
        def push_progress(obj: Dict[str, Any]) -> None:
            try:
                logs_queue.put(json.dumps(obj, ensure_ascii=False))
            except Exception:
                pass
        try:
            res = run_tasks(current_cfg.get("tasks", []), current_cfg, mode="manual", progress_callback=push_progress, stop_event=stop_event)
            for r in res:
                logs_queue.put(json.dumps(r, ensure_ascii=False))
        except Exception as e:
            logs_queue.put(f"批量运行失败: {e}")
        finally:
            try:
                logs_queue.put(json.dumps({"type": "runner_done"}, ensure_ascii=False))
            except Exception:
                pass

    def run_all_ui():
        nonlocal task_running, current_stop_event
        if task_running:
            append_log_msg("已有任务正在执行，不能重复启动。")
            return
        ev = threading.Event()
        task_running = True
        current_stop_event = ev
        try:
            btn_run.setEnabled(False)
            btn_run_all.setEnabled(False)
            btn_stop.setEnabled(True)
        except Exception:
            pass
        try:
            executor.submit(worker_run_all, ev)
        except Exception:
            threading.Thread(target=worker_run_all, args=(ev,), daemon=True).start()

    def stop_current_run():
        nonlocal current_stop_event
        if current_stop_event:
            try:
                current_stop_event.set()
                append_log_msg("已请求停止任务，正在等待子任务响应...")
                btn_stop.setEnabled(False)
            except Exception:
                pass

    btn_stop.clicked.connect(lambda: stop_current_run())

    # wire signals
    task_list.currentRowChanged.connect(lambda _i: on_task_selected())
    province_combo.currentIndexChanged.connect(lambda _i: update_cities())
    city_combo.currentIndexChanged.connect(lambda _i: update_counties())
    area_type_combo.currentIndexChanged.connect(lambda _i: update_mode_ui())
    btn_load.clicked.connect(lambda: (refresh_task_list(), update_provinces(), append_log_msg("已加载配置")))
    btn_save.clicked.connect(save_config_ui)
    btn_save_global.clicked.connect(save_config_ui)
    btn_save_advanced.clicked.connect(save_config_ui)
    # log query signals
    btn_query_logs.clicked.connect(query_logs_ui)
    btn_export_filtered.clicked.connect(lambda: export_logs_ui(True))
    btn_export_all_logs.clicked.connect(lambda: export_logs_ui(False))
    save_task_btn.clicked.connect(save_task)
    btn_add.clicked.connect(add_task_ui)
    btn_delete.clicked.connect(delete_task_ui)
    btn_run.clicked.connect(run_selected_ui)
    btn_run_all.clicked.connect(run_all_ui)

    # initialize UI values
    # set provider display text from stored internal key
    provider_combo.setCurrentText(provider_value_to_display.get(current_cfg.get("provider", ""), provider_combo.currentText()))
    # show resources as JSON for clarity and easy copy/paste
    try:
        resources_edit.setText(json.dumps(current_cfg.get("resources", []), ensure_ascii=False))
    except Exception:
        resources_edit.setText(','.join(current_cfg.get("resources", [])))
    export_combo.setCurrentText(str(current_cfg.get("export_format", export_combo.currentText())))
    page_spin.setValue(int(current_cfg.get("default_page_limit", page_spin.value())))
    province_expand_concurrency_spin.setValue(int(current_cfg.get("province_expand_concurrency", province_expand_concurrency_spin.value())))
    province_expand_delay_spin.setValue(float(current_cfg.get("province_expand_delay_seconds", province_expand_delay_spin.value())))
    check_interval_spin.setValue(int(current_cfg.get("scheduler", {}).get("check_interval_minutes", check_interval_spin.value())))
    incr_check.setChecked(bool(current_cfg.get("incremental", incr_check.isChecked())))
    sched_spin.setValue(int(current_cfg.get("schedule_interval_days", sched_spin.value())))
    # initialize area type display and UI mode
    area_type_combo.setCurrentText(type_value_to_display.get(current_cfg.get("default_area_type", "admin"), type_value_to_display.get("admin")))
    try:
        update_mode_ui()
    except Exception:
        pass
    update_provinces(); update_cities(); update_counties(); refresh_task_list()
    # populate log task filter and add Log Query tab to tabs
    populate_log_task_filter()
    # build log query tab layout and add
    tab_log = QtWidgets.QWidget()
    tab_log_l = QtWidgets.QVBoxLayout(tab_log)
    filter_layout = QtWidgets.QHBoxLayout()
    filter_layout.addWidget(QtWidgets.QLabel("从：")); filter_layout.addWidget(log_date_from)
    filter_layout.addWidget(QtWidgets.QLabel("到：")); filter_layout.addWidget(log_date_to)
    filter_layout.addWidget(QtWidgets.QLabel("任务：")); filter_layout.addWidget(log_task_filter)
    filter_layout.addWidget(QtWidgets.QLabel("提供商：")); filter_layout.addWidget(log_provider_filter)
    filter_layout.addWidget(btn_query_logs)
    tab_log_l.addLayout(filter_layout)
    tab_log_l.addWidget(log_table, 1)
    hb_export = QtWidgets.QHBoxLayout()
    hb_export.addWidget(btn_export_filtered)
    hb_export.addWidget(btn_export_all_logs)
    tab_log_l.addLayout(hb_export)
    tabs.addTab(tab_log, "日志查询")

    win.show()
    app.exec_()
