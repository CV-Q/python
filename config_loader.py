import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = {
    "api_keys": {"baidu": "", "gaode": "", "tianditu": ""},
}


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        # create parent if needed and write minimal default
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return DEFAULT_CONFIG.copy()
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        # Normalize legacy placement: some configs store 天地图 key under 'tencent'
        # Map it to 'tianditu' so callers can use a consistent key.
        try:
            ak = cfg.get("api_keys", {})
            if isinstance(ak, dict) and "tianditu" not in ak and "tencent" in ak:
                ak["tianditu"] = ak.get("tencent")
                cfg["api_keys"] = ak
        except Exception:
            pass
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(path: str, config: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_config_path(provider: str, base_path: str = "config/poi_config.json") -> str:
    """Return provider-specific config path. e.g. config/poi_config.tianditu.json"""
    p = Path(base_path)
    return str(p.parent / f"{p.stem}.{provider}{p.suffix}")


def load_provider_config(provider: str, base_path: str = "config/poi_config.json") -> Dict[str, Any]:
    """Load provider-specific config if exists, otherwise load base config."""
    prov_path = provider_config_path(provider, base_path)
    prov_p = Path(prov_path)
    if prov_p.exists():
        try:
            return json.loads(prov_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    # fallback to base
    return load_config(base_path)


def save_provider_config(provider: str, config: Dict[str, Any], base_path: str = "config/poi_config.json") -> None:
    prov_path = provider_config_path(provider, base_path)
    save_config(prov_path, config)
