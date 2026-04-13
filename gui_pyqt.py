try:
    from PyQt5 import QtWidgets, QtCore
except Exception:
    QtWidgets = None
    QtCore = None

from typing import Any, Dict
import queue
import threading
import json
import re
import concurrent.futures


def create_gui_pyqt(config_path: str) -> None:
    if QtWidgets is None:
        print("PyQt5 未安装。请通过 'pip install PyQt5' 安装后重试。")
        return

    # delay-import heavy application helpers to avoid circular import at module import time
    from map_poi_fetcher import (
        load_config,
        ensure_region_data,
        save_json,
        fetch_amap_subdistrict,
        get_task_area_summary,
        run_task,
        run_tasks,
        # load_logs is provided via poi_utils and exposed through map_poi_fetcher
        load_logs,
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
    hb.addWidget(btn_add)
    hb.addWidget(btn_delete)
    hb.addWidget(btn_run)
    hb.addWidget(btn_run_all)
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
    provider_display_to_value = {"百度": "baidu", "高德": "gaode", "腾讯": "tencent"}
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
    glob_layout.addRow("并发数：", concurrency_spin)
    glob_layout.addRow("省展开并发数：", province_expand_concurrency_spin)
    glob_layout.addRow("省展开延迟(秒)：", province_expand_delay_spin)
    glob_layout.addRow("调度检查间隔(分钟)：", check_interval_spin)
    glob_layout.addRow("分页限制：", page_spin)
    glob_layout.addRow("增量去重：", incr_check)
    glob_layout.addRow("调度间隔(天)：", sched_spin)
    tab_global_l.addWidget(glob_group)
    # add explicit save button inside global tab
    btn_save_global = QtWidgets.QPushButton("保存全局设置")
    tab_global_l.addWidget(btn_save_global)
    tabs.addTab(tab_global, "全局设置")

    right_l.addWidget(tabs)

    # logs
    logs = QtWidgets.QTextEdit(); logs.setReadOnly(True)
    right_l.addWidget(QtWidgets.QLabel("日志输出"))
    right_l.addWidget(logs, 1)

    splitter.addWidget(right_w)

    # load config and region data
    cfg_path = config_edit.text()
    current_cfg = load_config(cfg_path)
    region_data = ensure_region_data(cfg_path, current_cfg.get("api_keys", {}).get("gaode", ""))

    logs_queue: "queue.Queue[str]" = queue.Queue()
    # executor for PyQt GUI
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=int(current_cfg.get("max_concurrency", 1)))

    def append_log_msg(msg: str) -> None:
        # Called from main thread: also put into queue for consistency
        logs_queue.put(msg)

    def drain_logs() -> None:
        try:
            while True:
                msg = logs_queue.get_nowait()
                logs.append(msg)
        except Exception:
            pass

    timer = QtCore.QTimer()
    timer.timeout.connect(drain_logs)
    timer.start(300)

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
            # add '全部' option to allow fetching entire city when desired
            county_combo.addItem("全部")
            county_combo.addItems(region_data.get(prov, {}).get(cit, []))

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
        # display logs for this task (success/failure entries)
        try:
            display_task_logs(t.get("name", ""))
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
            save_json(config_edit.text(), current_cfg)
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
                task["admin_region"] = {"country": country_label.text(), "province": prov, "city": city, "county": county}
                task["bbox"] = None
            idx = task_list.currentRow()
            tasks = current_cfg.setdefault("tasks", [])
            if idx < 0:
                tasks.append(task)
            else:
                tasks[idx] = task
            save_json(config_edit.text(), current_cfg)
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
                save_json(config_edit.text(), current_cfg)
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
            save_json(config_edit.text(), current_cfg)
            refresh_task_list()
            append_log_msg(f"已删除任务: {t.get('name')}")
        except Exception as e:
            append_log_msg(f"删除任务失败: {e}")

    def worker_run_task(t: Dict[str, Any]) -> None:
        try:
            res = run_task(t, current_cfg, mode="manual")
            logs_queue.put(json.dumps(res, ensure_ascii=False))
        except Exception as e:
            logs_queue.put(f"任务运行失败: {e}")

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
        checked = get_checked_task_indices()
        if checked:
            for idx in checked:
                try:
                    t = current_cfg.get("tasks", [])[idx]
                except Exception:
                    continue
                try:
                    executor.submit(worker_run_task, t)
                except Exception:
                    threading.Thread(target=worker_run_task, args=(t,), daemon=True).start()
            return
        idx = task_list.currentRow()
        if idx < 0:
            logs_queue.put("请先选择任务。")
            return
        t = current_cfg.get("tasks", [])[idx]
        try:
            executor.submit(worker_run_task, t)
        except Exception:
            threading.Thread(target=worker_run_task, args=(t,), daemon=True).start()

    def worker_run_all():
        try:
            res = run_tasks(current_cfg.get("tasks", []), current_cfg, mode="manual")
            for r in res:
                logs_queue.put(json.dumps(r, ensure_ascii=False))
        except Exception as e:
            logs_queue.put(f"批量运行失败: {e}")

    def run_all_ui():
        try:
            executor.submit(worker_run_all)
        except Exception:
            threading.Thread(target=worker_run_all, daemon=True).start()

    # wire signals
    task_list.currentRowChanged.connect(lambda _i: on_task_selected())
    province_combo.currentIndexChanged.connect(lambda _i: update_cities())
    city_combo.currentIndexChanged.connect(lambda _i: update_counties())
    area_type_combo.currentIndexChanged.connect(lambda _i: update_mode_ui())
    btn_load.clicked.connect(lambda: (refresh_task_list(), update_provinces(), append_log_msg("已加载配置")))
    btn_save.clicked.connect(save_config_ui)
    btn_save_global.clicked.connect(save_config_ui)
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

    win.show()
    app.exec_()
