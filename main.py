# 导入标准库和第三方库
import argparse  # 解析命令行参数
import csv  # 生成 CSV 文件
import datetime  # 处理日期
import sys  # 访问命令行参数
import tkinter as tk  # GUI 库
from pathlib import Path  # 处理文件路径
from tkinter import filedialog, messagebox, ttk  # 为界面增加文件选择和样式组件
from typing import Any, Dict, List, Tuple  # 类型注解

import requests  # 发送 HTTP 请求

# 公开天气 API 的基础 URL
BASE_URL = "https://api.open-meteo.com/v1/forecast"

# 将 open-meteo 返回的天气代码映射为中文描述
WEATHERCODE_MAP = {
    0: "晴",
    1: "主要晴朗",
    2: "部分多云",
    3: "多云",
    45: "雾",
    48: "冻雾",
    51: "细雨",
    53: "中等强度毛毛雨",
    55: "大雨",
    56: "冻毛毛雨",
    57: "冻大雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻小雨",
    67: "冻大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "冰雹",
    80: "小阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷阵雨",
    96: "轻微雷阵雨",
    99: "强雷阵雨",
}

# 预先写入一些河北城市及其经纬度，便于界面输入城市名直接使用
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


def get_coordinates(location: str) -> Tuple[float, float]:
    """根据城市名或经纬度字符串返回坐标。

    支持已知河北城市名，也支持 `纬度,经度` 格式。
    """
    location = location.strip()
    if not location:
        raise ValueError("请输入城市名称或经纬度。")

    # 先按城市名查找
    if location in CITY_COORDINATES:
        return CITY_COORDINATES[location]

    # 如果用户输入了经纬度，例如 "38.0428,114.5149"
    if "," in location:
        parts = [part.strip() for part in location.split(",") if part.strip()]
        if len(parts) == 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass

    raise ValueError("城市名称未识别。请使用河北城市名称或输入格式为 '纬度,经度'。")


def fetch_weather_data(latitude: float, longitude: float, start_date: datetime.date, end_date: datetime.date) -> Dict[str, Any]:
    """调用天气 API，获取指定日期范围内的天气原始 JSON 数据。"""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
        "timezone": "Asia/Shanghai",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    # 发送 GET 请求
    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()  # 如果请求出错，则抛出异常
    return response.json()


def format_weather_code(code: int) -> str:
    """把天气代码转换成中文描述。"""
    return WEATHERCODE_MAP.get(code, f"天气代码 {code}")


def parse_weather_data(raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 API 返回的 JSON 中提取每一天的天气信息。"""
    daily = raw_data.get("daily", {})
    dates = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    codes = daily.get("weathercode", [])
    precipitation = daily.get("precipitation_sum", [])

    # 数据完整性检查，避免后续索引错误
    if not dates or not highs or not lows:
        raise ValueError("未能从天气数据中解析出有效的日常气象字段。")

    weather_list = []
    for index, date_str in enumerate(dates):
        weather_list.append({
            "date": date_str,
            "high_celsius": highs[index] if index < len(highs) else None,
            "low_celsius": lows[index] if index < len(lows) else None,
            "precipitation_mm": precipitation[index] if index < len(precipitation) else None,
            "description": format_weather_code(codes[index]) if index < len(codes) else "未知",
        })
    return weather_list


def save_as_csv(weather_data: List[Dict[str, Any]], filename: str) -> Path:
    """把天气数据保存成 CSV 文件。"""
    path = Path(filename)
    fieldnames = ["date", "high_celsius", "low_celsius", "precipitation_mm", "description"]

    # 使用 utf-8-sig 使 Excel 打开 CSV 时不会出现乱码
    with path.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in weather_data:
            writer.writerow(row)
    return path


def run_scraper(city: str, start_date_str: str, end_date_str: str, csv_file: str, log_callback=None) -> None:
    """实际执行爬虫流程：参数验证、请求天气、解析数据、保存 CSV。"""
    if log_callback:
        log_callback(f"开始爬取：{city}，日期 {start_date_str} ~ {end_date_str}，保存到 {csv_file}\n")

    try:
        # 解析输入城市和日期
        latitude, longitude = get_coordinates(city)
        start_date = datetime.date.fromisoformat(start_date_str)
        end_date = datetime.date.fromisoformat(end_date_str)
        if start_date > end_date:
            raise ValueError("起始日期必须不晚于结束日期。")

        # 获取天气数据并保存为 CSV
        raw_data = fetch_weather_data(latitude, longitude, start_date, end_date)
        weather_data = parse_weather_data(raw_data)
        save_as_csv(weather_data, csv_file)

        if log_callback:
            log_callback("爬取成功！已保存 CSV 文件。\n")
        else:
            print("爬取成功！已保存 CSV 文件。")

    except requests.RequestException as exc:
        message = f"网络请求失败：{exc}\n"
        if log_callback:
            log_callback(message)
        else:
            print(message)
    except ValueError as exc:
        message = f"参数校验失败：{exc}\n"
        if log_callback:
            log_callback(message)
        else:
            print(message)
    except Exception as exc:
        message = f"发生未知错误：{exc}\n"
        if log_callback:
            log_callback(message)
        else:
            print(message)


def create_gui() -> None:
    """创建并显示图形用户界面。"""
    root = tk.Tk()
    root.title("河北天气爬虫")
    root.geometry("520x420")
    root.resizable(False, False)

    main_frame = ttk.Frame(root, padding=12)
    main_frame.pack(fill="both", expand=True)

    today = datetime.date.today()
    default_end = today.isoformat()
    default_start = (today - datetime.timedelta(days=6)).isoformat()

    # 城市输入框
    ttk.Label(main_frame, text="城市名称（河北城市或经纬度）：").grid(row=0, column=0, sticky="w")
    city_var = tk.StringVar(value="石家庄")
    city_entry = ttk.Entry(main_frame, textvariable=city_var, width=40)
    city_entry.grid(row=0, column=1, columnspan=2, sticky="w")

    # 起始日期输入框
    ttk.Label(main_frame, text="起始日期 (YYYY-MM-DD)：").grid(row=1, column=0, sticky="w", pady=(10, 0))
    start_var = tk.StringVar(value=default_start)
    start_entry = ttk.Entry(main_frame, textvariable=start_var, width=20)
    start_entry.grid(row=1, column=1, sticky="w", pady=(10, 0))

    # 结束日期输入框
    ttk.Label(main_frame, text="结束日期 (YYYY-MM-DD)：").grid(row=2, column=0, sticky="w", pady=(10, 0))
    end_var = tk.StringVar(value=default_end)
    end_entry = ttk.Entry(main_frame, textvariable=end_var, width=20)
    end_entry.grid(row=2, column=1, sticky="w", pady=(10, 0))

    # CSV 保存路径输入框
    ttk.Label(main_frame, text="导出 CSV 路径：").grid(row=3, column=0, sticky="w", pady=(10, 0))
    csv_var = tk.StringVar(value="shijiazhuang_weather.csv")
    csv_entry = ttk.Entry(main_frame, textvariable=csv_var, width=32)
    csv_entry.grid(row=3, column=1, sticky="w", pady=(10, 0))

    def choose_csv_file() -> None:
        """弹出文件保存对话框，选择 CSV 输出路径。"""
        path = filedialog.asksaveasfilename(
            title="选择导出 CSV 文件",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*")],
        )
        if path:
            csv_var.set(path)

    browse_btn = ttk.Button(main_frame, text="浏览...", command=choose_csv_file)
    browse_btn.grid(row=3, column=2, sticky="w", padx=(6, 0), pady=(10, 0))

    # 日志输出区，用于显示运行时信息
    output_text = tk.Text(main_frame, width=62, height=12, wrap="word")
    output_scroll = ttk.Scrollbar(main_frame, orient="vertical", command=output_text.yview)
    output_text.configure(yscrollcommand=output_scroll.set)
    output_text.grid(row=4, column=0, columnspan=3, pady=(12, 0), sticky="nsew")
    output_scroll.grid(row=4, column=3, pady=(12, 0), sticky="ns")

    def append_log(message: str) -> None:
        output_text.insert("end", message)
        output_text.see("end")

    def clear_log() -> None:
        output_text.delete("1.0", "end")

    def on_run() -> None:
        clear_log()
        run_scraper(city_var.get(), start_var.get(), end_var.get(), csv_var.get(), log_callback=append_log)

    run_btn = ttk.Button(main_frame, text="开始爬取", command=on_run)
    run_btn.grid(row=5, column=1, pady=(12, 0), sticky="e")

    close_btn = ttk.Button(main_frame, text="退出", command=root.destroy)
    close_btn.grid(row=5, column=2, pady=(12, 0), sticky="w")

    for i in range(3):
        main_frame.grid_columnconfigure(i, weight=1)

    root.mainloop()


def main() -> None:
    """程序入口：支持 GUI 模式和命令行模式。"""
    parser = argparse.ArgumentParser(description="河北天气爬虫：GUI 和命令行都支持。")
    parser.add_argument("--gui", action="store_true", help="打开界面模式")
    parser.add_argument("--city", default="石家庄", help="城市名称或经纬度，例如 38.0428,114.5149")
    parser.add_argument("--start-date", default=(datetime.date.today() - datetime.timedelta(days=6)).isoformat(), help="起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=datetime.date.today().isoformat(), help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--csv", default="shijiazhuang_weather.csv", help="输出 CSV 文件路径")
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        create_gui()
    else:
        run_scraper(args.city, args.start_date, args.end_date, args.csv)


if __name__ == "__main__":
    main()