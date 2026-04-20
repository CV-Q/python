#!/usr/bin/env python3
"""
模拟 GUI 的一次端到端加载 -> 保存 流程（不启动 PyQt），并输出详细的逐项匹配日志。

用法:
  python tools/simulate_gui_e2e.py --config config/poi_config.json --task-index 0

脚本行为：
- 加载配置与区域缓存
- 模拟 `load_task` 的匹配逻辑，逐项记录省/市/区匹配情况
- 模拟 `save_task` 的保存逻辑（资源编码处理、展开“全部”城市为区县）
- 备份原始配置并写回修改后的配置（在同一路径加上 .bak）
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    import config_loader
except Exception:
    config_loader = None

try:
    from map_poi_fetcher import ensure_region_data, fetch_amap_subdistrict, load_region_cache, save_region_cache, get_region_cache_path
except Exception:
    ensure_region_data = None
    fetch_amap_subdistrict = None
    load_region_cache = None
    save_region_cache = None
    get_region_cache_path = None


def normalize_region_name(s: Optional[str]) -> str:
    if s is None:
        return ""
    x = str(s).strip()
    for suf in ["省", "市", "自治区", "特别行政区", "自治州", "地区", "区", "县", "市辖区"]:
        if x.endswith(suf):
            x = x[: -len(suf)]
    return x.strip().lower()


def find_province(region_data: Dict[str, Any], province: str) -> Optional[str]:
    npr = normalize_region_name(province)
    for key in region_data.keys():
        if normalize_region_name(key) == npr:
            return key
    # fuzzy: substring
    for key in region_data.keys():
        kn = normalize_region_name(key)
        if npr and (npr in kn or kn in npr):
            return key
    return None


def find_city(prov_val: Any, city: str) -> Optional[str]:
    nci = normalize_region_name(city)
    if isinstance(prov_val, dict):
        for key in prov_val.keys():
            if normalize_region_name(key) == nci:
                return key
        for key in prov_val.keys():
            kn = normalize_region_name(key)
            if nci and (nci in kn or kn in nci):
                return key
    elif isinstance(prov_val, list):
        for entry in prov_val:
            if normalize_region_name(str(entry)) == nci:
                return str(entry)
        for entry in prov_val:
            en = normalize_region_name(str(entry))
            if nci and (nci in en or en in nci):
                return str(entry)
    return None


def extract_county_name(c: Any) -> str:
    if isinstance(c, dict):
        return str(c.get('name') or c.get('fullname') or c.get('adname') or '')
    if isinstance(c, str):
        try:
            parsed = ast.literal_eval(c)
            if isinstance(parsed, dict):
                return str(parsed.get('name') or parsed.get('adname') or '')
        except Exception:
            return c
    return str(c)


def find_county(counties: List[Any], county: str) -> Optional[str]:
    nco = normalize_region_name(county)
    for c in counties:
        cname = extract_county_name(c)
        if normalize_region_name(cname) == nco:
            return cname
    for c in counties:
        cname = extract_county_name(c)
        kn = normalize_region_name(cname)
        if nco and (nco in kn or kn in nco):
            return cname
    return None


def load_data_type_tree(cfg_dir: str, prov_key: str) -> Optional[Dict[str, Any]]:
    candidates = [os.path.join(cfg_dir, f"data_type_tree.{prov_key}.json"), os.path.join('config', f"data_type_tree.{prov_key}.json")]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
    return None


def flatten_type_tree(tree: Dict[str, Any]) -> List[Tuple[List[str], Dict[str, Any]]]:
    out: List[Tuple[List[str], Dict[str, Any]]] = []

    def rec(node: Any, path: List[str]):
        if isinstance(node, dict):
            # node may have code/id and children
            code = node.get('code') or node.get('id')
            out.append((path.copy(), {'code': code, 'node': node}))
            ch = node.get('children') if isinstance(node.get('children'), dict) else None
            if ch:
                for k, v in ch.items():
                    rec(v, path + [k])
        else:
            # leaf as string
            out.append((path.copy(), {'code': None, 'node': node}))

    if isinstance(tree, dict):
        for k, v in tree.items():
            rec(v, [k])
    return out


def expand_city_all(reg_cache: Dict[str, Any], prov: str, city: str, gaode_key: str) -> List[str]:
    counties: List[str] = []
    try:
        if isinstance(reg_cache, dict) and prov in reg_cache and isinstance(reg_cache.get(prov), dict) and city in reg_cache[prov]:
            val = reg_cache[prov][city]
            counties = [extract_county_name(x) for x in val if x]
    except Exception:
        counties = []
    if not counties and fetch_amap_subdistrict and gaode_key and prov and city:
        try:
            subs = fetch_amap_subdistrict(gaode_key, prov, city)
            if subs:
                counties = [d.get('name') if isinstance(d, dict) else str(d) for d in subs if d]
                try:
                    reg_cache.setdefault(prov, {})
                    reg_cache[prov].setdefault(city, subs)
                    # try to save cache if helper exists
                    if save_region_cache and get_region_cache_path:
                        try:
                            save_region_cache(get_region_cache_path(cfg_path), reg_cache)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
    return counties


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', '-c', default='config/poi_config.json')
    parser.add_argument('--task-index', '-i', type=int, default=0)
    args = parser.parse_args()

    global cfg_path
    cfg_path = args.config
    if not os.path.exists(cfg_path):
        print(f"配置文件不存在: {cfg_path}")
        sys.exit(2)

    # load config
    try:
        if config_loader and hasattr(config_loader, 'load_config'):
            current_cfg = config_loader.load_config(cfg_path)
        else:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                current_cfg = json.load(f)
    except Exception as e:
        print(f"无法加载配置: {e}")
        sys.exit(2)

    tasks = current_cfg.get('tasks', []) or []
    if not tasks:
        print("配置中没有任务。")
        return
    if args.task_index < 0 or args.task_index >= len(tasks):
        print(f"任务索引越界: {args.task_index}")
        return

    t = tasks[args.task_index]
    print("===== 模拟 GUI 端到端：选择任务 -> 加载 -> 保存 =====")
    print(f"任务索引: {args.task_index}；任务名: {t.get('name')}")
    print(json.dumps(t, ensure_ascii=False, indent=2))

    # load region data / cache
    api_key = current_cfg.get('api_keys', {}).get('gaode', '')
    region_data = {}
    region_cache = {}
    try:
        if ensure_region_data:
            region_data = ensure_region_data(cfg_path, api_key) or {}
    except Exception:
        region_data = {}
    # region_data loaded from cache (normalized by ensure_region_data)
    try:
        if load_region_cache and get_region_cache_path:
            p = get_region_cache_path(cfg_path)
            region_cache = load_region_cache(p) or {}
    except Exception:
        # fallback try config/region_cache.json
        try:
            with open('config/region_cache.json', 'r', encoding='utf-8') as f:
                region_cache = json.load(f)
        except Exception:
            region_cache = {}

    print("\n--- 区域匹配逐项日志 ---")
    # build normalized admin_regions list from task
    regions = t.get('admin_regions') or ([t.get('admin_region')] if t.get('admin_region') else [])
    normr: List[Tuple[str, str, str]] = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        pr = (r.get('province') or '').strip()
        ci = (r.get('city') or '').strip()
        co = (r.get('county') or '').strip()
        normr.append((pr, ci, co))

    for idx, (pr, ci, co) in enumerate(normr, start=1):
        print(f"[区域 {idx}] 原始: 省='{pr}'；市='{ci}'；区='{co}'")
        npr = normalize_region_name(pr)
        nci = normalize_region_name(ci)
        nco = normalize_region_name(co)
        matched_prov = None
        if pr:
            matched_prov = find_province(region_data, pr)
            if matched_prov:
                print(f"  -> 省匹配: 找到 '{matched_prov}'")
            else:
                print(f"  -> 省匹配: 未找到匹配项 (尝试模糊匹配) ")
        else:
            print("  -> 省为空，跳过匹配")

        if matched_prov is None:
            # try to continue by fuzzy searching across all provinces for city
            possible_provs = []
            if ci:
                for pk, pv in region_data.items():
                    if isinstance(pv, dict):
                        if any(normalize_region_name(k) == nci or nci in normalize_region_name(k) for k in pv.keys()):
                            possible_provs.append(pk)
            if possible_provs:
                matched_prov = possible_provs[0]
                print(f"  -> 通过市模糊定位到省: '{matched_prov}'")

        if matched_prov:
            prov_val = region_data.get(matched_prov)
            if not ci or ci == '全部':
                print("  -> 市为空或为 '全部'：表示选择整个省（或用户将选择省下所有城市/区县）。")
            else:
                matched_city = find_city(prov_val, ci)
                if matched_city:
                    print(f"  -> 市匹配: 找到 '{matched_city}'")
                    # county handling
                    if not co or co == '全部':
                        print("    -> 区县为空或为 '全部'：表示选择整个市（保存时会尝试展开为所有区/县）。")
                    else:
                        # attempt to get counties list
                        counties = []
                        if isinstance(prov_val, dict):
                            counties = prov_val.get(matched_city, []) or []
                        elif isinstance(prov_val, list):
                            counties = []
                        found_county = find_county(counties, co) if counties else None
                        if found_county:
                            print(f"    -> 区县匹配: 找到 '{found_county}'")
                        else:
                            print("    -> 区县匹配: 未找到。保存时将尝试从缓存或高德再拉取子区以展开，若失败则保留 '全部' 表示意图。")
                else:
                    print("  -> 市匹配: 未找到匹配的市（可能缓存中没有或名称不一致）")
        else:
            print("  -> 无法定位省/市：该区域可能和当前 region_cache 不匹配。")

    print("\n--- 资源匹配逐项日志 ---")
    prov_for_resources = t.get('provider') or current_cfg.get('provider', 'gaode')
    print(f"提供商: {prov_for_resources}")
    cfg_dir = os.path.dirname(cfg_path) or 'config'
    tree = load_data_type_tree(cfg_dir, prov_for_resources)
    flat = flatten_type_tree(tree) if tree else []

    resources = t.get('resources') or []
    if not resources:
        print("任务未指定资源。")
    for ri, res in enumerate(resources, start=1):
        print(f"[资源 {ri}] 原始: {res}")
        matched = False
        if prov_for_resources in ('gaode', 'tianditu'):
            # expected codes
            target = str(res)
            for path, meta in flat:
                code = meta.get('code')
                if code and str(code) == target:
                    print(f"  -> 匹配到代码: {' / '.join(path)} (code={code})")
                    matched = True
                    break
            if not matched:
                # try match by name
                for path, meta in flat:
                    name = path[-1] if path else ''
                    if normalize_region_name(name) == normalize_region_name(str(res)):
                        print(f"  -> 通过名称匹配: {' / '.join(path)}")
                        matched = True
                        break
        elif prov_for_resources == 'baidu':
            # expected pairs or names
            if isinstance(res, dict):
                q = (res.get('query') or '').strip()
                tp = (res.get('type') or '').strip()
                print(f"  -> 百度查询对: query='{q}', type='{tp}' (尝试匹配树中的 parent/child)")
                # brute-force check in flat
                for path, meta in flat:
                    if path and path[-1] == tp:
                        # parent is path[-2] if available
                        parent = path[-2] if len(path) >= 2 else ''
                        if (not q) or normalize_region_name(parent) == normalize_region_name(q):
                            print(f"    -> 匹配: {' / '.join(path)}")
                            matched = True
                            break
            else:
                # legacy case: match by name
                for path, meta in flat:
                    name = path[-1] if path else ''
                    if normalize_region_name(name) == normalize_region_name(str(res)):
                        print(f"  -> 通过名称匹配: {' / '.join(path)}")
                        matched = True
                        break
        else:
            # fallback name based match
            for path, meta in flat:
                name = path[-1] if path else ''
                if normalize_region_name(name) == normalize_region_name(str(res)):
                    print(f"  -> 匹配到资源名: {' / '.join(path)}")
                    matched = True
                    break
        if not matched:
            print("  -> 未匹配到对应资源（可能需要更新 data_type_tree 或使用不同的 provider 设置）。")

    print("\n--- 模拟保存（expand/normalize） ---")
    # 备份配置
    bak_path = cfg_path + '.bak'
    try:
        shutil.copyfile(cfg_path, bak_path)
        print(f"已备份配置到: {bak_path}")
    except Exception as e:
        print(f"备份配置失败: {e}")

    # 构造要保存的 task（尽量模拟 GUI 的保存逻辑）
    saved_task: Dict[str, Any] = {}
    saved_task['name'] = t.get('name')
    saved_task['enabled'] = True
    atype = t.get('area_type', 'admin')
    saved_task['area_type'] = atype
    if atype == 'bbox':
        saved_task['bbox'] = t.get('bbox') or None
    else:
        saved_task['bbox'] = None

    saved_task['provider'] = t.get('provider') or current_cfg.get('provider', 'gaode')

    # resources: preserve format but normalize per-provider like GUI
    try:
        prov = saved_task['provider']
        if prov in ('gaode', 'tianditu'):
            # prefer storing codes; if original are names, leave as-is
            codes = []
            for r in resources:
                codes.append(str(r))
            # dedupe preserving order
            uniq = []
            seen = set()
            for c in codes:
                if c not in seen:
                    seen.add(c); uniq.append(c)
            saved_task['resources'] = uniq
        elif prov == 'baidu':
            # keep as list of dicts if provided
            saved_task['resources'] = resources
        else:
            saved_task['resources'] = resources
    except Exception:
        saved_task['resources'] = resources

    # regions: expand any city-level 全部 into concrete counties when possible
    sel_regions = normr
    expanded_regions: List[Dict[str, str]] = []
    for pr, ci, co in sel_regions:
        if co and co != '全部':
            expanded_regions.append({'country': '中华人民共和国', 'province': pr, 'city': ci, 'county': co})
            continue
        # need to expand
        if not ci or ci == '全部':
            # whole province -> attempt to expand all cities and their counties if cache available
            prov_key = find_province(region_cache if region_cache else region_data, pr) or pr
            if prov_key and isinstance(region_cache.get(prov_key), dict):
                for c, vals in region_cache.get(prov_key, {}).items():
                    counties = [extract_county_name(x) for x in (vals or []) if x]
                    if counties:
                        for cc in counties:
                            expanded_regions.append({'country': '中华人民共和国', 'province': prov_key, 'city': c, 'county': cc})
                    else:
                        expanded_regions.append({'country': '中华人民共和国', 'province': prov_key, 'city': c, 'county': '全部'})
            else:
                # fallback: keep province-level intent
                expanded_regions.append({'country': '中华人民共和国', 'province': pr, 'city': '', 'county': '全部'})
        else:
            # expand city -> counties
            prov_key = find_province(region_cache if region_cache else region_data, pr) or pr
            counties = []
            if prov_key and isinstance(region_cache.get(prov_key), dict):
                counties = [extract_county_name(x) for x in (region_cache[prov_key].get(ci) or []) if x]
            if not counties:
                counties = expand_city_all(region_cache, prov_key, ci, api_key)
            if counties:
                for cc in counties:
                    expanded_regions.append({'country': '中华人民共和国', 'province': prov_key, 'city': ci, 'county': cc})
            else:
                expanded_regions.append({'country': '中华人民共和国', 'province': pr, 'city': ci, 'county': '全部'})

    saved_task['admin_regions'] = expanded_regions

    # write back into config
    try:
        tasks_copy = list(tasks)
        tasks_copy[args.task_index] = saved_task
        current_cfg['tasks'] = tasks_copy
        # try config_loader.save_config if available
        saved_ok = False
        if config_loader and hasattr(config_loader, 'save_config'):
            try:
                config_loader.save_config(cfg_path, current_cfg)
                saved_ok = True
            except Exception:
                saved_ok = False
        if not saved_ok:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(current_cfg, f, ensure_ascii=False, indent=2)
                saved_ok = True
        print(f"已保存任务（索引 {args.task_index} ）到配置: {cfg_path}")
        print("保存后的任务对象:")
        print(json.dumps(saved_task, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"保存失败: {e}")


if __name__ == '__main__':
    main()
