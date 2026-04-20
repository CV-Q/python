import traceback,importlib
importlib.invalidate_caches()
try:
    import providers
    import map_poi_fetcher
    print('OK')
except Exception:
    traceback.print_exc()
