"""
天地图调试脚本
用法示例：
python tools/tianditu_debug.py --keyword "加油站" --province "河北省" --city "石家庄市" --page_limit 1
或传入完整 postStr JSON:
python tools/tianditu_debug.py --postStr '{"queryType":13,"start":0,"count":20,"dataTypes":"230212","specify":"130100"}'

该脚本会打印发送的请求 URL/params 与响应的状态与 JSON（或文本片段）。
"""
import argparse
import json
import sys
from pathlib import Path

import requests

try:
    import config_loader
except Exception:
    config_loader = None

try:
    from providers import fetch_tianditu
except Exception:
    fetch_tianditu = None


def main():
    p = argparse.ArgumentParser(description="Tianditu 调试工具：构造并发送天地图 v2/search 请求，打印请求与响应。")
    p.add_argument('--key', help='天地图 API Key，若未提供则从 config/poi_config.json 读取')
    p.add_argument('--keyword', help='查询关键词（可与 dataTypes 一起使用）')
    p.add_argument('--datatypes', help='dataTypes（code 列表，逗号分隔）')
    p.add_argument('--province')
    p.add_argument('--city')
    p.add_argument('--county')
    p.add_argument('--bbox', help='bbox: left,bottom,right,top')
    p.add_argument('--page_limit', type=int, default=1)
    p.add_argument('--postStr', help='传入完整 postStr JSON 字符串（优先）')
    p.add_argument('--raw', action='store_true', help='直接发送原始 GET 请求而不是使用 providers.fetch_tianditu')
    p.add_argument('--full-url', help='直接使用完整 URL 发送请求（例如包含已编码的 postStr）')
    p.add_argument('--print-full-response', action='store_true', help='打印完整响应文本（可能非常大）')
    p.add_argument('--debug', action='store_true', help='在 providers 中开启 debug 输出')
    args = p.parse_args()

    key = args.key
    if not key:
        # 尝试从配置读取
        try:
            cfg = config_loader.load_config('config/poi_config.json') if config_loader else {}
            key = (cfg.get('api_keys') or {}).get('tianditu', '')
        except Exception:
            key = ''
    if not key:
        print('未提供天地图 Key，也未从 config 中读取到 key。请通过 --key 提供。', file=sys.stderr)
        sys.exit(2)

    if args.postStr:
        try:
            post = json.loads(args.postStr)
        except Exception as e:
            print('无法解析 postStr JSON:', e, file=sys.stderr)
            sys.exit(2)
        params = {"postStr": json.dumps(post, ensure_ascii=False), "type": "query", "tk": key}
        url = 'http://api.tianditu.gov.cn/v2/search'
        print('[DEBUG] 发送原始请求:')
        print('URL:', url)
        print('params:', params)
        resp = requests.get(url, params=params, timeout=30)
        print('[DEBUG] STATUS:', resp.status_code)
        txt = resp.text or ''
        if args.print_full_response:
            try:
                print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False))
            except Exception:
                print('[DEBUG] TEXT:', txt)
        else:
            try:
                print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False)[:4000])
            except Exception:
                print('[DEBUG] TEXT:', txt[:4000])
        return

    if args.full_url:
        # 直接发送用户提供的完整 URL（假定已包含完整 query，包括 postStr 与 tk）
        full = args.full_url
        print('[DEBUG] 发送完整 URL:', full)
        resp = requests.get(full, timeout=30)
        print('[DEBUG] STATUS:', resp.status_code)
        if args.print_full_response:
            try:
                print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False))
            except Exception:
                print('[DEBUG] TEXT:', resp.text or '')
        else:
            try:
                print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False)[:4000])
            except Exception:
                print('[DEBUG] TEXT:', (resp.text or '')[:4000])
        return

    # 构造调用参数
    bbox = None
    if args.bbox:
        try:
            l, b, r, t = [float(x) for x in args.bbox.split(',')]
            bbox = {"left": l, "bottom": b, "right": r, "top": t}
        except Exception as e:
            print('无法解析 bbox 参数：', e, file=sys.stderr)
            sys.exit(2)

    admin = None
    if args.province or args.city or args.county:
        admin = {"province": args.province or "", "city": args.city or "", "county": args.county or ""}

    # 优先使用 providers.fetch_tianditu（如果可用且未指定 --raw）
    if fetch_tianditu and not args.raw:
        try:
            res = fetch_tianditu(key, args.keyword or '', args.datatypes or '', None, None, bbox, admin, page_limit=args.page_limit, debug=args.debug)
            print('返回记录数：', len(res))
            try:
                print(json.dumps(res[:20], ensure_ascii=False, indent=2))
            except Exception:
                print(res[:20])
        except Exception as e:
            print('调用 fetch_tianditu 出错：', repr(e), file=sys.stderr)
            sys.exit(1)
        return

    # 否则构造 postStr 并直接请求
    payload = {"queryType": 13, "start": 0, "count": 20}
    if args.datatypes:
        payload['dataTypes'] = args.datatypes
    if bbox is not None:
        payload['mapBound'] = f"{bbox['left']},{bbox['bottom']},{bbox['right']},{bbox['top']}"
    elif admin:
        if admin.get('county'):
            payload['specify'] = admin.get('county')
        elif admin.get('city'):
            payload['specify'] = admin.get('city')
        elif admin.get('province'):
            payload['specify'] = admin.get('province')
    if args.keyword:
        payload['keyword'] = args.keyword
    params = {"postStr": json.dumps(payload, ensure_ascii=False), "type": "query", "tk": key}
    url = 'http://api.tianditu.gov.cn/v2/search'
    print('[DEBUG] 发送构造请求:')
    print('URL:', url)
    print('params:', params)
    resp = requests.get(url, params=params, timeout=30)
    print('[DEBUG] STATUS:', resp.status_code)
    if args.print_full_response:
        try:
            print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False))
        except Exception:
            print('[DEBUG] TEXT:', (resp.text or ''))
    else:
        try:
            print('[DEBUG] JSON:', json.dumps(resp.json(), ensure_ascii=False)[:4000])
        except Exception:
            print('[DEBUG] TEXT:', (resp.text or '')[:4000])

    return

    # NOTE: unreachable, kept for structure



if __name__ == '__main__':
    main()
