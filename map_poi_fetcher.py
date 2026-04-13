import argparse
import csv
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

import requests

SUPPORTED_PROVIDERS = ["baidu", "gaode", "tencent"]
SUPPORTED_PLACES = ["hospital", "warehouse", "school", "supermarket", "car_repair", "gas_station"]
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
}

PLACE_KEYWORDS = {
    "hospital": "医院",
    "warehouse": "仓库",
    "school": "学校",
    "supermarket": "超市",
    "car_repair": "汽车修理厂",
    "gas_station": "加油站",
}

AMAP_TYPES = {
    "hospital": "120000",
    "warehouse": "190300",
    "school": "120100",
    "supermarket": "060400",
    "car_repair": "050400",
    "gas_station": "050700",
}

DEFAULT_FIELDS = ["source", "id", "name", "address", "latitude", "longitude", "type"]


def load_keys(path: str) -> Dict[str, str]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件未找到: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "baidu": data.get("baidu_api_key", ""),
        "gaode": data.get("gaode_api_key", ""),
        "tencent": data.get("tencent_api_key", ""),
    }


def normalize_record(source: str, element: Dict[str, Any], place_type: str) -> Dict[str, Any]:
    return {
        "source": source,
        "id": element.get("id") or element.get("uid") or element.get("id"),
        "name": element.get("name", ""),
        "address": element.get("address", ""),
        "latitude": element.get("latitude") or element.get("lat") or element.get("location_lat"),
        "longitude": element.get("longitude") or element.get("lng") or element.get("location_lng"),
        "type": place_type,
    }


def fetch_baidu(key: str, place_type: str, latitude: Optional[float], longitude: Optional[float], radius: Optional[int], bbox: Optional[Dict[str, float]] = None, page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("百度 API Key 未配置。")

    if bbox is None and (latitude is None or longitude is None or radius is None):
        raise ValueError("百度查询需要提供圆形参数或矩形 bbox 参数。")

    keyword = PLACE_KEYWORDS[place_type]
    result = []
    for page in range(0, page_limit):
        params = {
            "query": keyword,
            "output": "json",
            "page_size": 20,
            "page_num": page,
            "ak": key,
            "scope": 2,
        }
        if bbox is not None:
            params["bounds"] = f"{bbox['bottom']},{bbox['left']},{bbox['top']},{bbox['right']}"
        else:
            params["location"] = f"{latitude},{longitude}"
            params["radius"] = radius
        resp = requests.get("http://api.map.baidu.com/place/v2/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            raise RuntimeError(f"百度 API 返回错误: {data}")
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            location = item.get("location", {})
            result.append(normalize_record(
                "baidu",
                {
                    "id": item.get("uid", item.get("id")),
                    "name": item.get("name", ""),
                    "address": item.get("address", ""),
                    "latitude": location.get("lat"),
                    "longitude": location.get("lng"),
                },
                place_type,
            ))
        if len(results) < 20:
            break
    return result


def fetch_gaode(key: str, place_type: str, latitude: Optional[float], longitude: Optional[float], radius: Optional[int], bbox: Optional[Dict[str, float]] = None, page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("高德 API Key 未配置。")

    if bbox is None and (latitude is None or longitude is None or radius is None):
        raise ValueError("高德查询需要提供圆形参数或矩形 bbox 参数。")

    types = AMAP_TYPES.get(place_type, "")
    result = []
    for page in range(1, page_limit + 1):
        if bbox is not None:
            url = "https://restapi.amap.com/v3/place/polygon"
            polygon = (
                f"{bbox['left']},{bbox['top']};"
                f"{bbox['right']},{bbox['top']};"
                f"{bbox['right']},{bbox['bottom']};"
                f"{bbox['left']},{bbox['bottom']}"
            )
            params = {
                "key": key,
                "polygon": polygon,
                "keywords": PLACE_KEYWORDS[place_type],
                "offset": 20,
                "page": page,
                "extensions": "base",
            }
        else:
            url = "https://restapi.amap.com/v3/place/around"
            params = {
                "key": key,
                "location": f"{longitude},{latitude}",
                "keywords": PLACE_KEYWORDS[place_type],
                "radius": radius,
                "offset": 20,
                "page": page,
                "extensions": "base",
            }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"高德 API 返回错误: {data}")
        pois = data.get("pois", [])
        if not pois:
            break
        for item in pois:
            location = item.get("location", "")
            lng, lat = (location.split(",") + [""])[:2]
            result.append(normalize_record(
                "gaode",
                {
                    "id": item.get("id", item.get("uid")),
                    "name": item.get("name", ""),
                    "address": item.get("address", "") or item.get("pname", "") + item.get("cityname", "") + item.get("adname", ""),
                    "latitude": float(lat) if lat else None,
                    "longitude": float(lng) if lng else None,
                },
                place_type,
            ))
        if len(pois) < 20:
            break
    return result


def fetch_tencent(key: str, place_type: str, latitude: Optional[float], longitude: Optional[float], radius: Optional[int], bbox: Optional[Dict[str, float]] = None, page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("腾讯 API Key 未配置。")

    if bbox is None and (latitude is None or longitude is None or radius is None):
        raise ValueError("腾讯查询需要提供圆形参数或矩形 bbox 参数。")

    keyword = PLACE_KEYWORDS[place_type]
    result = []
    for page in range(1, page_limit + 1):
        if bbox is not None:
            boundary = f"rectangle({bbox['bottom']},{bbox['left']},{bbox['top']},{bbox['right']})"
        else:
            boundary = f"nearby({latitude},{longitude},{radius})"
        params = {
            "keyword": keyword,
            "boundary": boundary,
            "key": key,
            "page_size": 20,
            "page_index": page,
            "orderby": "nearest",
        }
        resp = requests.get("https://apis.map.qq.com/ws/place/v1/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            raise RuntimeError(f"腾讯 API 返回错误: {data}")
        pois = data.get("data", [])
        if not pois:
            break
        for item in pois:
            location = item.get("location", {})
            result.append(normalize_record(
                "tencent",
                {
                    "id": item.get("id"),
                    "name": item.get("title", ""),
                    "address": item.get("address", ""),
                    "latitude": location.get("lat"),
                    "longitude": location.get("lng"),
                },
                place_type,
            ))
        if len(pois) < 20:
            break
    return result


def save_to_csv(records: List[Dict[str, Any]], path: str, warn_callback=None) -> Path:
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_path = filepath
    write_header = True
    mode = "w"

    if filepath.exists():
        with filepath.open("r", encoding="utf-8-sig", newline="") as csvfile:
            reader = csv.reader(csvfile)
            try:
                existing_header = next(reader)
            except StopIteration:
                existing_header = []

        if existing_header == DEFAULT_FIELDS:
            mode = "a"
            write_header = False
        else:
            new_path = filepath.with_name(filepath.stem + "_new" + filepath.suffix)
            warning = (
                f"目标 CSV 文件 {filepath} 的表头与预期不一致。"
                f"已改为创建新文件 {new_path} 并写入数据。\n"
            )
            if warn_callback:
                warn_callback(warning)
            else:
                print(warning)
            write_path = new_path
            mode = "w"
            write_header = True

    with write_path.open(mode, encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=DEFAULT_FIELDS)
        if write_header:
            writer.writeheader()
        for record in records:
            writer.writerow(record)
    return write_path


def save_to_json(records: List[Dict[str, Any]], path: str) -> Path:
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return filepath


def run_fetch(provider: str, keys: Dict[str, str], place_type: str, latitude: Optional[float], longitude: Optional[float], radius: Optional[int], bbox: Optional[Dict[str, float]], output: str, json_output: Optional[str], page_limit: int, log_callback=None) -> None:
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    providers = SUPPORTED_PROVIDERS if provider == "all" else [provider]
    all_records: List[Dict[str, Any]] = []
    for current in providers:
        log(f"=== 查询 {current} {place_type} ===\n")
        try:
            records = fetch_places(current, keys, place_type, latitude, longitude, radius, bbox, page_limit=page_limit)
            log(f"从 {current} 获取到 {len(records)} 条结果。\n")
            all_records.extend(records)
        except Exception as exc:
            log(f"{current} 查询失败：{exc}\n")
    if not all_records:
        log("未获取到任何数据。\n")
        return

    saved_csv = save_to_csv(all_records, output, warn_callback=log)
    log(f"已保存 CSV：{saved_csv}\n")
    if json_output:
        saved_json = save_to_json(all_records, json_output)
        log(f"已保存 JSON：{saved_json}\n")


def fetch_places(provider: str, keys: Dict[str, str], place_type: str, latitude: Optional[float], longitude: Optional[float], radius: Optional[int], bbox: Optional[Dict[str, float]], page_limit: int = 5) -> List[Dict[str, Any]]:
    provider = provider.lower()
    if provider == "baidu":
        return fetch_baidu(keys.get("baidu", ""), place_type, latitude, longitude, radius, bbox=bbox, page_limit=page_limit)
    if provider == "gaode":
        return fetch_gaode(keys.get("gaode", ""), place_type, latitude, longitude, radius, bbox=bbox, page_limit=page_limit)
    if provider == "tencent":
        return fetch_tencent(keys.get("tencent", ""), place_type, latitude, longitude, radius, bbox=bbox, page_limit=page_limit)
    raise ValueError(f"不支持的 provider: {provider}")


def create_gui() -> None:
    root = tk.Tk()
    root.title("地图 POI 抓取器")
    root.geometry("720x520")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="地图服务：").grid(row=0, column=0, sticky="w")
    provider_var = tk.StringVar(value="all")
    provider_menu = ttk.Combobox(frame, textvariable=provider_var, values=["all"] + SUPPORTED_PROVIDERS, state="readonly", width=18)
    provider_menu.grid(row=0, column=1, sticky="w", pady=(0, 6))

    ttk.Label(frame, text="地点类型：").grid(row=0, column=2, sticky="w", padx=(12, 0))
    type_var = tk.StringVar(value="hospital")
    type_menu = ttk.Combobox(frame, textvariable=type_var, values=SUPPORTED_PLACES, state="readonly", width=18)
    type_menu.grid(row=0, column=3, sticky="w", pady=(0, 6))

    ttk.Label(frame, text="查询模式：").grid(row=1, column=0, sticky="w")
    mode_var = tk.StringVar(value="circle")
    ttk.Radiobutton(frame, text="圆形", variable=mode_var, value="circle").grid(row=1, column=1, sticky="w")
    ttk.Radiobutton(frame, text="矩形", variable=mode_var, value="bbox").grid(row=1, column=2, sticky="w")

    ttk.Label(frame, text="中心点纬度：").grid(row=2, column=0, sticky="w")
    lat_var = tk.StringVar()
    lat_entry = ttk.Entry(frame, textvariable=lat_var, width=20)
    lat_entry.grid(row=2, column=1, sticky="w")

    ttk.Label(frame, text="中心点经度：").grid(row=2, column=2, sticky="w", padx=(12, 0))
    lon_var = tk.StringVar()
    lon_entry = ttk.Entry(frame, textvariable=lon_var, width=20)
    lon_entry.grid(row=2, column=3, sticky="w")

    ttk.Label(frame, text="半径（米）：").grid(row=3, column=0, sticky="w", pady=(8, 0))
    radius_var = tk.StringVar(value="2000")
    radius_entry = ttk.Entry(frame, textvariable=radius_var, width=20)
    radius_entry.grid(row=3, column=1, sticky="w", pady=(8, 0))

    bbox_frame = ttk.Frame(frame)
    bbox_frame.grid(row=4, column=0, columnspan=4, pady=(8, 0), sticky="w")
    ttk.Label(bbox_frame, text="上边界(lat)：").grid(row=0, column=0, sticky="w")
    top_var = tk.StringVar()
    top_entry = ttk.Entry(bbox_frame, textvariable=top_var, width=16)
    top_entry.grid(row=0, column=1, sticky="w")

    ttk.Label(bbox_frame, text="下边界(lat)：").grid(row=0, column=2, sticky="w", padx=(12, 0))
    bottom_var = tk.StringVar()
    bottom_entry = ttk.Entry(bbox_frame, textvariable=bottom_var, width=16)
    bottom_entry.grid(row=0, column=3, sticky="w")

    ttk.Label(bbox_frame, text="左边界(lon)：").grid(row=1, column=0, sticky="w", pady=(8, 0))
    left_var = tk.StringVar()
    left_entry = ttk.Entry(bbox_frame, textvariable=left_var, width=16)
    left_entry.grid(row=1, column=1, sticky="w", pady=(8, 0))

    ttk.Label(bbox_frame, text="右边界(lon)：").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
    right_var = tk.StringVar()
    right_entry = ttk.Entry(bbox_frame, textvariable=right_var, width=16)
    right_entry.grid(row=1, column=3, sticky="w", pady=(8, 0))

    def toggle_mode() -> None:
        mode = mode_var.get()
        circle_state = "normal" if mode == "circle" else "disabled"
        bbox_state = "disabled" if mode == "circle" else "normal"
        lat_entry.configure(state=circle_state)
        lon_entry.configure(state=circle_state)
        radius_entry.configure(state=circle_state)
        top_entry.configure(state=bbox_state)
        bottom_entry.configure(state=bbox_state)
        left_entry.configure(state=bbox_state)
        right_entry.configure(state=bbox_state)

    mode_var.trace_add("write", lambda *args: toggle_mode())
    toggle_mode()

    ttk.Label(frame, text="API Key 配置：").grid(row=5, column=0, sticky="w", pady=(8, 0))
    config_var = tk.StringVar(value="map_keys.json")
    ttk.Entry(frame, textvariable=config_var, width=48).grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Button(frame, text="浏览...", command=lambda: choose_file(config_var, [("JSON 文件", "*.json"), ("所有文件", "*")])).grid(row=5, column=3, sticky="w", padx=(6,0), pady=(8,0))

    ttk.Label(frame, text="输出 CSV：").grid(row=6, column=0, sticky="w", pady=(8, 0))
    output_var = tk.StringVar(value="poi_results.csv")
    ttk.Entry(frame, textvariable=output_var, width=48).grid(row=6, column=1, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Button(frame, text="浏览...", command=lambda: save_file(output_var, [("CSV 文件", "*.csv"), ("所有文件", "*")])).grid(row=6, column=3, sticky="w", padx=(6,0), pady=(8,0))

    ttk.Label(frame, text="可选 JSON：").grid(row=7, column=0, sticky="w", pady=(8, 0))
    json_var = tk.StringVar()
    ttk.Entry(frame, textvariable=json_var, width=48).grid(row=7, column=1, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Button(frame, text="浏览...", command=lambda: save_file(json_var, [("JSON 文件", "*.json"), ("所有文件", "*")])).grid(row=7, column=3, sticky="w", padx=(6,0), pady=(8,0))

    ttk.Label(frame, text="分页限制：").grid(row=8, column=0, sticky="w", pady=(8, 0))
    page_var = tk.StringVar(value="3")
    ttk.Entry(frame, textvariable=page_var, width=20).grid(row=8, column=1, sticky="w", pady=(8, 0))

    output_text = tk.Text(frame, width=88, height=14, wrap="word")
    output_scroll = ttk.Scrollbar(frame, orient="vertical", command=output_text.yview)
    output_text.configure(yscrollcommand=output_scroll.set)
    output_text.grid(row=9, column=0, columnspan=3, pady=(12, 0), sticky="nsew")
    output_scroll.grid(row=9, column=3, pady=(12, 0), sticky="ns")

    def append_log(message: str) -> None:
        output_text.insert("end", message)
        output_text.see("end")

    def clear_log() -> None:
        output_text.delete("1.0", "end")

    def choose_file(variable: tk.StringVar, filetypes):
        path = filedialog.askopenfilename(title="选择文件", filetypes=filetypes)
        if path:
            variable.set(path)

    def save_file(variable: tk.StringVar, filetypes):
        path = filedialog.asksaveasfilename(title="保存文件", defaultextension=filetypes[0][1].replace("*", ""), filetypes=filetypes)
        if path:
            variable.set(path)

    def on_run() -> None:
        clear_log()
        try:
            provider = provider_var.get()
            place_type = type_var.get()
            mode = mode_var.get()
            lat = float(lat_var.get()) if lat_var.get().strip() else None
            lon = float(lon_var.get()) if lon_var.get().strip() else None
            radius = int(radius_var.get()) if radius_var.get().strip() else None
            top = float(top_var.get()) if top_var.get().strip() else None
            bottom = float(bottom_var.get()) if bottom_var.get().strip() else None
            left = float(left_var.get()) if left_var.get().strip() else None
            right = float(right_var.get()) if right_var.get().strip() else None
            config_path = config_var.get().strip() or "map_keys.json"
            output_path = output_var.get().strip() or "poi_results.csv"
            json_path = json_var.get().strip() or None
            page = int(page_var.get())

            bbox = None
            if mode == "bbox":
                if top is None or bottom is None or left is None or right is None:
                    raise ValueError("矩形模式下必须填写上、下、左、右边界。")
                bbox = {"top": top, "bottom": bottom, "left": left, "right": right}
            else:
                if lat is None or lon is None or radius is None:
                    raise ValueError("圆形模式下必须填写中心点和半径。")

            keys = load_keys(config_path)
            run_fetch(provider, keys, place_type, lat, lon, radius, bbox, output_path, json_path, page, log_callback=append_log)
        except Exception as exc:
            append_log(f"错误：{exc}\n")
            messagebox.showerror("运行错误", str(exc))

    ttk.Button(frame, text="开始抓取", command=on_run).grid(row=8, column=1, pady=(12, 0), sticky="e")
    ttk.Button(frame, text="退出", command=root.destroy).grid(row=8, column=2, pady=(12, 0), sticky="w")

    for i in range(4):
        frame.grid_columnconfigure(i, weight=1)
    frame.grid_rowconfigure(9, weight=1)

    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="统一地图 POI 抓取工具，支持百度、高德、腾讯。")
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS + ["all"], default="all", help="选择地图服务提供商")
    parser.add_argument("--type", choices=SUPPORTED_PLACES, default="hospital", help="要抓取的地点类型")
    parser.add_argument("--mode", choices=["circle", "bbox"], default="circle", help="查询模式：circle 表示中心点+半径，bbox 表示矩形区域")
    parser.add_argument("--lat", type=float, help="中心点纬度，仅 circle 模式有效")
    parser.add_argument("--lon", type=float, help="中心点经度，仅 circle 模式有效")
    parser.add_argument("--radius", type=int, default=2000, help="查询半径（米），仅 circle 模式有效")
    parser.add_argument("--top", type=float, help="矩形区域上边界纬度，仅 bbox 模式有效")
    parser.add_argument("--bottom", type=float, help="矩形区域下边界纬度，仅 bbox 模式有效")
    parser.add_argument("--left", type=float, help="矩形区域左边界经度，仅 bbox 模式有效")
    parser.add_argument("--right", type=float, help="矩形区域右边界经度，仅 bbox 模式有效")
    parser.add_argument("--config", default="map_keys.json", help="API Key 配置文件路径")
    parser.add_argument("--output", default="poi_results.csv", help="输出 CSV 文件路径")
    parser.add_argument("--json", help="可选的 JSON 输出路径")
    parser.add_argument("--page-limit", type=int, default=3, help="每个平台的分页页数限制（每页 20 条）")
    parser.add_argument("--gui", action="store_true", help="打开界面模式")
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        create_gui()
        return

    bbox = None
    if args.mode == "bbox":
        if args.top is None or args.bottom is None or args.left is None or args.right is None:
            raise ValueError("bbox 模式下必须提供 --top --bottom --left --right。")
        bbox = {
            "top": args.top,
            "bottom": args.bottom,
            "left": args.left,
            "right": args.right,
        }
    else:
        if args.lat is None or args.lon is None:
            raise ValueError("circle 模式下必须提供 --lat 和 --lon。")

    keys = load_keys(args.config)
    run_fetch(
        args.provider,
        keys,
        args.type,
        args.lat,
        args.lon,
        args.radius,
        bbox,
        args.output,
        args.json,
        args.page_limit,
    )


if __name__ == "__main__":
    main()
