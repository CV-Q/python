import json
import time
import sys
import os
from datetime import datetime

# 确保能导入上级目录中的模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import map_poi_fetcher

# 简单进度回调，直接打印到控制台（模拟 UI 日志窗口）
def progress_cb(msg):
    print("PROGRESS:", json.dumps(msg, ensure_ascii=False))

# Mock provider implementation
def mock_fetch_provider_records(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None):
    # 模拟延迟
    time.sleep(0.1)
    # 返回一条示例记录
    return [{
        "id": f"mock-{int(time.time())}",
        "name": "Mock POI",
        "address": "示例地址",
        "latitude": latitude if latitude is not None else 38.0428,
        "longitude": longitude if longitude is not None else 114.5149,
        "source": "mock",
    }]


if __name__ == '__main__':
    # 注入 mock
    map_poi_fetcher.fetch_provider_records = mock_fetch_provider_records

    cfg = map_poi_fetcher.DEFAULT_CONFIG.copy()
    cfg['incremental'] = False
    cfg['export_formats'] = []
    cfg['export_format'] = None
    cfg['results_dir'] = 'POI_Data_test'
    cfg['max_concurrency'] = 2

    task = {
        'name': 'mock_task',
        'provider': 'mock',
        'area_type': 'admin',
        'admin_region': {'province': '石家庄', 'city': '', 'county': ''},
        'resources': ['gas_station'],
        'enabled': True,
    }

    print('Running dry-run with mock provider...')
    res = map_poi_fetcher.run_task(task, cfg, mode='manual', progress_callback=progress_cb)
    print('Result:')
    print(json.dumps(res, ensure_ascii=False, indent=2))
