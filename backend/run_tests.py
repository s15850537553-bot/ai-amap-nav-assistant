from __future__ import annotations

import json
from pathlib import Path

from .amap_adapter import build_route
from .mock_context import get_mock_context
from .navigation_planner import plan_with_gpt
from .online_search_adapter import discover_places_with_model, enrich_routes_with_recommendations
from .route_ranker import rank_routes


def main() -> None:
    cases_path = Path(__file__).resolve().parents[1] / "test_cases" / "navigation_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    context = get_mock_context()
    failures = []
    for case in cases:
        task, logs = plan_with_gpt(case["input"], context)
        task, discovered_places, discovery_logs = discover_places_with_model(task, context, case["input"])
        routes, amap_logs = build_route(task, context)
        ranked = rank_routes(routes, task, context)
        ranked, search_logs = enrich_routes_with_recommendations(task, ranked, context, case["input"], discovered_places)
        if task["task_type"] != "navigation_planning":
            failures.append((case["id"], "task_type mismatch"))
        if not ranked:
            failures.append((case["id"], "no routes"))
        for key, expected in case.get("expect", {}).items():
            actual = task
            for part in key.split("."):
                actual = actual[part]
            if actual != expected:
                failures.append((case["id"], f"{key}: expected {expected!r}, got {actual!r}"))
        if "min_external_actions" in case:
            actual_count = len(task.get("external_actions", []))
            if actual_count < case["min_external_actions"]:
                failures.append((case["id"], f"external_actions: expected at least {case['min_external_actions']}, got {actual_count}"))
        if "min_execution_plan" in case:
            actual_count = len(task.get("execution_plan", []))
            if actual_count < case["min_execution_plan"]:
                failures.append((case["id"], f"execution_plan: expected at least {case['min_execution_plan']}, got {actual_count}"))
        if "min_recommendations" in case:
            actual_count = len(ranked[0].get("recommendations", []))
            if actual_count < case["min_recommendations"]:
                failures.append((case["id"], f"recommendations: expected at least {case['min_recommendations']}, got {actual_count}"))
        print(f"PASS {case['id']}: {case['input']} -> {ranked[0]['title']} / {ranked[0]['reason']}")
    if failures:
        for case_id, message in failures:
            print(f"FAIL {case_id}: {message}")
        raise SystemExit(1)
    print(f"All {len(cases)} navigation cases passed.")


if __name__ == "__main__":
    main()
