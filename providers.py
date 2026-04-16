import requests
import time
from typing import Any, Dict, List, Optional
import rate_limiter

AMAP_TYPE_MAP = {
    "hospital": "120000",
    "gas_station": "050700",
}


def fetch_tianditu(key: str, keyword: str, data_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    """Fetch POIs from Tianditu (天地图) using the search2 endpoint.

    Note: Tianditu parameters vary by service; we use a conservative generic request
    with 'tk' for token and 'text' for query. The caller may provide 'data_type'
    which will be sent as the 'type' parameter when present.
    """
    if not key:
        raise ValueError("天地图 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    # Tianditu paging convention is not uniform; iterate pages and stop when no results
    for page in range(1, page_limit + 1):
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        try:
            if progress_callback:
                progress_callback({"type": "subtask_page", "provider": "tianditu", "page": page, "keyword": keyword, "admin_region": admin_region, "data_type": data_type})
        except Exception:
            pass
        params = {
            "tk": key,
            "text": keyword or "",
            "pageno": page,
            "pagenum": 20,
            "type": data_type or "",
            "f": "json",
        }
        # If bbox provided, send as spatial filter when possible
        if bbox is not None:
            params["bbox"] = f"{bbox['left']},{bbox['bottom']},{bbox['right']},{bbox['top']}"
        else:
            if admin_region and isinstance(admin_region, dict):
                # prefer county/city/province as district filter
                region_val = admin_region.get("county") or admin_region.get("city") or admin_region.get("province")
                if region_val:
                    params["city"] = region_val
        try:
            rate_limiter.acquire("tianditu")
        except Exception:
            pass
        resp = requests.get("http://lbs.tianditu.gov.cn/server/search2.html", params=params, timeout=20)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            # fallback: treat response as text and skip
            break
        # Tianditu returns results under 'result' or 'results' depending on service
        items = data.get("result") or data.get("results") or data.get("features") or []
        # normalize GeoJSON-like features
        normalized = []
        if isinstance(items, dict) and "pois" in items:
            items = items.get("pois")
        if not items:
            break
        for item in items:
            # support feature geometry
            lat = None
            lng = None
            if isinstance(item, dict):
                # GeoJSON feature
                geom = item.get("geometry") or {}
                props = item.get("properties") or item
                if geom and isinstance(geom, dict):
                    coords = geom.get("coordinates") or []
                    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                        lng, lat = coords[0], coords[1]
                # common keys fallbacks
                name = props.get("name") or props.get("title") or props.get("place_name") or props.get("poi_name")
                addr = props.get("address") or props.get("addr") or ""
                contact = props.get("tel") or props.get("telephone") or ""
                pid = props.get("id") or props.get("uid") or props.get("poi_id")
            else:
                continue
            normalized.append({
                "id": pid,
                "name": name or "",
                "address": addr,
                "contact": contact,
                "latitude": lat,
                "longitude": lng,
                "source": "tianditu",
            })
        if not normalized:
            break
        result.extend(normalized)
        if len(normalized) < 20:
            break
    return result


def fetch_baidu(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("百度 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    for page in range(0, page_limit):
        # cooperative cancellation: if stop requested, break early
        try:
            if stop_event and getattr(stop_event, 'is_set', lambda: False)():
                return result
        except Exception:
            pass
        # notify caller about page being requested (Baidu uses page_num starting at 0)
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
        if bbox is not None:
            params["bounds"] = f"{bbox['bottom']},{bbox['left']},{bbox['top']},{bbox['right']}"
        else:
            city = None
            if admin_region and isinstance(admin_region, dict):
                city = admin_region.get("city") or admin_region.get("province")
            if city:
                params["region"] = city
                # 限定到指定城市，避免跨城模糊匹配（Baidu 支持 city_limit: true/false）
                params["city_limit"] = "true"
            else:
                if latitude is not None and longitude is not None:
                    params["location"] = f"{latitude},{longitude}"
        # Defensive fallback: if no bounds/location/region was set, try extracting from admin_region
        # (some callers may pass unexpected admin_region shapes). This prevents Baidu 'Parameter Invalid'.
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
        # ensure per-request rate limiting
        try:
            rate_limiter.acquire("baidu")
        except Exception:
            pass
        resp = requests.get("http://api.map.baidu.com/place/v2/search", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            # emit debug info to caller (GUI/log) so we can inspect exact params and response
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
            # also print to stderr/stdout to aid debugging when running from CLI
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
    types = AMAP_TYPE_MAP.get(place_type)
    # cap page_limit to a safe maximum (AMap doc suggests up to 40)
    page_limit = min(int(page_limit or 0) or 1, 40)
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
            url = "https://restapi.amap.com/v3/place/polygon"
            polygon = (
                f"{bbox['left']},{bbox['top']};"
                f"{bbox['right']},{bbox['top']};"
                f"{bbox['right']},{bbox['bottom']};"
                f"{bbox['left']},{bbox['bottom']}"
            )
            params = {
                "key": key,
                "polygon": polygon,
                "keywords": keyword,
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
                url = "https://restapi.amap.com/v3/place/text"
                params = {
                    "key": key,
                    "keywords": keyword,
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
                    "keywords": keyword,
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
                resp = requests.get(url, params=params, timeout=20)
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
        resp = requests.get("https://apis.map.qq.com/ws/place/v1/search", params=params, timeout=20)
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


def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int, progress_callback=None, stop_event=None) -> List[Dict[str, Any]]:
    if provider == "baidu":
        return fetch_baidu(api_keys.get("baidu", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event)
    if provider == "gaode":
        return fetch_gaode(api_keys.get("gaode", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event)
    if provider == "tianditu":
        # tianditu prefers a data type / category field; pass place_type as data_type
        return fetch_tianditu(api_keys.get("tianditu", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit, progress_callback=progress_callback, stop_event=stop_event)
    raise ValueError(f"不支持的 provider: {provider}")
