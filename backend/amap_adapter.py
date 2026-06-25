from __future__ import annotations

import json
import hashlib
import math
import os
import re
import urllib.parse
import urllib.request

from .mock_context import resolve_place


AMAP_REST = "https://restapi.amap.com/v3"


def _request(path: str, params: dict, logs: list[dict]) -> dict | None:
    key = os.getenv("AMAP_WEB_SERVICE_KEY") or os.getenv("AMAP_KEY")
    if not key:
        logs.append({"tool": f"amap.webservice.{path}", "mode": "mock", "status": "skipped", "detail": "AMAP_WEB_SERVICE_KEY 未配置"})
        return None
    request_params = {**params, "key": key}
    jscode = os.getenv("AMAP_WEB_SERVICE_JSCODE", "")
    if jscode:
        request_params["jscode"] = jscode
    private_key = os.getenv("AMAP_WEB_SERVICE_PRIVATE_KEY", "")
    if private_key:
        request_params["sig"] = _build_sig(request_params, private_key)
    query = urllib.parse.urlencode(request_params)
    url = f"{AMAP_REST}/{path}?{query}"
    logs.append(
        {
            "tool": f"amap.webservice.{path}",
            "mode": "live",
            "request": {k: v for k, v in params.items() if k != "key"},
            "signed": bool(private_key),
            "jscode": bool(jscode),
        }
    )
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        logs.append({"tool": f"amap.webservice.{path}", "status": "ok", "infocode": data.get("infocode"), "info": data.get("info")})
        return data
    except Exception as exc:
        logs.append({"tool": f"amap.webservice.{path}", "status": "fallback", "error": str(exc)})
        return None


def _build_sig(params: dict, private_key: str) -> str:
    raw = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.md5(f"{raw}{private_key}".encode("utf-8")).hexdigest()


def geocode(address: str, logs: list[dict], city: str | None = "上海") -> dict | None:
    params = {"address": address}
    if city:
        params["city"] = city
    data = _request("geocode/geo", params, logs)
    if data and data.get("geocodes"):
        item = data["geocodes"][0]
        return {"name": item.get("formatted_address") or address, "address": address, "location": item.get("location")}
    return None


def search_poi(keyword: str, center: str, logs: list[dict], city: str = "上海", category: str = "", candidate_names: list[str] | None = None, radius: int = 10000, max_terms: int = 8) -> dict:
    model_terms = _dedupe_terms([keyword, *_clean_candidate_names(candidate_names or [])])[:max_terms]
    for term in model_terms:
        data = _request(
            "place/around",
            {"keywords": term, "location": center, "radius": radius, "city": city, "offset": 5, "extensions": "base"},
            logs,
        )
        if data and data.get("pois"):
            poi = data["pois"][0]
            if _is_far_poi(poi, center, radius):
                logs.append(
                    {
                        "tool": "amap.poi_search",
                        "mode": "live",
                        "status": "rejected_far",
                        "keyword": term,
                        "result": poi.get("name", ""),
                        "location": poi.get("location", ""),
                        "center": center,
                        "radius": radius,
                        "detail": "高德命中结果超出本段搜索半径，继续尝试下一个候选",
                    }
                )
                continue
            if _is_bad_poi_result(poi, category):
                logs.append(
                    {
                        "tool": "amap.poi_search",
                        "mode": "live",
                        "status": "rejected",
                        "keyword": term,
                        "result": poi.get("name", ""),
                        "category": category,
                        "detail": "高德命中结果与推荐类别不匹配，继续尝试下一个候选",
                    }
                )
                continue
            result = {
                "name": poi.get("name", term),
                "address": poi.get("address", ""),
                "location": poi.get("location"),
                "category": category or keyword,
            }
            if term != keyword:
                result["original_keyword"] = keyword
                result["fallback_keyword"] = term
                result["fallback_source"] = "model_candidate"
                logs.append(
                    {
                        "tool": "amap.poi_search",
                        "mode": "live",
                        "status": "model_candidate_matched",
                        "original": keyword,
                        "fallback_keyword": term,
                        "result": result["name"],
                        "detail": "原推荐地点高德未命中，已改用联网模型给出的其他候选 POI",
                    }
                )
            return result
    for term in _poi_search_terms(keyword, category, city)[:max_terms]:
        if term in model_terms:
            continue
        data = _request(
            "place/around",
            {"keywords": term, "location": center, "radius": radius, "city": city, "offset": 5, "extensions": "base"},
            logs,
        )
        if data and data.get("pois"):
            poi = data["pois"][0]
            if _is_far_poi(poi, center, radius):
                logs.append(
                    {
                        "tool": "amap.poi_search",
                        "mode": "live",
                        "status": "rejected_far",
                        "keyword": term,
                        "result": poi.get("name", ""),
                        "location": poi.get("location", ""),
                        "center": center,
                        "radius": radius,
                        "detail": "高德兜底结果超出本段搜索半径，继续尝试下一个兜底词",
                    }
                )
                continue
            if _is_bad_poi_result(poi, category):
                logs.append(
                    {
                        "tool": "amap.poi_search",
                        "mode": "live",
                        "status": "rejected",
                        "keyword": term,
                        "result": poi.get("name", ""),
                        "category": category,
                        "detail": "高德兜底结果与推荐类别不匹配，继续尝试下一个兜底词",
                    }
                )
                continue
            result = {
                "name": poi.get("name", term),
                "address": poi.get("address", ""),
                "location": poi.get("location"),
                "category": category or keyword,
                "original_keyword": keyword,
                "fallback_keyword": term,
                "fallback_source": "amap_generic",
            }
            logs.append(
                {
                    "tool": "amap.poi_search",
                    "mode": "live",
                    "status": "generic_replaced",
                    "original": keyword,
                    "fallback_keyword": term,
                    "result": result["name"],
                    "detail": "联网模型候选均未被高德命中，最后使用高德同区域泛类 POI 兜底",
                }
            )
            return result
    unresolved = {"name": f"待联网确认：{keyword}", "address": "", "location": None, "category": keyword, "status": "unresolved"}
    logs.append({"tool": "amap.poi_search", "mode": "live", "status": "unresolved", "result": unresolved["name"], "detail": "高德 POI 未返回可用结果，未使用 Mock 店家数据"})
    return unresolved


def driving_route(origin: str, destination: str, waypoints: list[str], logs: list[dict], strategy: int = 32) -> dict:
    params = {"origin": origin, "destination": destination, "strategy": strategy, "extensions": "base"}
    if waypoints:
        params["waypoints"] = ";".join(waypoints)
    data = _request("direction/driving", params, logs)
    if data and data.get("route", {}).get("paths"):
        path = data["route"]["paths"][0]
        points = [origin, *waypoints, destination]
        steps = path.get("steps", [])
        if steps:
            polyline = []
            for step in steps:
                if step.get("polyline"):
                    polyline.extend(step["polyline"].split(";"))
            points = polyline or points
        return {
            "provider": "amap",
            "distance_m": int(float(path.get("distance", 0) or 0)),
            "duration_s": int(float(path.get("duration", 0) or 0)),
            "tolls_yuan": float(path.get("tolls", 0) or 0),
            "traffic_lights": int(path.get("traffic_lights", 0) or 0),
            "polyline": points,
        }
    return _mock_route(origin, destination, waypoints, strategy, logs)


def build_route(task: dict, context: dict) -> tuple[list[dict], list[dict]]:
    logs: list[dict] = []
    origin_place = resolve_place(task.get("origin"), context)
    destination_place = resolve_place(task.get("destination"), context)

    if task.get("destination", {}).get("type") != "poi" and not destination_place.get("location") and destination_place.get("address"):
        geocode_city = None if task.get("destination", {}).get("type") == "address" else "上海"
        destination_place = geocode(destination_place["address"], logs, city=geocode_city) or destination_place
    if task.get("destination", {}).get("type") == "poi" and not destination_place.get("location"):
        destination_task = task.get("destination", {})
        destination_keyword = destination_task.get("name") or destination_task.get("category") or "POI"
        destination_city = (
            _city_hint(destination_keyword)
            or _city_hint(origin_place.get("address") or "")
            or _city_hint(origin_place.get("name") or "")
            or ""
        )
        origin_city = _city_hint(origin_place.get("address") or "") or _city_hint(origin_place.get("name") or "")
        search_center = origin_place["location"]
        if destination_city and destination_city not in {"上海", "上海市"} and destination_city != origin_city:
            city_center = geocode(destination_city, logs, city=None)
            if city_center and city_center.get("location"):
                search_center = city_center["location"]
        destination_radius = 20000 if task.get("constraints", {}).get("fast_itinerary_route") else 50000
        destination_place = search_poi(
            destination_keyword,
            search_center,
            logs,
            city=destination_city or "全国",
            category=destination_task.get("category", ""),
            candidate_names=destination_task.get("amap_candidate_names", []),
            radius=destination_radius,
            max_terms=2 if task.get("constraints", {}).get("fast_itinerary_route") else 8,
        )

    resolved_waypoints = []
    route_locations = []
    last_location = origin_place["location"]
    destination_city = _city_hint(destination_place.get("address") or destination_place.get("name", ""))
    poi_center = destination_place["location"] if task.get("destination", {}).get("type") == "address" and destination_place.get("location") else last_location
    poi_city = destination_city or "上海"
    poi_radius = 50000 if task.get("destination", {}).get("type") == "address" else 10000
    for waypoint in task.get("waypoints", []):
        if waypoint.get("type") == "poi":
            place = search_poi(
                waypoint.get("name") or waypoint.get("category") or "POI",
                poi_center,
                logs,
                city=poi_city,
                category=waypoint.get("category", ""),
                candidate_names=waypoint.get("amap_candidate_names", []),
                radius=poi_radius,
                max_terms=2 if task.get("constraints", {}).get("fast_itinerary_route") else 8,
            )
        else:
            place = resolve_place(waypoint, context)
        resolved_waypoints.append(place)
        if place.get("location"):
            route_locations.append(place["location"])
            last_location = place["location"]
            if task.get("destination", {}).get("type") != "address":
                poi_center = last_location

    if task.get("constraints", {}).get("fast_itinerary_route"):
        strategies = [32]
    else:
        strategies = [32, 10, 2] if task.get("constraints", {}).get("avoid_congestion") else [10, 32, 0]
    routes = []
    for index, strategy in enumerate(strategies, start=1):
        destination_location = destination_place.get("location") or origin_place["location"]
        if not destination_place.get("location"):
            logs.append(
                {
                    "tool": "amap.destination_resolution",
                    "status": "fallback",
                    "detail": "终点未解析到坐标，临时使用起点坐标兜底，避免路线生成中断",
                    "destination": destination_place.get("name") or destination_place.get("address"),
                }
            )
        raw = driving_route(origin_place["location"], destination_location, route_locations, logs, strategy=strategy)
        routes.append(
            {
                "id": f"route-{index}",
                "title": ["推荐路线", "少拥堵备选", "少收费备选"][index - 1],
                "strategy": strategy,
                "origin": origin_place,
                "destination": destination_place,
                "waypoints": resolved_waypoints,
                **raw,
            }
        )
    return routes, logs


def _city_hint(address: str) -> str | None:
    city_aliases = {
        "上海": "上海市",
        "苏州": "苏州市",
        "南京": "南京市",
        "杭州": "杭州市",
        "无锡": "无锡市",
        "常州": "常州市",
        "宁波": "宁波市",
        "合肥": "合肥市",
    }
    for keyword, city in city_aliases.items():
        if keyword in (address or ""):
            return city
    match = re.search(r"([\u4e00-\u9fa5]{2,8}市)", address or "")
    if not match:
        return None
    city = match.group(1)
    if city.endswith("省"):
        return None
    return city


def _poi_search_terms(keyword: str, category: str = "", city: str = "") -> list[str]:
    terms: list[str] = []

    def add(value: str | None) -> None:
        value = (value or "").strip()
        if value and value not in terms:
            terms.append(value)

    add(keyword)
    simplified = re.sub(r"[（(].*?[）)]", "", keyword).strip()
    add(simplified)
    add(category)

    text = f"{keyword} {category}"
    if "太湖" in text:
        for term in ("太湖景区", "太湖湿地公园", "太湖旅游景点", "太湖"):
            add(term)
    if any(word in text for word in ("景点", "旅游", "公园", "古镇", "古村", "古码头", "湿地", "太湖", "观景", "景观", "木栈道", "岛")):
        for term in ("旅游景点", "景点", "公园"):
            add(term)
    if any(word in text for word in ("美食", "餐厅", "吃饭", "淮扬菜", "苏帮菜")):
        for term in ("美食餐厅", "餐厅", "苏帮菜"):
            add(term)
    if any(word in text for word in ("礼", "伴手礼", "礼品")):
        for term in ("礼品店", "商场", "伴手礼"):
            add(term)
    if any(word in text for word in ("酒店", "住宿", "民宿", "客栈")):
        for term in ("酒店", "住宿", "民宿"):
            add(term)
    if city and city not in {"上海", "上海市"}:
        add(f"{city}{category}")
    return terms[:8]


def _clean_candidate_names(candidate_names: list[str]) -> list[str]:
    cleaned = []
    for name in candidate_names:
        cleaned.append(name)
        cleaned.append(re.sub(r"[（(].*?[）)]", "", name or "").strip())
    return cleaned


def _dedupe_terms(terms: list[str]) -> list[str]:
    result = []
    for term in terms:
        term = (term or "").strip()
        if term and term not in result:
            result.append(term)
    return result


def _is_bad_poi_result(poi: dict, category: str) -> bool:
    name = poi.get("name", "") or ""
    poi_type = poi.get("type", "") or ""
    text = f"{name} {poi_type}"
    if any(word in text for word in ("洗手间", "卫生间", "厕所", "停车场", "出入口", "售票处")):
        return True
    if any(word in category for word in ("景点", "旅游")) and any(word in text for word in ("酒店", "宾馆", "公寓", "民宿", "餐厅", "饭店")):
        return True
    if any(word in category for word in ("美食", "餐厅", "午餐", "晚餐")) and any(word in text for word in ("酒店", "宾馆", "景区", "公园", "博物馆")):
        return True
    if any(word in category for word in ("酒店", "住宿")) and any(word in text for word in ("景区", "公园", "博物馆", "餐厅", "饭店")):
        return True
    return False


def _is_far_poi(poi: dict, center: str, radius: int) -> bool:
    location = poi.get("location")
    if not location or not center:
        return False
    try:
        return _distance_m(center, location) > radius * 1.25
    except Exception:
        return False


def _mock_poi(keyword: str, center: str) -> dict:
    lng, lat = [float(x) for x in center.split(",")]
    if "咖啡" in keyword:
        offset = 0.012
        name = "Manner Coffee 沿途店"
    elif "充电" in keyword:
        offset = -0.01
        name = "特来电沿途充电站"
    elif "礼" in keyword:
        offset = 0.009
        name = "虹桥沿途精选礼物店"
    elif "早餐" in keyword or "早饭" in keyword:
        offset = 0.007
        name = "沿途早餐店"
    elif "景点" in keyword or "旅游" in keyword:
        offset = 0.011
        name = "沿途城市观景点"
    elif "美食" in keyword or "餐" in keyword:
        offset = 0.01
        name = "沿途美食餐厅"
    else:
        offset = -0.015
        name = "中石化沿途加油站"
    return {"name": name, "address": "模拟沿途 POI", "location": f"{lng + offset:.6f},{lat + offset / 2:.6f}", "category": keyword}


def _mock_route(origin: str, destination: str, waypoints: list[str], strategy: int, logs: list[dict]) -> dict:
    points = [origin, *waypoints, destination]
    distance = 0.0
    for start, end in zip(points, points[1:]):
        distance += _distance_m(start, end)
    multiplier = {32: 1.08, 10: 1.0, 2: 1.15}.get(strategy, 1.03)
    duration = int(distance / 1000 / 34 * 3600 * multiplier)
    logs.append({"tool": "amap.route_planning", "mode": "mock", "status": "ok", "strategy": strategy, "points": len(points)})
    return {
        "provider": "mock-amap",
        "distance_m": int(distance * multiplier),
        "duration_s": duration,
        "tolls_yuan": 0 if strategy == 2 else 12,
        "traffic_lights": max(5, int(distance / 1800)),
        "polyline": points,
    }


def _distance_m(a: str, b: str) -> float:
    lng1, lat1 = [math.radians(float(x)) for x in a.split(",")]
    lng2, lat2 = [math.radians(float(x)) for x in b.split(",")]
    d_lng = lng2 - lng1
    d_lat = lat2 - lat1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))
