from pathlib import Path
import json

from poi_utils import bd09_to_gcj02, build_record_key, dedupe_records
import providers
import map_poi_fetcher as mp


def run():
    print("Integration smoke test start")
    # test poi_utils coordinate conversion
    lng, lat = 116.397, 39.908
    try:
        x, y = bd09_to_gcj02(lng, lat)
        print(f"bd09_to_gcj02: ({lng},{lat}) -> ({x:.6f},{y:.6f})")
    except Exception as e:
        print(f"bd09_to_gcj02 failed: {e}")

    # test dedupe
    rec1 = {"name": "A", "latitude": 39.908, "longitude": 116.397}
    rec2 = {"name": "A", "latitude": 39.9081, "longitude": 116.3971}
    recs = [rec1, rec2]
    deduped = dedupe_records(recs)
    print(f"dedupe_records: input={len(recs)} deduped={len(deduped)}")

    # test build_record_key
    k = build_record_key(rec1)
    print(f"build_record_key: {k}")

    # test config create/load
    cfg_path = Path("config/test_poi_config.json")
    if cfg_path.exists():
        cfg_path.unlink()
    cfg = mp.create_default_config(str(cfg_path))
    loaded = mp.load_config(str(cfg_path))
    print(f"config created and loaded, provider={loaded.get('provider')}")

    # providers.fetch_provider_records should exist but may raise without keys
    try:
        try:
            providers.fetch_provider_records('baidu', {'baidu': ''}, '加油站', 'gas_station', None, None, None, None, 1)
        except Exception as e:
            print(f"providers.fetch_provider_records raised (expected without keys): {e}")
    except Exception as e:
        print(f"providers module callable test failed: {e}")

    print("Integration smoke test completed")


if __name__ == '__main__':
    run()
