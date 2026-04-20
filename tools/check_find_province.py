import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from map_poi_fetcher import ensure_region_data

def normalize_region_name(s):
    if s is None:
        return ""
    x = str(s).strip()
    for suf in ["省", "市", "自治区", "特别行政区", "自治州", "地区", "区", "县", "市辖区"]:
        if x.endswith(suf):
            x = x[: -len(suf)]
    return x.strip().lower()

def find_province(region_data, province):
    npr = normalize_region_name(province)
    for key in region_data.keys():
        if normalize_region_name(key) == npr:
            return key
    for key in region_data.keys():
        kn = normalize_region_name(key)
        if npr and (npr in kn or kn in npr):
            return key
    return None

def main():
    rd = ensure_region_data('config/poi_config.json','')
    print('region_data keys:', list(rd.keys()))
    print("find_province('河南') ->", find_province(rd, '河南'))
    for k,v in rd.items():
        if isinstance(v, dict) and '郑州' in v:
            print('郑州 found under', k)

if __name__ == '__main__':
    main()
