from __future__ import annotations

import json
import os
import re
import urllib.request

from .mock_context import get_mock_context


DEFAULT_TASK = {
    "task_type": "navigation_planning",
    "scenario_id": "general_navigation",
    "origin": {"type": "current_location"},
    "destination": {"type": "memory_place", "name": "公司"},
    "waypoints": [],
    "constraints": {
        "arrive_before": None,
        "avoid_congestion": False,
        "max_detour_minutes": None,
        "prefer_less_fee": False,
        "poi_along_route": False,
    },
    "need_user_confirm": True,
    "clarification": None,
    "execution_plan": [],
    "external_actions": [],
    "decision_points": [],
    "itinerary_plan": [],
}

EXTERNAL_DESTINATION_ALIASES = {
    "南京": "南京市",
    "杭州": "杭州市",
    "苏州": "苏州市",
    "无锡": "无锡市",
    "常州": "常州市",
    "宁波": "宁波市",
    "合肥": "合肥市",
}


def _blank_task() -> dict:
    return json.loads(json.dumps(DEFAULT_TASK))


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def plan_with_gpt(user_input: str, context: dict | None = None) -> tuple[dict, list[dict]]:
    """Use OpenAI Responses API when OPENAI_API_KEY is present, otherwise rule fallback."""
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    context = context or get_mock_context()
    logs = []
    if not api_key:
        task = plan_with_rules(user_input)
        logs.append({"tool": "gpt.runtime", "mode": "mock", "status": "skipped", "detail": "OPENAI_API_KEY 未配置，使用本地规则模拟 GPT JSON 输出"})
        return task, logs

    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "navigation_planner.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"user_input": user_input, "mock_context": context}, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    logs.append({"tool": "gpt.runtime", "mode": "live", "request": {"model": model, "input": user_input}})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
        text = raw.get("output_text")
        if not text:
            chunks = []
            for item in raw.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        chunks.append(content.get("text", ""))
            text = "\n".join(chunks)
        task = merge_rule_hints(normalize_task(_extract_json(text)), plan_with_rules(user_input))
        logs.append({"tool": "gpt.runtime", "status": "ok", "response_id": raw.get("id")})
        return task, logs
    except Exception as exc:  # keep demo usable even when credentials/network fail
        logs.append({"tool": "gpt.runtime", "status": "fallback", "error": str(exc), "detail": "GPT 调用失败，已回退到本地规则解析"})
        return plan_with_rules(user_input), logs


def plan_with_rules(user_input: str) -> dict:
    text = user_input.strip()
    compact_text = re.sub(r"\s+", "", text)
    task = _blank_task()

    if "外卖" in text:
        task["scenario_id"] = "delivery_after_arrival"
        task["destination"] = {"type": "memory_place", "name": "家"}
        task["external_actions"].append({"type": "delivery_order", "status": "mock", "trigger": "到家 ETA 计算后", "constraint": "送达时间晚于用户到家时间"})
        task["execution_plan"].append("先规划回家路线并计算 ETA，再把外卖送达时间设置为 ETA 之后")

    if "孩子" in text or "学校" in text:
        task["scenario_id"] = "school_then_work"
        task["waypoints"].append({"type": "memory_place", "name": "孩子学校"})
    if "回家" in text or "到家" in text:
        task["destination"] = {"type": "memory_place", "name": "家"}
    elif "火车" in text or "车站" in text or "高铁" in text:
        task["destination"] = {"type": "memory_place", "name": "上海虹桥站"}
    elif "公司" in text:
        task["destination"] = {"type": "memory_place", "name": "公司"}

    external_destination = _extract_external_destination(text)
    if external_destination:
        task["scenario_id"] = "intercity_trip" if task["scenario_id"] == "general_navigation" else task["scenario_id"]
        task["destination"] = {"type": "address", "name": external_destination}

    if external_destination and ("虹桥火车站" in text or "虹桥站" in text or "虹桥高铁站" in text):
        if not any(waypoint.get("name") == "上海虹桥站" for waypoint in task["waypoints"]):
            task["waypoints"].append({"type": "memory_place", "name": "上海虹桥站"})

    if external_destination and any(keyword in text for keyword in ("玩两天", "两天", "2天", "规划个行程", "规划行程", "旅游")):
        task["scenario_id"] = "travel_itinerary"
        task["destination"] = {"type": "address", "name": external_destination}
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = task["constraints"]["max_detour_minutes"] or 25
        for waypoint in (
            {"type": "poi", "name": "苏州酒店", "category": "住宿酒店"},
            {"type": "poi", "name": "旅游景点", "category": "旅游景点"},
            {"type": "poi", "name": "美食餐厅", "category": "美食"},
        ):
            if not any(item.get("category") == waypoint["category"] for item in task["waypoints"]):
                task["waypoints"].append(waypoint)
        task["external_actions"].extend(
            [
                {"type": "hotel_recommendation", "status": "demo_supported", "scope": external_destination},
                {"type": "travel_attraction_plan", "status": "demo_supported", "duration": "2天"},
                {"type": "meal_recommendation", "status": "demo_supported", "scope": "当地特色餐厅"},
                {"type": "return_trip_plan", "status": "demo_supported", "trigger": "第二天游玩结束后"},
            ]
        )
        task["execution_plan"].extend(
            [
                "出发 -> 上海虹桥站接朋友 -> 苏州",
                "Day 1：抵达后入住酒店，安排近距离景点和晚餐",
                "Day 2：安排核心景点、午餐和返程前缓冲",
                "返程：根据第二天结束时间生成回上海路线",
            ]
        )
        task["itinerary_plan"] = [
            {"day": "Day 1", "slot": "上午/中午", "plan": "从当前位置出发，先到上海虹桥站接朋友，再开往苏州。"},
            {"day": "Day 1", "slot": "下午", "plan": "抵达苏州后先办理入住，选择酒店周边或顺路景点轻量游玩。"},
            {"day": "Day 1", "slot": "晚上", "plan": "安排苏州本地特色晚餐，晚餐后回酒店休息。"},
            {"day": "Day 2", "slot": "上午", "plan": "游玩苏州代表性景点，优先选择离酒店和返程方向更顺的地点。"},
            {"day": "Day 2", "slot": "中午/下午", "plan": "安排午餐和第二个景点，预留返程前休息与取行李时间。"},
            {"day": "返程", "slot": "傍晚", "plan": "从最后一个景点或酒店出发，规划返回上海路线。"},
        ]

    if "万达" in text or "地铁口" in text or "哪里等" in text or "哪儿等" in text:
        task["scenario_id"] = "pickup_point_recommendation"
        task["destination"] = {"type": "memory_place", "name": "万达地铁口"}
        task["constraints"]["avoid_congestion"] = True
        task["external_actions"].append({"type": "pickup_point_recommendation", "status": "mock", "constraint": "上车点顺路、少掉头、易描述"})
        task["decision_points"].append("需要比较多个候选上车点的绕行成本和可描述性")
        task["clarification"] = "已模拟推荐顺路上车点；真实产品需接入上下车点候选能力"

    if "芜湖" in text or "高铁" in text or "二等座" in text or "靠过道" in text:
        task["scenario_id"] = "train_trip_booking"
        task["destination"] = {"type": "memory_place", "name": "上海虹桥站"}
        task["constraints"]["arrive_before"] = "08:30" if "马上" in text or "时间有点赶" in text else task["constraints"]["arrive_before"]
        task["external_actions"].append({"type": "train_ticket_search", "status": "mock", "preference": "二等座、靠过道", "buffer_minutes": 30})
        task["execution_plan"].append("先计算到高铁站 ETA 和 30 分钟进站缓冲，再筛选可赶上的高铁班次")
        task["need_user_confirm"] = True

    if "虹桥机场" in text or "接我老婆" in text or "接机" in text:
        task["scenario_id"] = "airport_pickup_multi_stop"
        if external_destination:
            if not any(waypoint.get("name") == "虹桥机场" for waypoint in task["waypoints"]):
                task["waypoints"].append({"type": "memory_place", "name": "虹桥机场"})
            task["destination"] = {"type": "address", "name": external_destination}
        else:
            task["destination"] = {"type": "memory_place", "name": "虹桥机场"}
        if any(keyword in text for keyword in ("礼物", "礼品", "伴手礼", "买个她")):
            task["waypoints"].append({"type": "poi", "name": "礼物店", "category": "礼品"})
        task["external_actions"].extend([
            {"type": "flight_status_lookup", "status": "mock", "output": "到达时间、航站楼"},
            {"type": "restaurant_recommendation", "status": "mock", "scope": "机场接到人后的目的地附近"},
            {"type": "relax_place_recommendation", "status": "mock", "scope": "餐后放松"},
        ])
        task["execution_plan"].extend(["当前 -> 礼物店 -> 虹桥机场", "接到人后 -> 餐厅 -> 放松场所"])
        task["constraints"]["avoid_congestion"] = True

    if "家长会" in text or "收拾一下行李" in text or "出差3天" in compact_text:
        task["scenario_id"] = "complex_day_itinerary"
        task["destination"] = {"type": "memory_place", "name": "虹桥机场"}
        task["waypoints"] = [
            {"type": "memory_place", "name": "孩子学校"},
            {"type": "memory_place", "name": "上海虹桥站"},
            {"type": "poi", "name": "早餐店", "category": "早餐"},
            {"type": "memory_place", "name": "公司"},
            {"type": "memory_place", "name": "徐汇客户"},
            {"type": "memory_place", "name": "家"},
        ]
        task["constraints"]["arrive_before"] = "07:40"
        task["constraints"]["avoid_congestion"] = True
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 8
        task["external_actions"].extend([
            {"type": "itinerary_scheduler", "status": "demo_supported", "trigger": "用户上车且上一段完成"},
            {"type": "online_checkin", "status": "mock", "buffer_minutes": 60},
            {"type": "meal_slot_planning", "status": "mock", "breakfast": "沿途", "lunch": "根据客户到达时间追问"},
        ])
        task["decision_points"].append("需要询问到客户处的目标时间，以决定午饭安排在公司到客户之间还是客户到学校之间")
        task["execution_plan"].extend([
            "当前 -> 学校 -> 高铁站 -> 公司，穿插早餐",
            "公司 -> 徐汇客户",
            "客户 -> 学校 -> 家",
            "家 -> 机场，并预留登机和值机时间",
        ])
        task["need_user_confirm"] = True

    if "咖啡" in text:
        task["waypoints"].append({"type": "poi", "name": "咖啡店", "category": "咖啡"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 8 if "别太绕" in text else 12
        task["scenario_id"] = "poi_along_route" if task["scenario_id"] == "general_navigation" else task["scenario_id"]
    if task["scenario_id"] != "travel_itinerary" and any(keyword in text for keyword in ("旅游景点", "景点", "逛逛", "游玩")):
        task["waypoints"].append({"type": "poi", "name": "旅游景点", "category": "旅游景点"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 15 if "别太绕" in text else 25
        task["scenario_id"] = "poi_along_route" if task["scenario_id"] == "general_navigation" else task["scenario_id"]
        task["external_actions"].append({"type": "online_place_search", "status": "demo_supported", "category": "旅游景点", "detail": "联网搜索沿途景点介绍与推荐理由"})
    if any(keyword in text for keyword in ("美食", "吃饭", "餐厅", "午饭", "晚饭")):
        meal_name = "美食餐厅"
        if "午饭" in text:
            meal_name = "午餐餐厅"
        elif "晚饭" in text:
            meal_name = "晚餐餐厅"
        task["waypoints"].append({"type": "poi", "name": meal_name, "category": "美食"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = task["constraints"]["max_detour_minutes"] or (10 if "别太绕" in text else 18)
        task["scenario_id"] = "poi_along_route" if task["scenario_id"] == "general_navigation" else task["scenario_id"]
        task["external_actions"].append({"type": "online_place_search", "status": "demo_supported", "category": "美食", "detail": "联网搜索沿途美食介绍与推荐理由"})
    if "加油" in text or "加个油" in text or "油站" in text:
        task["scenario_id"] = "fuel_on_way_home"
        task["waypoints"].append({"type": "poi", "name": "加油站", "category": "加油站"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 10
        task["external_actions"].append({"type": "fuel_price_news", "status": "mock", "detail": "查询油价新闻和优惠提醒"})
        task["execution_plan"].append("判断油量是否足够到家，再推荐沿途加油站")
    if "电量" in text or "充电" in text or "SOC" in text:
        task["scenario_id"] = "low_soc_charging_plan"
        task["destination"] = {"type": "memory_place", "name": "家"}
        task["waypoints"].append({"type": "poi", "name": "充电站", "category": "充电站"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 12
        task["external_actions"].extend([
            {"type": "energy_estimation", "status": "mock", "detail": "根据 SOC 和路线距离判断是否可达"},
            {"type": "charging_station_recommendation", "status": "mock", "ranking": "忙闲、价格、绕行时间"},
            {"type": "meal_recommendation", "status": "mock", "trigger": "充电等待期间"},
        ])
        task["execution_plan"].append("若电量不足，沿途推荐充电站并安排附近吃饭")
    if "堵" in text or "换一条" in text:
        task["constraints"]["avoid_congestion"] = True
        task["need_user_confirm"] = False
        if task["destination"]["name"] == "公司":
            task["clarification"] = "已按避开拥堵重新规划备选路线"
    if task["scenario_id"] != "complex_day_itinerary" and ("8点半" in compact_text or "8:30" in compact_text or "八点半" in compact_text):
        task["constraints"]["arrive_before"] = "08:30"
        task["destination"] = {"type": "memory_place", "name": "上海虹桥站"}
        task["need_user_confirm"] = False

    return normalize_task(task)


def _extract_external_destination(text: str) -> str | None:
    if "苏州" in text and "太湖" in text:
        return "苏州太湖旅游度假区"
    for city, address in EXTERNAL_DESTINATION_ALIASES.items():
        if city not in text:
            continue
        if not any(keyword in text for keyword in ("去", "到", "前往", "导航", "目的地", "旅游", "玩")):
            continue
        if city == "南京" and "南京大牌档" in text:
            continue
        return address
    return None


def normalize_task(task: dict) -> dict:
    merged = _blank_task()
    merged.update({k: v for k, v in task.items() if k in merged})
    merged["constraints"].update(task.get("constraints") or {})
    merged.setdefault("waypoints", [])
    return merged


def merge_rule_hints(task: dict, rule_task: dict) -> dict:
    """Keep live GPT parsing, but make product-demo scenario coverage deterministic."""
    if rule_task.get("scenario_id") and rule_task.get("scenario_id") != "general_navigation":
        task["scenario_id"] = rule_task["scenario_id"]
        task["origin"] = rule_task.get("origin", task["origin"])
        task["destination"] = rule_task.get("destination", task["destination"])
        task["waypoints"] = rule_task.get("waypoints", task.get("waypoints", []))
        task["constraints"].update(rule_task.get("constraints", {}))
        task["need_user_confirm"] = rule_task.get("need_user_confirm", task.get("need_user_confirm", True))
        task["clarification"] = rule_task.get("clarification")
    for field in ("execution_plan", "external_actions", "decision_points"):
        if rule_task.get(field):
            task[field] = rule_task[field]
    return normalize_task(task)
