from __future__ import annotations

import json
import os
import re
import urllib.request

from .mock_context import get_mock_context


DEFAULT_TASK = {
    "task_type": "navigation_planning",
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
        task = normalize_task(_extract_json(text))
        logs.append({"tool": "gpt.runtime", "status": "ok", "response_id": raw.get("id")})
        return task, logs
    except Exception as exc:  # keep demo usable even when credentials/network fail
        logs.append({"tool": "gpt.runtime", "status": "fallback", "error": str(exc), "detail": "GPT 调用失败，已回退到本地规则解析"})
        return plan_with_rules(user_input), logs


def plan_with_rules(user_input: str) -> dict:
    text = user_input.strip()
    task = _blank_task()

    if "孩子" in text or "学校" in text:
        task["waypoints"].append({"type": "memory_place", "name": "孩子学校"})
    if "回家" in text or "到家" in text:
        task["destination"] = {"type": "memory_place", "name": "家"}
    elif "火车" in text or "车站" in text or "高铁" in text:
        task["destination"] = {"type": "memory_place", "name": "上海虹桥站"}
    elif "公司" in text:
        task["destination"] = {"type": "memory_place", "name": "公司"}

    if "咖啡" in text:
        task["waypoints"].append({"type": "poi", "name": "咖啡店", "category": "咖啡"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 8 if "别太绕" in text else 12
    if "加油" in text or "加个油" in text or "油站" in text:
        task["waypoints"].append({"type": "poi", "name": "加油站", "category": "加油站"})
        task["constraints"]["poi_along_route"] = True
        task["constraints"]["max_detour_minutes"] = 10
    if "堵" in text or "换一条" in text:
        task["constraints"]["avoid_congestion"] = True
        task["need_user_confirm"] = False
        if task["destination"]["name"] == "公司":
            task["clarification"] = "已按避开拥堵重新规划备选路线"
    compact_text = re.sub(r"\s+", "", text)
    if "8点半" in compact_text or "8:30" in compact_text or "八点半" in compact_text:
        task["constraints"]["arrive_before"] = "08:30"
        task["destination"] = {"type": "memory_place", "name": "上海虹桥站"}
        task["need_user_confirm"] = False

    return normalize_task(task)


def normalize_task(task: dict) -> dict:
    merged = _blank_task()
    merged.update({k: v for k, v in task.items() if k in merged})
    merged["constraints"].update(task.get("constraints") or {})
    merged.setdefault("waypoints", [])
    return merged
