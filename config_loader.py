import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = {
    "api_keys": {"baidu": "", "gaode": "", "tianditu": ""},
    "tasks": [],
    "auto_start": False,
    "scheduler": {"enabled": True, "check_interval_minutes": 15},
    "results_dir": "POI_Data",
    "logs_path": "logs/poi_fetcher_logs.jsonl",
    "export_format": "csv",
    "default_page_limit": 3,
    "incremental": True,
    "schedule_interval_days": 1,
    "max_concurrency": 1,
    "province_expand_delay_seconds": 1,
}

DEPRECATED_CONFIG_KEYS = {
    "keywords",
    "provider",
    "resources",
    "export_formats",
    "province_expand_concurrency",
}


def _deep_merge(defaults: Any, current: Any) -> Any:
    """Recursively merge current config into defaults."""
    if isinstance(defaults, dict):
        result = {}
        current_dict = current if isinstance(current, dict) else {}
        for k, v in defaults.items():
            if k in current_dict:
                result[k] = _deep_merge(v, current_dict[k])
            else:
                result[k] = _deep_merge(v, None)
        for k, v in current_dict.items():
            if k not in result:
                result[k] = v
        return result
    if isinstance(defaults, list):
        if isinstance(current, list):
            return current
        return list(defaults)
    return defaults if current is None else current


def _merge_with_defaults(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user config onto defaults while keeping user-provided values."""
    merged = _deep_merge(DEFAULT_CONFIG, cfg if isinstance(cfg, dict) else {})
    # ensure nested dict keeps all expected provider keys
    ak = merged.get("api_keys", {}) if isinstance(merged.get("api_keys"), dict) else {}
    default_ak = DEFAULT_CONFIG["api_keys"]
    normalized_ak = default_ak.copy()
    normalized_ak.update(ak)
    # Normalize legacy placement: some configs store 天地图 key under 'tencent'
    # Map it to 'tianditu' so callers can use a consistent key.
    if "tianditu" not in normalized_ak and "tencent" in normalized_ak:
        normalized_ak["tianditu"] = normalized_ak.get("tencent")
    merged["api_keys"] = normalized_ak
    for key in DEPRECATED_CONFIG_KEYS:
        merged.pop(key, None)
    return merged


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        # create parent if needed and write minimal default
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return _merge_with_defaults(DEFAULT_CONFIG)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        return _merge_with_defaults(cfg)
    except Exception:
        return _merge_with_defaults(DEFAULT_CONFIG)


def save_config(path: str, config: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = _merge_with_defaults(config if isinstance(config, dict) else {})
    p.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_config_path(provider: str, base_path: str = "config/poi_config.json") -> str:
    """Return the only supported config path.

    The project now uses a single config file and no longer writes
    provider-specific poi_config.*.json variants.
    """
    return str(Path(base_path))


def load_provider_config(provider: str, base_path: str = "config/poi_config.json") -> Dict[str, Any]:
    """Load the single shared config file."""
    return load_config(base_path)


def save_provider_config(provider: str, config: Dict[str, Any], base_path: str = "config/poi_config.json") -> None:
    """Save back to the single shared config file."""
    save_config(base_path, config)
