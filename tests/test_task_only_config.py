from pathlib import Path

import config_loader
import map_poi_fetcher as mp


REMOVED_TOP_LEVEL_KEYS = {
    "keywords",
    "provider",
    "resources",
    "export_formats",
    "province_expand_concurrency",
}


def main() -> None:
    temp_path = Path("config/test_task_only_config.json")
    if temp_path.exists():
        temp_path.unlink()

    generated = config_loader.load_config(str(temp_path))
    assert temp_path.exists(), "首次加载不存在的配置文件时，应自动生成配置文件"
    present_removed = sorted(REMOVED_TOP_LEVEL_KEYS.intersection(generated.keys()))
    assert not present_removed, f"首次生成配置不应包含已删除的顶层字段: {present_removed}"

    captured = {}

    def fake_fetch_provider_records(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None, debug=False):
        captured["provider"] = provider
        captured["keyword"] = keyword
        captured["place_type"] = place_type
        captured["admin_region"] = admin_region
        return []

    mp.fetch_provider_records = fake_fetch_provider_records

    task_only_config = {
        "api_keys": {"tianditu": "dummy"},
        "tasks": [],
        "results_dir": "POI_Data",
        "logs_path": "logs/poi_fetcher_logs.jsonl",
        "export_format": "csv",
        "default_page_limit": 1,
        "incremental": False,
        "max_concurrency": 1,
        "province_expand_delay_seconds": 0,
        "scheduler": {"enabled": True, "check_interval_minutes": 15},
        "schedule_interval_days": 1,
        "auto_start": False,
    }
    task = {
        "name": "task_only_resource_resolution",
        "enabled": True,
        "area_type": "admin",
        "provider": "tianditu",
        "resources": ["综合医院"],
        "admin_regions": [
            {
                "country": "中华人民共和国",
                "province": "北京",
                "city": "北京城区",
                "county": "门头沟区",
            }
        ],
    }

    result = mp.run_task(task, task_only_config, mode="manual")
    assert result["status"] == "success", result
    assert captured.get("provider") == "tianditu", captured
    assert captured.get("place_type") == "170101", captured

    temp_path.unlink(missing_ok=True)
    print("task-only config regression passed")


if __name__ == "__main__":
    main()