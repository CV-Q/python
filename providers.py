import requests
from typing import Any, Dict, List, Optional

AMAP_TYPE_MAP = {
    "hospital": "120000",
    "gas_station": "050700",
}


def fetch_baidu(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("百度 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    for page in range(0, page_limit):
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
            else:
                if latitude is not None and longitude is not None:
                    params["location"] = f"{latitude},{longitude}"
        resp = requests.get("http://api.map.baidu.com/place/v2/search", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
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


def fetch_gaode(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("高德 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    types = AMAP_TYPE_MAP.get(place_type)
    for page in range(1, page_limit + 1):
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
                city = admin_region.get("city") or admin_region.get("province")
            if city:
                url = "https://restapi.amap.com/v3/place/text"
                params = {
                    "key": key,
                    "keywords": keyword,
                    "city": city,
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
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            raise RuntimeError(f"高德 API 返回错误: {data}")
        pois = data.get("pois", [])
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


def fetch_tencent(key: str, keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int = 5) -> List[Dict[str, Any]]:
    if not key:
        raise ValueError("腾讯 API Key 未配置。")
    result: List[Dict[str, Any]] = []
    for page in range(1, page_limit + 1):
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


def fetch_provider_records(provider: str, api_keys: Dict[str, str], keyword: str, place_type: str, latitude: Optional[float], longitude: Optional[float], bbox: Optional[Dict[str, float]], admin_region: Optional[Dict[str, str]], page_limit: int) -> List[Dict[str, Any]]:
    if provider == "baidu":
        return fetch_baidu(api_keys.get("baidu", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit)
    if provider == "gaode":
        return fetch_gaode(api_keys.get("gaode", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit)
    if provider == "tencent":
        return fetch_tencent(api_keys.get("tencent", ""), keyword, place_type, latitude, longitude, bbox, admin_region, page_limit=page_limit)
    raise ValueError(f"不支持的 provider: {provider}")
