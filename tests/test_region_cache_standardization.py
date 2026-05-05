import json
from pathlib import Path

import map_poi_fetcher as mp


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


if __name__ == "__main__":
    main()