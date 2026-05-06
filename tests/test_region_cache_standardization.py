import json
from pathlib import Path

import map_poi_fetcher as mp
import gui_pyqt


def main() -> None:
    temp_dir = Path("config/test_region_cache_standardization")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text("{}", encoding="utf-8")
    cache_path.write_text(
        json.dumps(
            {
                "河北": {"石家庄": ["桥西区"]},
                "河北省": {"石家庄市": ["长安区"]},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    original_cache = cache_path.read_text(encoding="utf-8")
    region_data = mp.ensure_region_data(str(config_path), "")

    hebei = region_data.get("河北省", {})
    assert "石家庄市" in hebei, hebei
    assert "石家庄" not in hebei, hebei
    assert sorted(hebei["石家庄市"]) == ["桥西区", "长安区"], hebei
    assert cache_path.read_text(encoding="utf-8") == original_cache, "普通读取行政区缓存时不应改写 region_cache.json"

    unified = mp.unify_region_cache(str(config_path))
    unified_hebei = unified.get("河北省", {})
    assert "石家庄市" in unified_hebei, unified_hebei
    assert "石家庄" not in unified_hebei, unified_hebei
    assert sorted(unified_hebei["石家庄市"]) == ["桥西区", "长安区"], unified_hebei

    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    saved_hebei = saved.get("河北省", {})
    assert "石家庄市" in saved_hebei, saved_hebei
    assert "石家庄" not in saved_hebei, saved_hebei

    cache_path.unlink(missing_ok=True)
    config_path.unlink(missing_ok=True)
    temp_dir.rmdir()
    print("region cache standardization regression passed")


def test_fetch_and_save_region_hierarchy_enriches_counties() -> None:
    temp_dir = Path("config/test_region_cache_county_enrichment")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text("{}", encoding="utf-8")
    cache_path.write_text("{}", encoding="utf-8")

    orig_fetch_hierarchy = mp.fetch_amap_region_hierarchy
    orig_fetch_subdistrict = mp.fetch_amap_subdistrict
    mp.fetch_amap_region_hierarchy = lambda api_key: {
        "河北省": {
            "石家庄市": [],
            "唐山市": [],
        }
    }
    mp.fetch_amap_subdistrict = lambda api_key, province, city: [f"{city}A区", f"{city}B区"]
    try:
        merged = mp.fetch_and_save_region_hierarchy(str(config_path), "dummy", ["河北省"])
        hebei = merged.get("河北省", {})
        assert hebei.get("石家庄市") == ["石家庄市A区", "石家庄市B区"], hebei
        assert hebei.get("唐山市") == ["唐山市A区", "唐山市B区"], hebei

        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        saved_hebei = saved.get("河北省", {})
        assert saved_hebei.get("石家庄市") == ["石家庄市A区", "石家庄市B区"], saved_hebei
        assert saved_hebei.get("唐山市") == ["唐山市A区", "唐山市B区"], saved_hebei
    finally:
        mp.fetch_amap_region_hierarchy = orig_fetch_hierarchy
        mp.fetch_amap_subdistrict = orig_fetch_subdistrict
        cache_path.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)
        temp_dir.rmdir()


def test_gui_expand_city_updates_region_cache_to_county_level() -> None:
    temp_dir = Path("config/test_gui_expand_region_cache")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "poi_config.json"
    cache_path = temp_dir / "region_cache.json"

    config_path.write_text(
        json.dumps(
            {
                "api_keys": {"baidu": "", "gaode": "dummy", "tianditu": ""},
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
                    "石家庄市": []
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    orig_fetch_subdistrict = mp.fetch_amap_subdistrict
    mp.fetch_amap_subdistrict = lambda api_key, province, city: ["桥西区", "长安区"]
    try:
        hooks = {"skip_event_loop": True}
        gui_pyqt.create_gui_pyqt(str(config_path), hooks)
        region_tree = hooks["widgets"]["region_tree"]
        app = hooks["app"]

        province_item = region_tree.topLevelItem(0)
        city_item = province_item.child(0)
        region_tree.expandItem(city_item)
        app.processEvents()

        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        assert saved["河北省"]["石家庄市"] == ["桥西区", "长安区"], saved

        child_texts = [city_item.child(i).text(0) for i in range(city_item.childCount())]
        assert child_texts == ["桥西区", "长安区"], child_texts

        hooks["win"].close()
        hooks["app"].quit()
    finally:
        mp.fetch_amap_subdistrict = orig_fetch_subdistrict
        cache_path.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)
        temp_dir.rmdir()


if __name__ == "__main__":
    main()
    test_fetch_and_save_region_hierarchy_enriches_counties()
    test_gui_expand_city_updates_region_cache_to_county_level()