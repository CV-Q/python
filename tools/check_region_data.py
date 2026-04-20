import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from map_poi_fetcher import ensure_region_data

def main():
    keys = list(ensure_region_data('config/poi_config.json', '').keys())
    print('ensure_region_data keys:', keys)

if __name__ == '__main__':
    main()
