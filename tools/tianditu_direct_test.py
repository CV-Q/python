import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import providers, config_loader
cfg = config_loader.load_config('config/poi_config.json')
api_key = cfg.get('api_keys', {}).get('tianditu', '')
admin = cfg.get('tasks', [])[0].get('admin_regions', [])[0]
print('Admin region:', admin)
res = providers.fetch_tianditu(api_key, '', '120101', None, None, None, admin, page_limit=1, progress_callback=print, stop_event=None, debug=True)
print('Count:', len(res))
print(json.dumps(res[:3], ensure_ascii=False, indent=2))
