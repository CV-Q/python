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
import ast
import concurrent.futures
import config_loader


def create_gui_pyqt(config_path: str, testing_hooks: Dict[str, Any] = None) -> None:
    if QtWidgets is None:
        print("PyQt5 未安装。请通过 'pip install PyQt5' 安装后重试。")
        return

    # 延迟导入重量级应用辅助函数以避免模块导入时的循环依赖
    from map_poi_fetcher import (
        ensure_region_data,
        fetch_amap_subdistrict,
        fetch_and_save_region_hierarchy,
        load_region_cache,
        get_task_area_summary,
        run_task,
        run_tasks,
        # 日志辅助函数
        load_logs,
        export_logs,
        PROVIDER_DISPLAY,
        # 缓存辅助函数
        save_region_cache,
        get_region_cache_path,
    )

    app = QtWidgets.QApplication([])
    win = QtWidgets.QMainWindow()
    win.setWindowTitle("POI 任务调度器 (PyQt5)")
    central = QtWidgets.QWidget()
    win.setCentralWidget(central)
    layout = QtWidgets.QVBoxLayout(central)

    # 顶部：配置路径显示与加载/保存按钮
    top_h = QtWidgets.QHBoxLayout()
    config_edit = QtWidgets.QLineEdit(config_path)
    top_h.addWidget(QtWidgets.QLabel("配置文件："))
    top_h.addWidget(config_edit)
    btn_load = QtWidgets.QPushButton("刷新配置")
    btn_update_regions = QtWidgets.QPushButton("更新行政区(京津冀+山西+陕西+河南+湖北)")
    btn_save = QtWidgets.QPushButton("保存配置")
    top_h.addWidget(btn_load)
    top_h.addWidget(btn_update_regions)
    top_h.addWidget(btn_save)
    layout.addLayout(top_h)

    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    layout.addWidget(splitter, 1)

    # 左侧：任务列表与控制按钮
    left_w = QtWidgets.QWidget()
    left_l = QtWidgets.QVBoxLayout(left_w)
    task_list = QtWidgets.QListWidget()
    left_l.addWidget(task_list)
    hb = QtWidgets.QHBoxLayout()
    btn_add = QtWidgets.QPushButton("新增任务")
    btn_delete = QtWidgets.QPushButton("删除任务")
    btn_select_tasks = QtWidgets.QPushButton("全选/取消全选")
    btn_run = QtWidgets.QPushButton("运行选中任务")
    btn_run_all = QtWidgets.QPushButton("运行全部任务")
    btn_stop = QtWidgets.QPushButton("停止任务")
    btn_stop.setEnabled(False)
    hb.addWidget(btn_add)
    hb.addWidget(btn_delete)
    hb.addWidget(btn_select_tasks)
    hb.addWidget(btn_run)
    hb.addWidget(btn_run_all)
    hb.addWidget(btn_stop)
    left_l.addLayout(hb)
    # 实时日志区域（摘要信息）
    logs = QtWidgets.QTextEdit(); logs.setReadOnly(True)
    left_l.addWidget(QtWidgets.QLabel("日志输出（实时摘要）"))
    left_l.addWidget(logs, 1)
    splitter.addWidget(left_w)

    # 右侧：任务编辑器、全局设置与日志查询
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

    # 地区树：支持省市县多选，父子节点联动勾选行为
    region_tree = QtWidgets.QTreeWidget()
    region_tree.setHeaderLabels(["地区 (多选)"])
    region_tree.setColumnCount(1)
    region_tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    region_tree.setUniformRowHeights(True)
    region_explicit_role = QtCore.Qt.UserRole + 1
    form.addRow("地区选择：", region_tree)
    # (原先地区的全选按钮已移至任务列表区)

    bbox_left = QtWidgets.QLineEdit()
    bbox_bottom = QtWidgets.QLineEdit()
    bbox_right = QtWidgets.QLineEdit()
    bbox_top = QtWidgets.QLineEdit()
    form.addRow("BBox 左：", bbox_left)
    form.addRow("BBox 下：", bbox_bottom)
    form.addRow("BBox 右：", bbox_right)
    form.addRow("BBox 上：", bbox_top)

    # 每个任务的提供商、资源与导出选项将在创建控件后添加

    save_task_btn = QtWidgets.QPushButton("保存任务")

    def update_mode_ui():
        cur = area_type_combo.currentText()
        mode_val = type_display_to_value.get(cur, cur)
        is_admin = (mode_val == "admin")
        # 已移除单选下拉；仅控制 bbox 输入的启用/禁用
        bbox_left.setEnabled(not is_admin)
        bbox_bottom.setEnabled(not is_admin)
        bbox_right.setEnabled(not is_admin)
        bbox_top.setEnabled(not is_admin)

    # 使用选项卡：任务编辑 与 全局设置
    tabs = QtWidgets.QTabWidget()
    tab_task = QtWidgets.QWidget()
    tab_task_l = QtWidgets.QVBoxLayout(tab_task)
    tab_task_l.addLayout(form)
    # 将保存按钮放在任务编辑器底部（不嵌入中间表单）
    try:
        tab_task_l.addWidget(save_task_btn)
    except Exception:
        pass
    tabs.addTab(tab_task, "任务编辑")

    # 全局设置选项卡
    tab_global = QtWidgets.QWidget()
    tab_global_l = QtWidgets.QVBoxLayout(tab_global)
    glob_group = QtWidgets.QGroupBox("全局设置")
    glob_layout = QtWidgets.QFormLayout(glob_group)
    provider_combo = QtWidgets.QComboBox()
    # 显示中文名称，并映射到内部提供商键
    provider_display_to_value = {"百度": "baidu", "高德": "gaode", "天地图": "tianditu"}
    provider_value_to_display = {v: k for k, v in provider_display_to_value.items()}
    provider_combo.addItems(list(provider_display_to_value.keys()))
    # 资源选择：默认以逗号分隔关键字存储，但界面中使用资源树进行多选
    # 已移除资源编辑行，仅使用 resources_tree 选择资源
    export_combo = QtWidgets.QComboBox()
    export_combo.addItems(["csv", "json", "excel"])
    concurrency_spin = QtWidgets.QSpinBox(); concurrency_spin.setRange(1, 1); concurrency_spin.setValue(1); concurrency_spin.setEnabled(False)
    province_expand_delay_spin = QtWidgets.QDoubleSpinBox(); province_expand_delay_spin.setRange(0.0, 60.0); province_expand_delay_spin.setSingleStep(0.1)
    page_spin = QtWidgets.QSpinBox(); page_spin.setRange(1, 100)
    check_interval_spin = QtWidgets.QSpinBox(); check_interval_spin.setRange(1, 1440)
    incr_check = QtWidgets.QCheckBox()
    sched_spin = QtWidgets.QSpinBox(); sched_spin.setRange(1, 365)
    # glob_layout.addRow("说明：", QtWidgets.QLabel("提供商与资源已移至任务编辑；导出格式在任务编辑可见但仍为全局设置。"))
    # # 注意：并发、分页与调度选项已移至“高级设置”选项卡
    # adv_note = QtWidgets.QLabel("并发/分页/调度设置已移至“高级设置”选项卡。点击高级设置进行配置。")
    # try:
    #     adv_note.setWordWrap(True)
    # except Exception:
    #     pass
    # glob_layout.addRow(adv_note)
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
    # add per-task UI into the task editor form (provider, resources, export)
    try:
        form.addRow("提供商：", provider_combo)
        form.addRow("资源：", resources_tree)
        form.addRow("导出格式（全局）：", export_combo)
    except Exception:
        pass
    # resources_tree UI moved to task editor form; keep global tab minimal
    # add explicit save button inside global tab
    btn_save_global = QtWidgets.QPushButton("保存全局设置")
    tab_global_l.addWidget(btn_save_global)
    # advanced save button will be created below and wired to the same save logic
    # 全局设置页已移除，相关选项保留在高级设置和任务编辑中

    # Advanced settings tab (for concurrency, paging and scheduler settings)
    tab_advanced = QtWidgets.QWidget()
    tab_adv_l = QtWidgets.QVBoxLayout(tab_advanced)
    adv_group = QtWidgets.QGroupBox("高级设置")
    adv_layout = QtWidgets.QFormLayout(adv_group)
    adv_layout.addRow("并发数（固定串行）：", concurrency_spin)
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

    splitter.addWidget(right_w)

    # 加载配置与区域数据
    cfg_path = config_edit.text()
    current_cfg = config_loader.load_config(cfg_path)
    # 防御性补齐关键字段，避免旧配置在运行时触发 KeyError（如 logs_path）
    current_cfg.setdefault("logs_path", "logs/poi_fetcher_logs.jsonl")
    current_cfg.setdefault("results_dir", "POI_Data")
    current_cfg.setdefault("max_concurrency", 1)
    current_cfg.setdefault("incremental", True)
    region_data = ensure_region_data(cfg_path, current_cfg.get("api_keys", {}).get("gaode", ""))

    logs_queue: "queue.Queue[str]" = queue.Queue()
    # PyQt GUI 的线程池执行器
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=int(current_cfg.get("max_concurrency", 1)))
    # 运行状态与协作停止事件
    task_running = False
    current_stop_event = None

    def append_log_msg(msg: str) -> None:
        # 从主线程调用：也放入队列以保持一致性
        logs_queue.put(msg)

    def drain_logs() -> None:
        nonlocal task_running, current_stop_event
        try:
            while True:
                msg = logs_queue.get_nowait()
                # 尝试解析 JSON 消息并为用户显示友好摘要
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
                            # logs.append(f"{provider_name} · {keyword} · 第 {pg} 页")
                            continue
                        if ttype == 'summary_title':
                            # 三行摘要的第一行：标题
                            # logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'summary_query':
                            # 三行摘要的第二行：查询/子任务信息
                            # logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'summary_status':
                            # 三行摘要的第三行：状态/数量/错误
                            # logs.append(parsed.get('message', ''))
                            continue
                        if ttype == 'message':
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
                            # 后台运行器完成或停止；恢复 UI 状态
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
                        # 回退：若看起来像最终日志条目
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

    # --- 日志查询选项卡：构建 UI 元素（稍后加入选项卡） ---
    # 过滤器
    log_date_from = QtWidgets.QDateEdit(); log_date_from.setCalendarPopup(True); log_date_from.setDate(QtCore.QDate.currentDate())
    log_date_to = QtWidgets.QDateEdit(); log_date_to.setCalendarPopup(True); log_date_to.setDate(QtCore.QDate.currentDate())
    log_task_filter = QtWidgets.QComboBox(); log_task_filter.addItem("全部")
    log_provider_filter = QtWidgets.QComboBox(); log_provider_filter.addItems(["全部", "百度", "高德", "天地图"])
    btn_query_logs = QtWidgets.QPushButton("查询日志")
    btn_export_filtered = QtWidgets.QPushButton("导出筛选结果")
    btn_export_all_logs = QtWidgets.QPushButton("导出全部日志")
    # 表格
    log_table = QtWidgets.QTableWidget();
    log_table.setColumnCount(7)
    log_table.setHorizontalHeaderLabels(["任务名称", "运行时间", "区域", "提供商", "状态", "记录数", "消息"])
    log_table.horizontalHeader().setStretchLastSection(True)


    def refresh_task_list() -> None:
        task_list.clear()
        for t in current_cfg.get("tasks", []):
            name = t.get('name')
            text = name if name else get_task_area_summary(t)
            item = QtWidgets.QListWidgetItem(text)
            # 设置提示以显示区域摘要，便于查看
            try:
                item.setToolTip(get_task_area_summary(t))
            except Exception:
                pass
            # 项目默认保持未勾选；加载任务时会恢复地区选择
            # 启用复选框以方便多选
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
                            if counties:
                                for c in counties:
                                    cname = None
                                    try:
                                        if isinstance(c, dict):
                                            cname = c.get("name")
                                        elif isinstance(c, str):
                                            # 有些缓存会将 dict 字符串化存储；尝试安全解析
                                            try:
                                                parsed = ast.literal_eval(c)
                                                if isinstance(parsed, dict):
                                                    cname = parsed.get('name')
                                            except Exception:
                                                cname = str(c)
                                        else:
                                            cname = str(c)
                                    except Exception:
                                        cname = str(c)
                                    county_item = QtWidgets.QTreeWidgetItem([cname])
                                    county_item.setFlags(county_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                                    county_item.setCheckState(0, QtCore.Qt.Unchecked)
                                    city_item.addChild(county_item)
                                # 标记为已加载，避免懒加载时重复添加子节点
                                try:
                                    city_item.setData(0, QtCore.Qt.UserRole, 'loaded')
                                except Exception:
                                    pass
                            else:
                                # 无明确县列表：添加表示整个城市的占位项
                                ph = QtWidgets.QTreeWidgetItem(["全部"])
                                ph.setFlags(ph.flags() | QtCore.Qt.ItemIsUserCheckable)
                                ph.setCheckState(0, QtCore.Qt.Unchecked)
                                city_item.addChild(ph)
                elif isinstance(cities, list):
                    for city in cities:
                        city_item = QtWidgets.QTreeWidgetItem([str(city)])
                        city_item.setFlags(city_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                        city_item.setCheckState(0, QtCore.Qt.Unchecked)
                        prov_item.addChild(city_item)
                        # 添加占位县节点，确保树为三层结构
                        ph = QtWidgets.QTreeWidgetItem(["全部"])
                        ph.setFlags(ph.flags() | QtCore.Qt.ItemIsUserCheckable)
                        ph.setCheckState(0, QtCore.Qt.Unchecked)
                        city_item.addChild(ph)
        except Exception:
            pass

    def populate_resources_tree():
        try:
            resources_tree.clear()
            # 确定所选提供商的内部键名
            try:
                prov_display = provider_combo.currentText()
                prov_key = provider_display_to_value.get(prov_display, "gaode")
            except Exception:
                prov_key = "gaode"
            # candidate path: same dir as config_edit
            import os
            cfg_dir = os.path.dirname(config_edit.text()) or "config"
            tree_path = os.path.join(cfg_dir, f"data_type_tree.{prov_key}.json")
            data = None
            try:
                with open(tree_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = None
            # 回退：尝试工作区的 config 目录
            if data is None:
                try:
                    tree_path = os.path.join('config', f"data_type_tree.{prov_key}.json")
                    with open(tree_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = None

            # 辅助：从 data_type_tree 使用的嵌套 dict 格式构建节点
            def add_node(parent, key, node):
                try:
                    it = QtWidgets.QTreeWidgetItem([key])
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                    it.setCheckState(0, QtCore.Qt.Unchecked)
                    # 若存在则附加提供商特定的编码
                    try:
                        code = None
                        if isinstance(node, dict):
                            code = node.get('code') or node.get('id')
                        if code is not None:
                            it.setData(0, QtCore.Qt.UserRole, str(code))
                    except Exception:
                        pass
                    parent.addChild(it)
                    # 子项可能位于 'children' 字段下
                    ch = node.get('children') if isinstance(node, dict) else None
                    if isinstance(ch, dict):
                        for subk, subv in ch.items():
                            add_node(it, subk, subv if isinstance(subv, dict) else {})
                except Exception:
                    pass

            # 填充资源树
            if isinstance(data, dict):
                # top-level keys
                for k, v in data.items():
                    try:
                        top = QtWidgets.QTreeWidgetItem([k])
                        top.setFlags(top.flags() | QtCore.Qt.ItemIsUserCheckable)
                        top.setCheckState(0, QtCore.Qt.Unchecked)
                        # 顶层编码
                        try:
                            code = None
                            if isinstance(v, dict):
                                code = v.get('code') or v.get('id')
                            if code is not None:
                                top.setData(0, QtCore.Qt.UserRole, str(code))
                        except Exception:
                            pass
                        resources_tree.addTopLevelItem(top)
                        # 子项
                        ch = v.get('children') if isinstance(v, dict) else None
                        if isinstance(ch, dict):
                            for subk, subv in ch.items():
                                add_node(top, subk, subv if isinstance(subv, dict) else {})
                    except Exception:
                        pass
            try:
                setattr(resources_tree, '_updating', False)
            except Exception:
                pass
        except Exception:
            pass

    def propagate_check(item, col):
        tw = item.treeWidget()
        # prevent re-entrant signal handling when we programmatically change states
        if getattr(tw, '_updating', False):
            return
        try:
            tw._updating = True
            state = item.checkState(col)
            if tw is region_tree:
                def clear_explicit(it):
                    try:
                        it.setData(0, region_explicit_role, False)
                    except Exception:
                        pass
                    for idx in range(it.childCount()):
                        clear_explicit(it.child(idx))

                if state == QtCore.Qt.Checked:
                    clear_explicit(item)
                    item.setData(0, region_explicit_role, True)
                elif state == QtCore.Qt.Unchecked:
                    clear_explicit(item)
            # set all children to the same state
            def set_children(it):
                for i in range(it.childCount()):
                    ch = it.child(i)
                    ch.setCheckState(0, state)
                    set_children(ch)
            set_children(item)
            # propagate upwards without causing children to be re-toggled
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
        finally:
            try:
                tw._updating = False
            except Exception:
                pass

    # 绑定树的信号处理（父子节点勾选联动）
    try:
        region_tree.itemChanged.connect(propagate_check)
        resources_tree.itemChanged.connect(propagate_check)
    except Exception:
        pass

    def toggle_task_select_all():
        # 切换任务列表中项目的勾选状态：若存在未勾选 -> 全选，否则全不选
        try:
            any_unchecked = False
            for i in range(task_list.count()):
                it = task_list.item(i)
                if it.checkState() != QtCore.Qt.Checked:
                    any_unchecked = True
                    break
            target = QtCore.Qt.Checked if any_unchecked else QtCore.Qt.Unchecked
            for i in range(task_list.count()):
                it = task_list.item(i)
                try:
                    it.setCheckState(target)
                except Exception:
                    pass
        except Exception:
            pass

    def on_region_item_expanded(item) -> None:
        """当城市节点被展开时，按需（懒加载）加载其下属区/县（若尚未加载）。"""
        try:
            # only proceed if this looks like a city (has a parent which is a province)
            parent = item.parent()
            if parent is None:
                return
            # already loaded marker
            if item.data(0, QtCore.Qt.UserRole) == 'loaded':
                return
            prov = parent.text(0)
            cit = item.text(0)
            gaode_key = current_cfg.get("api_keys", {}).get("gaode", "")
            subs = []
            try:
                subs = fetch_amap_subdistrict(gaode_key, prov, cit)
            except Exception:
                subs = []
            if not subs:
                # mark as loaded to avoid repeated attempts
                item.setData(0, QtCore.Qt.UserRole, 'loaded')
                return
            # add children nodes for counties (remove placeholder children first to avoid duplicates)
            tw = item.treeWidget()
            setattr(tw, '_updating', True)
            try:
                # clear existing children (e.g., placeholder "全部")
                while item.childCount() > 0:
                    item.removeChild(item.child(0))
                for c in subs:
                    cname = c.get('name') if isinstance(c, dict) else str(c)
                    if not cname:
                        continue
                    county_item = QtWidgets.QTreeWidgetItem([cname])
                    county_item.setFlags(county_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    county_item.setCheckState(0, QtCore.Qt.Unchecked)
                    item.addChild(county_item)
                item.setData(0, QtCore.Qt.UserRole, 'loaded')
            finally:
                try:
                    setattr(tw, '_updating', False)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        region_tree.itemExpanded.connect(on_region_item_expanded)
    except Exception:
        pass

    def update_selected_provinces():
        """从高德拉取指定省份的区域层次，并仅将这些省份合并到本地缓存中。

        该操作仅在用户手动点击“更新行政区”按钮时触发，避免程序启动时的自动联网。
        """
        gaode_key = current_cfg.get("api_keys", {}).get("gaode", "")
        if not gaode_key:
            append_log_msg("未配置高德 key，无法更新行政区。")
            return
        target = ["北京市", "天津市", "河北省", "山西省", "陕西省", "河南省", "湖北省"]

        def worker():
            try:
                # explicitly fetch from AMap (only on user action)
                fetched = fetch_and_save_region_hierarchy(cfg_path, gaode_key, target)
            except Exception:
                fetched = {}
            # fetched is normalized {prov: {city: [counties]}}, merge selected provinces
            updated = False
            for prov in target:
                if prov in fetched and fetched.get(prov):
                    region_data.setdefault(prov, {})
                    region_data[prov].update(fetched.get(prov))
                    updated = True
            if updated:
                # schedule UI update on main thread
                try:
                    QtCore.QTimer.singleShot(0, populate_region_tree)
                except Exception:
                    pass
                append_log_msg("已更新指定省份行政区并保存到缓存。")
            else:
                append_log_msg("未获取到目标省份数据。")

        threading.Thread(target=worker, daemon=True).start()

    try:
        btn_update_regions.clicked.connect(update_selected_provinces)
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
        """重新加载配置与区域缓存并重建地区树。

        确保每次用户刷新配置时，GUI 使用本地缓存（`region_cache.json` 或其归一化回退）
        来生成树结构，避免在界面刷新时发起网络请求。
        """
        nonlocal current_cfg, region_data, cfg_path
        try:
            cfg_path = config_edit.text()
        except Exception:
            pass
        # reload config if possible
        try:
            current_cfg = config_loader.load_config(cfg_path)
            current_cfg.setdefault("logs_path", "logs/poi_fetcher_logs.jsonl")
            current_cfg.setdefault("results_dir", "POI_Data")
            current_cfg.setdefault("max_concurrency", 1)
            current_cfg.setdefault("incremental", True)
        except Exception:
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    current_cfg = json.load(f)
            except Exception:
                current_cfg = current_cfg
        # 仅从本地缓存重建 region_data；不要在刷新/启动时写回 region_cache.json
        try:
            region_data = ensure_region_data(cfg_path, current_cfg.get("api_keys", {}).get("gaode", ""))
        except Exception:
            try:
                # fallback: try direct load of region_cache
                region_data = load_region_cache(get_region_cache_path(cfg_path)) or {}
            except Exception:
                region_data = {}
        # refresh task list (in case tasks changed) and UI tree
        try:
            refresh_task_list()
        except Exception:
            pass
        try:
            populate_region_tree()
        except Exception:
            pass

    def update_cities():
        # stub: no-op since per-task single-selection removed
        return

    def update_counties():
        # stub: no-op since per-task single-selection removed
        return

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
        # update enabled/disabled widgets based on loaded mode
        try:
            update_mode_ui()
        except Exception:
            pass
        # 不在主面板日志输出区显示历史日志（历史日志请使用“日志查询”选项卡查看）
        # record which task index is currently loaded in the editor
        nonlocal selected_task_index
        selected_task_index = idx
        # restore selected regions (admin_regions or admin_region)
        try:
            regions = t.get("admin_regions") or ([t.get("admin_region")] if t.get("admin_region") else [])
            # normalize list of dicts
            normr = []
            for r in regions:
                if not isinstance(r, dict):
                    continue
                pr = (r.get("province") or "").strip()
                ci = (r.get("city") or "").strip()
                co = (r.get("county") or "").strip()
                normr.append((pr, ci, co))
            try:
                setattr(region_tree, '_updating', True)
            except Exception:
                pass

            # clear all checks first
            def clear_checks(node):
                try:
                    node.setCheckState(0, QtCore.Qt.Unchecked)
                    node.setData(0, region_explicit_role, False)
                except Exception:
                    pass
                for i in range(node.childCount()):
                    clear_checks(node.child(i))

            for i in range(region_tree.topLevelItemCount()):
                clear_checks(region_tree.topLevelItem(i))

            # helper to find and check node by path
            def normalize_region_name(s: str) -> str:
                try:
                    if s is None:
                        return ""
                    x = str(s).strip()
                    # remove common administrative suffixes for fuzzy matching
                    for suf in ["省", "市", "自治区", "特别行政区", "自治州", "地区", "区", "县", "市辖区"]:
                        if x.endswith(suf):
                            x = x[: -len(suf)]
                    return x.strip().lower()
                except Exception:
                    return (s or "").strip().lower()

            def check_path(path_tuple):
                pr, ci, co = path_tuple
                npr = normalize_region_name(pr)
                nci = normalize_region_name(ci)
                nco = normalize_region_name(co)
                for pi in range(region_tree.topLevelItemCount()):
                    pitem = region_tree.topLevelItem(pi)
                    if normalize_region_name(pitem.text(0)) != npr:
                        continue
                    # province matched
                    # if city is empty or explicitly '全部', check whole province
                    if not ci or (isinstance(ci, str) and ci.strip() == '全部'):
                        pitem.setCheckState(0, QtCore.Qt.Checked)
                        pitem.setData(0, region_explicit_role, True)
                        return
                    # find city
                    for ci_idx in range(pitem.childCount()):
                        city_item = pitem.child(ci_idx)
                        if normalize_region_name(city_item.text(0)) != nci:
                            continue
                        # city matched
                        # if county is empty or explicitly '全部', check whole city
                        if not co or (isinstance(co, str) and co.strip() == '全部'):
                            city_item.setCheckState(0, QtCore.Qt.Checked)
                            city_item.setData(0, region_explicit_role, True)
                            return
                        # find county
                        for co_idx in range(city_item.childCount()):
                            county_item = city_item.child(co_idx)
                            if normalize_region_name(county_item.text(0)) == nco:
                                county_item.setCheckState(0, QtCore.Qt.Checked)
                                county_item.setData(0, region_explicit_role, True)
                                return
                        # if county not found, mark city as checked if county unspecified
                        return

            for p in normr:
                if p[0]:
                    check_path(p)

            # derive parent partial states from children
            def derive_parent(node):
                try:
                    explicit_checked = bool(node.data(0, region_explicit_role)) and node.checkState(0) == QtCore.Qt.Checked
                    if explicit_checked:
                        return True
                    if node.childCount() == 0:
                        return node.checkState(0) == QtCore.Qt.Checked
                    all_checked = True
                    any_checked = False
                    for j in range(node.childCount()):
                        ch = node.child(j)
                        child_checked = derive_parent(ch)
                        if child_checked:
                            any_checked = True
                        else:
                            all_checked = False
                    if all_checked:
                        node.setCheckState(0, QtCore.Qt.Checked)
                        return True
                    if any_checked:
                        node.setCheckState(0, QtCore.Qt.PartiallyChecked)
                        return True
                    node.setCheckState(0, QtCore.Qt.Unchecked)
                    return False
                except Exception:
                    return False

            for i in range(region_tree.topLevelItemCount()):
                try:
                    derive_parent(region_tree.topLevelItem(i))
                except Exception:
                    pass

            try:
                setattr(region_tree, '_updating', False)
            except Exception:
                pass
        except Exception:
            pass
        # restore provider and resources to task editor
        try:
            prov = t.get("provider")
            if prov:
                try:
                    provider_combo.setCurrentText(provider_value_to_display.get(prov, provider_combo.currentText()))
                except Exception:
                    pass
            # repopulate resources tree for this provider
            try:
                populate_resources_tree()
            except Exception:
                pass
            # check resources according to task (match any tree node by text recursively)
            try:
                task_res = t.get("resources", []) or []
                try:
                    setattr(resources_tree, '_updating', True)
                except Exception:
                    pass
                def norm(s):
                    try:
                        return (s or "").strip().replace('\ufeff', '')
                    except Exception:
                        return s

                def set_checked_from_task(node):
                    # set children first
                    for j in range(node.childCount()):
                        set_checked_from_task(node.child(j))
                    # if leaf, check if in task_res
                    try:
                        if node.childCount() == 0:
                            # determine whether task_res items are codes or names for this provider
                            try:
                                tprov = t.get("provider")
                            except Exception:
                                tprov = None
                            use_code = tprov in ("gaode", "tianditu")
                            node_code = None
                            try:
                                node_code = node.data(0, QtCore.Qt.UserRole)
                            except Exception:
                                node_code = None
                            if use_code and node_code is not None:
                                if norm(str(node_code)) in [norm(x) for x in task_res]:
                                    node.setCheckState(0, QtCore.Qt.Checked)
                                else:
                                    node.setCheckState(0, QtCore.Qt.Unchecked)
                            elif tprov == "baidu":
                                # task_res expected as list of dicts {'query':..., 'type':...} or legacy names
                                try:
                                    pairs = []
                                    for it in task_res:
                                        if isinstance(it, dict):
                                            pairs.append((norm(it.get('query','')), norm(it.get('type',''))))
                                        else:
                                            # legacy single-name entries: match child name
                                            pairs.append(("", norm(str(it))))
                                    parent = node.parent()
                                    pnorm = norm(parent.text(0)) if parent is not None else ""
                                    lnorm = norm(node.text(0))
                                    if (pnorm, lnorm) in pairs or ("", lnorm) in pairs:
                                        node.setCheckState(0, QtCore.Qt.Checked)
                                    else:
                                        node.setCheckState(0, QtCore.Qt.Unchecked)
                                except Exception:
                                    if norm(node.text(0)) in [norm(x) for x in task_res]:
                                        node.setCheckState(0, QtCore.Qt.Checked)
                                    else:
                                        node.setCheckState(0, QtCore.Qt.Unchecked)
                            else:
                                if norm(node.text(0)) in [norm(x) for x in task_res]:
                                    node.setCheckState(0, QtCore.Qt.Checked)
                                else:
                                    node.setCheckState(0, QtCore.Qt.Unchecked)
                        else:
                            # non-leaf: derive state from children
                            all_checked = True
                            any_checked = False
                            for k in range(node.childCount()):
                                s = node.child(k).checkState(0)
                                if s == QtCore.Qt.Checked:
                                    any_checked = True
                                else:
                                    all_checked = False
                            if all_checked:
                                node.setCheckState(0, QtCore.Qt.Checked)
                            elif any_checked:
                                node.setCheckState(0, QtCore.Qt.PartiallyChecked)
                            else:
                                node.setCheckState(0, QtCore.Qt.Unchecked)
                    except Exception:
                        pass
                for i in range(resources_tree.topLevelItemCount()):
                    set_checked_from_task(resources_tree.topLevelItem(i))
                try:
                    setattr(resources_tree, '_updating', False)
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def on_task_selected():
        idx = task_list.currentRow()
        if idx >= 0:
            load_task(idx)


    def save_config_ui():
        nonlocal executor
        # write global settings into current_cfg and save
        try:
            # map displayed provider name back to internal key
            try:
                sched_cfg = current_cfg.setdefault("scheduler", {})
                sched_cfg["check_interval_minutes"] = int(check_interval_spin.value())
            except Exception:
                current_cfg.setdefault("scheduler", {})
            current_cfg["incremental"] = bool(incr_check.isChecked())
            try:
                current_cfg["schedule_interval_days"] = int(sched_spin.value())
            except Exception:
                current_cfg["schedule_interval_days"] = int(current_cfg.get("schedule_interval_days", 1))
            current_cfg["max_concurrency"] = 1
            # resources are per-task now; do not save them as global here
            # ensure export format saved globally
            try:
                current_cfg["export_format"] = export_combo.currentText()
            except Exception:
                pass
            config_loader.save_config(config_edit.text(), current_cfg)
            # recreate executor if changed
            try:
                new_max = 1
                if getattr(executor, "_max_workers", None) != new_max:
                    try:
                        executor.shutdown(wait=False)
                    except Exception:
                # single-selection admin dropdowns removed; bbox fields preserved
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
            else:
                # single-selection dropdowns removed; admin will be set from region_tree selection
                admin = {"country": country_label.text(), "province": "", "city": "", "county": ""}
                # admin regions will be stored in 'admin_regions' only
                task["bbox"] = None
            # per-task provider
            try:
                prov_disp = provider_combo.currentText()
                prov_key = provider_display_to_value.get(prov_disp, prov_disp)
                task["provider"] = prov_key
            except Exception:
                pass
            # collect selected resources from resources_tree as final-level (leaf) nodes
            sel_resources = []
            try:
                def norm(s):
                    try:
                        return (s or "").strip().replace('\ufeff', '')
                    except Exception:
                        return s

                def collect_res_leaves(node):
                    out = []
                    if node.childCount() == 0:
                        if node.checkState(0) == QtCore.Qt.Checked:
                            # for providers with codes, prefer storing the code
                            try:
                                prov_disp_local = provider_combo.currentText()
                                prov_key_local = provider_display_to_value.get(prov_disp_local, prov_disp_local)
                                use_code = prov_key_local in ("gaode", "tianditu")
                            except Exception:
                                use_code = False
                            try:
                                node_code = node.data(0, QtCore.Qt.UserRole)
                            except Exception:
                                node_code = None
                            if use_code and node_code:
                                out.append(norm(node_code))
                            else:
                                out.append(norm(node.text(0)))
                    else:
                        for j in range(node.childCount()):
                            out.extend(collect_res_leaves(node.child(j)))
                    return out

                for i in range(resources_tree.topLevelItemCount()):
                    root = resources_tree.topLevelItem(i)
                    sel_resources.extend(collect_res_leaves(root))
                # dedupe while preserving order
                seen = set(); uniq = []
                for r in sel_resources:
                    if r not in seen:
                        seen.add(r); uniq.append(r)
                sel_resources = uniq
            except Exception:
                sel_resources = []
            # Provider-specific storage: gaode/tianditu store checked leaf codes, baidu store {query,type}
            try:
                prov = task.get("provider")
                if prov in ("gaode", "tianditu"):
                    # 仅保存已勾选叶子节点，优先保存 code
                    codes = []
                    for i in range(resources_tree.topLevelItemCount()):
                        def collect_codes(node):
                            out = []
                            if node.childCount() == 0:
                                if node.checkState(0) == QtCore.Qt.Checked:
                                    code = node.data(0, QtCore.Qt.UserRole)
                                    name = node.text(0)
                                    if code:
                                        out.append(str(code))
                                    else:
                                        out.append(norm(name))
                            else:
                                for j in range(node.childCount()):
                                    out.extend(collect_codes(node.child(j)))
                            return out
                        codes.extend(collect_codes(resources_tree.topLevelItem(i)))
                    # dedupe
                    seen = set(); uniq_codes = []
                    for c in codes:
                        if c not in seen:
                            seen.add(c); uniq_codes.append(c)
                    task["resources"] = uniq_codes
                elif prov == "baidu":
                    # store parent->child pairs as {'query': parent, 'type': child}
                    pairs = []
                    for i in range(resources_tree.topLevelItemCount()):
                        def collect_pairs(node):
                            out = []
                            if node.childCount() == 0:
                                parent = node.parent()
                                if parent is not None:
                                    out.append({"query": norm(parent.text(0)), "type": norm(node.text(0))})
                                else:
                                    out.append({"query": "", "type": norm(node.text(0))})
                            else:
                                for j in range(node.childCount()):
                                    out.extend(collect_pairs(node.child(j)))
                            return out
                        pairs.extend(collect_pairs(resources_tree.topLevelItem(i)))
                    # filter by selected leaves only
                    selected_pairs = []
                    for p in pairs:
                        # find node by parent/type and only include if checked
                        try:
                            # locate parent node
                            for ii in range(resources_tree.topLevelItemCount()):
                                top = resources_tree.topLevelItem(ii)
                                for jj in range(top.childCount()):
                                    par = top.child(jj)
                                    if norm(par.text(0)) == p.get("query"):
                                        for kk in range(par.childCount()):
                                            child = par.child(kk)
                                            if norm(child.text(0)) == p.get("type") and child.checkState(0) == QtCore.Qt.Checked:
                                                selected_pairs.append(p)
                        except Exception:
                            pass
                    task["resources"] = selected_pairs
                else:
                    task["resources"] = sel_resources
            except Exception:
                task["resources"] = sel_resources

            # collect selected regions from region_tree using the original UI selection semantics
            selected_regions = []
            try:
                direct_admin_provinces = {"北京市", "天津市", "上海市", "重庆市"}

                def append_region(province_name, city_name, county_name):
                    selected_regions.append({
                        "country": country_label.text(),
                        "province": province_name,
                        "city": city_name,
                        "county": county_name,
                    })

                def collect_original_selection(node, province_name="", city_name=""):
                    explicit = bool(node.data(0, region_explicit_role))
                    parent = node.parent()
                    text = node.text(0)
                    if explicit:
                        if parent is None:
                            if text in direct_admin_provinces and node.childCount() == 1:
                                city_item = node.child(0)
                                if city_item is not None and city_item.text(0):
                                    append_region(text, city_item.text(0), "全部")
                                    return
                            append_region(text, "", "")
                            return
                        if parent.parent() is None:
                            append_region(province_name, text, "全部")
                            return
                        append_region(province_name, city_name, text)
                        return
                    next_province = text if parent is None else province_name
                    next_city = text if parent is not None and parent.parent() is None else city_name
                    for idx in range(node.childCount()):
                        collect_original_selection(node.child(idx), province_name=next_province, city_name=next_city)

                for pi in range(region_tree.topLevelItemCount()):
                    collect_original_selection(region_tree.topLevelItem(pi))
            except Exception:
                selected_regions = []

            # consolidate selected regions into a single task using the original selection only
            try:
                if selected_regions:
                    task["admin_regions"] = selected_regions
                else:
                    task.pop("admin_regions", None)
                nonlocal selected_task_index
                idx = selected_task_index if selected_task_index is not None else task_list.currentRow()
                tasks = current_cfg.setdefault("tasks", [])
                if idx < 0:
                    tasks.append(task)
                else:
                    # replace existing task at idx
                    try:
                        tasks[idx] = task
                    except Exception:
                        # fallback to append
                        tasks.append(task)
            except Exception:
                pass
            # 同步保存导出格式为全局设置（在保存任务时也保存该全局偏好）
            try:
                current_cfg["export_format"] = export_combo.currentText()
            except Exception:
                pass
            config_loader.save_config(config_edit.text(), current_cfg)
            refresh_task_list()
            append_log_msg(f"已保存任务: {task['name']}")
        except Exception as e:
            append_log_msg(f"保存任务失败: {e}")

    def add_task_ui():
        nonlocal selected_task_index
        selected_task_index = -1
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
    area_type_combo.currentIndexChanged.connect(lambda _i: update_mode_ui())
    try:
        btn_select_tasks.clicked.connect(toggle_task_select_all)
    except Exception:
        pass
    try:
        provider_combo.currentIndexChanged.connect(lambda _i: populate_resources_tree())
    except Exception:
        pass
    btn_load.clicked.connect(lambda: (update_provinces(), populate_resources_tree(), append_log_msg("已加载配置")))
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
    # resources tree will be populated and checked by populate_resources_tree()
    export_combo.setCurrentText(str(current_cfg.get("export_format", export_combo.currentText())))
    page_spin.setValue(int(current_cfg.get("default_page_limit", page_spin.value())))
    province_expand_delay_spin.setValue(float(current_cfg.get("province_expand_delay_seconds", province_expand_delay_spin.value())))
    concurrency_spin.setValue(1)
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
    # populate trees so user can select regions and resources
    try:
        populate_region_tree()
    except Exception:
        pass
    try:
        populate_resources_tree()
    except Exception:
        pass
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

    if testing_hooks is not None:
        testing_hooks["app"] = app
        testing_hooks["win"] = win
        testing_hooks["widgets"] = {
            "task_name_edit": task_name_edit,
            "area_type_combo": area_type_combo,
            "provider_combo": provider_combo,
            "region_tree": region_tree,
            "task_list": task_list,
            "resources_tree": resources_tree,
            "bbox_left": bbox_left,
            "bbox_bottom": bbox_bottom,
            "bbox_right": bbox_right,
            "bbox_top": bbox_top,
        }
        testing_hooks["actions"] = {
            "save_task": save_task,
            "load_task": load_task,
            "populate_resources_tree": populate_resources_tree,
        }
        if testing_hooks.get("skip_event_loop", False):
            return

    win.show()
    app.exec_()
