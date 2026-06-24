from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def get_mock_context() -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return {
        "home": {
            "name": "家",
            "address": "上海市浦东新区世纪大道100号",
            "location": "121.506377,31.245105",
        },
        "company": {
            "name": "公司",
            "address": "上海市徐汇区漕河泾开发区宜山路900号",
            "location": "121.397832,31.176559",
        },
        "child_school": {
            "name": "孩子学校",
            "address": "上海市浦东新区丁香路910号",
            "location": "121.557404,31.224745",
        },
        "train_station": {
            "name": "上海虹桥站",
            "address": "上海市闵行区申贵路1500号",
            "location": "121.320997,31.19491",
        },
        "vehicle": {
            "current_location": {
                "name": "当前车辆位置",
                "address": "上海市浦东新区陆家嘴环路1000号",
                "location": "121.499809,31.239666",
            },
            "fuel_percent": 28,
            "soc_percent": 42,
        },
        "current_time": now.isoformat(timespec="minutes"),
    }


def resolve_place(place: dict | None, context: dict | None = None) -> dict:
    context = context or get_mock_context()
    if not place:
        return context["vehicle"]["current_location"]

    place_type = place.get("type")
    name = (place.get("name") or "").lower()
    aliases = {
        "home": context["home"],
        "家": context["home"],
        "company": context["company"],
        "公司": context["company"],
        "child_school": context["child_school"],
        "学校": context["child_school"],
        "孩子学校": context["child_school"],
        "train_station": context["train_station"],
        "火车站": context["train_station"],
        "上海虹桥站": context["train_station"],
    }

    if place_type == "current_location":
        return context["vehicle"]["current_location"]

    return aliases.get(name, {"name": place.get("name") or "未命名地点", "address": place.get("name") or "", "location": place.get("location")})
