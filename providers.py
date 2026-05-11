import requests
import time
import re
import json
from typing import Any, Dict, List, Optional
from pathlib import Path
from urllib.parse import unquote
import rate_limiter

AMAP_TYPE_MAP = {
    "hospital": "120000",
    "gas_station": "050700",
}

_GAODE_CODE_NAME_MAP: Optional[Dict[str, str]] = None


def _load_gaode_code_name_map() -> Dict[str, str]:
    global _GAODE_CODE_NAME_MAP
    if _GAODE_CODE_NAME_MAP is not None:
        return _GAODE_CODE_NAME_MAP
    mapping: Dict[str, str] = {}
    try:
        candidates = [
            Path(__file__).parent / "config" / "data_type_tree.gaode.json",
            Path("config") / "data_type_tree.gaode.json",
        ]
        tree_path = None
        for p in candidates:
            if p.exists():
                tree_path = p
                break
        if tree_path is not None:
            with open(tree_path, "r", encoding="utf-8") as f:
                tree = json.load(f)

            def walk(node: Any) -> None:
                if not isinstance(node, dict):
                    return
                for name, val in node.items():
                    if isinstance(val, dict):
                        code = val.get("code") or val.get("id")
                        if code:
                            mapping[str(code).strip()] = str(name).strip()
                        children = val.get("children")
                        if isinstance(children, dict):
                            walk(children)

            walk(tree)
    except Exception:
        mapping = {}
    _GAODE_CODE_NAME_MAP = mapping
    return _GAODE_CODE_NAME_MAP


def _resolve_gaode_keywords(keyword: str, place_type: Optional[str]) -> str:
    kw = str(keyword or "").strip()
    pt = str(place_type or "").strip() if place_type is not None else ""

    # 非纯数字优先按原样作为关键词。
    if kw and not re.fullmatch(r"\d+", kw):
        return kw
    if pt and not re.fullmatch(r"\d+", pt):
        return pt

    # 数字编码反查中文名称，满足“keywords 必填且可用中文 POI 类型”。
    code = kw if re.fullmatch(r"\d+", kw or "") else pt
    if code:
        code_map = _load_gaode_code_name_map()
        name = code_map.get(code)
        if name:
            return name
        return code
    return kw or pt


def _build_full_url(url: str, params: Optional[Dict[str, Any]]) -> str:
    try:
        req = requests.Request("GET", url, params=params)
        prepared = req.prepare()
        return str(prepared.url)
    except Exception:
        return str(url)


def _print_api_request(provider: str, url: str, params: Optional[Dict[str, Any]]) -> None:
    try:
        full_url = _build_full_url(url, params)
        print(f"[API REQUEST][{provider}] {full_url}")
        print(f"[API REQUEST DECODED][{provider}] {unquote(full_url)}")
    except Exception:
        pass


def _print_api_response(provider: str, resp: requests.Response) -> None:
    try:
        print(f"[API RESPONSE][{provider}] status={resp.status_code}")
        print(f"[API RESPONSE BODY][{provider}] {resp.text}")
    except Exception:
        pass


def _parse_polygon_text(raw: Any) -> List[List[float]]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    chunks = [c.strip() for c in re.split(r"[|;]", text) if c and c.strip()]
    points: List[List[float]] = []
    for chunk in chunks:
        pair = [x.strip() for x in chunk.split(",")]
        if len(pair) != 2:
            raise ValueError("polygon 坐标格式错误，应为 lng,lat|lng,lat")
        points.append([float(pair[0]), float(pair[1])])
    return points


def _close_polygon_points(points: List[List[float]]) -> List[List[float]]:
    if not points:
        return points
    first = points[0]
    last = points[-1]
    if abs(first[0] - last[0]) > 1e-12 or abs(first[1] - last[1]) > 1e-12:
        return points + [[first[0], first[1]]]
    return points


def _polygon_to_pipe(points: List[List[float]]) -> str:
    return "|".join([f"{p[0]:.12g},{p[1]:.12g}" for p in points])


def _polygon_to_comma(points: List[List[float]]) -> str:
    out: List[str] = []
    for p in points:
        out.append(f"{p[0]:.12g}")
        out.append(f"{p[1]:.12g}")
    return ",".join(out)


def fetch_tianditu(key: str, keyword: str, data_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None, debug: bool = False) -> List[Dict[str, Any]]:
    """Fetch POIs from Tianditu (天地图) using the official `search` API.

    This implementation follows the official `postStr` example provided in
    the project plan. It constructs a JSON payload for `postStr` and calls
    `http://api.tianditu.gov.cn/v2/search?type=query&postStr=...&tk=KEY`.

    Requirements from plan:
    - Prefer `specify` (行政区 9 位国标码) when available in `admin_region`.
    - If `bbox` is provided, include `mapBound` instead of `specify`.
    - If polygon coordinates are provided in `bbox['polygon']`, use polygon query.
    - `data_type` may be a comma-separated category string or list.
    """
    
    if not key:
        raise ValueError("天地图 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    page_size = 20
    # 天地图文档约束：start 取值 0-300。
    max_pages = (300 // page_size) + 1
    safe_page_limit = max(1, min(int(page_limit or 1), max_pages))
    for page in range(0, safe_page_limit):
        # cooperative cancellation
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        try:
            if progress_callback:
                progress_callback({"type": "subtask_page", "provider": "tianditu", "page": page + 1, "keyword": keyword, "admin_region": admin_region, "data_type": data_type})
        except Exception:
            pass

        # build postStr payload according to official example
        start = page * page_size
        if start > 300:
            break
        payload: Dict[str, Any] = {"queryType": 13, "start": start, "count": page_size}

        # dataTypes: accept list or comma-separated string.
        # 如果传入的是资源名（如 config 中的中文项），尝试从 config/data_type_tree.tianditu.json 映射为 code。
        dt = data_type or keyword or ""
        def load_tianditu_mapping():
            try:
                from pathlib import Path
                cfg_path = Path(__file__).parent / 'config' / 'data_type_tree.tianditu.json'
                if not cfg_path.exists():
                    cfg_path = Path('config') / 'data_type_tree.tianditu.json'
                if not cfg_path.exists():
                    return {}
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    tree = json.load(f)
                mapping = {}
                def walk(node):
                    if not isinstance(node, dict):
                        return
                    # node like {"名称": {"code": "...", "children": {...}}}
                    for name, val in node.items():
                        if isinstance(val, dict):
                            code = val.get('code')
                            if code:
                                mapping[str(name).strip()] = str(code)
                            # children may be under 'children'
                            ch = val.get('children')
                            if isinstance(ch, dict):
                                walk(ch)
                walk(tree)
                return mapping
            except Exception:
                return {}

        mapping = load_tianditu_mapping()
        code_to_name: Dict[str, str] = {}
        try:
            for name, code in mapping.items():
                c = str(code).strip()
                n = str(name).strip()
                if c and n and c not in code_to_name:
                    code_to_name[c] = n
        except Exception:
            code_to_name = {}

        def map_entry(e: str) -> Optional[str]:
            if not e:
                return None
            s = str(e).strip()
            if re.fullmatch(r"\d+", s):
                return s
            # direct name mapping
            if s in mapping:
                return mapping[s]
            # try stripped/normalized match
            ls = s.replace(' ', '')
            for k, v in mapping.items():
                if k.replace(' ', '') == ls:
                    return v
            return None

        # dt may be list/tuple, or comma-separated string, or a single name/code
        codes: List[str] = []
        if isinstance(dt, (list, tuple)):
            for x in dt:
                code = map_entry(x)
                if code:
                    codes.append(code)
        elif isinstance(dt, str) and dt:
            # comma-separated
            parts = [p.strip() for p in dt.split(',') if p.strip()]
            for p in parts:
                code = map_entry(p)
                if code:
                    codes.append(code)

        if codes:
            # tianditu may accept comma-separated codes
            payload["dataTypes"] = ",".join(codes)
        else:
            # fallback to original string if it's numeric or let the API handle unknown names
            if isinstance(dt, str) and dt:
                payload["dataTypes"] = dt

        # spatial filter: prefer polygon, then bbox(mapBound), then admin_region.specify
        polygon_text = None
        try:
            if isinstance(bbox, dict):
                polygon_text = bbox.get("polygon")
        except Exception:
            polygon_text = None

        if polygon_text:
            pts = _parse_polygon_text(polygon_text)
            pts = _close_polygon_points(pts)
            if len(pts) < 4:
                raise ValueError("polygon 至少需要 3 个点并闭合")
            payload["queryType"] = 10
            payload["polygon"] = _polygon_to_comma(pts)
            payload["start"] = max(0, min(start, 300))
            payload["count"] = max(1, min(page_size, 300))
            # show 为可选：为获取省市区/typeCode/typeName，默认请求详细 POI 信息。
            payload.setdefault("show", 2)
            # 天地图 queryType=10 实测要求必须带 keyWord。
            kw_text = str(keyword or "").strip()
            if kw_text and not re.fullmatch(r"\d+", kw_text):
                payload["keyWord"] = kw_text
            else:
                code_candidate = ""
                if kw_text and re.fullmatch(r"\d+", kw_text):
                    code_candidate = kw_text
                elif codes:
                    code_candidate = str(codes[0]).strip()
                elif isinstance(dt, str) and dt and re.fullmatch(r"\d+", dt):
                    code_candidate = dt

                mapped_kw = code_to_name.get(code_candidate, "") if code_candidate else ""
                if mapped_kw:
                    payload["keyWord"] = mapped_kw
                elif code_candidate:
                    # 无法反查中文时回退为编码，至少满足 keyWord 必填。
                    payload["keyWord"] = code_candidate

            if not str(payload.get("keyWord") or "").strip():
                raise ValueError("天地图 polygon 查询需提供 keyWord。")
        elif bbox is not None:
            # mapBound expected as "minx,miny,maxx,maxy"
            payload["mapBound"] = f"{bbox['left']},{bbox['bottom']},{bbox['right']},{bbox['top']}"
        else:
            if admin_region and isinstance(admin_region, dict):
                ad = admin_region.get("adcode") or admin_region.get("adcode")
                if ad:
                    payload["specify"] = str(ad)
                else:
                    # fallback: allow name-based specify when adcode unavailable
                    name = admin_region.get("county") or admin_region.get("city") or admin_region.get("province")
                    if name:
                        payload["specify"] = str(name)
        # require either mapBound or specify per plan
        if "mapBound" not in payload and "specify" not in payload and "polygon" not in payload:
            raise ValueError("天地图查询需提供 polygon、specify(区/县国标码) 或 bbox(mapBound)。")

        params = {"postStr": json.dumps(payload, ensure_ascii=False), "type": "query", "tk": key}
        try:
            rate_limiter.acquire("tianditu")
        except Exception:
            pass
        _print_api_request("tianditu", "http://api.tianditu.gov.cn/v2/search", params)
        resp = requests.get("http://api.tianditu.gov.cn/v2/search", params=params, timeout=20)
        _print_api_response("tianditu", resp)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            # JSON 解析失败时响应正文已由统一日志函数输出
            break

        # normalize possible result containers
        items = []
        if isinstance(data, dict):
            # official may return {"result": {"pois": [...]}} or similar
            if "result" in data and isinstance(data.get("result"), dict) and "pois" in data.get("result"):
                items = data["result"]["pois"]
            elif "result" in data and isinstance(data.get("result"), list):
                items = data.get("result")
            elif "pois" in data:
                items = data.get("pois")
            elif "results" in data:
                items = data.get("results")
            elif "data" in data:
                items = data.get("data")
        if not items:
            break

        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            def first_text(*keys: str) -> str:
                for k in keys:
                    v = item.get(k)
                    if v is None:
                        continue
                    s = str(v).strip()
                    if s:
                        return s
                return ""
            # try common keys
            name = item.get("name") or item.get("title") or item.get("poi_name") or ""
            addr = item.get("address") or item.get("addr") or ""
            contact = item.get("tel") or item.get("telephone") or item.get("contact") or ""
            pid = item.get("id") or item.get("poi_id") or item.get("uid") or ""
            # coordinates: try explicit fields, geometry, or Tianditu's 'lonlat' string
            lat = item.get("lat") or item.get("latitude") or item.get("y")
            lng = item.get("lon") or item.get("longitude") or item.get("x")
            # Tianditu often returns a combined 'lonlat' string like "115.24551,37.88896"
            if (lat is None or lng is None) and isinstance(item.get("lonlat"), str):
                try:
                    parts = [p.strip() for p in item.get("lonlat").split(',') if p.strip()]
                    if len(parts) >= 2:
                        lng = float(parts[0])
                        lat = float(parts[1])
                except Exception:
                    pass
            geom = item.get("geometry") or {}
            if (lat is None or lng is None) and isinstance(geom, dict):
                coords = geom.get("coordinates") or geom.get("coords") or []
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    lng, lat = coords[0], coords[1]
            normalized.append({
                "id": pid,
                "name": name or "",
                "address": addr,
                "contact": contact,
                "latitude": lat,
                "longitude": lng,
                "province": first_text("province", "provinceName", "prov", "provName", "pname"),
                "city": first_text("city", "cityName", "cityname", "cname", "province", "provinceName", "pname"),
                "county": first_text("county", "countyName", "district", "districtName", "adname"),
                "source": "tianditu",
            })
        if not normalized:
            break
        result.extend(normalized)
        if len(result) < (page + 1) * page_size:
            break
    return result


def fetch_baidu(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("百度 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    for page in range(0, page_limit):
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        try:
            if progress_callback:
                progress_callback({"type": "subtask_page", "provider": "baidu", "page": page, "keyword": keyword, "admin_region": admin_region, "place_type": place_type})
        except Exception:
            pass
        params = {
            "query": keyword,
            "output": "json",
            "page_size": 20,
            "page_num": page,
            "ak": key,
            "scope": 2,
        }
        try:
            if place_type:
                if isinstance(place_type, dict):
                    tag_val = place_type.get("type") or place_type.get("tag") or None
                else:
                    tag_val = str(place_type)
                if tag_val:
                    params["tag"] = tag_val
        except Exception:
            pass
        if bbox is not None:
            params["bounds"] = f"{bbox['bottom']},{bbox['left']},{bbox['top']},{bbox['right']}"
        else:
            city = None
            if admin_region and isinstance(admin_region, dict):
                city = admin_region.get("city") or admin_region.get("province")
            if city:
                params["region"] = city
                params["city_limit"] = "true"
            else:
                if latitude is not None and longitude is not None:
                    params["location"] = f"{latitude},{longitude}"
        try:
            if "bounds" not in params and "location" not in params and "region" not in params:
                region_val = None
                if admin_region:
                    if isinstance(admin_region, dict):
                        region_val = admin_region.get("city") or admin_region.get("county") or admin_region.get("province")
                    else:
                        region_val = getattr(admin_region, "city", None) or getattr(admin_region, "county", None) or getattr(admin_region, "province", None)
                if region_val:
                    params["region"] = region_val
                    params["city_limit"] = "true"
        except Exception:
            pass
        try:
            rate_limiter.acquire("baidu")
        except Exception:
            pass
        _print_api_request("baidu", "http://api.map.baidu.com/place/v2/search", params)
        resp = requests.get("http://api.map.baidu.com/place/v2/search", params=params, timeout=20)
        _print_api_response("baidu", resp)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            try:
                if progress_callback:
                    progress_callback({
                        "type": "provider_error",
                        "provider": "baidu",
                        "params": params,
                        "admin_region": admin_region,
                        "response": data,
                    })
            except Exception:
                pass
            try:
                print(f"[DEBUG] BAIDU ERROR admin_region={admin_region} params={params} response={data}")
            except Exception:
                pass
            raise RuntimeError(f"百度 API 返回错误: {data}")
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            location = item.get("location", {})
            result.append({
                "id": item.get("uid", item.get("id")),
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "contact": item.get("telephone", ""),
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
                "source": "baidu",
            })
        if len(results) < 20:
            break
    return result


def fetch_gaode(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:

    if not key:
        raise ValueError("高德 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    # place_type may be a logical resource key (e.g. 'hospital') or a numeric AMap code string.
    types = None
    try:
        # if place_type looks like a numeric code, use it directly
        if isinstance(place_type, str) and re.fullmatch(r"\d+", place_type):
            types = place_type
        else:
            types = AMAP_TYPE_MAP.get(place_type)
    except Exception:
        types = AMAP_TYPE_MAP.get(place_type)
    # cap page_limit to a safe maximum (AMap doc suggests up to 40)
    page_limit = min(int(page_limit or 0) or 1, 40)
    keyword_text = _resolve_gaode_keywords(str(keyword or "").strip(), types)
    # prefer admin_region adcode if provided for precise county-level query
    for page in range(1, page_limit + 1):
        # cooperative cancellation: if stop requested, break early
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        # notify caller about page being requested (AMap pages start at 1)
        try:
            if progress_callback:
                progress_callback({"type": "subtask_page", "provider": "gaode", "page": page, "keyword": keyword, "admin_region": admin_region, "place_type": place_type})
        except Exception:
            pass
        if bbox is not None:
            polygon_text = None
            try:
                if isinstance(bbox, dict):
                    polygon_text = bbox.get("polygon")
            except Exception:
                polygon_text = None

            if polygon_text:
                pts = _parse_polygon_text(polygon_text)
                pts = _close_polygon_points(pts)
                if len(pts) < 4:
                    raise ValueError("多边形至少需要 3 个点并闭合")
                url = "https://restapi.amap.com/v5/place/polygon"
                polygon = _polygon_to_pipe(pts)
            else:
                url = "https://restapi.amap.com/v3/place/polygon"
                polygon = (
                    f"{bbox['left']},{bbox['top']}|"
                    f"{bbox['right']},{bbox['top']}|"
                    f"{bbox['right']},{bbox['bottom']}|"
                    f"{bbox['left']},{bbox['bottom']}|"
                    f"{bbox['left']},{bbox['top']}"
                )
            params = {
                "key": key,
                "polygon": polygon,
                "keywords": keyword_text,
                "offset": 20,
                "page": page,
                "extensions": "base",
            }
        else:
            city = None
            if admin_region and isinstance(admin_region, dict):
                # if adcode present, use it as city parameter (AMap accepts adcode)
                city = admin_region.get("adcode") or admin_region.get("county") or admin_region.get("city") or admin_region.get("province")
            if city:
                ##https://restapi.amap.com/v3/place/text?key=您的key&keywords=&types=高等院校&city=石家庄&children=1&offset=20&page=1&extensions=base
                url = "https://restapi.amap.com/v3/place/text"
                params = {
                    "key": key,
                    "keywords": keyword_text,
                    "city": city,
                    # 限定到指定城市/区县，避免跨城模糊匹配（AMap 支持 true/false）
                    "citylimit": "true",
                    "offset": 20,
                    "page": page,
                    "extensions": "base",
                }
            else:
                url = "https://restapi.amap.com/v3/place/around"
                params = {
                    "key": key,
                    "location": f"{longitude},{latitude}",
                    "keywords": keyword_text,
                    "radius": None,
                    "offset": 20,
                    "page": page,
                    "extensions": "base",
                }
        if types:
            params["types"] = types
        # perform request with retry/backoff for transient errors or rate limits
        retries = 5
        backoff_base = 1.0
        data = None
        for attempt in range(retries):
            try:
                # per-request rate limiting for AMap
                try:
                    rate_limiter.acquire("gaode")
                except Exception:
                    pass
                _print_api_request("gaode", url, params)
                resp = requests.get(url, params=params, timeout=20)
                _print_api_response("gaode", resp)
                resp.raise_for_status()
                data = resp.json()
                # check AMap status
                if data.get("status") != "1":
                    infocode = str(data.get("infocode", ""))
                    # handle rate limit specially (10021) with stronger backoff
                    if infocode == "10021":
                        if attempt < retries - 1:
                            # exponential backoff + extra delay for quota issues
                            sleep_time = backoff_base * (2 ** attempt) + 2 * (attempt + 1)
                            time.sleep(sleep_time)
                            continue
                        else:
                            raise RuntimeError(f"高德 API 返回错误: {data}")
                    # other transient codes (e.g., 10020) treat as retryable but with normal backoff
                    if infocode == "10020":
                        if attempt < retries - 1:
                            time.sleep(backoff_base * (2 ** attempt))
                            continue
                        else:
                            raise RuntimeError(f"高德 API 返回错误: {data}")
                    # non-retryable error
                    raise RuntimeError(f"高德 API 返回错误: {data}")
                break
            except requests.RequestException as req_exc:
                if attempt < retries - 1:
                    time.sleep(backoff_base * (2 ** attempt))
                    continue
                raise
        pois = data.get("pois", []) if isinstance(data, dict) else []
        if not pois:
            break
        for item in pois:
            location = item.get("location", "")
            lng, lat = (location.split(",") + [""])[:2]
            result.append({
                "id": item.get("id", item.get("uid")),
                "name": item.get("name", ""),
                "address": item.get("address", "") or item.get("pname", "") + item.get("cityname", "") + item.get("adname", ""),
                "contact": item.get("tel", ""),
                "latitude": float(lat) if lat else None,
                "longitude": float(lng) if lng else None,
                "province": item.get("pname", "") or "",
                "city": item.get("cityname", "") or "",
                "county": item.get("adname", "") or "",
                "source": "gaode",
            })
        if len(pois) < 20:
            break
    return result


def fetch_tencent(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("腾讯 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    for page in range(1, page_limit + 1):
        # cooperative cancellation: if stop requested, break early
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        # notify caller about page being requested (Tencent pages start at 1)
        try:
            if progress_callback:
                progress_callback({"type": "subtask_page", "provider": "tencent", "page": page, "keyword": keyword, "admin_region": admin_region, "place_type": place_type})
        except Exception:
            pass
        if bbox is not None:
            boundary = f"rectangle({bbox['bottom']},{bbox['left']},{bbox['top']},{bbox['right']})"
        else:
            city = None
            if admin_region and isinstance(admin_region, dict):
                city = admin_region.get("city") or admin_region.get("province")
            if city:
                boundary = f"region({city},0)"
            else:
                boundary = f"nearby({latitude},{longitude},0)"
        params = {
            "keyword": keyword,
            "boundary": boundary,
            "key": key,
            "page_size": 20,
            "page_index": page,
            "orderby": "nearest",
        }
        # per-request rate limiting for Tencent
        try:
            rate_limiter.acquire("tencent")
        except Exception:
            pass
        _print_api_request("tencent", "https://apis.map.qq.com/ws/place/v1/search", params)
        resp = requests.get("https://apis.map.qq.com/ws/place/v1/search", params=params, timeout=20)
        _print_api_response("tencent", resp)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            raise RuntimeError(f"腾讯 API 返回错误: {data}")
        pois = data.get("data", [])
        if not pois:
            break
        for item in pois:
            location = item.get("location", {})
            result.append({
                "id": item.get("id"),
                "name": item.get("title", ""),
                "address": item.get("address", ""),
                "contact": item.get("tel", ""),
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
                "source": "tencent",
            })
        if len(pois) < 20:
            break
    return result


def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int, progress_callback=None, stop_event=None, debug: bool = False) -> List[Dict[str, Any]]:
    if provider == "baidu":
        return fetch_baidu(api_keys.get("baidu", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event)
    if provider == "gaode":
        return fetch_gaode(api_keys.get("gaode", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event)
    if provider == "tianditu":
        # tianditu prefers a data type / category field; pass place_type as data_type
        # 透传 debug 参数以便调用方能开启天地图的详细调试输出
        return fetch_tianditu(api_keys.get("tianditu", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event, debug=debug)
    raise ValueError(f"不支持的 provider: {provider}")
