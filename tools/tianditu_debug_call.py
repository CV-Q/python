import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import providers, map_poi_fetcher
from config_loader import load_config
cfg = load_config('config/poi_config.json')
key = cfg.get('api_keys', {}).get('tianditu', '')
admin = {'province':'河北','city':'石家庄市','county':'辛集市'}
print('Using key:', key[:6]+'...' if key else '<empty>')
res = providers.fetch_tianditu(key, '加油站', '120101', None, None, None, admin, page_limit=1, progress_callback=print, stop_event=None, debug=True)
print('Result count:', len(res))
print(json.dumps(res[:5], ensure_ascii=False, indent=2))
