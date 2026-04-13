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
)
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
SUPPORTED_PROVIDERS = ["baidu", "gaode", "tencent"]
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
    "api_keys": {"baidu": "", "gaode": "", "tencent": ""},
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
    config["api_keys"] = config["api_keys"].copy()
    config["keywords"] = {k: v.copy() for k, v in DEFAULT_KEYWORDS.items()}
    save_json(path, config)
    return config


def load_config(path: str) -> Dict[str, Any]:
    config = load_json(path)
    if config is None:
        config = create_default_config(path)
    if "keywords" not in config:
        config["keywords"] = {k: v.copy() for k, v in DEFAULT_KEYWORDS.items()}
    if "tasks" not in config:
        config["tasks"] = []
    if "api_keys" not in config:
        config["api_keys"] = {"baidu": "", "gaode": "", "tencent": ""}
    if "results_dir" not in config:
        config["results_dir"] = "results"
    if "logs_path" not in config:
        config["logs_path"] = "logs/poi_fetcher_logs.jsonl"
    if "export_formats" not in config:
        config["export_formats"] = ["csv", "json", "excel"]
    if "default_page_limit" not in config:
        config["default_page_limit"] = 3
    if "scheduler" not in config:
        config["scheduler"] = {"enabled": True, "check_interval_minutes": 15}
    return config


def get_region_cache_path(config_path: str) -> str:
    return str(Path(config_path).with_name("region_cache.json"))


def load_region_cache(path: str) -> Dict[str, Any]:
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def save_region_cache(path: str, data: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_amap_region_hierarchy(key: str) -> Dict[str, Dict[str, List[str]]]:
    if not key:
        raise ValueError("高德 API Key 未配置，无法获取行政区数据。")
    params = {
        "key": key,
        "keywords": "中国",
        "subdistrict": 3,
        "extensions": "base",
        "output": "json",
    }
    resp = requests.get("https://restapi.amap.com/v3/config/district", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(f"高德行政区数据接口返回错误: {data}")
    result: Dict[str, Dict[str, List[str]]] = {}
    provinces = data.get("districts", [])
    for province in provinces:
        province_name = province.get("name", "")
        if not province_name:
            continue
        result[province_name] = {}
        for city in province.get("districts", []):
            city_name = city.get("name", "")
            if not city_name:
                continue
            counties = [district.get("name", "") for district in city.get("districts", []) if district.get("name")]
            result[province_name][city_name] = counties
    return result


def fetch_amap_subdistrict(key: str, province: str, city: str) -> List[str]:
    """Fetch county/district list for a given province+city from Amap (subdistrict=1).

    Returns a list of county names (may be empty).
    """
    if not key:
        return []
    params = {
        "key": key,
        "keywords": city,
        "subdistrict": 1,
        "extensions": "base",
        "output": "json",
    }
    resp = requests.get("https://restapi.amap.com/v3/config/district", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        return []
    # data['districts'] may contain multiple provinces; try to find matching province
    for prov in data.get("districts", []):
        prov_name = prov.get("name", "")
        # match by provided province or accept if only one province returned
        if prov_name and (prov_name == province or len(data.get("districts", [])) == 1):
            # If the returned top-level item is the city itself (common when searching by city name),
            # then its child districts are the counties we want.
            if prov_name == city:
                return [d.get("name") for d in prov.get("districts", []) if d.get("name")]
            for cit in prov.get("districts", []):
                if cit.get("name") == city:
                    return [d.get("name") for d in cit.get("districts", []) if d.get("name")]
    # fallback: try first district's child that matches city
    for prov in data.get("districts", []):
        for cit in prov.get("districts", []):
            if cit.get("name") == city:
                return [d.get("name") for d in cit.get("districts", []) if d.get("name")]
    return []


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
    return f"{admin.get('province','')} / {admin.get('city','')} / {admin.get('county','')}".strip()


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
    return f"{admin.get('province','')} / {admin.get('city','')} / {admin.get('county','')}"


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
    def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int) -> List[Dict[str, Any]]:
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


def run_task(task: Dict[str, Any], config: Dict[str, Any], mode: str = "manual") -> Dict[str, Any]:
    run_time = format_time(datetime.now())
    task_name = task.get("name", task.get("task_name", "unnamed_task"))
    area = get_task_area_summary(task)
    page_limit = int(config.get("default_page_limit", 3))
    # providers and resources are global settings now (in config)
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
    target = task_target_values(task)
    keywords = []
    for resource in config.get("resources", []):
        keywords.extend(merge_keywords(config, resource))
    keywords = list(dict.fromkeys(keywords))
    records: List[Dict[str, Any]] = []
    for keyword in keywords:
        for provider in providers:
            # If admin task and city is empty (UI '全部' selected at city level), expand to all cities in province
            if task.get("area_type") == "admin":
                admin = task.get("admin_region", {})
                prov = admin.get("province", "")
                cit = admin.get("city", None)
                # treat None as not set; empty-string indicates UI '全部'
                if cit == "":
                    # try to load region cache from common location
                    try:
                        cache = load_region_cache("config/region_cache.json")
                    except Exception:
                        cache = {}
                    cities_list = []
                    if isinstance(cache, dict) and prov in cache:
                        val = cache[prov]
                        if isinstance(val, list):
                            cities_list = [str(x) for x in val]
                        elif isinstance(val, dict):
                            cities_list = list(val.keys())
                    if not cities_list and prov in REGION_DATA:
                        cities_list = list(REGION_DATA.get(prov, []))
                    # if still empty, fall back to a single empty city to preserve prior behavior
                    if not cities_list:
                        cities_list = [""]

                    # Use a thread pool to fetch per-city, honoring configured concurrency and delay
                    concurrency = int(config.get("province_expand_concurrency", config.get("max_concurrency", 1)))
                    delay = float(config.get("province_expand_delay_seconds", 0.0))

                    # global rate limiter state for spacing requests
                    rate_lock = threading.Lock()
                    last_call = {"t": 0.0}

                    def call_fetch_for_city(city_name: str):
                        # enforce minimal delay between requests (global)
                        with rate_lock:
                            now = time.time()
                            wait = max(0.0, delay - (now - last_call["t"]))
                            if wait > 0:
                                time.sleep(wait)
                            last_call["t"] = time.time()
                        try:
                            return fetch_provider_records(
                                provider,
                                config.get("api_keys", {}),
                                keyword,
                                task.get("resource_type", ""),
                                None,
                                None,
                                None,
                                {"province": prov, "city": city_name, "county": ""},
                                page_limit,
                            )
                        except Exception as exc:
                            append_log(config["logs_path"], {
                                "task_name": task_name,
                                "run_time": run_time,
                                "area": f"{prov} / {city_name} / ",
                                "status": "failed",
                                "records": 0,
                                "mode": mode,
                                "message": f"子区域抓取失败: {exc}",
                            })
                            return []

                    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
                        futures = {pool.submit(call_fetch_for_city, c): c for c in cities_list}
                        for fut in as_completed(futures):
                            city_item = futures[fut]
                            try:
                                provider_records = fut.result()
                            except Exception as exc:
                                provider_records = []
                            for item in provider_records:
                                records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
                    # finished expanding cities for this provider+keyword
                    continue
            # default single-call behavior
            try:
                provider_records = fetch_provider_records(
                    provider,
                    config.get("api_keys", {}),
                    keyword,
                    task.get("resource_type", ""),
                    target.get("latitude"),
                    target.get("longitude"),
                    target.get("bbox"),
                    task.get("admin_region") if task.get("area_type") == "admin" else None,
                    page_limit,
                )
            except Exception as exc:
                entry = {
                    "task_name": task_name,
                    "run_time": run_time,
                    "area": area,
                    "status": "failed",
                    "records": 0,
                    "mode": mode,
                    "message": str(exc),
                }
                append_log(config["logs_path"], entry)
                return entry
            for item in provider_records:
                records.append(normalize_record(provider, item, ",".join(config.get("resources", [])), task_name, run_time))
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
        append_log(config["logs_path"], entry)
        return entry
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    base_dir = Path(config.get("results_dir", "POI_Data"))
    output_base = base_dir / date_folder / f"{task_name}_{timestamp}"
    saved_paths: List[str] = []
    # determine export formats: prefer single global `export_format`, fall back to legacy list
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
        "status": "success",
        "records": len(records),
        "mode": mode,
        "message": "; ".join(saved_paths),
    }
    append_log(config["logs_path"], entry)
    return entry


def run_tasks(tasks: List[Dict[str, Any]], config: Dict[str, Any], mode: str = "manual") -> List[Dict[str, Any]]:
    results = []
    for task in tasks:
        if not task.get("enabled", True):
            continue
        result = run_task(task, config, mode=mode)
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
