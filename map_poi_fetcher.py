import argparse
import csv
import json
from typing import Any, Dict, List, Optional, Tuple
import math
from datetime import datetime, timedelta
import concurrent.futures as concurrent
import queue
import time
import threading
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from math import radians, cos, sin, asin, sqrt
from poi_utils import (
    save_to_csv,
    save_to_json,
    save_to_excel,
    append_log,
    load_logs,
    export_logs,
    build_record_key,
    dedupe_records,
    bd09_to_gcj02,
    normalize_record,
    merge_keywords,
    get_city_center,
    append_new_records,
    make_log_entry,
    format_time,
    normalize_area,
)
import config_loader
from providers import fetch_provider_records
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    raise ImportError("requests is required. Run 'pip install requests'.")

try:
    import openpyxl
except ImportError:
    openpyxl = None

# tkinter usage has been removed to avoid requiring a Tkinter dependency.
# See archive/gui_tk_backup.py for the original implementation if needed.
tk = None

try:
    from PyQt5 import QtWidgets, QtCore
except Exception:
    QtWidgets = None
    QtCore = None
try:
    from providers import fetch_provider_records, fetch_baidu, fetch_gaode, fetch_tencent
except Exception:
    # providers module may be created during refactor; fallback to names if present
    pass

# --- Constants ---
SUPPORTED_PROVIDERS = ["baidu", "gaode", "tianditu"]
RESOURCE_TYPES = ["gas_station", "service_area", "hospital", "repair_factory"]
DEFAULT_KEYWORDS = {
    "gas_station": ["加油站"],
    "service_area": ["服务区"],
    "hospital": ["医院"],
    "repair_factory": ["维修工厂", "汽车修理厂"],
}
AMAP_TYPE_MAP = {
    "hospital": "120000",
    "gas_station": "050700",
}

# Provider display names for logs/UI
PROVIDER_DISPLAY = {"baidu": "百度", "gaode": "高德", "tianditu": "天地图"}
DEFAULT_FIELDS = [
    "source",
    "id",
    "name",
    "address",
    "latitude",
    "longitude",
    "type",
    "contact",
    "task",
    "run_time",
]

REGION_DATA = {
    "北京": ["北京市"],
    "天津": ["天津市"],
    "河北": ["石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水"],
    "山西": ["太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁"],
    "陕西": ["西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛"],
    "河南": ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"],
    "湖北": ["武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江", "天门", "神农架"],
}

CITY_COORDINATES = {
    "石家庄": (38.0428, 114.5149),
    "唐山": (39.6305, 118.1800),
    "保定": (38.8739, 115.4643),
    "邯郸": (36.6256, 114.5384),
    "沧州": (38.3044, 116.8388),
    "衡水": (37.7388, 115.6768),
    "邢台": (37.0682, 114.5049),
    "秦皇岛": (39.9354, 119.5996),
    "张家口": (40.8244, 114.8876),
    "承德": (40.9529, 117.9630),
    "廊坊": (39.5209, 116.7037),
    "太原": (37.8706, 112.5489),
    "西安": (34.3416, 108.9398),
    "郑州": (34.7466, 113.6254),
    "武汉": (30.5928, 114.3055),
}

DEFAULT_CONFIG = {
    "api_keys": {"baidu": "", "gaode": "", "tianditu": ""},
    "keywords": DEFAULT_KEYWORDS,
    "tasks": [],
    "auto_start": False,
    "scheduler": {"enabled": True, "check_interval_minutes": 15},
    "results_dir": "POI_Data",
    "logs_path": "logs/poi_fetcher_logs.jsonl",
    # global defaults (single provider, single export format, resources list, paging, incremental, schedule interval)
    "provider": SUPPORTED_PROVIDERS[0],
    "resources": ["gas_station"],
    "export_format": "csv",
    "export_formats": ["csv", "json", "excel"],
    "default_page_limit": 3,
    "incremental": True,
    "schedule_interval_days": 1,
    "max_concurrency": 3,
    # when expanding a province into per-city requests (UI '全部' at city level),
    # control how many city-requests run concurrently and minimal delay between requests
    "province_expand_concurrency": 1,
    "province_expand_delay_seconds": 1,
}

X_PI = math.pi * 3000.0 / 180.0

# --- Utility functions ---

def ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_json(path: str) -> Any:
    if not Path(path).exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_default_config(path: str) -> Dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config


def load_config_file(path: str) -> Dict[str, Any]:
    try:
        return load_config(path)
    except Exception:
        return create_default_config(path)


def get_region_cache_path(config_path: str) -> str:
    p = Path(config_path)
    cache_dir = p.parent if p.parent.exists() else Path("config")
    return str(cache_dir / "region_cache.json")


def load_region_cache(path: str) -> Dict[str, Any]:
    try:
        if Path(path).exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return {}
    return {}


def save_region_cache(path: str, data: Any) -> None:
    try:
        ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch_amap_subdistrict(gaode_key: str, province: str, city: str) -> List[str]:
    """Fetch subdistrict (counties) of a given city from AMap (高德).
    Returns list of dicts: {"name": <name>, "adcode": <adcode>, "polyline": <polyline or empty>}.
    Falls back to list of names for backward compatibility.
    """
    if not gaode_key:
        return []
    try:
        params = {"key": gaode_key, "keywords": city or province, "subdistrict": 1, "extensions": "base"}
        resp = requests.get("https://restapi.amap.com/v3/config/district", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            return []
        districts = data.get("districts", [])
        if not districts:
            return []
        # navigate into subdistricts
        first = districts[0]
        sub = first.get("districts", [])
        out = []
        for d in sub:
            if not d:
                continue
            name = d.get("name") or ""
            adcode = d.get("adcode") or d.get("citycode") or ""
            polyline = d.get("polyline") or ""
            if name:
                out.append({"name": name, "adcode": adcode, "polyline": polyline})
        return out
    except Exception:
        return []


def fetch_amap_region_hierarchy(api_key: str) -> Dict[str, Any]:
    """Attempt to fetch a two-level region hierarchy from AMap."""
    if not api_key:
        return {}
    try:
        params = {"key": api_key, "keywords": "中国", "subdistrict": 2, "extensions": "base"}
        resp = requests.get("https://restapi.amap.com/v3/config/district", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            return {}
        districts = data.get("districts", [])
        if not districts:
            return {}
        # first element should be the country -> provinces
        country = districts[0]
        out: Dict[str, Dict[str, List[str]]] = {}
        for prov in country.get("districts", []):
            prov_name = prov.get("name", "")
            out[prov_name] = {}
            for city in prov.get("districts", []):
                city_name = city.get("name", "")
                counties = [c.get("name", "") for c in city.get("districts", []) if c.get("name")]
                out[prov_name][city_name] = counties
        return out
    except Exception:
        return {}

def ensure_region_data(config_path: str, api_key: str) -> Dict[str, Dict[str, List[str]]]:
    cache_path = get_region_cache_path(config_path)
    cache = load_region_cache(cache_path)
    # normalize cache structure so that result is {province: {city: [counties...]}}
    def normalize(raw: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
        if not isinstance(raw, dict):
            return {}
        # If top-level is a single country key (e.g. '中华人民共和国'), unwrap it.
        # Also handle the case where the country key maps to a LIST of province names
        # (some cached formats use that), by converting it to a province->{} map.
        if len(raw) == 1:
            first = next(iter(raw))
            if first in ("中国", "中华人民共和国"):
                val = raw[first]
                if isinstance(val, dict):
                    raw = val
                elif isinstance(val, list):
                    raw = {str(prov): {} for prov in val}
        out: Dict[str, Dict[str, List[str]]] = {}
        for prov, val in raw.items():
            # if value is a list of city names, convert to {city: []}
            if isinstance(val, list):
                out[prov] = {str(city): [] for city in val}
            elif isinstance(val, dict):
                # if inner dict maps city -> list (counties) keep, else coerce
                inner: Dict[str, List[str]] = {}
                for city, sub in val.items():
                    if isinstance(sub, list):
                        inner[str(city)] = [str(x) for x in sub]
                    else:
                        inner[str(city)] = []
                out[prov] = inner
            else:
                out[prov] = {}
        return out

    if cache:
        return normalize(cache)

    try:
        fetched = fetch_amap_region_hierarchy(api_key)
        normalized = normalize(fetched)
        try:
            save_region_cache(cache_path, fetched)
        except Exception:
            pass
        return normalized
    except Exception:
        fallback: Dict[str, Dict[str, List[str]]] = {}
        for province, cities in REGION_DATA.items():
            fallback[province] = {city: [] for city in cities}
        return fallback



def build_area_description(task: Dict[str, Any]) -> str:
    if task.get("area_type") == "bbox":
        bbox = task.get("bbox", {})
        return f"bbox({bbox.get('left')},{bbox.get('top')},{bbox.get('right')},{bbox.get('bottom')})"
    admin = task.get("admin_region", {})
    return normalize_area(f"{admin.get('province','')} / {admin.get('city','')} / {admin.get('county','')}")


def task_target_values(task: Dict[str, Any]) -> Dict[str, Any]:
    if task.get("area_type") == "bbox":
        return {"bbox": task.get("bbox", {}), "latitude": None, "longitude": None}
    # 对于行政区任务，不再使用中心+半径查询；由 provider 使用 admin_region 的 city/province 执行区域内搜索
    return {"bbox": None, "latitude": None, "longitude": None}


def get_task_area_summary(task: Dict[str, Any]) -> str:
    if task.get("area_type") == "bbox":
        bbox = task.get("bbox", {})
        return f"BBox {bbox.get('left')} , {bbox.get('bottom')} -> {bbox.get('right')} , {bbox.get('top')}"
    admin = task.get("admin_region", {})
    return normalize_area(f"{admin.get('province','')} / {admin.get('city','')} / {admin.get('county','')}")


def format_time(dt: Optional[datetime]) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""




# provider implementations moved to providers.py


# provider implementations moved to providers.py


# provider implementations moved to providers.py


try:
    # prefer imported provider implementation
    fetch_provider_records  # type: ignore
except Exception:
    # fallback: simple lookup to avoid NameError during refactor
    def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
        raise RuntimeError('providers.fetch_provider_records not available')





def load_existing_keys(results_dir: str) -> set:
    keys = set()
    path = Path(results_dir)
    if not path.exists():
        return keys
    for file_path in path.iterdir():
        if file_path.suffix.lower() == ".csv":
            with file_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    keys.add(build_record_key(row))
        elif file_path.suffix.lower() == ".json":
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for row in data:
                        keys.add(build_record_key(row))
            except Exception:
                continue
    return keys


# utility functions moved to poi_utils.py


def run_task(task: Dict[str, Any], config: Dict[str, Any], mode: str = "manual", progress_callback=None, stop_event=None) -> Dict[str, Any]:
    run_time = format_time(datetime.now())
    task_name = task.get("name", task.get("task_name", "unnamed_task"))
    area = get_task_area_summary(task)
    page_limit = int(config.get("default_page_limit", 3))

    # prepare incremental output path and existing keys set for incremental writes
    base_dir = Path(config.get("results_dir", "POI_Data"))
    date_folder = datetime.now().strftime("%Y-%m-%d")
    result_dir = base_dir / date_folder
    incremental_path = result_dir / f"{task_name}_incremental.csv"
    existing_keys = set()
    if config.get("incremental", True):
        try:
            existing_keys = load_existing_keys(config.get("results_dir", "POI_Data"))
        except Exception:
            existing_keys = set()

    # determine providers
    prov = config.get("provider")
    if isinstance(config.get("providers"), list) and config.get("providers"):
        providers = config.get("providers")
    elif prov:
        providers = [prov]
    else:
        providers = SUPPORTED_PROVIDERS

    if task.get("area_type") == "admin" and not task.get("admin_region"):
        raise ValueError("行政区域任务必须包含 admin_region 配置。")
    if task.get("area_type") == "bbox" and not task.get("bbox"):
        raise ValueError("BBox 任务必须包含 bbox 配置。")

    # resources: iterate one resource at a time to ensure single-resource-per-request
    resources = config.get("resources", [])
    if not isinstance(resources, list):
        resources = [resources]

    def build_keywords_for_resource(resource_item):
        try:
            if isinstance(resource_item, str) and (resource_item in config.get("keywords", {}) or resource_item in RESOURCE_TYPES):
                return merge_keywords(config, resource_item)
            else:
                return [p.strip() for p in re.split(r"[,，]", str(resource_item)) if p.strip()]
        except Exception:
            return [p.strip() for p in re.split(r"[,，]", str(resource_item)) if p.strip()]

    records: List[Dict[str, Any]] = []

    def emit_progress_lines(title: str = None, line1: str = None, line2: str = None):
        """向 progress_callback 发送三行摘要（为可读性而非原始 JSON）：
        - title: 任务头，格式：TaskName - 区域 - 资源 - 提供商
        - line1: 子任务第一行，格式：区域-资源名
        - line2: 子任务第二行，显示执行结果或错误/数量
        发送类型分别为 summary_title/summary_query/summary_status，UI 端可按行处理显示。
        """
        if not progress_callback:
            return
        try:
            if title is not None:
                progress_callback({"type": "summary_title", "message": title})
            if line1 is not None:
                progress_callback({"type": "summary_query", "message": line1})
            if line2 is not None:
                progress_callback({"type": "summary_status", "message": line2})
        except Exception:
            pass

    # rate limiting
    rate_lock = threading.Lock()
    last_call = {"t": 0.0}
    global_delay = float(config.get("province_expand_delay_seconds", 0.0))

    import rate_limiter

    def fetch_with_delay(provider_arg, api_keys_arg, keyword_arg, resource_type_arg, latitude_arg, longitude_arg, bbox_arg, admin_region_arg, page_limit_arg, stop_event=None):
        # global minimal delay between requests (keeps province expansion gentle)
        with rate_lock:
            now = time.time()
            wait = max(0.0, global_delay - (now - last_call["t"]))
            if wait > 0:
                time.sleep(wait)
            last_call["t"] = time.time()
        # per-provider rate limiter (token-bucket, default 1 qps)
        try:
            rate_limiter.acquire(provider_arg)
        except Exception:
            # if limiter fails, fall back to a conservative sleep
            time.sleep(max(1.0, global_delay))
        # debug: show what admin_region is being passed
        try:
            print(f"[DEBUG] fetch_with_delay provider={provider_arg} admin_region={admin_region_arg} keyword={keyword_arg} resource={resource_type_arg}")
        except Exception:
            pass
        res = fetch_provider_records(
            provider_arg,
            api_keys_arg,
            keyword_arg,
            resource_type_arg,
            latitude_arg,
            longitude_arg,
            bbox_arg,
            admin_region_arg,
            page_limit_arg,
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
        # If provider-specific config does not exist, generate a minimal provider config after successful first response
        try:
            if res:
                prov_path = config_loader.provider_config_path(provider_arg, "config/poi_config.json")
                from pathlib import Path as _P
                if provider_arg not in created_provider_configs and not _P(prov_path).exists():
                    minimal = {
                        "api_keys": {provider_arg: api_keys.get(provider_arg, "")},
                        "resources": config.get("resources", []),
                        "keywords": config.get("keywords", {}),
                        "provider": provider_arg,
                    }
                    try:
                        config_loader.save_provider_config(provider_arg, minimal, "config/poi_config.json")
                        created_provider_configs.add(provider_arg)
                        append_log(config.get("logs_path"), make_log_entry(task_name, run_time, normalize_area(str(admin_region_arg)), "info", records=0, provider=PROVIDER_DISPLAY.get(provider_arg, provider_arg), message=f"已生成 provider 配置: {prov_path}"))
                    except Exception:
                        pass
        except Exception:
            pass
        return res

    def bbox_from_polyline(polyline: str) -> Optional[Dict[str, float]]:
        try:
            if not polyline:
                return None
            pts = [p.split(',') for p in polyline.split(';') if p]
            lons = [float(p[0]) for p in pts if len(p) >= 2]
            lats = [float(p[1]) for p in pts if len(p) >= 2]
            if not lons or not lats:
                return None
            return {"left": min(lons), "right": max(lons), "bottom": min(lats), "top": max(lats)}
        except Exception:
            return None

    def generate_grid(bbox: Dict[str, float], nx: int = 2, ny: int = 2) -> List[Dict[str, float]]:
        out = []
        if not bbox:
            return out
        left, right, bottom, top = bbox["left"], bbox["right"], bbox["bottom"], bbox["top"]
        dx = (right - left) / max(1, nx)
        dy = (top - bottom) / max(1, ny)
        for i in range(nx):
            for j in range(ny):
                l = left + i * dx
                r = left + (i + 1) * dx
                b = bottom + j * dy
                t = bottom + (j + 1) * dy
                out.append({"left": l, "right": r, "bottom": b, "top": t})
        return out

    api_keys = config.get("api_keys", {})
    created_provider_configs = set()

    for resource in resources:
        keywords = list(dict.fromkeys(build_keywords_for_resource(resource)))
        for keyword in keywords:
            for provider in providers:
                if task.get("area_type") == "admin":
                    admin = task.get("admin_region", {})
                    prov_name = admin.get("province", "")
                    cit = admin.get("city", None)
                    cnty = admin.get("county", None)

                # province-level expand: iterate cities
                if cit == "":
                    try:
                        cache = load_region_cache(get_region_cache_path("config/poi_config.json"))
                    except Exception:
                        cache = {}
                    cities_list: List[str] = []
                    if isinstance(cache, dict) and prov_name in cache:
                        val = cache[prov_name]
                        if isinstance(val, list):
                            cities_list = [str(x) for x in val]
                        elif isinstance(val, dict):
                            cities_list = list(val.keys())
                    if not cities_list and prov_name in REGION_DATA:
                        cities_list = list(REGION_DATA.get(prov_name, []))
                    if not cities_list:
                        cities_list = [""]

                    for city_name in cities_list:
                        if progress_callback:
                            try:
                                progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": city_name, "level": "city", "provider": provider})
                            except Exception:
                                pass
                            # 额外发送三行摘要：任务名 / 查询(关键词/资源/区域) / 执行状态
                            emit_progress_lines(
                                title=f"{task_name} - {prov_name}/{city_name} - {resource} - {provider}",
                                line1=f"{prov_name}/{city_name} - {resource}",
                                line2="开始",
                            )
                        try:
                            provider_records = fetch_with_delay(
                                provider,
                                api_keys,
                                keyword,
                                resource,
                                None,
                                None,
                                None,
                                {"province": prov_name, "city": city_name, "county": ""},
                                page_limit,
                                stop_event=stop_event,
                            )
                        except Exception as exc:
                            append_log(config["logs_path"], {
                                "task_name": task_name,
                                "run_time": run_time,
                                "area": normalize_area(f"{prov_name} / {city_name} / "),
                                "provider": PROVIDER_DISPLAY.get(provider, provider),
                                "status": "failed",
                                "records": 0,
                                "mode": mode,
                                "message": f"子区域抓取失败: {exc}",
                            })
                            if progress_callback:
                                try:
                                    progress_callback({"type": "subtask_failed", "task_name": task_name, "province": prov_name, "city": city_name, "level": "city", "provider": provider, "message": str(exc)})
                                except Exception:
                                    pass
                                emit_progress_lines(
                                    title=f"{task_name} - {prov_name}/{city_name} - {resource} - {provider}",
                                    line1=f"{prov_name}/{city_name} - {resource}",
                                    line2=f"失败: {exc}",
                                )
                            provider_records = []

                        for item in provider_records:
                            records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                        if progress_callback:
                            try:
                                progress_callback({"type": "subtask_done", "task_name": task_name, "province": prov_name, "city": city_name, "level": "city", "provider": provider, "count": len(provider_records)})
                            except Exception:
                                pass
                            emit_progress_lines(
                                title=f"{task_name} - {prov_name}/{city_name} - {resource} - {provider}",
                                line1=f"{prov_name}/{city_name} - {resource}",
                                line2=f"成功, 数据数量: {len(provider_records)}",
                            )
                        # incremental append
                        try:
                            if config.get("incremental", True) and provider_records:
                                new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in provider_records]
                                appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                                append_log(config["logs_path"], make_log_entry(task_name, run_time, f"{prov_name} / {city_name}", "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
                        except Exception:
                            pass
                    continue

                # city-level expand: iterate counties
                if cit and cnty == "":
                    try:
                        cache = load_region_cache(get_region_cache_path("config/poi_config.json"))
                    except Exception:
                        cache = {}
                    counties_list: List[str] = []
                    if isinstance(cache, dict) and prov_name in cache:
                        val = cache[prov_name]
                        if isinstance(val, dict) and cit in val:
                            counties_list = [str(x) for x in val.get(cit, [])]
                    if not counties_list:
                        gaode_key = api_keys.get("gaode", "")
                        counties_list = fetch_amap_subdistrict(gaode_key, prov_name, cit)
                    if not counties_list:
                        counties_list = [""]

                    for county_name in counties_list:
                        # support counties_list items that may be dicts with adcode
                        county_display = county_name.get("name") if isinstance(county_name, dict) else county_name
                        county_adcode = county_name.get("adcode") if isinstance(county_name, dict) else ""
                        if progress_callback:
                            try:
                                progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "county", "provider": provider})
                            except Exception:
                                pass
                            emit_progress_lines(
                                title=f"{task_name} - {prov_name}/{cit}/{county_display} - {resource} - {provider}",
                                line1=f"{prov_name}/{cit}/{county_display} - {resource}",
                                line2="开始",
                            )
                        try:
                            admin_region_param = {"province": prov_name, "city": cit, "county": county_display}
                            if county_adcode:
                                # include adcode for provider to use precise county query
                                admin_region_param["adcode"] = county_adcode
                            provider_records = fetch_with_delay(
                                provider,
                                api_keys,
                                keyword,
                                resource,
                                None,
                                None,
                                None,
                                admin_region_param,
                                page_limit,
                                stop_event=stop_event,
                            )
                        except Exception as exc:
                            append_log(config["logs_path"], {
                                "task_name": task_name,
                                "run_time": run_time,
                                "area": normalize_area(f"{prov_name} / {cit} / {county_display}"),
                                "provider": PROVIDER_DISPLAY.get(provider, provider),
                                "status": "failed",
                                "records": 0,
                                "mode": mode,
                                "message": f"子区域抓取失败: {exc}",
                            })
                            if progress_callback:
                                try:
                                    progress_callback({"type": "subtask_failed", "task_name": task_name, "province": prov_name, "city": cit, "county": county_name, "level": "county", "provider": provider, "message": str(exc)})
                                except Exception:
                                    pass
                                emit_progress_lines(
                                    title=f"{task_name} - {prov_name}/{cit}/{county_name} - {resource} - {provider}",
                                    line1=f"{prov_name}/{cit}/{county_name} - {resource}",
                                    line2=f"失败: {exc}",
                                )
                            provider_records = []

                        for item in provider_records:
                            records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                        if progress_callback:
                            try:
                                progress_callback({"type": "subtask_done", "task_name": task_name, "province": prov_name, "city": cit, "county": county_name, "level": "county", "provider": provider, "count": len(provider_records)})
                            except Exception:
                                pass
                            emit_progress_lines(
                                title=f"{task_name} - {prov_name}/{cit}/{county_name} - {resource} - {provider}",
                                line1=f"{prov_name}/{cit}/{county_name} - {resource}",
                                line2=f"成功, 数据数量: {len(provider_records)}",
                            )
                        # incremental append for county
                        try:
                            if config.get("incremental", True) and provider_records:
                                new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in provider_records]
                                appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                                append_log(config["logs_path"], make_log_entry(task_name, run_time, f"{prov_name} / {cit} / {county_display}", "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
                        except Exception:
                            pass

                        # If provider returned results hitting the page_limit * page_size threshold,
                        # consider the area under-sampled and attempt grid refinement using the
                        # county polyline (if available).
                        try:
                            page_size = 20
                            max_expected = int(page_limit) * page_size
                            if len(provider_records) >= max_expected:
                                # only attempt refinement when we have polyline info
                                if isinstance(county_name, dict) and county_name.get("polyline"):
                                    bbox = bbox_from_polyline(county_name.get("polyline"))
                                    if bbox:
                                        grids = generate_grid(bbox, nx=2, ny=2)
                                        for idx, cell in enumerate(grids):
                                            if progress_callback:
                                                try:
                                                    progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "grid", "provider": provider, "grid_index": idx})
                                                except Exception:
                                                    pass
                                                emit_progress_lines(
                                                    title=f"{task_name} - {prov_name}/{cit}/{county_display} [grid {idx}] - {resource} - {provider}",
                                                    line1=f"{prov_name}/{cit}/{county_display} [grid {idx}] - {resource}",
                                                    line2=f"开始 网格 {idx}",
                                                )
                                            try:
                                                cell_records = fetch_with_delay(
                                                    provider,
                                                    api_keys,
                                                    keyword,
                                                    resource,
                                                    None,
                                                    None,
                                                    cell,
                                                    None,
                                                    page_limit,
                                                    stop_event=stop_event,
                                                )
                                            except Exception as exc:
                                                cell_records = []
                                            for item in cell_records:
                                                records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                                            if progress_callback:
                                                try:
                                                    progress_callback({"type": "subtask_done", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "grid", "provider": provider, "grid_index": idx, "count": len(cell_records)})
                                                except Exception:
                                                    pass
                                                emit_progress_lines(
                                                    title=f"{task_name} - {prov_name}/{cit}/{county_display} [grid {idx}] - {resource} - {provider}",
                                                    line1=f"{prov_name}/{cit}/{county_display} [grid {idx}] - {resource}",
                                                    line2=f"成功, 数据数量: {len(cell_records)} (网格 {idx})",
                                                )
                                            # incremental append for grid cell
                                            try:
                                                if config.get("incremental", True) and cell_records:
                                                    new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in cell_records]
                                                    appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                                                    append_log(config["logs_path"], make_log_entry(task_name, run_time, f"{prov_name} / {cit} / {county_display} [grid {idx}]", "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
                                            except Exception:
                                                pass
                        except Exception:
                            pass
                    continue

                # specific admin region -> single call
                if progress_callback:
                    try:
                        progress_callback({"type": "start_subtask", "task_name": task_name, "area": normalize_area(area), "level": "single", "provider": provider})
                    except Exception:
                        pass
                emit_progress_lines(
                    title=f"{task_name} - {area} - {resource} - {provider}",
                    line1=f"{area} - {resource}",
                    line2="开始",
                )
                try:
                    provider_records = fetch_with_delay(
                        provider,
                        api_keys,
                        keyword,
                        resource,
                        None,
                        None,
                        None,
                        admin,
                        page_limit,
                        stop_event=stop_event,
                    )
                except Exception as exc:
                        entry = {
                            "task_name": task_name,
                            "run_time": run_time,
                            "area": area,
                            "provider": PROVIDER_DISPLAY.get(provider, provider),
                            "status": "failed",
                            "records": 0,
                            "mode": mode,
                            "message": str(exc),
                        }
                        append_log(config["logs_path"], entry)
                        if progress_callback:
                            try:
                                progress_callback({"type": "subtask_failed", "task_name": task_name, "area": area, "provider": provider, "message": str(exc)})
                            except Exception:
                                pass
                        provider_records = []
                for item in provider_records:
                    records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                if progress_callback:
                    try:
                        progress_callback({"type": "subtask_done", "task_name": task_name, "area": area, "level": "single", "provider": provider, "count": len(provider_records)})
                    except Exception:
                        pass
                # incremental append for bbox/point call
                try:
                    if config.get("incremental", True) and provider_records:
                        new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in provider_records]
                        appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                        append_log(config["logs_path"], make_log_entry(task_name, run_time, area, "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
                except Exception:
                    pass
                # incremental append for single admin region
                try:
                    if config.get("incremental", True) and provider_records:
                        new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in provider_records]
                        appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                        append_log(config["logs_path"], make_log_entry(task_name, run_time, area, "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
                except Exception:
                    pass

            if task.get("area_type") != "admin":
                # bbox or point-based call
                if progress_callback:
                    try:
                        progress_callback({"type": "start_subtask", "task_name": task_name, "area": area, "level": "single", "provider": provider})
                    except Exception:
                        pass
                try:
                    provider_records = fetch_with_delay(
                        provider,
                        api_keys,
                        keyword,
                        resource,
                        task_target_values(task).get("latitude"),
                        task_target_values(task).get("longitude"),
                        task.get("bbox") if task.get("area_type") == "bbox" else None,
                        None,
                        page_limit,
                        stop_event=stop_event,
                    )
                except Exception as exc:
                    append_log(config["logs_path"], {
                        "task_name": task_name,
                        "run_time": run_time,
                        "area": normalize_area(area),
                        "provider": PROVIDER_DISPLAY.get(provider, provider),
                        "status": "failed",
                        "records": 0,
                        "mode": mode,
                        "message": str(exc),
                    })
                    if progress_callback:
                        try:
                            progress_callback({"type": "subtask_failed", "task_name": task_name, "area": area, "provider": provider, "message": str(exc)})
                        except Exception:
                            pass
                        emit_progress_lines(
                            title=f"{task_name} - {area} - {resource} - {provider}",
                            line1=f"{area} - {resource}",
                            line2=f"失败: {exc}",
                        )
                    provider_records = []
                for item in provider_records:
                    records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                if progress_callback:
                    try:
                        progress_callback({"type": "subtask_done", "task_name": task_name, "area": area, "level": "single", "provider": provider, "count": len(provider_records)})
                    except Exception:
                        pass
                    emit_progress_lines(
                        title=f"{task_name} - {area} - {resource} - {provider}",
                        line1=f"{area} - {resource}",
                        line2=f"成功, 数据数量: {len(provider_records)}",
                    )

    # finalize records
    records = dedupe_records(records)
    if config.get("incremental", True):
        existing_keys = load_existing_keys(config.get("results_dir", "POI_Data"))
        records = dedupe_records(records, existing_keys=existing_keys)

    if not records:
        entry = {
            "task_name": task_name,
            "run_time": run_time,
            "area": area,
            "status": "success",
            "records": 0,
            "mode": mode,
            "message": "无新增数据。",
        }
        entry["area"] = normalize_area(entry.get("area", ""))
        append_log(config["logs_path"], entry)
        if progress_callback:
            try:
                progress_callback({"type": "task_done", "task_name": task_name, "records": 0})
            except Exception:
                pass
        return entry

    # save outputs
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    base_dir = Path(config.get("results_dir", "POI_Data"))
    output_base = base_dir / date_folder / f"{task_name}_{timestamp}"
    saved_paths: List[str] = []
    formats: List[str] = []
    if config.get("export_format"):
        formats = [config.get("export_format")]
    else:
        formats = config.get("export_formats", [])
    if "csv" in formats:
        saved_paths.append(save_to_csv(records, f"{output_base}.csv"))
    if "json" in formats:
        saved_paths.append(save_to_json(records, f"{output_base}.json"))
    if "excel" in formats:
        try:
            saved_paths.append(save_to_excel(records, f"{output_base}.xlsx"))
        except ImportError as exc:
            saved_paths.append(f"excel-export-failed: {exc}")

    entry = {
        "task_name": task_name,
        "run_time": run_time,
        "area": area,
        "provider": ",".join([PROVIDER_DISPLAY.get(p, p) for p in providers]),
        "status": "success",
        "records": len(records),
        "mode": mode,
        "message": "; ".join(saved_paths),
    }
    entry["area"] = normalize_area(entry.get("area", ""))
    append_log(config["logs_path"], entry)
    if progress_callback:
        try:
            progress_callback({"type": "task_done", "task_name": task_name, "records": len(records)})
        except Exception:
            pass
    return entry


def run_tasks(tasks: List[Dict[str, Any]], config: Dict[str, Any], mode: str = "manual", progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    results = []
    for task in tasks:
        if not task.get("enabled", True):
            continue
        result = run_task(task, config, mode=mode, progress_callback=progress_callback, stop_event=stop_event)
        results.append(result)
    return results


def get_last_run_time(logs: List[Dict[str, Any]], task_name: str) -> Optional[datetime]:
    filtered = [log for log in logs if log.get("task_name") == task_name and log.get("status") == "success"]
    if not filtered:
        return None
    latest = max(filtered, key=lambda x: x.get("run_time", ""))
    try:
        return datetime.fromisoformat(latest["run_time"])
    except Exception:
        return None


def is_task_due(task: Dict[str, Any], logs: List[Dict[str, Any]], config: Dict[str, Any]) -> bool:
    # Use task schedule if present, otherwise fall back to global schedule_interval_days in config
    schedule = task.get("schedule", {"type": "daily", "interval_days": config.get("schedule_interval_days", 1)})
    if schedule.get("type") != "daily":
        return False
    interval = int(schedule.get("interval_days", config.get("schedule_interval_days", 1)))
    last_run = get_last_run_time(logs, task.get("name", ""))
    if last_run is None:
        return True
    return datetime.now() >= last_run + timedelta(days=interval)


def run_scheduled_tasks(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config.get("scheduler", {}).get("enabled", True):
        return []
    logs = load_logs(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
    due_tasks = [task for task in config.get("tasks", []) if task.get("enabled", True) and is_task_due(task, logs, config)]
    return run_tasks(due_tasks, config, mode="scheduled")


def start_scheduler(config: Dict[str, Any]) -> threading.Thread:
    stop_event = threading.Event()

    def loop() -> None:
        while not stop_event.is_set():
            try:
                run_scheduled_tasks(config)
            except Exception:
                pass
            time.sleep(max(60, int(config.get("scheduler", {}).get("check_interval_minutes", 15)) * 60))

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread

# --- CLI / GUI ---

def list_tasks(config: Dict[str, Any]) -> None:
    global_resources = config.get("resources", [])
    for task in config.get("tasks", []):
        print(f"- {task.get('name')} (enabled={task.get('enabled', True)}, area={get_task_area_summary(task)}, resources={global_resources})")


def show_logs(config: Dict[str, Any], status: Optional[str] = None) -> None:
    logs = load_logs(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
    for entry in logs:
        if status and entry.get("status") != status:
            continue
        print(json.dumps(entry, ensure_ascii=False))


def create_gui(config_path: str) -> None:
    # Tkinter GUI has been removed to avoid depending on tkinter.
    # Use the PyQt GUI instead by running with `--gui`.
    print("Tkinter GUI 已移除。请使用 PyQt GUI（运行时加 --gui）。")


def create_gui_pyqt(config_path: str) -> None:
    # delegate to extracted gui_pyqt module (lazy import to avoid circular imports)
    try:
        from gui_pyqt import create_gui_pyqt as _create_gui_pyqt

        return _create_gui_pyqt(config_path)
    except Exception as exc:
        print(f"无法启动 PyQt GUI: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保障资源 POI 抓取与调度工具")
    parser.add_argument("--config", default="config/poi_config.json", help="配置文件路径")
    parser.add_argument("--init-config", action="store_true", help="初始化默认配置文件")
    parser.add_argument("--list-tasks", action="store_true", help="列出当前配置中的任务")
    parser.add_argument("--run-all", action="store_true", help="执行全部任务")
    parser.add_argument("--run-task", help="执行指定任务名称")
    parser.add_argument("--run-scheduled", action="store_true", help="执行到期的调度任务")
    parser.add_argument("--show-logs", action="store_true", help="显示日志")
    parser.add_argument("--export-logs", help="导出日志到 CSV/JSON 文件")
    parser.add_argument("--add-keyword", nargs=2, metavar=("RESOURCE", "KEYWORD"), help="向资源类型添加关键字")
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败任务")
    parser.add_argument("--allow-auto-start", action="store_true", help="程序启动时执行调度任务")
    return parser.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    # load using config_loader and merge with DEFAULT_CONFIG
    try:
        cfg = config_loader.load_config(path)
    except Exception:
        return create_default_config(path)
    merged = DEFAULT_CONFIG.copy()
    if isinstance(cfg, dict):
        merged.update(cfg)
    return merged


def retry_failed_tasks(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    logs = load_logs(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
    failed_names = {entry["task_name"] for entry in logs if entry.get("status") == "failed"}
    tasks_to_retry = [task for task in config.get("tasks", []) if task.get("name") in failed_names]
    return run_tasks(tasks_to_retry, config, mode="retry")


def main() -> None:
    args = parse_args()
    no_cli_flags = not any([
        args.init_config,
        args.add_keyword,
        args.list_tasks,
        args.run_all,
        args.run_task,
        args.run_scheduled,
        args.show_logs,
        args.export_logs,
        args.retry_failed,
        args.allow_auto_start,
        args.gui,
    ])
    if no_cli_flags:
        create_gui_pyqt(args.config)
        return

    config = load_config(args.config)
    if args.init_config:
        create_default_config(args.config)
        print(f"已生成默认配置：{args.config}")
        return
    if args.add_keyword:
        resource, keyword = args.add_keyword
        if resource not in RESOURCE_TYPES:
            print(f"未知资源类型: {resource}")
            return
        keywords = config.setdefault("keywords", {}).setdefault(resource, [])
        if keyword not in keywords:
            keywords.append(keyword)
            save_json(args.config, config)
            print(f"已添加关键字 '{keyword}' 到资源 {resource}")
        else:
            print(f"关键字已存在: {keyword}")
        return
    if args.list_tasks:
        list_tasks(config)
        return
    if args.show_logs:
        show_logs(config)
        return
    if args.export_logs:
        logs = load_logs(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
        exported = export_logs(logs, args.export_logs)
        print(f"已导出日志：{exported}")
        return
    if args.retry_failed:
        results = retry_failed_tasks(config)
        for entry in results:
            print(json.dumps(entry, ensure_ascii=False))
        return
    if args.run_task:
        task = next((task for task in config.get("tasks", []) if task.get("name") == args.run_task), None)
        if task is None:
            print(f"未找到任务: {args.run_task}")
            return
        result = run_task(task, config, mode="manual")
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.run_all:
        results = run_tasks(config.get("tasks", []), config, mode="manual")
        for entry in results:
            print(json.dumps(entry, ensure_ascii=False))
        return
    if args.run_scheduled or args.allow_auto_start or config.get("auto_start", False):
        results = run_scheduled_tasks(config)
        for entry in results:
            print(json.dumps(entry, ensure_ascii=False))
        if not args.gui and not args.run_scheduled:
            return
    if args.gui:
        create_gui_pyqt(args.config)
        return
    if args.allow_auto_start:
        if config.get("scheduler", {}).get("enabled", True):
            start_scheduler(config)
        print("自动调度已启动，按 Ctrl+C 退出。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("退出。")
        return
    print("未指定操作，请使用 --help 查看可用选项。")

if __name__ == "__main__":
    main()
