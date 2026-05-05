from pathlib import Path
import threading
import time

import map_poi_fetcher as mp


def main() -> None:
    temp_dir = Path("config/test_serial_execution")
    temp_dir.mkdir(parents=True, exist_ok=True)

    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def fake_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None, debug=False):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        try:
            time.sleep(0.05)
            return [
                {
                    "id": admin_region["county"],
                    "name": admin_region["county"],
                    "address": "",
                    "contact": "",
                    "latitude": 38.0,
                    "longitude": 114.0,
                    "source": provider,
                }
            ]
        finally:
            with lock:
                state["current"] -= 1

    orig_fetch = mp.fetch_provider_records
    mp.fetch_provider_records = fake_fetch
    try:
        config = {
            "api_keys": {"tianditu": "dummy"},
            "tasks": [],
            "results_dir": str(temp_dir / "results"),
            "logs_path": str(temp_dir / "logs.jsonl"),
            "export_format": "csv",
            "default_page_limit": 1,
            "incremental": False,
            "max_concurrency": 8,
            "province_expand_delay_seconds": 0,
            "scheduler": {"enabled": True, "check_interval_minutes": 15},
            "schedule_interval_days": 1,
            "auto_start": False,
        }
        task = {
            "name": "serial_only",
            "enabled": True,
            "area_type": "admin",
            "provider": "tianditu",
            "resources": ["170101"],
            "admin_regions": [
                {"country": "中华人民共和国", "province": "河北省", "city": "石家庄市", "county": "桥西区"},
                {"country": "中华人民共和国", "province": "河北省", "city": "石家庄市", "county": "长安区"},
            ],
        }
        result = mp.run_task(task, config, mode="manual")
        assert result["status"] == "success", result
        assert state["max"] == 1, state
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
    print("serial execution regression passed")


if __name__ == "__main__":
    main()