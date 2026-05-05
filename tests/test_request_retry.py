from pathlib import Path

import map_poi_fetcher as mp


def main() -> None:
    temp_dir = Path("config/test_request_retry")
    temp_dir.mkdir(parents=True, exist_ok=True)

    attempts = {"count": 0}

    def flaky_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None, debug=False):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return [
            {
                "id": "ok-1",
                "name": "ok",
                "address": "addr",
                "contact": "",
                "latitude": 38.0,
                "longitude": 114.0,
                "source": provider,
            }
        ]

    orig_fetch = mp.fetch_provider_records
    mp.fetch_provider_records = flaky_fetch
    try:
        config = {
            "api_keys": {"tianditu": "dummy"},
            "tasks": [],
            "results_dir": str(temp_dir / "results"),
            "logs_path": str(temp_dir / "logs.jsonl"),
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
            "name": "retry_task",
            "enabled": True,
            "area_type": "admin",
            "provider": "tianditu",
            "resources": ["170101"],
            "admin_regions": [
                {
                    "country": "中华人民共和国",
                    "province": "北京",
                    "city": "北京城区",
                    "county": "门头沟区",
                }
            ],
        }
        result = mp.run_task(task, config, mode="manual")
        assert attempts["count"] == 3, attempts
        assert result["status"] == "success", result
        assert result["records"] == 1, result
    finally:
        mp.fetch_provider_records = orig_fetch
        if (temp_dir / "logs.jsonl").exists():
            (temp_dir / "logs.jsonl").unlink()
        if (temp_dir / "results").exists():
            for child in (temp_dir / "results").rglob("*"):
                if child.is_file():
                    child.unlink()
            for child in sorted((temp_dir / "results").rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            (temp_dir / "results").rmdir()
        temp_dir.rmdir()
    print("request retry regression passed")


if __name__ == "__main__":
    main()