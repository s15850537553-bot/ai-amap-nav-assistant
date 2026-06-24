from __future__ import annotations

import json
import hashlib
import math
import os
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
        }
    )
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        logs.append({"tool": f"amap.webservice.{path}", "status": "ok", "infocode": data.get("infocode"), "info": data.get("info")})
        return data
    except Exception as exc:
        logs.append({"tool": f"amap.webservice.{path}", "status": "fallback", "error": str(exc)})
        return None


def _build_sig(params: dict, private_key: str) -> str:
    raw = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.md5(f"{raw}{private_key}".encode("utf-8")).hexdigest()


def geocode(address: str, logs: list[dict]) -> dict | None:
    data = _request("geocode/geo", {"address": address, "city": "上海"}, logs)
    if data and data.get("geocodes"):
        item = data["geocodes"][0]
        return {"name": item.get("formatted_address") or address, "address": address, "location": item.get("location")}
    return None


def search_poi(keyword: str, center: str, logs: list[dict]) -> dict:
    data = _request(
        "place/around",
        {"keywords": keyword, "location": center, "radius": 5000, "city": "上海", "offset": 5, "extensions": "base"},
        logs,
    )
    if data and data.get("pois"):
        poi = data["pois"][0]
        return {"name": poi.get("name", keyword), "address": poi.get("address", ""), "location": poi.get("location"), "category": keyword}
    mock = _mock_poi(keyword, center)
    logs.append({"tool": "amap.poi_search", "mode": "mock", "status": "ok", "result": mock["name"]})
    return mock


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

    if not destination_place.get("location") and destination_place.get("address"):
        destination_place = geocode(destination_place["address"], logs) or destination_place

    resolved_waypoints = []
    route_locations = []
    last_location = origin_place["location"]
    for waypoint in task.get("waypoints", []):
        if waypoint.get("type") == "poi":
            place = search_poi(waypoint.get("name") or waypoint.get("category") or "POI", last_location, logs)
        else:
            place = resolve_place(waypoint, context)
        resolved_waypoints.append(place)
        if place.get("location"):
            route_locations.append(place["location"])
            last_location = place["location"]

    strategies = [32, 10, 2] if task.get("constraints", {}).get("avoid_congestion") else [10, 32, 0]
    routes = []
    for index, strategy in enumerate(strategies, start=1):
        raw = driving_route(origin_place["location"], destination_place["location"], route_locations, logs, strategy=strategy)
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


def _mock_poi(keyword: str, center: str) -> dict:
    lng, lat = [float(x) for x in center.split(",")]
    offset = 0.012 if "咖啡" in keyword else -0.015
    name = "Manner Coffee 沿途店" if "咖啡" in keyword else "中石化沿途加油站"
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
