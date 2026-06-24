from __future__ import annotations

from . import amap_adapter


def build_route(task: dict, context: dict) -> tuple[list[dict], list[dict]]:
    """AMap Skill/MCP adapter seam.

    This MVP keeps the runtime dependency-free: it records the intended AMap
    Skill calls, then delegates to the WebService adapter. When the official
    Skill/MCP runtime is available, replace the delegated calls here.
    """
    skill_logs: list[dict] = [
        {
            "tool": "amap-lbs-skill.navigation_planning",
            "mode": "skill-adapter",
            "status": "started",
            "detail": "使用高德 Skill/MCP 适配层；当前 MVP 委托 WebService adapter 执行",
        }
    ]

    if _needs_poi_search(task):
        skill_logs.append(
            {
                "tool": "amap-lbs-skill.poi_search",
                "mode": "skill-adapter",
                "status": "planned",
                "request": _poi_requests(task),
            }
        )

    skill_logs.append(
        {
            "tool": "amap-lbs-skill.route_planning",
            "mode": "skill-adapter",
            "status": "planned",
            "request": {
                "origin": task.get("origin"),
                "destination": task.get("destination"),
                "waypoints": task.get("waypoints", []),
                "constraints": task.get("constraints", {}),
            },
        }
    )

    routes, webservice_logs = amap_adapter.build_route(task, context)
    for route in routes:
        route["provider"] = "amap-skill-adapter" if route.get("provider") == "amap" else route.get("provider", "mock-amap")

    skill_logs.append(
        {
            "tool": "amap-jsapi-skill.map_render",
            "mode": "skill-adapter",
            "status": "planned",
            "detail": "前端使用高德 JS API Driving 在地图内算路渲染",
        }
    )
    return routes, [*skill_logs, *webservice_logs]


def _needs_poi_search(task: dict) -> bool:
    return any(waypoint.get("type") == "poi" for waypoint in task.get("waypoints", []))


def _poi_requests(task: dict) -> list[dict]:
    return [
        {
            "keyword": waypoint.get("name") or waypoint.get("category"),
            "category": waypoint.get("category"),
            "along_route": task.get("constraints", {}).get("poi_along_route", False),
        }
        for waypoint in task.get("waypoints", [])
        if waypoint.get("type") == "poi"
    ]
