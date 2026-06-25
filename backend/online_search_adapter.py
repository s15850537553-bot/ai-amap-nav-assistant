from __future__ import annotations

import json
import os
import re
import urllib.request
from copy import deepcopy
from html import unescape
from urllib.parse import quote_plus


RECOMMENDATION_KEYWORDS = {
    "景点": "旅游景点",
    "旅游": "旅游景点",
    "逛": "旅游景点",
    "玩": "旅游景点",
    "美食": "美食",
    "餐厅": "餐厅",
    "吃饭": "餐厅",
    "午饭": "午餐",
    "晚饭": "晚餐",
    "早餐": "早餐",
    "早饭": "早餐",
    "咖啡": "咖啡",
    "放松": "休闲放松",
    "礼物": "礼物店",
    "酒店": "住宿酒店",
    "住宿": "住宿酒店",
}


def enrich_routes_with_recommendations(
    task: dict,
    routes: list[dict],
    context: dict,
    user_input: str = "",
    discovered_places: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    needs = _recommendation_needs(task, user_input)
    if not needs and not discovered_places:
        return routes, []

    logs: list[dict] = []
    live_items = discovered_places or []
    enriched = []
    for route in routes:
        copied = deepcopy(route)
        recommendations = live_items or _recommendations_from_route_places(copied, needs)
        recommendations = recommendations or _search_with_duckduckgo(needs, task, context, user_input, logs)
        if not recommendations:
            recommendations = _unavailable_recommendations(needs)
        elif len(recommendations) < len(needs):
            recommendations = [
                *recommendations,
                *_unavailable_recommendations(needs[len(recommendations) :]),
            ]
        copied["recommendations"] = _match_route_places(copied, recommendations)
        enriched.append(copied)
    logs.append(
        {
            "tool": "online.search.place_recommendation",
            "status": "ok",
            "mode": _recommendation_mode(enriched),
            "request": needs,
            "result_count": len(enriched[0].get("recommendations", [])) if enriched else 0,
        }
    )
    return enriched, logs


def discover_places_with_model(task: dict, context: dict, user_input: str) -> tuple[dict, list[dict], list[dict]]:
    needs = _recommendation_needs(task, user_input)
    if not needs:
        return task, [], []

    logs: list[dict] = []
    provider = os.getenv("PLACE_SEARCH_PROVIDER", "qwen").strip().lower()
    candidates: list[dict] = []
    if provider in {"qwen", "dashscope", "qianwen"}:
        candidates = _search_with_qwen(needs, task, context, user_input, logs)
    elif provider == "openai":
        candidates = _search_with_openai(needs, task, context, user_input, logs)

    if not candidates:
        logs.append(
            {
                "tool": "place_discovery.model_search",
                "status": "unavailable",
                "provider": provider,
                "detail": "未拿到联网模型候选地点，保留原始 POI 类型给高德兜底校验",
            }
        )
        return task, [], logs

    updated = deepcopy(task)
    poi_indexes = [index for index, waypoint in enumerate(updated.get("waypoints", [])) if waypoint.get("type") == "poi"]
    if not poi_indexes:
        updated["waypoints"] = list(updated.get("waypoints", []))

    selected_places = []
    for index, need in enumerate(needs):
        grouped_candidates = _candidates_for_need(candidates, need)
        primary = grouped_candidates[0] if grouped_candidates else {
            "name": need.get("keyword") or need.get("category") or "推荐地点",
            "category": need.get("category") or "推荐地点",
            "source_title": provider,
        }
        waypoint = {
            "type": "poi",
            "name": primary.get("name") or primary.get("keyword") or primary.get("category") or "推荐地点",
            "category": primary.get("category") or need.get("category") or "推荐地点",
            "discovered_by": primary.get("source_title") or provider,
            "amap_candidate_names": [item.get("name") for item in grouped_candidates[:3] if item.get("name")],
        }
        if grouped_candidates:
            waypoint["discovered_candidates"] = [
                {
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "source_title": item.get("source_title"),
                }
                for item in grouped_candidates[:3]
            ]
            selected_places.append(primary)
        if index < len(poi_indexes):
            updated["waypoints"][poi_indexes[index]] = waypoint
        else:
            updated["waypoints"].append(waypoint)

    updated.setdefault("constraints", {})
    updated["constraints"]["poi_along_route"] = True
    logs.append(
        {
            "tool": "place_discovery.model_search",
            "status": "ok",
            "provider": provider,
            "result_count": len(candidates),
            "selected_count": len(selected_places),
            "candidates": [{"name": item.get("name"), "category": item.get("category"), "source": item.get("source_title")} for item in candidates],
        }
    )
    return updated, selected_places, logs


def _recommendation_mode(routes: list[dict]) -> str:
    items = routes[0].get("recommendations", []) if routes else []
    if not items:
        return "unavailable"
    if any(item.get("source_url") for item in items):
        return "web-html"
    if any("千问" in (item.get("source_title") or "") or "OpenAI" in (item.get("source_title") or "") for item in items):
        return "model-search"
    if any(item.get("source_title") == "高德 Web Service POI 搜索" for item in items):
        return "amap-poi"
    return "unavailable"


def _recommendation_needs(task: dict, user_input: str) -> list[dict]:
    needs = []
    text = user_input or ""
    for place in (task.get("origin"), task.get("destination")):
        if place and place.get("type") == "poi":
            category = place.get("category") or place.get("name") or "推荐地点"
            if not _has_category(needs, category):
                needs.append({"category": category, "keyword": place.get("name") or category, "source": "navigation_task"})
    for waypoint in task.get("waypoints", []):
        if waypoint.get("type") == "poi":
            category = waypoint.get("category") or waypoint.get("name") or "推荐地点"
            if not _has_category(needs, category):
                needs.append({"category": category, "keyword": waypoint.get("name") or category, "source": "navigation_task"})

    for keyword, category in RECOMMENDATION_KEYWORDS.items():
        if keyword in text and not _has_category(needs, category):
            needs.append({"category": category, "keyword": keyword, "source": "user_input"})

    return needs[:4]


def _candidates_for_need(candidates: list[dict], need: dict) -> list[dict]:
    grouped = []
    need_category = need.get("category") or need.get("keyword") or ""
    for item in candidates:
        item_category = item.get("category") or ""
        item_group = _category_group(item_category) if item_category else _category_group(_candidate_text(item))
        if item_group == _category_group(need_category):
            grouped.append(item)
    return grouped[:5]


def _candidate_text(item: dict) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("name", "category", "intro", "why", "source_title")
    )


def _has_category(needs: list[dict], category: str) -> bool:
    return any(_category_group(item.get("category") or item.get("keyword") or "") == _category_group(category) for item in needs)


def _category_group(category: str) -> str:
    if any(key in category for key in ("酒店", "住宿", "民宿", "客栈")):
        return "hotel"
    if any(key in category for key in ("美食", "餐", "午", "晚", "早")):
        return "meal"
    if any(key in category for key in ("景点", "旅游", "逛", "玩", "太湖", "古村", "观景", "景观", "木栈道", "湿地", "公园", "岛")):
        return "tour"
    if "咖啡" in category:
        return "coffee"
    if "礼" in category:
        return "gift"
    return category


def _search_with_openai(needs: list[dict], task: dict, context: dict, user_input: str, logs: list[dict]) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logs.append({"tool": "openai.web_search", "mode": "live", "status": "skipped", "detail": "OPENAI_API_KEY 未配置，改用公开网页搜索兜底"})
        return []


def _search_with_qwen(needs: list[dict], task: dict, context: dict, user_input: str, logs: list[dict]) -> list[dict]:
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not api_key:
        logs.append({"tool": "qwen.web_search", "mode": "live", "status": "skipped", "detail": "DASHSCOPE_API_KEY 未配置，无法先用千问联网搜索候选地点"})
        return []

    model = os.getenv("QWEN_MODEL", "qwen-plus-latest")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是车载导航助手的联网地点发现模块。必须先联网搜索真实地点，"
                    "再返回严格 JSON，不要编造不存在的店。每个需求推荐 2-3 个候选地点，按优先级排序；"
                    "后续系统会逐个用高德 POI 校验，只有都搜不到才用高德泛类兜底。"
                    "JSON 格式：{\"recommendations\":[{\"name\":\"真实地点名\",\"category\":\"\","
                    "\"intro\":\"基于联网资料的简短介绍\",\"why\":\"为什么适合本次路线和用户偏好\","
                    "\"source_title\":\"资料来源标题\",\"source_url\":\"资料来源URL\"}]}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_input": user_input,
                        "needs": needs,
                        "city": "上海",
                        "origin": task.get("origin"),
                        "destination": task.get("destination"),
                        "route_context": task.get("waypoints", []),
                        "mock_context": context,
                        "instruction": "请先搜索真实地点，每个推荐需求给出2-3个候选；地点名尽量使用高德/大众点评/携程/官方常见名称，便于后续高德 POI 校验。",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "enable_search": True,
        "search_options": {
            "search_strategy": "turbo",
            "forced_search": True,
            "intention_options": {"prompt_intervene": "优先搜索中国大陆中文网页、点评攻略、商场/景点/餐厅官方信息"},
        },
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    logs.append({"tool": "qwen.web_search", "mode": "live", "request": {"model": model, "needs": needs}})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _extract_json(content)
        items = parsed.get("recommendations", [])
        desired_count = max(len(needs) * 2, 3 if any(word in user_input for word in ("几个", "多个", "几家")) else len(needs) * 2)
        if len(items) < desired_count:
            more_items = _retry_qwen_for_more_candidates(api_key, model, needs, task, context, user_input, items, logs)
            items = _merge_candidate_items(items, more_items)
        logs.append({"tool": "qwen.web_search", "status": "ok", "request_id": raw.get("request_id") or raw.get("id"), "result_count": len(items)})
        return [_normalize_item(item, "千问联网搜索") for item in items[:12]]
    except Exception as exc:
        logs.append({"tool": "qwen.web_search", "status": "fallback", "error": str(exc), "detail": "千问联网搜索失败，未使用 Mock 地点"})
        return []

    model = os.getenv("OPENAI_WEB_SEARCH_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "tools": [{"type": "web_search"}],
        "input": [
            {
                "role": "system",
                "content": (
                    "你是车载导航助手的地点推荐模块。请联网搜索并返回严格 JSON。"
                    "只推荐适合沿途短暂停留的地点，输出 1-4 个结果。"
                    "JSON 格式：{\"recommendations\":[{\"name\":\"\",\"category\":\"\","
                    "\"intro\":\"\",\"why\":\"\",\"source_title\":\"\",\"source_url\":\"\"}]}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_input": user_input,
                        "needs": needs,
                        "origin": task.get("origin"),
                        "destination": task.get("destination"),
                        "waypoints": task.get("waypoints", []),
                        "city": "上海",
                        "mock_context": context,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    logs.append({"tool": "openai.web_search", "mode": "live", "request": {"model": model, "needs": needs}})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = json.loads(response.read().decode("utf-8"))
        text = raw.get("output_text") or _collect_response_text(raw)
        parsed = _extract_json(text)
        items = parsed.get("recommendations", [])
        logs.append({"tool": "openai.web_search", "status": "ok", "response_id": raw.get("id"), "result_count": len(items)})
        return [_normalize_item(item, "OpenAI Web Search") for item in items[:4]]
    except Exception as exc:
        logs.append({"tool": "openai.web_search", "status": "fallback", "error": str(exc), "detail": "OpenAI 联网搜索失败，改用公开网页搜索兜底"})
        return []


def _retry_qwen_for_more_candidates(api_key: str, model: str, needs: list[dict], task: dict, context: dict, user_input: str, existing_items: list[dict], logs: list[dict]) -> list[dict]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是车载导航助手的候选地点补充搜索模块。请联网搜索并补齐候选。"
                    "只返回真实地点，不要返回机场、车站等非用户要求推荐的途经点。"
                    "每个需求至少补充2个可导航地点，返回严格 JSON："
                    "{\"recommendations\":[{\"name\":\"真实地点名\",\"category\":\"\",\"intro\":\"\",\"why\":\"\",\"source_title\":\"\",\"source_url\":\"\"}]}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_input": user_input,
                        "needs": needs,
                        "destination": task.get("destination"),
                        "route_context": task.get("waypoints", []),
                        "existing_items": [{"name": item.get("name"), "category": item.get("category")} for item in existing_items],
                        "mock_context": context,
                        "instruction": "请补充不同于 existing_items 的真实推荐地点，地点名优先使用高德/携程/大众点评常见名称。",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "enable_search": True,
        "search_options": {
            "search_strategy": "turbo",
            "forced_search": True,
            "intention_options": {"prompt_intervene": "优先搜索中国大陆中文攻略、官方景区、点评/地图常见地点名称"},
        },
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    logs.append({"tool": "qwen.web_search.expand_candidates", "mode": "live", "request": {"model": model, "needs": needs}})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        items = _extract_json(content).get("recommendations", [])
        logs.append({"tool": "qwen.web_search.expand_candidates", "status": "ok", "request_id": raw.get("request_id") or raw.get("id"), "result_count": len(items)})
        return items
    except Exception as exc:
        logs.append({"tool": "qwen.web_search.expand_candidates", "status": "fallback", "error": str(exc)})
        return []


def _merge_candidate_items(items: list[dict], more_items: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for item in [*items, *more_items]:
        name = (item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        merged.append(item)
    return merged


def _search_with_duckduckgo(needs: list[dict], task: dict, context: dict, user_input: str, logs: list[dict]) -> list[dict]:
    items = []
    route_hint = _route_hint(task, context)
    for need in needs:
        category = need.get("category") or need.get("keyword") or "推荐地点"
        query = f"上海 {route_hint} 附近 {category} 推荐 介绍"
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        logs.append({"tool": "web.search.duckduckgo", "mode": "live", "request": {"query": query}})
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                },
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                html = response.read().decode("utf-8", errors="ignore")
            result = _parse_duckduckgo_result(html)
            if result:
                items.append(
                    {
                        "name": result["title"] or category,
                        "category": category,
                        "intro": result["snippet"] or "已通过公开网页搜索获取候选资料。",
                        "why": f"用户要求沿途推荐{category}，系统结合路线方向和绕行约束，把该类地点作为候选停靠点。",
                        "source_title": result["title"] or "DuckDuckGo Search Result",
                        "source_url": result["url"],
                    }
                )
                logs.append({"tool": "web.search.duckduckgo", "status": "ok", "result": result["title"]})
            else:
                logs.append({"tool": "web.search.duckduckgo", "status": "empty", "query": query})
        except Exception as exc:
            logs.append({"tool": "web.search.duckduckgo", "status": "fallback", "error": str(exc), "query": query})
    return items[:4]


def _route_hint(task: dict, context: dict) -> str:
    names = []
    for place in [task.get("origin"), *task.get("waypoints", []), task.get("destination")]:
        if not place:
            continue
        if place.get("type") == "memory_place":
            names.append(place.get("name", ""))
        elif place.get("type") == "poi":
            names.append(place.get("name") or place.get("category") or "")
    return " ".join(name for name in names if name) or "沿途"


def _parse_duckduckgo_result(html: str) -> dict | None:
    blocks = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>)', html, re.S)
    for href, title_html, snippet_a, snippet_div in blocks:
        title = _strip_tags(title_html)
        snippet = _strip_tags(snippet_a or snippet_div)
        url = unescape(href)
        if title and url:
            return {"title": title, "snippet": snippet, "url": url}
    return None


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _collect_response_text(raw: dict) -> str:
    chunks = []
    for item in raw.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "\n".join(chunks)


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return {"recommendations": []}
        return json.loads(match.group(0))


def _normalize_item(item: dict, default_source: str) -> dict:
    return {
        "name": item.get("name") or "推荐地点",
        "category": item.get("category") or "推荐",
        "intro": item.get("intro") or "适合沿途短暂停留。",
        "why": item.get("why") or "与当前路线方向匹配，绕行成本较低。",
        "source_title": item.get("source_title") or default_source,
        "source_url": item.get("source_url") or "",
    }


def _unavailable_recommendations(needs: list[dict]) -> list[dict]:
    provider = os.getenv("PLACE_SEARCH_PROVIDER", "qwen").strip().lower()
    key_hint = "DASHSCOPE_API_KEY" if provider in {"qwen", "dashscope", "qianwen"} else "OPENAI_API_KEY"
    return [
        {
            "name": f"{need.get('category') or need.get('keyword') or '推荐地点'}：未完成真实联网搜索",
            "category": need.get("category") or "推荐",
            "intro": "当前没有拿到公开网页搜索结果，系统不会使用 Mock 店家介绍代替真实结果。",
            "why": f"请检查 {key_hint}、模型联网搜索权限或服务器网络后重新规划。",
            "source_title": "真实联网搜索未完成",
            "source_url": "",
            "search_status": "unavailable",
        }
        for need in needs[:4]
    ]


def _recommendations_from_route_places(route: dict, needs: list[dict]) -> list[dict]:
    items = []
    route_places = []
    destination = route.get("destination") or {}
    if destination.get("category") or _match_need_category(destination.get("name", ""), needs):
        route_places.append(destination)
    route_places.extend(route.get("waypoints", []))

    for place in route_places:
        if not place.get("location") or place.get("status") == "unresolved":
            continue
        category = place.get("category") or _match_need_category(place.get("name", ""), needs)
        address = place.get("address") or "暂无地址"
        items.append(
            {
                "name": place.get("name") or category or "沿途地点",
                "category": category or "推荐地点",
                "intro": f"这是高德 Web Service 实时 POI 搜索返回的沿途候选点，地址：{address}。",
                "why": "该地点位于当前路线搜索半径内，可作为沿途停靠候选；实际产品可继续叠加评分、营业状态和用户偏好。",
                "source_title": "高德 Web Service POI 搜索",
                "source_url": "",
                "route_place_name": place.get("name"),
                "address": place.get("address", ""),
                "location": place.get("location", ""),
            }
        )
    return items[: max(1, len(needs))]


def _match_need_category(name: str, needs: list[dict]) -> str:
    for need in needs:
        keyword = need.get("keyword") or ""
        if keyword and keyword in name:
            return need.get("category") or keyword
    return needs[0].get("category", "") if needs else ""


def _match_route_places(route: dict, recommendations: list[dict]) -> list[dict]:
    waypoints = [waypoint for waypoint in route.get("waypoints", []) if waypoint.get("category") or waypoint.get("original_keyword")]
    matched = []
    for index, item in enumerate(recommendations):
        copied = deepcopy(item)
        if index < len(waypoints):
            waypoint = waypoints[index]
            copied["route_place_name"] = waypoint.get("name")
            copied["address"] = waypoint.get("address", "")
            copied["location"] = waypoint.get("location", "")
            copied["amap_match_status"] = "matched" if waypoint.get("location") else "unmatched"
        matched.append(copied)
    return matched
