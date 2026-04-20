import sys, os
sys.path.insert(0, os.getcwd())
import map_poi_fetcher

cfg = map_poi_fetcher.load_config("config/poi_config.json")
# 找到名为 河北 的任务（或使用第一个任务作为回退）
task = None
for t in cfg.get('tasks', []):
    if t.get('name') == '河北':
        task = t
        break
if task is None:
    task = cfg.get('tasks', [None])[0]

print('Using task:', task.get('name') if task else None)

# 注入假 fetch_provider_records，避免网络并打印 admin_region
def fake_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None):
    print('FAKE_FETCH called -> provider=', provider, 'keyword=', keyword, 'place_type=', place_type, 'admin_region=', admin_region)
    if progress_callback:
        try:
            progress_callback({"type": "subtask_page", "task_name": task.get('name'), "page": 1})
        except Exception:
            pass
    return []

map_poi_fetcher.fetch_provider_records = fake_fetch

# 简单 progress callback 打印事件
def pcb(evt):
    print('PROGRESS:', evt)

res = map_poi_fetcher.run_task(task, cfg, mode='debug', progress_callback=pcb)
print('RUN_TASK RESULT:')
print(res)
