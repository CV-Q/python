import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gui_pyqt


def _find_leaf_by_text(tree, text):
    def walk(node):
        if node.childCount() == 0 and node.text(0) == text:
            return node
        for index in range(node.childCount()):
            found = walk(node.child(index))
            if found is not None:
                return found
        return None

    for index in range(tree.topLevelItemCount()):
        found = walk(tree.topLevelItem(index))
        if found is not None:
            return found
    return None


def main() -> None:
    config_path = Path("config/test_gui_save_task_resources.json")
    config_path.write_text(
        json.dumps(
            {
                "api_keys": {"baidu": "", "gaode": "", "tianditu": ""},
                "tasks": [],
                "auto_start": False,
                "scheduler": {"enabled": True, "check_interval_minutes": 15},
                "results_dir": "POI_Data",
                "logs_path": "logs/poi_fetcher_logs.jsonl",
                "export_format": "csv",
                "default_page_limit": 1,
                "incremental": False,
                "schedule_interval_days": 1,
                "max_concurrency": 1,
                "province_expand_delay_seconds": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    hooks = {"skip_event_loop": True}
    gui_pyqt.create_gui_pyqt(str(config_path), hooks)

    widgets = hooks["widgets"]
    actions = hooks["actions"]

    widgets["task_name_edit"].setText("gui_resource_save")
    widgets["area_type_combo"].setCurrentText("多边形")
    widgets["provider_combo"].setCurrentText("天地图")
    actions["populate_resources_tree"]()

    polygon_points = [
        (116.0, 40.0),
        (117.0, 40.0),
        (117.0, 39.0),
        (116.0, 39.0),
    ]
    for index, (lng, lat) in enumerate(polygon_points):
        widgets["polygon_point_spins"][index]["lng"].setValue(lng)
        widgets["polygon_point_spins"][index]["lat"].setValue(lat)

    leaf = _find_leaf_by_text(widgets["resources_tree"], "综合医院")
    assert leaf is not None, "资源树中应存在 综合医院"
    leaf.setCheckState(0, gui_pyqt.QtCore.Qt.Checked)

    actions["save_task"]()

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    task = saved["tasks"][0]
    assert task["provider"] == "tianditu", task
    assert task["resources"] == ["170101"], task
    assert task["polygon"] == "116,40|117,40|117,39|116,39|116,40", task
    assert task["bbox"] == {"left": 116.0, "bottom": 39.0, "right": 117.0, "top": 40.0, "polygon": "116,40|117,40|117,39|116,39|116,40"}, task

    hooks["win"].close()
    hooks["app"].quit()
    config_path.unlink(missing_ok=True)
    print("gui save task resources regression passed")


if __name__ == "__main__":
    main()