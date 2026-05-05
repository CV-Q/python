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
import logging
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
    get_city_center,
    append_new_records,
    make_log_entry,
    load_keys_from_file,
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

# module logger
logger = logging.getLogger(__name__)

# 为避免依赖 Tkinter，已移除 tkinter 用法。
# 需要原始实现时可见 archive/gui_tk_backup.py。
tk = None

try:
    from PyQt5 import QtWidgets, QtCore
except Exception:
    QtWidgets = None
    QtCore = None
try:
    from providers import fetch_provider_records, fetch_baidu, fetch_gaode, fetch_tencent
except Exception:
    # providers 模块在重构期间可能尚未创建；若缺失则保留后备名称以避免导入错误
    pass

# --- 常量 ---
SUPPORTED_PROVIDERS = ["baidu", "gaode", "tianditu"]
RESOURCE_TYPES = ["gas_station", "service_area", "hospital", "repair_factory"]
AMAP_TYPE_MAP = {
    "hospital": "120000",
    "gas_station": "050700",
}

# 提供商在日志/UI 中的展示名
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

X_PI = math.pi * 3000.0 / 180.0

# --- 工具函数 ---

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
    """从高德地图查询指定市的下级区/县（子区）。

    返回：
        - 成功时返回列表，每个元素为 dict，包含至少 `name` 与 `adcode` 字段（兼容旧缓存格式）。
        - 失败或未配置 `gaode_key` 时返回空列表。

    说明：本函数用于在 GUI 展开城市节点或保存任务时按需拉取县/区信息；尽量保持幂等性与容错性，调用方无需在失败时重试本函数内部错误。
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
        # 进入子区列表（下级行政区）
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
    """从高德拉取国家下的省/市两层级区域层次结构。

    返回结构示例：{ "省名": {"市名": ["区/县1","区/县2", ...], ...}, ... }
    若请求失败、返回非成功状态或未提供 `api_key`，函数将返回空字典。

    该函数仅在用户显式请求更新行政区时由上层调用，不会在程序启动时自动触发网络请求。
    """
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
        # 首个元素应为国家层级，其下为各省份
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


def _normalize_region_cache_data(raw: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """将行政区缓存规范化为高德命名优先的 {province: {city: [counties...]}} 结构。"""
    if not isinstance(raw, dict):
        return {}

    def _expand_country_level(data: Dict[str, Any]) -> Dict[str, Any]:
        if len(data) == 1:
            first = next(iter(data))
            if first in ("中国", "中华人民共和国"):
                val = data[first]
                if isinstance(val, dict):
                    return val
                if isinstance(val, list):
                    return {str(prov): {} for prov in val}
        return data

    def _norm(name: Any) -> str:
        try:
            text = str(name or "").strip()
            for suffix in ["省", "市", "自治区", "特别行政区", "自治州", "地区", "区", "县", "市辖区", "盟", "林区"]:
                if text.endswith(suffix):
                    text = text[: -len(suffix)]
            return text.strip().lower()
        except Exception:
            return str(name or "").strip().lower()

    def _prefer_standard_name(candidates: List[str], level: str) -> str:
        names = [str(name).strip() for name in candidates if str(name).strip()]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]

        if level == "province":
            suffixes = ("省", "市", "自治区", "特别行政区")
        else:
            suffixes = ("市", "城区", "自治州", "地区", "盟", "林区")

        def score(name: str) -> tuple:
            suffix_score = 1 if any(name.endswith(suffix) for suffix in suffixes) else 0
            special_score = 1 if any(token in name for token in ("城区", "自治州", "特别行政区", "林区")) else 0
            return (suffix_score, special_score, len(name), name)

        return max(names, key=score)

    def _merge_city_values(dest_list: List[Any], src_list: List[Any]) -> List[Any]:
        seen = set()
        out = []
        for item in list(dest_list) + list(src_list):
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(item if isinstance(item, dict) else name)
        return out

    expanded = _expand_country_level(raw)
    grouped: Dict[str, Dict[str, Any]] = {}

    for prov_key, prov_val in expanded.items():
        prov_name = str(prov_key).strip()
        prov_norm = _norm(prov_name)
        prov_bucket = grouped.setdefault(prov_norm, {"names": [], "cities": {}})
        prov_bucket["names"].append(prov_name)

        if isinstance(prov_val, list):
            city_items = {str(city): [] for city in prov_val}
        elif isinstance(prov_val, dict):
            city_items = prov_val
        else:
            city_items = {}

        for city_key, subs in city_items.items():
            city_name = str(city_key).strip()
            city_norm = _norm(city_name)
            city_bucket = prov_bucket["cities"].setdefault(city_norm, {"names": [], "subs": []})
            city_bucket["names"].append(city_name)
            if isinstance(subs, list):
                city_bucket["subs"] = _merge_city_values(city_bucket["subs"], subs)

    normalized: Dict[str, Dict[str, List[str]]] = {}
    for prov_bucket in grouped.values():
        province_name = _prefer_standard_name(prov_bucket.get("names", []), "province")
        normalized[province_name] = {}
        for city_bucket in prov_bucket.get("cities", {}).values():
            city_name = _prefer_standard_name(city_bucket.get("names", []), "city")
            city_subs = []
            for item in city_bucket.get("subs", []):
                if isinstance(item, dict):
                    value = str(item.get("name") or "").strip()
                else:
                    value = str(item).strip()
                if value:
                    city_subs.append(value)
            normalized[province_name][city_name] = city_subs

    return normalized


def ensure_region_data(config_path: str, api_key: str) -> Dict[str, Dict[str, List[str]]]:
    """确保并返回用于 GUI 的区域数据，结构为 {province: {city: [counties...]}}。

    行为：
      - 仅从 `config/region_cache.json` 加载并规范化为统一结构。
      - 若缓存不存在或为空，则返回空字典，不在首次启动时联网，也不注入内置简称。

    返回值适用于直接渲染 GUI 树（省->市->区/县）。
    """
    cache_path = get_region_cache_path(config_path)
    cache = load_region_cache(cache_path)
    if cache:
        return _normalize_region_cache_data(cache)
    return {}


def fetch_and_save_region_hierarchy(config_path: str, api_key: str, target_provinces: Optional[List[str]] = None) -> Dict[str, Dict[str, List[str]]]:
    """从高德拉取省/市/区层级并保存到 region_cache.json。

    行为：
    - 若未提供 `target_provinces`，保持原有行为：保存完整抓取结果到缓存并返回该结果。
    - 若提供 `target_provinces`（列表），则只将抓取结果中属于这些省份的条目合并到已有缓存，
      并只保存/更新这些省份的内容；其他省份在缓存中保持不变。

    仅在用户主动点击“更新行政区”时调用。返回合并后的缓存（完整字典）。
    """
    cache_path = get_region_cache_path(config_path)
    try:
        fetched = fetch_amap_region_hierarchy(api_key)
    except Exception:
        fetched = {}

    # 将抓取到的层级规范为仅包含字符串名称的结构
    out_fetched: Dict[str, Dict[str, List[str]]] = {}
    if isinstance(fetched, dict):
        for prov, cities in fetched.items():
            try:
                if isinstance(cities, dict):
                    out_fetched[prov] = {}
                    for city, subs in cities.items():
                        if isinstance(subs, list):
                            out_fetched[prov][city] = [str(x.get('name') if isinstance(x, dict) and x.get('name') else x) for x in subs if x]
                        else:
                            out_fetched[prov][city] = []
                elif isinstance(cities, list):
                    out_fetched[prov] = {str(c): [] for c in cities}
                else:
                    out_fetched[prov] = {}
            except Exception:
                out_fetched[prov] = {}

    # 若调用方只请求特定省份，则将这些省份的抓取结果合并到现有缓存中
    if target_provinces:
        try:
            existing = load_region_cache(cache_path) or {}
            if not isinstance(existing, dict):
                existing = {}
            merged = dict(existing)
            for prov in target_provinces:
                if prov in out_fetched and out_fetched.get(prov):
                    merged[prov] = out_fetched.get(prov, {})
            try:
                save_region_cache(cache_path, merged)
            except Exception:
                pass
            return merged
        except Exception:
            # 回退：仅返回抓取到的目标子集（不覆盖现有缓存）
            subset = {p: out_fetched.get(p, {}) for p in (target_provinces or [])}
            return subset

    # 默认行为：保存完整抓取的层级（兼容历史行为）
    try:
        save_region_cache(cache_path, out_fetched)
    except Exception:
        pass
    return out_fetched


def unify_region_cache(config_path: str) -> Dict[str, Any]:
    """规范并合并 `config/region_cache.json` 中的顶层省级键。

    目的：消除不同命名（如 "河北" / "河北省"、"石家庄" / "石家庄市"）导致的重复条目，
    并优先保留高德标准命名。
    """
    cache_path = get_region_cache_path(config_path)
    raw = load_region_cache(cache_path) or {}
    merged = _normalize_region_cache_data(raw)

    try:
        save_region_cache(cache_path, merged)
    except Exception:
        pass

    return merged



def build_area_description(task: Dict[str, Any]) -> str:
    if task.get("area_type") == "bbox":
        bbox = task.get("bbox", {})
        return f"bbox({bbox.get('left')},{bbox.get('top')},{bbox.get('right')},{bbox.get('bottom')})"
    # 若存在 admin_regions（新格式），则优先使用其中的第一项，否则使用 admin_region
    admin = {}
    if task.get("admin_regions") and isinstance(task.get("admin_regions"), list) and task.get("admin_regions"):
        admin = task.get("admin_regions")[0] or {}
    else:
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
    # 若存在 admin_regions 列表，摘要优先使用首条
    admin = {}
    if task.get("admin_regions") and isinstance(task.get("admin_regions"), list) and task.get("admin_regions"):
        admin = task.get("admin_regions")[0] or {}
    else:
        admin = task.get("admin_region", {})
    return normalize_area(f"{admin.get('province','')} / {admin.get('city','')} / {admin.get('county','')}")


def format_time(dt: Optional[datetime]) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""




# 提供者实现已迁移到 providers.py


# 提供者实现已迁移到 providers.py


# 提供者实现已迁移到 providers.py


try:
    # 优先使用导入的 providers 实现
    fetch_provider_records  # type: ignore
except Exception:
    # 回退：提供一个占位函数以避免重构期间出现 NameError
    def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
        raise RuntimeError('providers.fetch_provider_records not available')




# 每文件的关键键加载由 poi_utils.load_keys_from_file 提供


# 一些工具函数已移动到 poi_utils.py

def run_task(task: Dict[str, Any], config: Dict[str, Any], mode: str = "manual", progress_callback=None, stop_event=None) -> Dict[str, Any]:
    # 核心任务执行函数的简要说明已移至 docs/PLAN_AND_COMMIT.md
    # 本处保留最小内联说明与必要代码缩进以保证语法正确
    run_time = format_time(datetime.now())
    task_name = task.get("name", task.get("task_name", "unnamed_task"))
    # configure module logger based on task config
    debug_mode = bool(config.get("debug", False)) if isinstance(config, dict) else False
    if debug_mode:
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logger.addHandler(ch)
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    area = get_task_area_summary(task)
    page_limit = int(config.get("default_page_limit", 3))
    cache_path = get_region_cache_path(str(config.get("_config_path", "config/poi_config.json")))

    # 准备增量输出路径并加载用于增量写入的已存在键集合
    base_dir = Path(config.get("results_dir", "POI_Data"))
    date_folder = datetime.now().strftime("%Y-%m-%d")
    result_dir = base_dir / date_folder
    incremental_path = result_dir / f"{task_name}_incremental.csv"
    existing_keys = set()
    if config.get("incremental", True):
        try:
            # 按用户要求：最终去重只针对增量文件中的键进行检查
            if incremental_path.exists():
                existing_keys = load_keys_from_file(str(incremental_path))
            else:
                existing_keys = set()
        except Exception:
            existing_keys = set()
    # 保存运行开始时的增量键快照，用于在运行结束时进行最终去重，
    # 避免把本次运行过程中 append_new_records 已写入文件的记录当作“已存在”键
    initial_existing_keys = set(existing_keys)

    # 确定提供商：仅使用任务级 `provider` 来指定单一提供商；若任务未指定则使用内置支持列表
    prov = task.get("provider")
    if prov:
        providers = [prov]
    else:
        # 任务未指定 provider：记录失败并终止该任务（避免隐式使用其他提供商）
        entry = {
            "task_name": task_name,
            "run_time": run_time,
            "area": area,
            "status": "failed",
            "records": 0,
            "mode": mode,
            "message": "任务未指定地图提供商（provider）。请在任务配置中设置 'provider' 字段。",
        }
        entry["area"] = normalize_area(entry.get("area", ""))
        try:
            append_log(config.get("logs_path"), entry)
        except Exception:
            pass
        if progress_callback:
            try:
                progress_callback({"type": "task_failed", "task_name": task_name, "message": "未指定 provider"})
            except Exception:
                pass
        return entry

    if task.get("area_type") == "admin" and not (task.get("admin_region") or task.get("admin_regions")):
        raise ValueError("行政区域任务必须包含 admin_regions 配置（或兼容的 admin_region）。")
    if task.get("area_type") == "bbox" and not task.get("bbox"):
        raise ValueError("BBox 任务必须包含 bbox 配置。")

    # 资源仅来自任务本身；高德/天地图使用 data_type_tree 解析编码。
    resources = task.get("resources", [])
    if not isinstance(resources, list):
        resources = [resources]
    if not resources:
        raise ValueError("任务必须包含 resources 配置。")

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
        # try:
        #     if title is not None:
        #         progress_callback({"type": "summary_title", "message": title})
        #     if line1 is not None:
        #         progress_callback({"type": "summary_query", "message": line1})
        #     if line2 is not None:
        #         progress_callback({"type": "summary_status", "message": line2})
        # except Exception:
        #     pass
        # 同时在控制台输出一条紧凑的一行摘要，方便快速查看
        try:
            parts = []
            if title:
                parts.append(str(title))
            if line1:
                parts.append(str(line1))
            if line2:
                parts.append(str(line2))
            if parts:
                compact = " | ".join(parts)
                try:
                    progress_callback({"type": "message", "message": compact})
                    logger.info(compact)
                    print(compact)
                except Exception:
                    # fallback to print if logger fails
                    try:
                        print(compact)
                    except Exception:
                        pass
        except Exception:
            pass

    # 限速：用于控制省级展开时的最小请求间隔与每提供商的令牌桶速率限制
    rate_lock = threading.Lock()
    last_call = {"t": 0.0}
    global_delay = float(config.get("province_expand_delay_seconds", 0.0))

    import rate_limiter

    def fetch_with_delay(provider_arg, api_keys_arg, keyword_arg, resource_type_arg, latitude_arg, longitude_arg, bbox_arg, admin_region_arg, page_limit_arg, stop_event=None, pcallback=None):
        # 全局最小请求间隔（使省级展开请求更平缓）
        with rate_lock:
            now = time.time()
            wait = max(0.0, global_delay - (now - last_call["t"]))
            if wait > 0:
                time.sleep(wait)
            last_call["t"] = time.time()
        # 按提供商的令牌桶限流（默认 1 qps）
        try:
            rate_limiter.acquire(provider_arg)
        except Exception:
            # 若限流器失败，则退回到保守的 sleep 等待
            time.sleep(max(1.0, global_delay))
        # 调试：显示传入的 admin_region
        try:
            logger.debug("fetch_with_delay provider=%s admin_region=%s keyword=%s resource=%s", provider_arg, admin_region_arg, keyword_arg, resource_type_arg)
        except Exception:
            pass
        # allow caller to override progress_callback for per-subtask page tracking
        use_callback = pcallback if pcallback is not None else progress_callback
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
            progress_callback=use_callback,
            stop_event=stop_event,
        )
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

    # 加载提供商映射文件（tree + flat），若存在则使用
    provider_mappings: Dict[str, Dict[str, Any]] = {}
    for p in SUPPORTED_PROVIDERS:
        try:
            tree = load_json(f"config/data_type_tree.{p}.json") or {}
        except Exception:
            tree = {}
        try:
            flat = load_json(f"config/data_type_map.{p}.json") or {}
        except Exception:
            flat = {}
        provider_mappings[p] = {"tree": tree, "flat": flat}

    def resolve_data_type(provider_name: str, resource_name: str, keyword_name: str) -> Optional[str]:
        """尝试使用扁平映射(flat)然后树映射(tree)解析提供商特定的数据类型/编码。

        优先顺序：flat[resource] -> flat[keyword] -> tree 顶级精确匹配 -> tree 子项匹配 -> None
        """
        try:
            mapping = provider_mappings.get(provider_name, {})
            flat = mapping.get("flat", {}) or {}
            tree = mapping.get("tree", {}) or {}
            # 扁平映射精确匹配
            if resource_name and resource_name in flat and flat.get(resource_name):
                return flat.get(resource_name)
            if keyword_name and keyword_name in flat and flat.get(keyword_name):
                return flat.get(keyword_name)
            # 树映射顶层精确匹配
            if resource_name and resource_name in tree and tree[resource_name].get("code"):
                return tree[resource_name].get("code")
            if keyword_name and keyword_name in tree and tree[keyword_name].get("code"):
                return tree[keyword_name].get("code")
            # 树映射子项
            for top, node in tree.items():
                children = node.get("children", {}) if isinstance(node, dict) else {}
                if resource_name and resource_name in children:
                    code = children[resource_name].get("code") if isinstance(children[resource_name], dict) else None
                    if code:
                        return code
                if keyword_name and keyword_name in children:
                    code = children[keyword_name].get("code") if isinstance(children[keyword_name], dict) else None
                    if code:
                        return code
        except Exception:
            return None
        return None

    def compute_provider_query(provider_name: str, keyword_value, pass_resource_value):
        """返回传给提供商的 (keyword, place_type)：
        - 对于百度：使用 keyword 作为查询，并将 place_type 作为 type（当 pass_resource_value 为 dict 时使用其字段）
        - 对于高德/天地图：保留 keyword，place_type 应使用已解析的编码或字符串
        - 其他提供商：返回 (keyword, pass_resource_value)
        """
        try:
            call_kw = keyword_value
            call_place = pass_resource_value
            if provider_name == "baidu":
                    # 如果 pass_resource_value 是以 {'query':..., 'type':...} 形式保存的 dict
                if isinstance(pass_resource_value, dict):
                    call_kw = pass_resource_value.get("query") or keyword_value
                    call_place = pass_resource_value.get("type") or ""
                else:
                        # 否则保留 keyword 作为主要查询，并将资源作为次要类型传递
                    call_place = pass_resource_value
            # 高德/天地图：在 call_place 保留解析后的编码（已由 resolve_data_type 处理）
            return call_kw, call_place
        except Exception:
            return keyword_value, pass_resource_value

    # 写入与记录集合的并发保护
    write_lock = threading.Lock()

    def execute_subtask(call_kw, call_place, latitude_arg, longitude_arg, bbox_arg, admin_region_arg, area_label, level_label, resource, index: int = 1, total: int = 1):
        """统一执行一次子任务：调用 provider、归一化、进度上报、增量追加与日志记录。"""
        # track per-subtask page activity by wrapping progress_callback
        page_counter = {"pages": 0}

        def _wrapped_progress(evt: Dict[str, Any]):
            try:
                if isinstance(evt, dict) and evt.get("type") == "subtask_page":
                    page_counter["pages"] = max(page_counter.get("pages", 0), int(evt.get("page", 0)))
                    # emit a concise line showing current page for this subtask
                    emit_progress_lines(
                        title=f"[{index}/{total}] {task_name} - {area_label} - {resource} - {PROVIDER_DISPLAY.get(provider, provider)}",
                        line1=f"{area_label} - {resource}",
                        line2=f"正在请求第 {page_counter['pages']} 页...",
                    )
                # forward to outer progress_callback too
                if progress_callback:
                    try:
                        progress_callback(evt)
                    except Exception:
                        pass
            except Exception:
                pass

        provider_records = []
        last_exc = None
        for attempt in range(3):
            try:
                provider_records = fetch_with_delay(
                    provider,
                    api_keys,
                    call_kw,
                    call_place,
                    latitude_arg,
                    longitude_arg,
                    bbox_arg,
                    admin_region_arg,
                    page_limit,
                    stop_event=stop_event,
                    pcallback=_wrapped_progress,
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    try:
                        emit_progress_lines(
                            title=f"{task_name} - {area_label} - {resource} - {provider}",
                            line1=f"{area_label} - {resource}",
                            line2=f"请求失败，重试 {attempt + 1}/2: {exc}",
                        )
                    except Exception:
                        pass
                    continue
        if last_exc is not None:
            exc = last_exc
            append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), {
                "task_name": task_name,
                "run_time": run_time,
                "area": normalize_area(str(area_label)),
                "provider": PROVIDER_DISPLAY.get(provider, provider),
                "status": "failed",
                "records": 0,
                "mode": mode,
                "message": f"子区域抓取失败: {exc}",
            })
            if progress_callback:
                try:
                    progress_callback({"type": "subtask_failed", "task_name": task_name, "area": area_label, "level": level_label, "provider": provider, "message": str(exc)})
                except Exception:
                    pass
            emit_progress_lines(
                title=f"{task_name} - {area_label} - {resource} - {provider}",
                line1=f"{area_label} - {resource}",
                line2=f"失败: {exc}",
            )
            provider_records = []

        # 归一化并追加到共享 records（并发写保护）
        try:
            new_norm = [normalize_record(provider, item, resource, task_name, run_time) for item in provider_records]
            with write_lock:
                records.extend(new_norm)
        except Exception:
            new_norm = []

        fetched_count = len(provider_records) if provider_records else 0
        normalized_count = len(new_norm)
        appended_count = 0

        if progress_callback:
            try:
                progress_callback({"type": "subtask_done", "task_name": task_name, "area": area_label, "level": level_label, "provider": provider, "count": fetched_count})
            except Exception:
                pass
            emit_progress_lines(
                title=f"{task_name} - {area_label} - {resource} - {provider}",
                line1=f"{area_label} - {resource}",
                line2=f"成功, 数据数量: {fetched_count}",
            )

        try:
            if config.get("incremental", True) and new_norm:
                # 增量写入与 existing_keys 更新须由写锁保护
                with write_lock:
                    appended = append_new_records(new_norm, str(incremental_path), existing_keys)
                    appended_count = appended
                    append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), make_log_entry(task_name, run_time, str(area_label), "partial", records=appended, provider=PROVIDER_DISPLAY.get(provider, provider), message="incremental append"))
        except Exception:
            pass

        # 临时调试输出：记录子任务各阶段计数（fetched / normalized / appended）
        try:
            logger.debug("subtask_counts area=%r resource=%r provider=%r fetched=%d normalized=%d appended=%d", area_label, resource, provider, fetched_count, normalized_count, appended_count)
        except Exception:
            pass

        return provider_records

    # providers 已由任务级决定（单一提供商），将其展开为单一变量以简化后续逻辑
    provider = providers[0]
    # 收集子任务队列，后续顺序消费以便统一限速/重试策略
    subtasks: List[Dict[str, Any]] = []
    for resource in resources:
        keywords = [resource]
        try:
            logger.debug("processing resource=%r keywords=%s", resource, keywords)
        except Exception:
            pass
        for keyword in keywords:
                # 解析提供商特定的数据类型/编码（优先 tree，然后 flat）；若无则回退到资源名
                resolved = resolve_data_type(provider, resource, keyword)
                pass_resource = resolved if resolved else resource
                if task.get("area_type") == "admin":
                    # 规范化 admin_regions 列表
                    regions_list = task.get("admin_regions") if task.get("admin_regions") else [task.get("admin_region", {})]
                    norm_regions = []
                    for a in regions_list:
                        try:
                            prov_name = a.get('province', '') if isinstance(a, dict) else ''
                            cit = a.get('city', '') if isinstance(a, dict) else ''
                            cnty = a.get('county', '') if isinstance(a, dict) else ''
                            if isinstance(cit, str) and cit.strip() == '全部':
                                cit = ''
                            if isinstance(cnty, str) and cnty.strip() == '全部':
                                cnty = ''
                            norm_regions.append({'province': prov_name, 'city': cit, 'county': cnty})
                        except Exception:
                            norm_regions.append({'province': a.get('province', '') if isinstance(a, dict) else '', 'city': '', 'county': ''})
                    regions_list = norm_regions

                    # 对每个指定区域逐一展开为子任务（市级/区县/单点）
                    for admin in regions_list:
                        prov_name = admin.get('province', '')
                        cit = admin.get('city', None)
                        cnty = admin.get('county', None)

                        # 省级展开（city == "" 表示 UI 中选择了全部市）
                        if cit == "":
                            try:
                                cache = load_region_cache(cache_path)
                            except Exception:
                                cache = {}
                            cities_list: List[str] = []
                            province_cache = {}
                            if isinstance(cache, dict) and prov_name in cache:
                                val = cache[prov_name]
                                province_cache = val if isinstance(val, dict) else {}
                                if isinstance(val, list):
                                    cities_list = [str(x) for x in val]
                                elif isinstance(val, dict):
                                    cities_list = list(val.keys())
                            if not cities_list:
                                cities_list = [""]

                            # 直辖市在缓存中通常只有一个“城区”节点；省级空 city 配置应直接下钻到区县。
                            if isinstance(province_cache, dict) and len(cities_list) == 1:
                                municipality_city = cities_list[0]
                                municipality_counties = list(province_cache.get(municipality_city, []))
                                if municipality_city and municipality_counties:
                                    for county_name in municipality_counties:
                                        county_display = county_name.get("name") if isinstance(county_name, dict) else county_name
                                        county_adcode = county_name.get("adcode") if isinstance(county_name, dict) else ""
                                        if progress_callback:
                                            try:
                                                progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": municipality_city, "county": county_display, "level": "county", "provider": provider})
                                            except Exception:
                                                pass
                                        admin_region_param = {"province": prov_name, "city": municipality_city, "county": county_display}
                                        if county_adcode:
                                            admin_region_param["adcode"] = county_adcode
                                        call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                                        logger.debug("append direct-admin county subtask prov=%r city=%r county=%r resource=%r", prov_name, municipality_city, county_display, resource)
                                        subtasks.append({
                                            "call_kw": call_kw,
                                            "call_place": call_place,
                                            "latitude": None,
                                            "longitude": None,
                                            "bbox": None,
                                            "admin_region": admin_region_param,
                                            "resource": resource,
                                            "area_label": f"{prov_name} / {municipality_city} / {county_display}",
                                            "level_label": "county",
                                        })
                                    continue

                            for city_name in cities_list:
                                if progress_callback:
                                    try:
                                        progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": city_name, "level": "city", "provider": provider})
                                    except Exception:
                                        pass
                                call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                                logger.debug("append city subtask prov=%r city=%r resource=%r", prov_name, city_name, resource)
                                subtasks.append({
                                    "call_kw": call_kw,
                                    "call_place": call_place,
                                    "latitude": None,
                                    "longitude": None,
                                    "bbox": None,
                                    "admin_region": {"province": prov_name, "city": city_name, "county": ""},
                                    "resource": resource,
                                    "area_label": f"{prov_name} / {city_name}",
                                    "level_label": "city",
                                })
                            # 处理完当前 admin，继续下一个 admin
                            continue

                        # 市级展开（只有 city 指定、county 为空）
                        if cit and (cnty == "" or cnty is None):
                            try:
                                cache = load_region_cache(cache_path)
                            except Exception:
                                cache = {}
                            counties_list: List[str] = []
                            if isinstance(cache, dict) and prov_name in cache:
                                val = cache[prov_name]
                                if isinstance(val, dict) and cit in val:
                                    counties_list = list(val.get(cit, []))
                            if not counties_list:
                                gaode_key = api_keys.get("gaode", "")
                                counties_list = fetch_amap_subdistrict(gaode_key, prov_name, cit)
                            if not counties_list:
                                counties_list = [""]

                            for county_name in counties_list:
                                county_display = county_name.get("name") if isinstance(county_name, dict) else county_name
                                county_adcode = county_name.get("adcode") if isinstance(county_name, dict) else ""
                                if progress_callback:
                                    try:
                                        progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "county", "provider": provider})
                                    except Exception:
                                        pass
                                admin_region_param = {"province": prov_name, "city": cit, "county": county_display}
                                if county_adcode:
                                    admin_region_param["adcode"] = county_adcode
                                call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                                logger.debug("append county subtask prov=%r city=%r county=%r resource=%r", prov_name, cit, county_display, resource)
                                subtasks.append({
                                    "call_kw": call_kw,
                                    "call_place": call_place,
                                    "latitude": None,
                                    "longitude": None,
                                    "bbox": None,
                                    "admin_region": admin_region_param,
                                    "resource": resource,
                                    "area_label": f"{prov_name} / {cit} / {county_display}",
                                    "level_label": "county",
                                })
                            continue

                        # 指定完整行政区（省/市/县） -> 单次查询
                        call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                        if progress_callback:
                            try:
                                progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": cnty, "level": "single", "provider": provider})
                            except Exception:
                                pass
                        logger.debug("append single admin subtask prov=%r city=%r county=%r resource=%r", prov_name, cit, cnty, resource)
                        subtasks.append({
                            "call_kw": call_kw,
                            "call_place": call_place,
                            "latitude": None,
                            "longitude": None,
                            "bbox": None,
                            "admin_region": {"province": prov_name, "city": cit, "county": cnty},
                            "resource": resource,
                            "area_label": f"{prov_name} / {cit} / {cnty}",
                            "level_label": "single",
                        })
                    # 完成 admin_regions 的展开后，跳到下一个 keyword
                    continue
                # 市级展开：遍历区/县
                if cit and cnty == "":
                    try:
                        cache = load_region_cache(cache_path)
                    except Exception:
                        cache = {}
                    counties_list: List[str] = []
                    if isinstance(cache, dict) and prov_name in cache:
                        val = cache[prov_name]
                        if isinstance(val, dict) and cit in val:
                            counties_list = list(val.get(cit, []))
                    if not counties_list:
                        gaode_key = api_keys.get("gaode", "")
                        counties_list = fetch_amap_subdistrict(gaode_key, prov_name, cit)
                    if not counties_list:
                        counties_list = [""]

                    for county_name in counties_list:
                        # 支持 counties_list 条目为包含 adcode 的 dict 格式
                        county_display = county_name.get("name") if isinstance(county_name, dict) else county_name
                        county_adcode = county_name.get("adcode") if isinstance(county_name, dict) else ""
                        if progress_callback:
                            try:
                                progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "county", "provider": provider})
                                print(f"1098");
                            except Exception:
                                pass
                            # emit_progress_lines(
                            #     title=f"{task_name} - {prov_name}/{cit}/{county_display} - {resource} - {provider}",
                            #     line1=f"{prov_name}/{cit}/{county_display} - {resource}",
                            #     line2="开始",
                            # )
                        admin_region_param = {"province": prov_name, "city": cit, "county": county_display}
                        if county_adcode:
                            admin_region_param["adcode"] = county_adcode
                        call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                        logger.debug("append county subtask prov=%r city=%r county=%r resource=%r", prov_name, cit, county_display, resource)
                        subtasks.append({
                            "call_kw": call_kw,
                            "call_place": call_place,
                            "latitude": None,
                            "longitude": None,
                            "bbox": None,
                            "admin_region": admin_region_param,
                            "resource": resource,
                            "area_label": f"{prov_name} / {cit} / {county_display}",
                            "level_label": "county",
                        })
                        # 如果提供商在当前区县返回的结果达到 page_limit * page_size 阈值，
                        # 说明该区可能存在漏采（过于稠密）。在有 polyline 的情况下，尝试使用网格细化采集。
                        try:
                            page_size = 20
                            max_expected = int(page_limit) * page_size
                            if len(provider_records) >= max_expected:
                                # 仅在存在 polyline 信息时尝试细化
                                if isinstance(county_name, dict) and county_name.get("polyline"):
                                    bbox = bbox_from_polyline(county_name.get("polyline"))
                                    if bbox:
                                        grids = generate_grid(bbox, nx=2, ny=2)
                                        for idx, cell in enumerate(grids):
                                            if progress_callback:
                                                try:
                                                    progress_callback({"type": "start_subtask", "task_name": task_name, "province": prov_name, "city": cit, "county": county_display, "level": "grid", "provider": provider, "grid_index": idx})
                                                    print(f"1137");
                                                except Exception:
                                                    pass
                                                emit_progress_lines(
                                                    title=f"{task_name} - {prov_name}/{cit}/{county_display} [grid {idx}] - {resource} - {provider}",
                                                    line1=f"{prov_name}/{cit}/{county_display} [grid {idx}] - {resource}",
                                                    line2=f"开始 网格 {idx}",
                                                )
                                                call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                                                subtasks.append({
                                                    "call_kw": call_kw,
                                                    "call_place": call_place,
                                                    "latitude": None,
                                                    "longitude": None,
                                                    "bbox": cell,
                                                    "admin_region": None,
                                                    "resource": resource,
                                                    "area_label": f"{prov_name} / {cit} / {county_display} [grid {idx}]",
                                                    "level_label": f"grid_{idx}",
                                                })
                            
                        except Exception:
                            pass
                    continue
                    
                    
                    

                # 具体的行政区（省/市/县） -> 单次查询调用（使用 execute_subtask）
                call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                if progress_callback:
                    try:
                        progress_callback({"type": "start_subtask", "task_name": task_name, "area": normalize_area(area), "level": "single", "provider": provider})
                        print(f"1166");
                    except Exception:
                        pass
                # emit_progress_lines(
                #     title=f"{task_name} - {area} - {resource} - {provider}",
                #     line1=f"{area} - {resource}",
                #     line2="开始",
                # )
                logger.debug("append single subtask area=%r resource=%r admin=%r", area, resource, admin)
                subtasks.append({
                    "call_kw": call_kw,
                    "call_place": call_place,
                    "latitude": None,
                    "longitude": None,
                    "bbox": None,
                    "admin_region": admin,
                    "resource": resource,
                    "area_label": area,
                    "level_label": "single",
                })

                if task.get("area_type") != "admin":
                    # 基于 bbox 或点的调用
                    if progress_callback:
                        try:
                            progress_callback({"type": "start_subtask", "task_name": task_name, "area": area, "level": "single", "provider": provider})
                            print(f"1193");
                        except Exception:
                            pass
                    # 对于 bbox/点 查询也加入子任务队列，统一在队列消费时处理
                    call_kw, call_place = compute_provider_query(provider, keyword, pass_resource)
                    subtasks.append({
                        "call_kw": call_kw,
                        "call_place": call_place,
                        "latitude": task_target_values(task).get("latitude"),
                        "longitude": task_target_values(task).get("longitude"),
                        "bbox": task.get("bbox") if task.get("area_type") == "bbox" else None,
                        "admin_region": None,
                        "resource": resource,
                        "area_label": area,
                        "level_label": "single",
                    })

    # 最终去重处理并根据增量文件执行最终去重
    # 开始顺序消费子任务队列
    # Debug: 输出子任务列表以便定位多区域展开问题
    try:
        logger.debug("subtasks_count=%d", len(subtasks))
    except Exception:
        pass
    total_subtasks = len(subtasks)
    try:
        logger.debug("total_subtasks=%d", total_subtasks)
    except Exception:
        pass

    # Emit task start summary (0)
    try:
        emit_progress_lines(title=f"{task_name} - {PROVIDER_DISPLAY.get(provider, provider)} - 子任务 {total_subtasks}", line1=f"任务: {task_name}", line2=f"提供商: {PROVIDER_DISPLAY.get(provider, provider)} | 子任务共 {total_subtasks}")
    except Exception:
        pass
    try:
        max_workers = 1

        subtask_attempts = total_subtasks
        subtask_success = 0
        total_fetched = 0

        if max_workers <= 1:
            # 退回到顺序消费以保证兼容性
            for idx, st in enumerate(subtasks, start=1):
                if stop_event and getattr(stop_event, "is_set", lambda: False)():
                    break
                area_label = st.get("area_label")
                level_label = st.get("level_label")
                # 上报子任务开始
                if progress_callback:
                    try:
                        progress_callback({
                            "type": "start_subtask",
                            "task_name": task_name,
                            "area": area_label,
                            "level": level_label,
                            "provider": provider,
                        })
                    except Exception:
                        pass
                emit_progress_lines(
                    title=f"[{idx}/{total_subtasks}] {task_name} - {area_label} - {st.get('resource')} - {PROVIDER_DISPLAY.get(provider, provider)}",
                    line1=f"{area_label} - {st.get('resource')}",
                    line2=f"开始 子任务 {idx}/{total_subtasks}",
                )
                try:
                    provider_records = execute_subtask(
                        st.get("call_kw"),
                        st.get("call_place"),
                        st.get("latitude"),
                        st.get("longitude"),
                        st.get("bbox"),
                        st.get("admin_region"),
                        st.get("area_label"),
                        st.get("level_label"),
                        st.get("resource"),
                        index=idx,
                        total=total_subtasks,
                    )
                    fetched = len(provider_records) if provider_records else 0
                    total_fetched += fetched
                    if fetched >= 0:
                        subtask_success += 1
                except Exception:
                    try:
                        append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), make_log_entry(task_name, run_time, "", "error", records=0, provider=PROVIDER_DISPLAY.get(provider, provider), message=f"子任务异常"))
                    except Exception:
                        pass
        else:
            # 并发消费子任务，但保留对 stop_event 的检查
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for idx, st in enumerate(subtasks, start=1):
                    if stop_event and getattr(stop_event, "is_set", lambda: False)():
                        break
                    area_label = st.get("area_label")
                    level_label = st.get("level_label")
                    if progress_callback:
                        try:
                            progress_callback({
                                "type": "start_subtask",
                                "task_name": task_name,
                                "area": area_label,
                                "level": level_label,
                                "provider": provider,
                            })
                            print(f"1299");
                        except Exception:
                            pass
                    emit_progress_lines(
                        title=f"[{idx}/{total_subtasks}] {task_name} - {area_label} - {st.get('resource')} - {PROVIDER_DISPLAY.get(provider, provider)}",
                        line1=f"{area_label} - {st.get('resource')}",
                        line2=f"开始 子任务 {idx}/{total_subtasks}",
                    )
                    futures.append(
                        executor.submit(
                            execute_subtask,
                            st.get("call_kw"),
                            st.get("call_place"),
                            st.get("latitude"),
                            st.get("longitude"),
                            st.get("bbox"),
                            st.get("admin_region"),
                            st.get("area_label"),
                            st.get("level_label"),
                            st.get("resource"),
                            idx,
                            total_subtasks,
                        )
                    )

                for fut in as_completed(futures):
                    if stop_event and getattr(stop_event, "is_set", lambda: False)():
                        break
                    try:
                        provider_records = fut.result()
                        fetched = len(provider_records) if provider_records else 0
                        total_fetched += fetched
                        subtask_success += 1
                    except Exception as exc:
                        try:
                            append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), make_log_entry(task_name, run_time, "", "error", records=0, provider=PROVIDER_DISPLAY.get(provider, provider), message=f"子任务异常: {exc}"))
                        except Exception:
                            pass
                        # 将错误通过 progress_callback 也发送到日志窗口/UI
                        if progress_callback:
                            try:
                                progress_callback({"type": "subtask_failed", "task_name": task_name, "message": str(exc)})
                            except Exception:
                                pass
                        
    except Exception:
        pass

    records = dedupe_records(records)
    if config.get("incremental", True):
        try:
            # 使用运行开始时的增量键快照进行最终去重，
            # 这样本次运行期间已写入增量文件的记录不会把内存中的 records 全部去掉
            existing_keys_for_final = initial_existing_keys
        except Exception:
            existing_keys_for_final = set()
        records = dedupe_records(records, existing_keys=existing_keys_for_final)

    if not records:
        entry = {
            "task_name": task_name,
            "run_time": run_time,
            "area": area,
            "status": "success",
            "records": 0,
            "mode": mode,
            "message": "无新增数据。",
            "subtask_attempts": int(total_subtasks) if 'total_subtasks' in locals() else 0,
            "subtask_success": int(subtask_success) if 'subtask_success' in locals() else 0,
            "total_fetched": int(total_fetched) if 'total_fetched' in locals() else 0,
        }
        entry["area"] = normalize_area(entry.get("area", ""))
        append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), entry)
        if progress_callback:
            try:
                progress_callback({"type": "task_done", "task_name": task_name, "records": 0})
            except Exception:
                pass
        try:
            emit_progress_lines(
                title=f"{task_name} - 完成",
                line1=f"子任务: {entry.get('subtask_attempts')}/{entry.get('subtask_success')} 完成 | 抓取总数: {entry.get('total_fetched')} | 去重后: {entry.get('records')}",
                line2=f"输出: {entry.get('message')}",
            )
        except Exception:
            pass
        return entry

    # 保存输出
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    base_dir = Path(config.get("results_dir", "POI_Data"))
    output_base = base_dir / date_folder / f"{task_name}_{timestamp}"
    saved_paths: List[str] = []
    formats: List[str] = [config.get("export_format", "csv")]
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
        "subtask_attempts": int(total_subtasks),
        "subtask_success": int(subtask_success) if 'subtask_success' in locals() else None,
        "total_fetched": int(total_fetched) if 'total_fetched' in locals() else None,
    }
    entry["area"] = normalize_area(entry.get("area", ""))
    append_log(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"), entry)
    if progress_callback:
        try:
            progress_callback({"type": "task_done", "task_name": task_name, "records": len(records)})
        except Exception:
            pass
    # Emit final task summary line for UI/console
    try:
        emit_progress_lines(
            title=f"{task_name} - 完成",
            line1=f"子任务: {entry.get('subtask_attempts')}/{entry.get('subtask_success')} 完成 | 抓取总数: {entry.get('total_fetched')} | 去重后: {entry.get('records')}",
            line2=f"输出: {entry.get('message')}",
        )
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
    # 若任务自身存在调度配置则使用，否则退回到配置中的全局 schedule_interval_days
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
    for task in config.get("tasks", []):
        print(f"- {task.get('name')} (enabled={task.get('enabled', True)}, area={get_task_area_summary(task)}, resources={task.get('resources', [])})")


def show_logs(config: Dict[str, Any], status: Optional[str] = None) -> None:
    logs = load_logs(config.get("logs_path", "logs/poi_fetcher_logs.jsonl"))
    for entry in logs:
        if status and entry.get("status") != status:
            continue
        print(json.dumps(entry, ensure_ascii=False))


def create_gui(config_path: str) -> None:
    # 为避免依赖 tkinter，已移除 Tkinter GUI。
    # 请改用 PyQt GUI，运行时加上 --gui 参数。
    print("Tkinter GUI 已移除。请使用 PyQt GUI（运行时加 --gui）。")


def create_gui_pyqt(config_path: str) -> None:
    # 委托给提取的 gui_pyqt 模块（延迟导入以避免循环依赖）
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
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败任务")
    parser.add_argument("--allow-auto-start", action="store_true", help="程序启动时执行调度任务")
    return parser.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    # 使用 config_loader 加载并与 DEFAULT_CONFIG 合并
    try:
        cfg = config_loader.load_config(path)
    except Exception:
        return create_default_config(path)
    merged = DEFAULT_CONFIG.copy()
    if isinstance(cfg, dict):
        merged.update(cfg)
    merged["_config_path"] = path
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
