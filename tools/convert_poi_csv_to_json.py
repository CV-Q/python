import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)


def convert_gaode_tree(src: Path, tree_dst: Path, flat_dst: Path):
    tree = {}
    flat = {}
    with src.open('r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        current_top = None
        current_mid = None
        for row in reader:
            if not row or len(row) < 5:
                continue
            _, code, big, mid, small = row[:5]
            code = code.strip()
            big = big.strip()
            mid = mid.strip()
            small = small.strip()

            # determine level by code suffix
            if code.endswith('0000'):
                # top-level
                current_top = big or small or mid
                if not current_top:
                    continue
                tree.setdefault(current_top, {'code': code, 'children': {}})
                flat[current_top] = code
                current_mid = None
            elif code.endswith('00'):
                # mid-level
                name = mid or small or big
                if current_top is None:
                    # fallback: create a synthetic top using big
                    current_top = big or '其它'
                    tree.setdefault(current_top, {'code': None, 'children': {}})
                tree[current_top]['children'].setdefault(name, {'code': code, 'children': {}})
                flat[name] = code
                current_mid = name
            else:
                # small-level
                name = small or mid or big
                if current_top is None:
                    continue
                if current_mid is None:
                    # attach under a synthetic mid using mid or big
                    current_mid = mid or big or '其它'
                    tree[current_top]['children'].setdefault(current_mid, {'code': None, 'children': {}})
                tree[current_top]['children'][current_mid]['children'][name] = {'code': code}
                flat[name] = code

    _ensure_dir(tree_dst)
    tree_dst.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    _ensure_dir(flat_dst)
    flat_dst.write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding='utf-8')


def convert_tianditu_tree(src: Path, tree_dst: Path, flat_dst: Path):
    tree = {}
    flat = {}
    last_top = None
    with src.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(',') if p.strip()!='']
            # last part should be code
            code = parts[-1]
            name = parts[0]
            # if name contains multiple values separated by '/', take first
            name = name.split('/')[0].strip()
            if code.endswith('00'):
                # top-level
                tree.setdefault(name, {'code': code, 'children': {}})
                flat[name] = code
                last_top = name
            else:
                if last_top is None:
                    # create unknown top
                    last_top = '其它'
                    tree.setdefault(last_top, {'code': None, 'children': {}})
                tree[last_top]['children'][name] = {'code': code}
                flat[name] = code

    _ensure_dir(tree_dst)
    tree_dst.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    _ensure_dir(flat_dst)
    flat_dst.write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding='utf-8')


def convert_baidu_empty(tree_dst: Path, flat_dst: Path):
    _ensure_dir(tree_dst)
    tree_dst.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding='utf-8')
    _ensure_dir(flat_dst)
    flat_dst.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding='utf-8')


def convert_baidu(src: Path, tree_dst: Path, flat_dst: Path):
    tree = {}
    flat = {}
    with src.open('r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        for row in reader:
            if not row or len(row) < 2:
                continue
            top = row[0].strip()
            subs_raw = row[1].strip()
            # 百度二级可能用顿号分隔
            subs = [s.strip() for s in subs_raw.replace('，', '、').split('、') if s.strip()]
            if not top:
                continue
            children = {}
            for s in subs:
                children[s] = {'code': None}
                flat[s] = None
            tree[top] = {'code': None, 'children': children}
            flat[top] = None

    _ensure_dir(tree_dst)
    tree_dst.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    _ensure_dir(flat_dst)
    flat_dst.write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    gaode_csv = ROOT / '地图资料' / '高德地图' / '高德POI分类与编码.csv'
    tianditu_csv = ROOT / '地图资料' / '天地图' / 'POI分类.csv'
    out_dir = ROOT / 'config'

    convert_gaode_tree(gaode_csv, out_dir / 'data_type_tree.gaode.json', out_dir / 'data_type_map.gaode.json')
    convert_tianditu_tree(tianditu_csv, out_dir / 'data_type_tree.tianditu.json', out_dir / 'data_type_map.tianditu.json')
    baidu_csv = ROOT / '地图资料' / '百度地图' / '百度POI分类与编码.csv'
    if baidu_csv.exists():
        convert_baidu(baidu_csv, out_dir / 'data_type_tree.baidu.json', out_dir / 'data_type_map.baidu.json')
    else:
        convert_baidu_empty(out_dir / 'data_type_tree.baidu.json', out_dir / 'data_type_map.baidu.json')
    print('Generated data_type_tree.* and data_type_map.* JSON files in config/')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import sys, traceback
        traceback.print_exc()
        sys.exit(1)
