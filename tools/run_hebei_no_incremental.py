import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import map_poi_fetcher, providers
from config_loader import load_config

cfg = load_config('config/poi_config.json')
# disable incremental and exports for dry run
cfg['incremental'] = False
cfg['export_format'] = None
cfg['export_formats'] = []
cfg['results_dir'] = 'POI_Data_test'

# enable tianditu debug via wrapper
orig_fetch = providers.fetch_provider_records

def wrapper(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None):
    if provider == 'tianditu':
        return providers.fetch_tianditu(api_keys.get('tianditu',''), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event, debug=True)
    return orig_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=progress_callback, stop_event=stop_event)

providers.fetch_provider_records = wrapper
map_poi_fetcher.fetch_provider_records = wrapper

# progress callback prints concise info

def progress_cb(msg):
    print('PROGRESS:', json.dumps(msg, ensure_ascii=False))

# find task 河北
task = next((t for t in cfg.get('tasks', []) if t.get('name') == '河北'), None)
if not task:
    print('Task 河北 not found')
    sys.exit(1)

print('Running 河北 with incremental disabled...')
print('Task passed to run_task:', json.dumps(task, ensure_ascii=False))
print('Config resources:', cfg.get('resources'))
res = map_poi_fetcher.run_task(task, cfg, mode='manual', progress_callback=progress_cb)
print('Result:')
print(json.dumps(res, ensure_ascii=False, indent=2))
