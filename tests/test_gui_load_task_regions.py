import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gui_pyqt


def _find_tree_item(root, texts):
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


def main() -> None:
    temp_dir = Path("config/test_gui_load_task_regions")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text(
        json.dumps(
            {
                "api_keys": {"baidu": "", "gaode": "", "tianditu": ""},
                "tasks": [
                    {
                        "name": "province_scope",
                        "enabled": True,
                        "area_type": "admin",
                        "provider": "tianditu",
                        "resources": ["170101"],
                        "admin_regions": [
                            {
                                "country": "中华人民共和国",
                                "province": "河北省",
                                "city": "",
                                "county": "",
                            }
                        ],
                    },
                    {
                        "name": "city_scope",
                        "enabled": True,
                        "area_type": "admin",
                        "provider": "tianditu",
                        "resources": ["170101"],
                        "admin_regions": [
                            {
                                "country": "中华人民共和国",
                                "province": "河北省",
                                "city": "石家庄市",
                                "county": "全部",
                            }
                        ],
                    },
                ],
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
                    "石家庄市": ["桥西区", "长安区"],
                    "唐山市": ["路南区"],
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

    region_tree = widgets["region_tree"]
    task_list = widgets["task_list"]

    province_item = _find_tree_item(region_tree, ["河北省"])
    city_item = _find_tree_item(region_tree, ["河北省", "石家庄市"])
    assert province_item is not None
    assert city_item is not None

    task_list.setCurrentRow(0)
    assert province_item.checkState(0) == gui_pyqt.QtCore.Qt.Checked, province_item.checkState(0)
    assert city_item.checkState(0) == gui_pyqt.QtCore.Qt.Unchecked, city_item.checkState(0)

    task_list.setCurrentRow(1)
    assert province_item.checkState(0) == gui_pyqt.QtCore.Qt.PartiallyChecked, province_item.checkState(0)
    assert city_item.checkState(0) == gui_pyqt.QtCore.Qt.Checked, city_item.checkState(0)

    hooks["win"].close()
    hooks["app"].quit()
    config_path.unlink(missing_ok=True)
    cache_path.unlink(missing_ok=True)
    temp_dir.rmdir()
    print("gui load task regions regression passed")


if __name__ == "__main__":
    main()