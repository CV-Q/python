import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import openpyxl
except Exception:
    openpyxl = None

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
    "province",
    "city",
    "county",
    "run_time",
]

X_PI = math.pi * 3000.0 / 180.0


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


def save_to_csv(records: List[Dict[str, Any]], path: str) -> str:
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=DEFAULT_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in DEFAULT_FIELDS})
    return str(filepath)


def append_to_csv(records: List[Dict[str, Any]], path: str) -> int:
    """Append records to a CSV file. Writes header if file does not exist.

    Returns number of rows appended.
    """
    if not records:
        return 0
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_header = not filepath.exists()
    appended = 0
    with filepath.open("a", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=DEFAULT_FIELDS)
        if write_header:
            writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in DEFAULT_FIELDS})
            appended += 1
    return appended


def append_new_records(records: List[Dict[str, Any]], path: str, existing_keys: Optional[set] = None) -> int:
    """Append only records whose build_record_key is not in existing_keys.

    Returns number appended and updates existing_keys in-place if provided.
    """
    if existing_keys is None:
        existing_keys = set()
    to_append: List[Dict[str, Any]] = []
    # helper to check if a name has any coord-key in existing_keys
    def name_has_coord(name: str) -> bool:
        prefix = f"{name}|"
        for k in existing_keys:
            if k.startswith(prefix):
                return True
        return False

    for record in records:
        name = (record.get("name") or "").strip().lower()
        lat = record.get("latitude")
        lng = record.get("longitude")
        if lat is None or lng is None:
            # incoming record has no coords: consider it existing if either name-only
            # key exists or any coord-key for same name exists
            if name in existing_keys or name_has_coord(name):
                continue
            key = name
            existing_keys.add(key)
            to_append.append(record)
        else:
            # incoming record has coords: build primary key
            key = f"{name}|{round(float(lat),6)}|{round(float(lng),6)}"
            # consider existing if primary exists or name-only exists
            if key in existing_keys or name in existing_keys:
                continue
            existing_keys.add(key)
            to_append.append(record)
    if not to_append:
        return 0
    return append_to_csv(to_append, path)


def save_to_json(records: List[Dict[str, Any]], path: str) -> str:
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return str(filepath)


def save_to_excel(records: List[Dict[str, Any]], path: str) -> str:
    if openpyxl is None:
        raise ImportError("Excel 导出需要 openpyxl，可通过 pip install openpyxl 安装。")
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(DEFAULT_FIELDS)
    for record in records:
        sheet.append([record.get(field, "") for field in DEFAULT_FIELDS])
    workbook.save(filepath)
    return str(filepath)


def append_log(log_path: str, entry: Dict[str, Any]) -> None:
    filepath = Path(log_path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def make_log_entry(task_name: str, run_time: str, area: str, status: str, records: int = 0, provider: str = "", message: str = "") -> Dict[str, Any]:
    # normalize area string to remove empty segments and extra spaces
    def _normalize(a: str) -> str:
        try:
            if not a:
                return ""
            parts = [p.strip() for p in str(a).split("/")]
            parts = [p for p in parts if p]
            return " / ".join(parts)
        except Exception:
            return str(a)

    return {
        "task_name": task_name,
        "run_time": run_time,
        "area": _normalize(area),
        "status": status,
        "records": records,
        "provider": provider,
        "message": message,
    }


def normalize_area(area: str) -> str:
    """Normalize area strings by splitting on '/' and joining non-empty, stripped parts with ' / '."""
    try:
        if not area:
            return ""
        parts = [p.strip() for p in str(area).split("/")]
        parts = [p for p in parts if p]
        return " / ".join(parts)
    except Exception:
        return str(area)


def load_logs(log_path: str) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    path = Path(log_path)
    if not path.exists():
        return logs
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                logs.append(json.loads(line.strip()))
            except Exception:
                continue
    return logs


def export_logs(logs: List[Dict[str, Any]], export_path: str) -> str:
    path = Path(export_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        fields = ["task_name", "run_time", "area", "status", "records", "mode", "message"]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for log_entry in logs:
                writer.writerow({k: log_entry.get(k, "") for k in fields})
    else:
        with path.open("w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    return str(path)


def build_record_key(record: Dict[str, Any]) -> str:
    name = (record.get("name") or "").strip().lower()
    lat = record.get("latitude")
    lng = record.get("longitude")
    if lat is None or lng is None:
        return name
    return f"{name}|{round(float(lat), 6)}|{round(float(lng), 6)}"


def dedupe_records(records: List[Dict[str, Any]], existing_keys: Optional[set] = None) -> List[Dict[str, Any]]:
    if existing_keys is None:
        existing_keys = set()
    deduped: List[Dict[str, Any]] = []
    seen = set(existing_keys)

    def name_has_coord_in_seen(name: str) -> bool:
        prefix = f"{name}|"
        for k in seen:
            if k.startswith(prefix):
                return True
        return False

    for record in records:
        name = (record.get("name") or "").strip().lower()
        lat = record.get("latitude")
        lng = record.get("longitude")
        if lat is None or lng is None:
            # incoming has no coords: skip if name-only seen or any coord for name seen
            if name in seen or name_has_coord_in_seen(name):
                continue
            seen.add(name)
            deduped.append(record)
        else:
            key = f"{name}|{round(float(lat),6)}|{round(float(lng),6)}"
            # skip if exact key or name-only seen
            if key in seen or name in seen:
                continue
            seen.add(key)
            deduped.append(record)
    return deduped


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


def load_keys_from_file(path: str) -> set:
    """Load dedupe keys from a single CSV or JSON file.

    Returns a set of build_record_key() values for records already present
    in the given file. If the path does not exist or cannot be read, an
    empty set is returned.
    """
    keys = set()
    p = Path(path)
    if not p.exists():
        return keys
    if p.is_file():
        if p.suffix.lower() == ".csv":
            try:
                with p.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            keys.add(build_record_key(row))
                        except Exception:
                            continue
            except Exception:
                return set()
        elif p.suffix.lower() == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for row in data:
                        try:
                            keys.add(build_record_key(row))
                        except Exception:
                            continue
            except Exception:
                return set()
    return keys


def format_time(dt: Optional[Any]) -> str:
    try:
        return dt.isoformat(timespec="seconds") if dt else ""
    except Exception:
        return str(dt) if dt else ""


def bd09_to_gcj02(lng: float, lat: float) -> (float, float):
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def normalize_record(
    source: str,
    element: Dict[str, Any],
    place_type: str,
    task_name: str,
    run_time: str,
    admin_region: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    latitude = element.get("latitude") or element.get("lat") or element.get("location_lat")
    longitude = element.get("longitude") or element.get("lng") or element.get("location_lng")
    if source == "baidu" and latitude is not None and longitude is not None:
        longitude, latitude = bd09_to_gcj02(float(longitude), float(latitude))
    admin_region = admin_region or {}

    def _first_nonempty(*vals: Any) -> str:
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return ""

    province_val = _first_nonempty(
        admin_region.get("province", ""),
        element.get("province", ""),
        element.get("provinceName", ""),
        element.get("pname", ""),
        element.get("prov", ""),
        element.get("provName", ""),
    )
    city_val = _first_nonempty(
        admin_region.get("city", ""),
        element.get("city", ""),
        element.get("cityName", ""),
        element.get("cityname", ""),
        element.get("cname", ""),
    )
    county_val = _first_nonempty(
        admin_region.get("county", ""),
        element.get("county", ""),
        element.get("countyName", ""),
        element.get("district", ""),
        element.get("districtName", ""),
        element.get("adname", ""),
    )

    return {
        "source": source,
        "id": element.get("id") or element.get("uid") or element.get("sid") or "",
        "name": element.get("name", ""),
        "address": element.get("address", ""),
        "latitude": float(latitude) if latitude is not None else None,
        "longitude": float(longitude) if longitude is not None else None,
        "type": place_type,
        "contact": element.get("contact", "") or element.get("telephone", "") or element.get("tel", ""),
        "task": task_name,
        "province": province_val,
        "city": city_val,
        "county": county_val,
        "run_time": run_time,
    }


def merge_keywords(config: Dict[str, Any], resource_type: str) -> List[str]:
    keywords = config.get("keywords", {}).get(resource_type, [])
    return list(dict.fromkeys(keywords))


def get_city_center(province: str, city: str, city_coords: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, float]]:
    if city_coords and city in city_coords:
        lat, lon = city_coords[city]
        return {"latitude": lat, "longitude": lon}
    return None
