from __future__ import annotations

import json
from pathlib import Path

from .amap_adapter import build_route
from .mock_context import get_mock_context
from .navigation_planner import plan_with_gpt
from .route_ranker import rank_routes


def main() -> None:
    cases_path = Path(__file__).resolve().parents[1] / "test_cases" / "navigation_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    context = get_mock_context()
    failures = []
    for case in cases:
        task, logs = plan_with_gpt(case["input"], context)
        routes, amap_logs = build_route(task, context)
        ranked = rank_routes(routes, task, context)
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
        print(f"PASS {case['id']}: {case['input']} -> {ranked[0]['title']} / {ranked[0]['reason']}")
    if failures:
        for case_id, message in failures:
            print(f"FAIL {case_id}: {message}")
        raise SystemExit(1)
    print(f"All {len(cases)} navigation cases passed.")


if __name__ == "__main__":
    main()
