import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gui_pyqt


def _find_tree_item(root, texts):
    if not texts:
        return None

    current = None
    for index, text in enumerate(texts):
        if index == 0:
            for i in range(root.topLevelItemCount()):
                item = root.topLevelItem(i)
                if item.text(0) == text:
                    current = item
                    break
        else:
            if current is None:
                return None
            found = None
            for i in range(current.childCount()):
                child = current.child(i)
                if child.text(0) == text:
                    found = child
                    break
            current = found
        if current is None:
            return None
    return current


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
    temp_dir = Path("config/test_gui_save_task_regions")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

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
    cache_path.write_text(
        json.dumps(
            {
                "河北省": {
                    "石家庄市": ["桥西区", "长安区"]
                }
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

    widgets["task_name_edit"].setText("gui_region_save")
    widgets["area_type_combo"].setCurrentText("行政区")
    widgets["provider_combo"].setCurrentText("天地图")
    actions["populate_resources_tree"]()

    resource_leaf = _find_leaf_by_text(widgets["resources_tree"], "综合医院")
    assert resource_leaf is not None, "资源树中应存在 综合医院"
    resource_leaf.setCheckState(0, gui_pyqt.QtCore.Qt.Checked)

    city_item = _find_tree_item(widgets["region_tree"], ["河北省", "石家庄市"])
    assert city_item is not None, "地区树中应存在 河北省/石家庄市"
    city_item.setCheckState(0, gui_pyqt.QtCore.Qt.Checked)

    actions["save_task"]()

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    task = saved["tasks"][0]
    assert task["admin_regions"] == [
        {
            "country": "中华人民共和国",
            "province": "河北省",
            "city": "石家庄市",
            "county": "全部",
        }
    ], task

    hooks["win"].close()
    hooks["app"].quit()
    config_path.unlink(missing_ok=True)
    cache_path.unlink(missing_ok=True)
    temp_dir.rmdir()
    print("gui save task regions regression passed")


if __name__ == "__main__":
    main()