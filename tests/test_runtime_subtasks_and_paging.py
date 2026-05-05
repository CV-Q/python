import json
from pathlib import Path

import map_poi_fetcher as mp
import providers


def test_runtime_city_all_expansion() -> None:
    temp_dir = Path("config/test_runtime_subtasks")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text("{}", encoding="utf-8")
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

    calls = []

    def fake_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None, debug=False):
        calls.append(admin_region)
        return [
            {
                "id": f"{admin_region['county']}-1",
                "name": admin_region["county"],
                "address": "x",
                "contact": "",
                "latitude": 38.0,
                "longitude": 114.0,
                "source": provider,
            }
        ]

    orig_fetch = mp.fetch_provider_records
    mp.fetch_provider_records = fake_fetch
    try:
        config = {
            "api_keys": {"tianditu": "dummy"},
            "tasks": [],
            "_config_path": str(config_path),
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
            "name": "runtime_expand_city_all",
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
        }
        result = mp.run_task(task, config, mode="manual")
        assert result["status"] == "success", result
        assert [call["county"] for call in calls] == ["桥西区", "长安区"], calls
    finally:
        mp.fetch_provider_records = orig_fetch
        if cache_path.exists():
            cache_path.unlink()
        if config_path.exists():
            config_path.unlink()
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


def test_provider_paging_accumulates_all_results() -> None:
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.status_code = 200
            self.text = json.dumps(payload, ensure_ascii=False)

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    gaode_pages = {
        1: {"status": "1", "pois": [{"id": str(i), "name": f"g{i}", "location": "114.0,38.0", "address": "a", "tel": ""} for i in range(20)]},
        2: {"status": "1", "pois": [{"id": f"2-{i}", "name": f"g2-{i}", "location": "114.0,38.0", "address": "a", "tel": ""} for i in range(5)]},
    }
    tianditu_pages = {
        0: {"pois": [{"id": str(i), "name": f"t{i}", "lonlat": "114.0,38.0"} for i in range(20)]},
        20: {"pois": [{"id": f"20-{i}", "name": f"t20-{i}", "lonlat": "114.0,38.0"} for i in range(5)]},
    }

    orig_get = providers.requests.get
    orig_acquire = providers.rate_limiter.acquire

    def fake_get(url, params=None, timeout=20):
        if "amap.com" in url:
            return FakeResponse(gaode_pages.get(int(params.get("page", 1)), {"status": "1", "pois": []}))
        start = json.loads(params["postStr"])["start"]
        return FakeResponse(tianditu_pages.get(start, {"pois": []}))

    providers.requests.get = fake_get
    providers.rate_limiter.acquire = lambda provider: None
    try:
        gaode = providers.fetch_gaode("dummy", "医院", "120000", None, None, None, {"city": "石家庄市"}, page_limit=5)
        tianditu = providers.fetch_tianditu("dummy", "", "170101", None, None, None, {"adcode": "130100000"}, page_limit=5)
        assert len(gaode) == 25, len(gaode)
        assert len(tianditu) == 25, len(tianditu)
    finally:
        providers.requests.get = orig_get
        providers.rate_limiter.acquire = orig_acquire


def test_runtime_direct_admin_province_expands_to_counties() -> None:
    temp_dir = Path("config/test_runtime_subtasks_direct_admin")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text("{}", encoding="utf-8")
    cache_path.write_text(
        json.dumps(
            {
                "北京市": {
                    "北京城区": [
                        {"name": "东城区", "adcode": "110101"},
                        {"name": "西城区", "adcode": "110102"}
                    ]
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    calls = []

    def fake_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None, debug=False):
        calls.append(admin_region)
        return [
            {
                "id": f"{admin_region.get('county', '')}-1",
                "name": admin_region.get("county", ""),
                "address": "x",
                "contact": "",
                "latitude": 39.9,
                "longitude": 116.4,
                "source": provider,
            }
        ]

    orig_fetch = mp.fetch_provider_records
    mp.fetch_provider_records = fake_fetch
    try:
        config = {
            "api_keys": {"gaode": "dummy"},
            "tasks": [],
            "_config_path": str(config_path),
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
            "name": "runtime_expand_direct_admin_province",
            "enabled": True,
            "area_type": "admin",
            "provider": "gaode",
            "resources": ["010101"],
            "admin_regions": [
                {
                    "country": "中华人民共和国",
                    "province": "北京市",
                    "city": "",
                    "county": "",
                }
            ],
        }
        result = mp.run_task(task, config, mode="manual")
        assert result["status"] == "success", result
        assert [call["county"] for call in calls] == ["东城区", "西城区"], calls
        assert all(call["city"] == "北京城区" for call in calls), calls
    finally:
        mp.fetch_provider_records = orig_fetch
        if cache_path.exists():
            cache_path.unlink()
        if config_path.exists():
            config_path.unlink()
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


def main() -> None:
    test_runtime_city_all_expansion()
    test_provider_paging_accumulates_all_results()
    test_runtime_direct_admin_province_expands_to_counties()
    print("runtime subtasks and paging regression passed")


if __name__ == "__main__":
    main()