from map_poi_fetcher import run_task


def fake_fetch_provider_records(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit):
    print(f"fetch_provider_records called with admin_region={admin_region}")
    return []


def main():
    import map_poi_fetcher as mpf

    # monkeypatch the fetch_provider_records used by run_task
    mpf.fetch_provider_records = fake_fetch_provider_records

    # common config
    cfg = {
        "api_keys": {"baidu": "", "gaode": "", "tencent": ""},
        "resources": ["gas_station"],
        "keywords": {"gas_station": ["加油站"]},
        "default_page_limit": 1,
        "incremental": False,
        "results_dir": "POI_Data",
        "logs_path": "logs/poi_fetcher_logs.jsonl",
        "provider": "gaode",
    }

    # Case A: city == '' (表示 UI 选择 '全部' 在城市位置) -> should use province as region
    task_city_all = {"name": "city_all", "area_type": "admin", "admin_region": {"province": "河北", "city": "", "county": ""}}

    # Case B: county == '' (表示 UI 选择 '全部' 在区县位置) -> should use city as region
    task_county_all = {"name": "county_all", "area_type": "admin", "admin_region": {"province": "河北", "city": "石家庄", "county": ""}}

    print("--- Running task where city is saved as empty (city ALL) ---")
    print(run_task(task_city_all, cfg, mode="manual"))

    print("--- Running task where county is saved as empty (county ALL) ---")
    print(run_task(task_county_all, cfg, mode="manual"))


if __name__ == "__main__":
    main()
