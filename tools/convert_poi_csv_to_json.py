import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def convert_gaode(src: Path, dst: Path):
    mapping = {}
    with src.open('r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        for row in reader:
            if not row or len(row) < 5:
                continue
            _, code, big, mid, small = row[:5]
            key = small.strip() or mid.strip() or big.strip()
            if not key:
                continue
            mapping[key] = code.strip()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')

def convert_tianditu(src: Path, dst: Path):
    mapping = {}
    with src.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 2:
                continue
            # assume last column is code
            name = parts[0]
            code = parts[-1]
            if name:
                mapping[name] = code
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')

def write_empty_baidu(dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding='utf-8')

def main():
    gaode_csv = ROOT / '地图资料' / '高德地图' / '高德POI分类与编码.csv'
    tianditu_csv = ROOT / '地图资料' / '天地图' / 'POI分类.csv'
    out_dir = ROOT / 'config'
    convert_gaode(gaode_csv, out_dir / 'data_type_map.gaode.json')
    convert_tianditu(tianditu_csv, out_dir / 'data_type_map.tianditu.json')
    write_empty_baidu(out_dir / 'data_type_map.baidu.json')
    print('Generated data_type_map JSON files in config/')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import sys, traceback
        traceback.print_exc()
        sys.exit(1)
