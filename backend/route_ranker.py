from __future__ import annotations

from datetime import datetime, timedelta


def rank_routes(routes: list[dict], task: dict, context: dict) -> list[dict]:
    constraints = task.get("constraints", {})
    ranked = []
    for route in routes:
        minutes = round(route["duration_s"] / 60)
        km = round(route["distance_m"] / 1000, 1)
        score = minutes
        reasons = [f"预计 {minutes} 分钟，约 {km} 公里"]
        resolved_waypoints = [p for p in route.get("waypoints", []) if p.get("location")]
        unresolved_waypoints = [p for p in route.get("waypoints", []) if not p.get("location")]
        if resolved_waypoints:
            reasons.append("已串联 " + "、".join(p["name"] for p in resolved_waypoints))
        if unresolved_waypoints:
            reasons.append("待确认沿途点 " + "、".join(p["name"] for p in unresolved_waypoints))
        if constraints.get("avoid_congestion"):
            score -= 6 if route["strategy"] == 32 else 0
            reasons.append("优先避开拥堵路段")
        if constraints.get("prefer_less_fee") or route["strategy"] == 2:
            score -= 3
            reasons.append("费用更低")
        if constraints.get("max_detour_minutes") is not None:
            reasons.append(f"控制绕行不超过 {constraints['max_detour_minutes']} 分钟")
        arrive_before = constraints.get("arrive_before")
        if arrive_before:
            current = datetime.fromisoformat(context["current_time"])
            target_hour, target_minute = [int(x) for x in arrive_before.split(":")[:2]]
            target = current.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            eta = current + timedelta(seconds=route["duration_s"])
            if eta <= target:
                reasons.append(f"预计 {eta.strftime('%H:%M')} 到达，赶得上 {arrive_before}")
                score -= 8
            else:
                reasons.append(f"预计 {eta.strftime('%H:%M')} 到达，晚于 {arrive_before}")
                score += 20
        ranked.append({**route, "score": score, "reason": "；".join(reasons)})
    ranked.sort(key=lambda item: item["score"])
    for index, route in enumerate(ranked, start=1):
        route["rank"] = index
    return ranked
