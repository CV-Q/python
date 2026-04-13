import argparse
import csv
import json
import math
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

DEFAULT_FIELDS = ["osm_id", "osm_type", "name", "latitude", "longitude", "address"]


def build_overpass_query(south: float, west: float, north: float, east: float) -> str:
    """生成 Overpass API 的查询语句。"""
    return (
        '[out:json][timeout:25];\n'
        '('
        '  node["amenity"="hospital"]({south},{west},{north},{east});\n'
        '  way["amenity"="hospital"]({south},{west},{north},{east});\n'
        '  relation["amenity"="hospital"]({south},{west},{north},{east});\n'
        ');\n'
        'out center tags;'
    ).format(south=south, west=west, north=north, east=east)


def fetch_hospitals(south: float, west: float, north: float, east: float) -> dict:
    """向 Overpass API 请求指定范围内的医院数据。"""
    query = build_overpass_query(south, west, north, east)
    response = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    response.raise_for_status()
    return response.json()


def bbox_from_center(lat: float, lon: float, radius_km: float) -> tuple:
    """根据中心坐标和半径计算经纬度边界框。"""
    if radius_km <= 0:
        raise ValueError("半径必须大于 0。")

    # 近似计算：1 度纬度约等于 111 公里
    lat_delta = radius_km / 111.0
    # 经度随纬度变化，取当前纬度的余弦作为缩放
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return (lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta)


def element_to_record(element: dict) -> dict:
    """把 Overpass 元素转换为 CSV 记录。"""
    tags = element.get("tags", {})
    if element["type"] == "node":
        lat = element.get("lat")
        lon = element.get("lon")
    else:
        center = element.get("center", {})
        lat = center.get("lat")
        lon = center.get("lon")

    address = []
    for key in ["addr:full", "addr:street", "addr:housenumber", "addr:city", "addr:postcode"]:
        if tags.get(key):
            address.append(tags[key])
    address_text = ", ".join(address)

    return {
        "osm_id": element.get("id"),
        "osm_type": element.get("type"),
        "name": tags.get("name", ""),
        "latitude": lat,
        "longitude": lon,
        "address": address_text,
    }


def save_records_csv(records: list, path: str) -> Path:
    """将医院记录保存为 CSV 文件。"""
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=DEFAULT_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    return filepath


def run_bbox(south: float, west: float, north: float, east: float, output: str, log_callback=None) -> None:
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    log(f"查询范围：南 {south}, 西 {west}, 北 {north}, 东 {east}")
    log("正在请求 Overpass API...")
    data = fetch_hospitals(south, west, north, east)
    elements = data.get("elements", [])
    log(f"共获得 {len(elements)} 条元素。")

    records = [element_to_record(elem) for elem in elements if elem.get("tags")]
    saved = save_records_csv(records, output)
    log(f"已保存 {len(records)} 条医院数据到：{saved}")


def run_center(latitude: float, longitude: float, radius_km: float, output: str, log_callback=None) -> None:
    south, west, north, east = bbox_from_center(latitude, longitude, radius_km)
    if log_callback:
        log_callback(f"中心点查询：纬度 {latitude}, 经度 {longitude}, 半径 {radius_km} 公里\n")
        log_callback(f"自动计算边界框：南 {south}, 西 {west}, 北 {north}, 东 {east}\n")
    else:
        print(f"中心点查询：纬度 {latitude}, 经度 {longitude}, 半径 {radius_km} 公里")
        print(f"自动计算边界框：南 {south}, 西 {west}, 北 {north}, 东 {east}")
    run_bbox(south, west, north, east, output, log_callback=log_callback)


def create_gui() -> None:
    root = tk.Tk()
    root.title("医院地图爬虫")
    root.geometry("620x520")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="边界框查询：").grid(row=0, column=0, sticky="w")
    south_var = tk.StringVar()
    west_var = tk.StringVar()
    north_var = tk.StringVar()
    east_var = tk.StringVar()

    ttk.Label(frame, text="南纬：").grid(row=1, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(frame, textvariable=south_var, width=18).grid(row=1, column=1, sticky="w", pady=(4, 0))
    ttk.Label(frame, text="西经：").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(4, 0))
    ttk.Entry(frame, textvariable=west_var, width=18).grid(row=1, column=3, sticky="w", pady=(4, 0))

    ttk.Label(frame, text="北纬：").grid(row=2, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(frame, textvariable=north_var, width=18).grid(row=2, column=1, sticky="w", pady=(4, 0))
    ttk.Label(frame, text="东经：").grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(4, 0))
    ttk.Entry(frame, textvariable=east_var, width=18).grid(row=2, column=3, sticky="w", pady=(4, 0))

    ttk.Separator(frame, orient="horizontal").grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 10))

    ttk.Label(frame, text="中心点查询：").grid(row=4, column=0, sticky="w")
    center_lat_var = tk.StringVar()
    center_lon_var = tk.StringVar()
    radius_var = tk.StringVar()

    ttk.Label(frame, text="中心纬度：").grid(row=5, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(frame, textvariable=center_lat_var, width=18).grid(row=5, column=1, sticky="w", pady=(4, 0))
    ttk.Label(frame, text="中心经度：").grid(row=5, column=2, sticky="w", padx=(12, 0), pady=(4, 0))
    ttk.Entry(frame, textvariable=center_lon_var, width=18).grid(row=5, column=3, sticky="w", pady=(4, 0))

    ttk.Label(frame, text="半径（公里）：").grid(row=6, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(frame, textvariable=radius_var, width=18).grid(row=6, column=1, sticky="w", pady=(4, 0))

    ttk.Separator(frame, orient="horizontal").grid(row=7, column=0, columnspan=4, sticky="ew", pady=(10, 10))

    ttk.Label(frame, text="输出 CSV 路径：").grid(row=8, column=0, sticky="w")
    csv_var = tk.StringVar(value="hospitals.csv")
    ttk.Entry(frame, textvariable=csv_var, width=48).grid(row=8, column=1, columnspan=2, sticky="w")

    def choose_csv_file() -> None:
        path = filedialog.asksaveasfilename(
            title="选择 CSV 输出文件",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*")],
        )
        if path:
            csv_var.set(path)

    ttk.Button(frame, text="浏览...", command=choose_csv_file).grid(row=8, column=3, sticky="w", padx=(6, 0))

    output_text = tk.Text(frame, width=72, height=12, wrap="word")
    output_scroll = ttk.Scrollbar(frame, orient="vertical", command=output_text.yview)
    output_text.configure(yscrollcommand=output_scroll.set)
    output_text.grid(row=9, column=0, columnspan=3, pady=(10, 0), sticky="nsew")
    output_scroll.grid(row=9, column=3, pady=(10, 0), sticky="ns")

    def append_log(message: str) -> None:
        output_text.insert("end", message)
        output_text.see("end")

    def clear_log() -> None:
        output_text.delete("1.0", "end")

    def on_run() -> None:
        clear_log()
        try:
            csv_path = csv_var.get().strip() or "hospitals.csv"
            if center_lat_var.get() and center_lon_var.get() and radius_var.get():
                lat = float(center_lat_var.get())
                lon = float(center_lon_var.get())
                radius = float(radius_var.get())
                run_center(lat, lon, radius, csv_path, log_callback=append_log)
            elif south_var.get() and west_var.get() and north_var.get() and east_var.get():
                south = float(south_var.get())
                west = float(west_var.get())
                north = float(north_var.get())
                east = float(east_var.get())
                run_bbox(south, west, north, east, csv_path, log_callback=append_log)
            else:
                raise ValueError("请填写完整的边界框参数或中心点与半径参数。")
        except Exception as exc:
            append_log(f"错误：{exc}\n")
            messagebox.showerror("运行错误", str(exc))

    ttk.Button(frame, text="开始爬取", command=on_run).grid(row=10, column=1, pady=(12, 0), sticky="e")
    ttk.Button(frame, text="退出", command=root.destroy).grid(row=10, column=2, pady=(12, 0), sticky="w")

    for i in range(4):
        frame.grid_columnconfigure(i, weight=1)
    frame.grid_rowconfigure(9, weight=1)

    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="爬取医院地图数据（OpenStreetMap）。支持边界框和中心半径两种查询方式。")
    parser.add_argument("--south", type=float, help="边界框南纬")
    parser.add_argument("--west", type=float, help="边界框西经")
    parser.add_argument("--north", type=float, help="边界框北纬")
    parser.add_argument("--east", type=float, help="边界框东经")
    parser.add_argument("--center-lat", type=float, help="中心点纬度")
    parser.add_argument("--center-lon", type=float, help="中心点经度")
    parser.add_argument("--radius", type=float, help="半径，单位公里")
    parser.add_argument("--csv", default="hospitals.csv", help="输出 CSV 文件路径")
    parser.add_argument("--gui", action="store_true", help="打开界面模式")
    args = parser.parse_args()

    try:
        if args.gui or len(sys.argv) == 1:
            create_gui()
        elif args.center_lat is not None or args.center_lon is not None or args.radius is not None:
            if args.center_lat is None or args.center_lon is None or args.radius is None:
                raise ValueError("使用中心半径查询时，必须同时指定 --center-lat、--center-lon 和 --radius。")
            run_center(args.center_lat, args.center_lon, args.radius, args.csv)
        else:
            if args.south is None or args.west is None or args.north is None or args.east is None:
                raise ValueError("使用边界框查询时，必须指定 --south、--west、--north、--east。")
            run_bbox(args.south, args.west, args.north, args.east, args.csv)
    except requests.RequestException as exc:
        print(f"网络请求失败：{exc}")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"响应解析失败：{exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"发生错误：{exc}")
        sys.exit(1)
