import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import map_poi_fetcher, providers
from config_loader import load_config

cfg = load_config('config/poi_config.json')

orig_fetch_with_delay = map_poi_fetcher.fetch_with_delay

def wrapped_fetch_with_delay(provider_arg, api_keys_arg, keyword_arg, resource_type_arg, latitude_arg, longitude_arg, bbox_arg, admin_region_arg, page_limit_arg, stop_event=None):
    print('[WRAP] fetch_with_delay called', provider_arg, keyword_arg, resource_type_arg, admin_region_arg)
    res = orig_fetch_with_delay(provider_arg, api_keys_arg, keyword_arg, resource_type_arg, latitude_arg, longitude_arg, bbox_arg, admin_region_arg, page_limit_arg, stop_event=stop_event)
    print('[WRAP] fetch_with_delay returned', len(res) if res else 0)
    return res

map_poi_fetcher.fetch_with_delay = wrapped_fetch_with_delay

# enable tianditu debug inside providers
orig_fetch = providers.fetch_provider_records

def wrapper(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=None, stop_event=None):
    if provider == 'tianditu':
        return providers.fetch_tianditu(api_keys.get('tianditu',''), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event, debug=True)
    return orig_fetch(provider, api_keys, keyword, place_type, latitude, longitude, bbox, admin_region, page_limit, progress_callback=progress_callback, stop_event=stop_event)

providers.fetch_provider_records = wrapper
map_poi_fetcher.fetch_provider_records = wrapper

# find task 河北
task = next((t for t in cfg.get('tasks', []) if t.get('name') == '河北'), None)
if not task:
    print('task not found')
    sys.exit(1)

print('Running...')
res = map_poi_fetcher.run_task(task, cfg, mode='manual', progress_callback=print)
print('Result:')
print(json.dumps(res, ensure_ascii=False, indent=2))
