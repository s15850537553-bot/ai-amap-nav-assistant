from __future__ import annotations

import os
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime

from .amap_adapter import build_route as build_route_with_webservice
from .amap_skill_adapter import build_route as build_route_with_skill
from .mock_context import get_mock_context
from .navigation_planner import plan_with_rules
from .online_search_adapter import discover_places_with_model, enrich_routes_with_recommendations
from .route_ranker import rank_routes


CHECK_INTERVAL_SECONDS = 3
PLANNING_TIMEOUT_SECONDS = 18


class ItineraryScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = self._new_idle_state()

    def start_demo(self, user_input: str = "") -> dict:
        with self._lock:
            task = plan_with_rules(user_input)
            segments = _segments_from_task(task, user_input)
            self._state = {
                "session_id": str(uuid.uuid4()),
                "status": "running",
                "user_onboard": False,
                "current_segment_index": 0,
                "last_check_at": None,
                "active_route": None,
                "source_input": user_input,
                "source_task": task,
                "segments": segments,
                "events": [
                    _event("itinerary.created", f"已根据当前输入创建 {len(segments)} 段行程计划"),
                    _event("scheduler.started", f"定时任务已启动，每 {CHECK_INTERVAL_SECONDS} 秒检查一次触发条件"),
                ],
            }
            return self._evaluate_locked(reason="start")

    def event(self, event_type: str) -> dict:
        with self._lock:
            if self._state["status"] == "idle":
                self._state["events"].append(_event("scheduler.ignored", "尚未启动多段行程"))
                return deepcopy(self._state)

            if event_type == "user_onboard":
                self._state["user_onboard"] = True
                self._state["events"].append(_event("vehicle.user_onboard", "检测到用户已上车，允许触发下一段路线"))
            elif event_type == "arrived":
                self._mark_arrived_locked()
            elif event_type == "reset_onboard":
                self._state["user_onboard"] = False
                self._state["events"].append(_event("vehicle.user_offboard", "用户上车状态已重置，等待下一次上车触发"))
            else:
                self._state["events"].append(_event("scheduler.unknown_event", f"未知事件：{event_type}"))

            return self._evaluate_locked(reason=event_type)

    def status(self) -> dict:
        with self._lock:
            if self._state["status"] == "running":
                return self._evaluate_locked(reason="poll")
            return deepcopy(self._state)

    def _evaluate_locked(self, reason: str) -> dict:
        now = time.time()
        last_check = self._state.get("last_check_at")
        should_check = reason != "poll" or not last_check or now - last_check >= CHECK_INTERVAL_SECONDS
        if not should_check:
            return deepcopy(self._state)

        self._state["last_check_at"] = now
        self._state["events"].append(_event("scheduler.tick", f"定时检查触发条件：{reason}"))

        index = self._state["current_segment_index"]
        segments = self._state["segments"]
        if index >= len(segments):
            self._state["status"] = "completed"
            return deepcopy(self._state)

        segment = segments[index]
        if segment["status"] == "waiting" and self._can_trigger_locked(segment):
            self._activate_segment_locked(index)
        elif segment["status"] == "planning":
            if _planning_timed_out(segment):
                segment["status"] = "waiting"
                segment["planning_error"] = f"后台推理超过 {PLANNING_TIMEOUT_SECONDS} 秒，已释放为可重试状态"
                self._state["user_onboard"] = False
                self._state["events"].append(
                    _event(
                        "route.timeout",
                        f"「{segment['title']}」生成超时，已停止等待；请重新模拟用户上车触发，系统会重新尝试或降级到高德泛类 POI",
                    )
                )
            else:
                self._state["events"].append(
                    _event("scheduler.planning", f"下一段「{segment['title']}」正在后台生成路线")
                )
        elif segment["status"] == "waiting":
            self._state["events"].append(
                _event(
                    "scheduler.waiting",
                    f"下一段「{segment['title']}」未触发：{'; '.join(_missing_conditions(segment, self._state))}",
                )
            )

        self._trim_events_locked()
        return deepcopy(self._state)

    def _can_trigger_locked(self, segment: dict) -> bool:
        if segment.get("requires_user_onboard") and not self._state["user_onboard"]:
            return False
        prev_index = self._state["current_segment_index"] - 1
        if prev_index >= 0 and self._state["segments"][prev_index]["status"] != "completed":
            return False
        return True

    def _activate_segment_locked(self, index: int) -> None:
        segment = self._state["segments"][index]
        if segment["status"] in {"planning", "active", "completed"}:
            return
        segment["status"] = "planning"
        segment["planning_started_at"] = _now()
        segment["planning_started_ts"] = time.time()
        self._state["events"].append(
            _event(
                "route.planning",
                f"正在推理「{segment['title']}」下一段路线：解析触发条件、检索推荐地点、调用高德生成算路",
            )
        )
        session_id = self._state["session_id"]
        segment_snapshot = deepcopy(segment)
        worker = threading.Thread(
            target=self._build_segment_route,
            args=(session_id, index, segment_snapshot),
            daemon=True,
        )
        worker.start()

    def _build_segment_route(self, session_id: str, index: int, segment: dict) -> None:
        context = get_mock_context()
        task = _segment_to_navigation_task(segment)
        try:
            segment_input = _segment_input(segment)
            task.setdefault("constraints", {})
            task["constraints"]["fast_itinerary_route"] = True
            if _segment_needs_fast_route(task):
                discovered_places = []
                discovery_logs = [
                    {
                        "tool": "place_discovery.model_search",
                        "status": "skipped",
                        "detail": "多段行程触发优先保证下一段路线生成，使用高德 POI 兜底，不等待联网模型候选",
                    }
                ]
            else:
                task, discovered_places, discovery_logs = discover_places_with_model(task, context, segment_input)
                _trim_segment_candidates(task, max_candidates=2)
            routes, logs = _build_route(task, context)
            logs = [*discovery_logs, *logs]
            ranked = rank_routes(routes, task, context)
            enriched, search_logs = enrich_routes_with_recommendations(
                task,
                ranked,
                context,
                segment_input,
                discovered_places,
            )
            logs.extend(search_logs)
            route = enriched[0]
            route["id"] = f"{segment['id']}-{route['id']}"
            route["title"] = segment["title"]
            route_summary = {
                "duration_minutes": round(route["duration_s"] / 60),
                "distance_km": round(route["distance_m"] / 1000, 1),
                "reason": route.get("reason", ""),
            }
            with self._lock:
                if not self._can_update_segment_locked(session_id, index, segment):
                    return
                current = self._state["segments"][index]
                current["status"] = "active"
                current["started_at"] = _now()
                current["recommended_route_id"] = route["id"]
                current["route"] = route
                current["route_summary"] = route_summary
                self._state["active_route"] = route
                self._state["events"].append(
                    _event("route.recommended", f"已触发「{segment['title']}」，自动生成下一步出行路线")
                )
                for log in logs[:8]:
                    self._state["events"].append({"at": _now(), **log})
                self._trim_events_locked()
        except Exception as exc:
            with self._lock:
                if not self._can_update_segment_locked(session_id, index, segment):
                    return
                current = self._state["segments"][index]
                current["status"] = "waiting"
                current["planning_error"] = str(exc)
                self._state["events"].append(
                    _event("route.failed", f"「{segment['title']}」路线生成失败，可重新模拟上车触发：{exc}")
                )
                self._trim_events_locked()

    def _can_update_segment_locked(self, session_id: str, index: int, segment: dict) -> bool:
        if self._state.get("session_id") != session_id:
            return False
        if index >= len(self._state["segments"]):
            return False
        current = self._state["segments"][index]
        return current.get("id") == segment.get("id") and current.get("status") == "planning"

    def _mark_arrived_locked(self) -> None:
        index = self._state["current_segment_index"]
        if index >= len(self._state["segments"]):
            return

        segment = self._state["segments"][index]
        if segment["status"] not in {"active", "waiting", "planning"}:
            return

        completed_route = segment.get("route") or {}
        segment["status"] = "completed"
        segment["completed_at"] = _now()
        self._state["events"].append(_event("segment.completed", f"已到达「{segment['title']}」"))
        self._state["user_onboard"] = False
        self._state["active_route"] = None

        next_index = index + 1
        self._state["current_segment_index"] = next_index
        if next_index < len(self._state["segments"]):
            next_segment = self._state["segments"][next_index]
            route_destination = completed_route.get("destination") or {}
            if route_destination.get("location"):
                next_segment["origin"] = {
                    "type": "resolved_place",
                    "name": route_destination.get("name") or segment.get("destination", {}).get("name") or "上一段终点",
                    "address": route_destination.get("address", ""),
                    "location": route_destination["location"],
                }
            self._state["events"].append(
                _event("segment.waiting", f"下一段「{next_segment['title']}」等待用户上车后触发")
            )
        else:
            self._state["status"] = "completed"
            self._state["events"].append(_event("itinerary.completed", "全部多段行程已完成"))

    def _trim_events_locked(self) -> None:
        self._state["events"] = self._state["events"][-80:]

    @staticmethod
    def _new_idle_state() -> dict:
        return {
            "session_id": None,
            "status": "idle",
            "user_onboard": False,
            "current_segment_index": 0,
            "last_check_at": None,
            "active_route": None,
            "source_input": "",
            "source_task": None,
            "segments": [],
            "events": [_event("scheduler.idle", "多段行程定时任务尚未启动")],
        }


def _build_route(task: dict, context: dict) -> tuple[list[dict], list[dict]]:
    adapter = os.getenv("AMAP_ADAPTER", "webservice").strip().lower()
    if adapter in {"skill", "mcp", "skills"}:
        return build_route_with_skill(task, context)
    return build_route_with_webservice(task, context)


def _segments_from_task(task: dict, user_input: str) -> list[dict]:
    if task.get("scenario_id") == "complex_day_itinerary":
        return _complex_day_segments()

    stops = [task.get("origin") or {"type": "current_location"}]
    stops.extend(task.get("waypoints", []))
    stops.append(task.get("destination") or {"type": "memory_place", "name": "公司"})

    segments = []
    for index, (origin, destination) in enumerate(zip(stops, stops[1:]), start=1):
        deadline = task.get("constraints", {}).get("arrive_before") if index == len(stops) - 1 else None
        segment = _make_segment(
            segment_id=f"seg-{index}",
            origin=origin,
            destination=destination,
            deadline=deadline,
            title=f"{_place_label(origin)} -> {_place_label(destination)}",
            trigger="用户上车且上一段完成后触发" if index > 1 else "用户上车后触发第一段路线",
        )
        segments.append(segment)

    if not segments:
        segments.append(
            _make_segment(
                segment_id="seg-1",
                origin={"type": "current_location"},
                destination={"type": "memory_place", "name": "公司"},
                deadline=None,
                title="当前车辆位置 -> 公司",
                trigger="用户上车后触发第一段路线",
            )
        )
    return segments


def _complex_day_segments() -> list[dict]:
    return [
        _make_segment("seg-school", {"type": "current_location"}, {"type": "memory_place", "name": "孩子学校"}, "07:40", "当前车辆位置 -> 孩子学校", "用户上车后触发第一段路线"),
        _make_segment("seg-train", {"type": "memory_place", "name": "孩子学校"}, {"type": "memory_place", "name": "上海虹桥站"}, "08:30", "孩子学校 -> 高铁站", "送达学校后，用户再次上车触发"),
        _make_segment("seg-company", {"type": "memory_place", "name": "上海虹桥站"}, {"type": "memory_place", "name": "公司"}, "10:00", "高铁站 -> 公司", "送达高铁站后，用户再次上车触发", [{"type": "poi", "name": "早餐店", "category": "早餐"}]),
        _make_segment("seg-client", {"type": "memory_place", "name": "公司"}, {"type": "memory_place", "name": "徐汇客户"}, "14:00", "公司 -> 徐汇客户", "会议结束且用户上车后触发"),
        _make_segment("seg-school-event", {"type": "memory_place", "name": "徐汇客户"}, {"type": "memory_place", "name": "孩子学校"}, "16:30", "徐汇客户 -> 学校家长会", "客户拜访结束且用户上车后触发"),
        _make_segment("seg-home", {"type": "memory_place", "name": "孩子学校"}, {"type": "memory_place", "name": "家"}, None, "学校 -> 家", "家长会结束且用户上车后触发"),
        _make_segment("seg-airport", {"type": "memory_place", "name": "家"}, {"type": "memory_place", "name": "虹桥机场"}, "19:00", "家 -> 虹桥机场", "收拾行李完成且用户上车后触发"),
    ]


def _make_segment(
    segment_id: str,
    origin: dict,
    destination: dict,
    deadline: str | None,
    title: str,
    trigger: str,
    waypoints: list[dict] | None = None,
) -> dict:
    return {
        "id": segment_id,
        "title": title,
        "origin": origin,
        "destination": destination,
        "waypoints": waypoints or [],
        "deadline": deadline,
        "trigger": trigger,
        "requires_user_onboard": True,
        "status": "waiting",
        "route": None,
        "route_summary": None,
    }


def _place_label(place: dict | None) -> str:
    if not place:
        return "未知地点"
    if place.get("type") == "current_location":
        return "当前车辆位置"
    return place.get("name") or place.get("address") or place.get("type") or "未知地点"


def _segment_to_navigation_task(segment: dict) -> dict:
    return {
        "task_type": "navigation_planning",
        "origin": segment["origin"],
        "destination": segment["destination"],
        "waypoints": segment.get("waypoints", []),
        "constraints": {
            "arrive_before": segment.get("deadline"),
            "avoid_congestion": True,
            "max_detour_minutes": 8 if segment.get("waypoints") else None,
            "prefer_less_fee": False,
            "poi_along_route": any(item.get("type") == "poi" for item in segment.get("waypoints", [])),
        },
        "need_user_confirm": False,
        "clarification": None,
    }


def _segment_input(segment: dict) -> str:
    parts = []
    for place in [*segment.get("waypoints", []), segment.get("destination")]:
        if not place:
            continue
        if place.get("type") == "poi":
            parts.append(place.get("category") or place.get("name") or "")
    return " ".join(part for part in parts if part)


def _trim_segment_candidates(task: dict, max_candidates: int) -> None:
    places = []
    if task.get("destination", {}).get("type") == "poi":
        places.append(task["destination"])
    places.extend(item for item in task.get("waypoints", []) if item.get("type") == "poi")
    for place in places:
        if place.get("amap_candidate_names"):
            place["amap_candidate_names"] = place["amap_candidate_names"][:max_candidates]


def _segment_needs_fast_route(task: dict) -> bool:
    if task.get("destination", {}).get("type") == "poi":
        return True
    return any(item.get("type") == "poi" for item in task.get("waypoints", []))


def _missing_conditions(segment: dict, state: dict) -> list[str]:
    missing = []
    if segment.get("requires_user_onboard") and not state.get("user_onboard"):
        missing.append("未检测到用户上车")
    prev_index = state["current_segment_index"] - 1
    if prev_index >= 0 and state["segments"][prev_index]["status"] != "completed":
        missing.append("上一段未完成")
    return missing or ["等待下一次定时检查"]


def _planning_timed_out(segment: dict) -> bool:
    started_ts = segment.get("planning_started_ts")
    if isinstance(started_ts, (int, float)):
        return time.time() - started_ts > PLANNING_TIMEOUT_SECONDS
    started_at = segment.get("planning_started_at")
    if not started_at:
        return False
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    return (datetime.now() - started).total_seconds() > PLANNING_TIMEOUT_SECONDS


def _event(event_type: str, detail: str) -> dict:
    return {"at": _now(), "tool": event_type, "status": "ok", "detail": detail}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


scheduler = ItineraryScheduler()
