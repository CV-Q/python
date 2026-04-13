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

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
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
    "max_concurrency": 1,
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
    if tk is None:
        print("当前环境不支持 Tkinter，无法启动 GUI。")
        return

    root = tk.Tk()
    root.title("POI 任务调度器")
    root.geometry("1000x700")

    main_frame = ttk.Frame(root, padding=10)
    main_frame.pack(fill="both", expand=True)

    config_var = tk.StringVar(value=config_path)
    ttk.Label(main_frame, text="配置文件：").grid(row=0, column=0, sticky="w")
    ttk.Entry(main_frame, textvariable=config_var, width=60).grid(row=0, column=1, sticky="w")
    ttk.Button(main_frame, text="刷新配置", command=lambda: load_config_file()).grid(row=0, column=2, sticky="w")
    ttk.Button(main_frame, text="保存配置", command=lambda: save_current_config()).grid(row=0, column=3, sticky="w")

    content_frame = ttk.Frame(main_frame)
    content_frame.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
    main_frame.rowconfigure(1, weight=1)
    main_frame.columnconfigure(1, weight=1)

    task_frame = ttk.LabelFrame(content_frame, text="任务列表与管理", padding=10)
    task_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    task_frame.rowconfigure(1, weight=1)
    task_frame.columnconfigure(0, weight=1)

    editor_frame = ttk.LabelFrame(content_frame, text="任务详情编辑", padding=10)
    editor_frame.grid(row=0, column=1, sticky="nsew")
    content_frame.columnconfigure(1, weight=1)

    task_list = tk.Listbox(task_frame, width=60, height=20)
    task_list.grid(row=1, column=0, sticky="nsew")
    task_scroll = ttk.Scrollbar(task_frame, orient="vertical", command=task_list.yview)
    task_scroll.grid(row=1, column=1, sticky="ns")
    task_list.config(yscrollcommand=task_scroll.set)

    task_buttons = ttk.Frame(task_frame)
    task_buttons.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky="w")
    ttk.Button(task_buttons, text="新增任务", command=lambda: add_task()).grid(row=0, column=0, padx=5)
    ttk.Button(task_buttons, text="删除任务", command=lambda: delete_task()).grid(row=0, column=1, padx=5)
    ttk.Button(task_buttons, text="运行选中任务", command=lambda: run_selected()).grid(row=0, column=2, padx=5)
    ttk.Button(task_buttons, text="运行全部任务", command=lambda: run_all_tasks()).grid(row=0, column=3, padx=5)
    ttk.Button(task_buttons, text="加载日志", command=lambda: load_log_entries()).grid(row=0, column=4, padx=5)

    log_frame = ttk.LabelFrame(main_frame, text="日志输出", padding=10)
    log_frame.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
    main_frame.rowconfigure(2, weight=1)

    log_text = tk.Text(log_frame, width=120, height=12, wrap="word")
    log_text.pack(fill="both", expand=True)

    def append_log(message: str) -> None:
        log_text.insert("end", message + "\n")
        log_text.see("end")

    current_task_index = {"value": None}
    current_config: Dict[str, Any] = {"value": load_config(config_path)}
    region_data: Dict[str, Dict[str, List[str]]] = {"value": ensure_region_data(config_path, current_config["value"].get("api_keys", {}).get("gaode", ""))}

    task_name_var = tk.StringVar()
    task_enabled_var = tk.BooleanVar(value=True)
    area_type_var = tk.StringVar(value="admin")
    country_var = tk.StringVar(value="中国")
    province_var = tk.StringVar()
    city_var = tk.StringVar()
    county_var = tk.StringVar()
    # radius removed per user request (center+radius queries disabled)
    bbox_left_var = tk.StringVar()
    bbox_bottom_var = tk.StringVar()
    bbox_right_var = tk.StringVar()
    bbox_top_var = tk.StringVar()
    # Global settings (now shared across all tasks)
    providers_var = tk.StringVar(value=current_config["value"].get("provider", SUPPORTED_PROVIDERS[0]))
    resources_var = tk.StringVar(value=",".join(current_config["value"].get("resources", [RESOURCE_TYPES[0]])))
    page_limit_var = tk.StringVar(value=str(current_config["value"].get("default_page_limit", 3)))
    incremental_var = tk.BooleanVar(value=bool(current_config["value"].get("incremental", True)))
    schedule_interval_var = tk.StringVar(value=str(current_config["value"].get("schedule_interval_days", 1)))
    # single export format (global)
    export_format_var = tk.StringVar(value=str(current_config["value"].get("export_format", (current_config["value"].get("export_formats", ["csv"])[0]))))
    # concurrency (thread pool size)
    concurrency_var = tk.StringVar(value=str(current_config["value"].get("max_concurrency", 1)))

    def get_country_choices() -> List[str]:
        return ["中华人民共和国"]
    def get_province_choices() -> List[str]:
        return sorted(region_data["value"].keys())
    def get_city_choices() -> List[str]:
        province = province_var.get().strip()
        return sorted(region_data["value"].get(province, {}).keys()) if province else []
    def get_county_choices() -> List[str]:
        province = province_var.get().strip()
        city = city_var.get().strip()
        return sorted(region_data["value"].get(province, {}).get(city, [])) if province and city else []
    def update_province_options(*_args) -> None:
        province_combobox["values"] = get_province_choices()
        if province_var.get() not in province_combobox["values"]:
            province_var.set("")
        update_city_options()
    def update_city_options(*_args) -> None:
        city_combobox["values"] = get_city_choices()
        if city_var.get() not in city_combobox["values"]:
            city_var.set("")
        update_county_options()
    def update_county_options(*_args) -> None:
        # 如果已有县列表则直接使用，否则尝试在线获取并缓存
        province = province_var.get().strip()
        city = city_var.get().strip()
        county_list = get_county_choices()
        if not county_list and province and city:
            try:
                gaode_key = current_config["value"].get("api_keys", {}).get("gaode", "")
                fetched = fetch_amap_subdistrict(gaode_key, province, city)
                if fetched:
                    region_data["value"].setdefault(province, {})[city] = fetched
                    try:
                        save_region_cache(get_region_cache_path(config_var.get()), region_data["value"])
                    except Exception:
                        pass
                    append_log(f"已在线获取并缓存区县：{province} / {city} -> {len(fetched)} 项")
                    county_list = fetched
            except Exception as exc:
                append_log(f"获取区县失败：{exc}")

        county_combobox["values"] = county_list
        if county_var.get() not in county_combobox["values"]:
            county_var.set("")
    def refresh_region_data() -> None:
        try:
            region_data["value"] = ensure_region_data(config_var.get(), current_config["value"].get("api_keys", {}).get("gaode", ""))
            append_log("已刷新省市区数据。")
            province_combobox["values"] = get_province_choices()
        except Exception as exc:
            messagebox.showwarning("警告", f"刷新省市区数据失败：{exc}\n已使用本地缓存或默认数据。")

    def load_config_file() -> None:
        try:
            current_config["value"] = load_config(config_var.get())
            region_data["value"] = ensure_region_data(config_var.get(), current_config["value"].get("api_keys", {}).get("gaode", ""))
            province_combobox["values"] = get_province_choices()
            city_combobox["values"] = get_city_choices()
            county_combobox["values"] = get_county_choices()
            refresh_tasks()
            # 更新 resources 帮助文本以反映当前配置
            try:
                cfg_keywords = current_config["value"].get("keywords", {})
                resources_example = ", ".join(sorted(cfg_keywords.keys())) if cfg_keywords else ", ".join(RESOURCE_TYPES)
                kw_examples = "; ".join([f"{k}: {', '.join((v or [])[:3])}" for k, v in cfg_keywords.items()]) if cfg_keywords else "; ".join([f"{k}: {', '.join(v[:3])}" for k, v in DEFAULT_KEYWORDS.items()])
                resources_help_label.config(text=f"可用资源: {resources_example}；关键词示例: {kw_examples}")
            except Exception:
                pass
            # 将全局设置同步到 UI
            try:
                providers_var.set(current_config["value"].get("provider", providers_var.get()))
                resources_var.set(",".join(current_config["value"].get("resources", [])))
                export_format_var.set(str(current_config["value"].get("export_format", export_format_var.get())))
                page_limit_var.set(str(current_config["value"].get("default_page_limit", page_limit_var.get())))
                incremental_var.set(bool(current_config["value"].get("incremental", incremental_var.get())))
                schedule_interval_var.set(str(current_config["value"].get("schedule_interval_days", schedule_interval_var.get())))
            except Exception:
                pass
            append_log(f"已加载配置：{config_var.get()}")
        except Exception as exc:
            messagebox.showerror("错误", f"加载配置失败：{exc}")

    # create executor for Tkinter GUI
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=int(current_config["value"].get("max_concurrency", 1)))

    def save_current_config() -> None:
        nonlocal executor
        try:
            # 更新 global 设置到 current_config
            try:
                current_config["value"]["provider"] = providers_var.get().strip()
                current_config["value"]["resources"] = [r.strip() for r in resources_var.get().split(",") if r.strip()]
                current_config["value"]["export_format"] = export_format_var.get().strip()
                current_config["value"]["max_concurrency"] = int(concurrency_var.get() or current_config["value"].get("max_concurrency", 1))
                # keep legacy export_formats list untouched
                current_config["value"]["default_page_limit"] = int(page_limit_var.get() or current_config["value"].get("default_page_limit", 3))
                current_config["value"]["incremental"] = bool(incremental_var.get())
                current_config["value"]["schedule_interval_days"] = int(schedule_interval_var.get() or current_config["value"].get("schedule_interval_days", 1))
            except Exception:
                pass
            save_json(config_var.get(), current_config["value"])
            # recreate executor if concurrency changed
            try:
                new_max = int(current_config["value"].get("max_concurrency", 1))
                # if changed, shutdown and recreate
                if getattr(executor, "_max_workers", None) != new_max:
                    try:
                        executor.shutdown(wait=False)
                    except Exception:
                        pass
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=new_max)
            except Exception:
                pass
            append_log(f"已保存配置：{config_var.get()}")
        except Exception as exc:
            messagebox.showerror("错误", f"保存配置失败：{exc}")

    def format_task_list_item(task: Dict[str, Any]) -> str:
        # resources display from global configuration
        global_resources = current_config["value"].get("resources", [])
        return f"{task.get('name')} | {get_task_area_summary(task)} | resources={global_resources} | enabled={task.get('enabled', True)}"

    def refresh_tasks() -> None:
        task_list.delete(0, "end")
        for task in current_config["value"].get("tasks", []):
            task_list.insert("end", format_task_list_item(task))
        clear_task_form()
        current_task_index["value"] = None

    def load_task_to_form(index: int) -> None:
        task = current_config["value"].get("tasks", [])[index]
        current_task_index["value"] = index
        task_name_var.set(task.get("name", ""))
        task_enabled_var.set(task.get("enabled", True))
        area_type_var.set(task.get("area_type", "admin"))
        country_var.set(task.get("admin_region", {}).get("country", "中华人民共和国"))
        province_var.set(task.get("admin_region", {}).get("province", ""))
        update_province_options()
        city_var.set(task.get("admin_region", {}).get("city", ""))
        update_city_options()
        county_var.set(task.get("admin_region", {}).get("county", ""))
        update_county_options()
        # radius removed; nothing to set
        bbox = task.get("bbox", {})
        bbox_left_var.set(str(bbox.get("left", "")))
        bbox_bottom_var.set(str(bbox.get("bottom", "")))
        bbox_right_var.set(str(bbox.get("right", "")))
        bbox_top_var.set(str(bbox.get("top", "")))
        # 注意：以下为全局设置（不随单个任务变化），故这里不从任务覆盖 UI 全局控件

    def clear_task_form() -> None:
        task_name_var.set("")
        task_enabled_var.set(True)
        area_type_var.set("admin")
        country_var.set("中华人民共和国")
        province_var.set("")
        city_var.set("")
        county_var.set("")
        province_combobox["values"] = get_province_choices()
        city_combobox["values"] = []
        county_combobox["values"] = []
        # radius removed
        bbox_left_var.set("")
        bbox_bottom_var.set("")
        bbox_right_var.set("")
        bbox_top_var.set("")
        # 全局设置从 current_config 恢复
        providers_var.set(current_config["value"].get("provider", SUPPORTED_PROVIDERS[0]))
        resources_var.set(",".join(current_config["value"].get("resources", [])))
        page_limit_var.set(str(current_config["value"].get("default_page_limit", 3)))
        incremental_var.set(bool(current_config["value"].get("incremental", True)))
        schedule_interval_var.set(str(current_config["value"].get("schedule_interval_days", 1)))
        export_format_var.set(str(current_config["value"].get("export_format", (current_config["value"].get("export_formats", ["csv"])[0]))))

    def build_task_from_form() -> Dict[str, Any]:
        task_name = task_name_var.get().strip()
        if not task_name:
            raise ValueError("任务名称不能为空。")
        # 注意：provider/resources/export_format/page_limit/incremental/schedule 为全局设置，
        # 不随单个任务存储。此处仅构造任务基本信息（名称、启用、区域/BBox）。
        area_type = area_type_var.get()
        task: Dict[str, Any] = {
            "name": task_name,
            "enabled": task_enabled_var.get(),
            "area_type": area_type,
        }
        if area_type == "bbox":
            task["bbox"] = {
                "left": float(bbox_left_var.get()),
                "bottom": float(bbox_bottom_var.get()),
                "right": float(bbox_right_var.get()),
                "top": float(bbox_top_var.get()),
            }
            # no radius for bbox mode
            task["admin_region"] = {"country": country_var.get().strip(), "province": "", "city": ""}
        else:
            task["admin_region"] = {
                "country": country_var.get().strip(),
                "province": province_var.get().strip(),
                "city": city_var.get().strip(),
            }
            # center+radius queries removed; do not include radius
            task["bbox"] = None
        return task
        return task

    def save_task_changes() -> None:
        try:
            task = build_task_from_form()
            tasks = current_config["value"].setdefault("tasks", [])
            index = current_task_index["value"]
            if index is None:
                tasks.append(task)
                append_log(f"已新增任务：{task['name']}")
            else:
                tasks[index] = task
                append_log(f"已更新任务：{task['name']}")
            save_json(config_var.get(), current_config["value"])
            refresh_tasks()
        except Exception as exc:
            messagebox.showerror("错误", f"保存任务失败：{exc}")

    def add_task() -> None:
        clear_task_form()
        current_task_index["value"] = None
        task_name_var.set(f"新任务_{len(current_config['value'].get('tasks', [])) + 1}")

    def delete_task() -> None:
        selection = task_list.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个任务。")
            return
        index = selection[0]
        task = current_config["value"].get("tasks", [])[index]
        if messagebox.askyesno("确认", f"确定删除任务 '{task.get('name')}' 吗？"):
            current_config["value"]["tasks"].pop(index)
            save_json(config_var.get(), current_config["value"])
            refresh_tasks()
            append_log(f"已删除任务：{task.get('name')}")

    def run_selected() -> None:
        selection = task_list.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个任务。")
            return
        index = selection[0]
        task = current_config["value"].get("tasks", [])[index]
        def worker():
            try:
                res = run_task(task, current_config["value"], mode="manual")
                root.after(0, lambda: append_log(json.dumps(res, ensure_ascii=False)))
            except Exception as e:
                root.after(0, lambda: append_log(f"任务运行失败: {e}"))
        try:
            executor.submit(worker)
        except Exception:
            threading.Thread(target=worker, daemon=True).start()

    def run_all_tasks() -> None:
        def worker_all():
            try:
                results = run_tasks(current_config["value"].get("tasks", []), current_config["value"], mode="manual")
                for entry in results:
                    root.after(0, lambda e=entry: append_log(json.dumps(e, ensure_ascii=False)))
            except Exception as e:
                root.after(0, lambda: append_log(f"批量运行失败: {e}"))
        try:
            executor.submit(worker_all)
        except Exception:
            threading.Thread(target=worker_all, daemon=True).start()

    def load_log_entries() -> None:
        logs = load_logs(current_config["value"].get("logs_path", "logs/poi_fetcher_logs.jsonl"))
        log_text.delete("1.0", "end")
        for entry in logs[-100:]:
            append_log(json.dumps(entry, ensure_ascii=False))

    def on_task_select(event: Any) -> None:
        selection = task_list.curselection()
        if not selection:
            return
        load_task_to_form(selection[0])

    task_list.bind("<<ListboxSelect>>", on_task_select)

    row = 0
    # 任务名称
    ttk.Label(editor_frame, text="任务名称：").grid(row=row, column=0, sticky="w")
    ttk.Entry(editor_frame, textvariable=task_name_var, width=40).grid(row=row, column=1, sticky="w")
    row += 1
    # 区域选择模式：行政区域(admin) 或 矩形区域(bbox)
    ttk.Label(editor_frame, text="选择模式：").grid(row=row, column=0, sticky="w")
    area_type_combobox = ttk.Combobox(editor_frame, textvariable=area_type_var, values=["admin", "bbox"], width=30, state="readonly")
    area_type_combobox.grid(row=row, column=1, sticky="w")
    # 当 area_type_var 改变（程序或用户）时更新控件状态
    try:
        area_type_var.trace_add('write', lambda *_: update_area_mode())
    except Exception:
        pass
    def update_area_mode(*_args):
        mode = area_type_var.get()
        if mode == "admin":
            # 启用省市区，禁用 bbox 输入
            province_combobox.config(state="readonly")
            city_combobox.config(state="readonly")
            county_combobox.config(state="readonly")
            for w in (bbox_left_entry, bbox_bottom_entry, bbox_right_entry, bbox_top_entry):
                w.config(state="disabled")
        else:
            # 矩形模式：禁用省市区，启用 bbox 输入
            province_combobox.config(state="disabled")
            city_combobox.config(state="disabled")
            county_combobox.config(state="disabled")
            for w in (bbox_left_entry, bbox_bottom_entry, bbox_right_entry, bbox_top_entry):
                w.config(state="normal")
    area_type_combobox.bind("<<ComboboxSelected>>", update_area_mode)

    # 将国家行放到选择模式之后的下一行
    row += 1
    ttk.Label(editor_frame, text="国家：").grid(row=row, column=0, sticky="w")
    country_combobox = ttk.Combobox(editor_frame, textvariable=country_var, values=get_country_choices(), width=30, state="readonly")
    country_combobox.grid(row=row, column=1, sticky="w")
    country_combobox.bind("<<ComboboxSelected>>", update_province_options)
    row += 1
    ttk.Label(editor_frame, text="省份：").grid(row=row, column=0, sticky="w")
    province_combobox = ttk.Combobox(editor_frame, textvariable=province_var, values=get_province_choices(), width=30, state="readonly")
    province_combobox.grid(row=row, column=1, sticky="w")
    province_combobox.bind("<<ComboboxSelected>>", update_city_options)
    row += 1
    ttk.Label(editor_frame, text="城市：").grid(row=row, column=0, sticky="w")
    city_combobox = ttk.Combobox(editor_frame, textvariable=city_var, values=get_city_choices(), width=30, state="readonly")
    city_combobox.grid(row=row, column=1, sticky="w")
    city_combobox.bind("<<ComboboxSelected>>", update_county_options)
    row += 1
    ttk.Label(editor_frame, text="区/县：").grid(row=row, column=0, sticky="w")
    county_combobox = ttk.Combobox(editor_frame, textvariable=county_var, values=get_county_choices(), width=30, state="readonly")
    county_combobox.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Button(editor_frame, text="刷新省市区", command=refresh_region_data).grid(row=row, column=0, columnspan=2, pady=(5, 5), sticky="w")
    row += 1
    # 半径功能已移除
    row += 0
    ttk.Label(editor_frame, text="BBox 左：").grid(row=row, column=0, sticky="w")
    bbox_left_entry = ttk.Entry(editor_frame, textvariable=bbox_left_var, width=12)
    bbox_left_entry.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="BBox 下：").grid(row=row, column=0, sticky="w")
    bbox_bottom_entry = ttk.Entry(editor_frame, textvariable=bbox_bottom_var, width=12)
    bbox_bottom_entry.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="BBox 右：").grid(row=row, column=0, sticky="w")
    bbox_right_entry = ttk.Entry(editor_frame, textvariable=bbox_right_var, width=12)
    bbox_right_entry.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="BBox 上：").grid(row=row, column=0, sticky="w")
    bbox_top_entry = ttk.Entry(editor_frame, textvariable=bbox_top_var, width=12)
    bbox_top_entry.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="Providers：").grid(row=row, column=0, sticky="w")
    providers_combobox = ttk.Combobox(editor_frame, textvariable=providers_var, values=SUPPORTED_PROVIDERS, width=37, state="readonly")
    providers_combobox.grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="Resources (逗号分隔)：").grid(row=row, column=0, sticky="w")
    ttk.Entry(editor_frame, textvariable=resources_var, width=40).grid(row=row, column=1, sticky="w")
    # 显示可用 resources 示例和关键词示例，帮助用户填写
    try:
        cfg_keywords = current_config["value"].get("keywords", {}) if isinstance(current_config.get("value"), dict) else DEFAULT_KEYWORDS
        resources_example = ", ".join(sorted(cfg_keywords.keys())) if cfg_keywords else ", ".join(RESOURCE_TYPES)
        kw_examples = "; ".join([f"{k}: {', '.join((v or [])[:3])}" for k, v in cfg_keywords.items()]) if cfg_keywords else "; ".join([f"{k}: {', '.join(v[:3])}" for k, v in DEFAULT_KEYWORDS.items()])
        help_text = f"可用资源: {resources_example}；关键词示例: {kw_examples}"
    except Exception:
        help_text = "可用资源示例见配置文件或文档。"
    resources_help_label = ttk.Label(editor_frame, text=help_text, foreground="gray", wraplength=420)
    resources_help_label.grid(row=row+1, column=0, columnspan=2, sticky="w", pady=(2,6))
    row += 2
    # 全局：导出格式（单选）
    ttk.Label(editor_frame, text="导出格式：").grid(row=row, column=0, sticky="w")
    export_combobox = ttk.Combobox(editor_frame, textvariable=export_format_var, values=["csv", "json", "excel"], width=12, state="readonly")
    export_combobox.grid(row=row, column=1, sticky="w")
    row += 1
    # 并发数（线程池大小）
    ttk.Label(editor_frame, text="并发数：").grid(row=row, column=0, sticky="w")
    ttk.Entry(editor_frame, textvariable=concurrency_var, width=12).grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="分页限制：").grid(row=row, column=0, sticky="w")
    ttk.Entry(editor_frame, textvariable=page_limit_var, width=12).grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Checkbutton(editor_frame, text="增量去重", variable=incremental_var).grid(row=row, column=0, columnspan=2, sticky="w")
    row += 1
    ttk.Label(editor_frame, text="调度间隔天数：").grid(row=row, column=0, sticky="w")
    ttk.Entry(editor_frame, textvariable=schedule_interval_var, width=12).grid(row=row, column=1, sticky="w")
    row += 1
    ttk.Button(editor_frame, text="保存任务", command=lambda: save_task_changes()).grid(row=row, column=0, columnspan=2, pady=(10, 0))

    # 初始化区域模式控件状态
    try:
        update_area_mode()
    except Exception:
        pass
    load_config_file()
    root.mainloop()


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
