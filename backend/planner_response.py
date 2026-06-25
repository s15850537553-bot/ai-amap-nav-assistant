from __future__ import annotations


def build_planner_reply(task: dict, routes: list[dict]) -> dict:
    route = routes[0] if routes else {}
    constraints = task.get("constraints", {})
    lines = []

    destination = _place_name(task.get("destination")) or "目的地"
    lines.append(f"我已理解你的出行目标：从当前位置出发，前往{destination}。")

    waypoint_names = [_place_name(item) for item in task.get("waypoints", [])]
    waypoint_names = [name for name in waypoint_names if name]
    if waypoint_names:
        lines.append(f"中途会串联：{'、'.join(waypoint_names)}。")

    if route:
        minutes = round((route.get("duration_s") or 0) / 60)
        distance = round((route.get("distance_m") or 0) / 1000, 1)
        lines.append(f"当前推荐路线预计 {minutes} 分钟，约 {distance} 公里。")

    if constraints.get("arrive_before"):
        lines.append(f"我会优先校验 {constraints['arrive_before']} 前到达的时间约束。")
    if constraints.get("avoid_congestion"):
        lines.append("已把避开拥堵作为路线排序的重要条件。")
    if constraints.get("max_detour_minutes") is not None:
        lines.append(f"沿途推荐地点会控制绕行，目标不超过 {constraints['max_detour_minutes']} 分钟。")

    itinerary_plan = task.get("itinerary_plan") or []
    if itinerary_plan:
        lines.append("两天行程安排：")
        for item in itinerary_plan:
            day = item.get("day", "")
            slot = item.get("slot", "")
            plan = item.get("plan", "")
            lines.append(f"{day} {slot}：{plan}")

    recommendations = route.get("recommendations", []) if route else []
    recommendation_lines = []
    for item in recommendations[:4]:
        if item.get("search_status") == "unavailable":
            recommendation_lines.append(f"{item.get('category', '推荐地点')}：真实联网搜索未完成，未使用 Mock 店家介绍。")
            continue
        name = item.get("route_place_name") or item.get("name") or "推荐地点"
        intro = item.get("intro") or ""
        why = item.get("why") or ""
        source = item.get("source_title") or "联网搜索"
        recommendation_lines.append(f"{name}：{intro} 推荐原因：{why} 来源：{source}")

    if recommendation_lines:
        lines.append("推荐地点说明：")
        lines.extend(recommendation_lines)

    return {
        "summary": "\n".join(lines),
        "recommendations": recommendations,
    }


def _place_name(place: dict | None) -> str:
    if not place:
        return ""
    if place.get("type") == "current_location":
        return "当前车辆位置"
    return place.get("name") or place.get("address") or place.get("category") or ""
