from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .amap_adapter import build_route as build_route_with_webservice
from .amap_skill_adapter import build_route as build_route_with_skill
from .itinerary_scheduler import scheduler
from .mock_context import get_mock_context
from .navigation_planner import plan_with_gpt
from .online_search_adapter import discover_places_with_model, enrich_routes_with_recommendations
from .planner_response import build_planner_reply
from .route_ranker import rank_routes


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_VERSION = os.getenv("APP_VERSION", "v2026.06.26")
APP_VERSION_DATE = os.getenv("APP_VERSION_DATE", "2026-06-26")
APP_COMMIT = (
    os.getenv("APP_COMMIT")
    or os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("VERCEL_GIT_COMMIT_SHA")
    or ""
)[:7]


def build_route(task: dict, context: dict) -> tuple[list[dict], list[dict]]:
    adapter = os.getenv("AMAP_ADAPTER", "webservice").strip().lower()
    if adapter in {"skill", "mcp", "skills"}:
        return build_route_with_skill(task, context)
    return build_route_with_webservice(task, context)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/context":
            return self._json(
                {
                    "context": get_mock_context(),
                    "amap_js_key": os.getenv("AMAP_JS_API_KEY", ""),
                    "amap_security_js_code": os.getenv("AMAP_SECURITY_JS_CODE", ""),
                    "amap_adapter": os.getenv("AMAP_ADAPTER", "webservice"),
                    "app": _app_meta(),
                }
            )
        if parsed.path == "/health":
            return self._json({"ok": True})
        if parsed.path == "/api/itinerary/status":
            return self._json(scheduler.status())
        path = FRONTEND / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if not path.resolve().is_relative_to(FRONTEND.resolve()) or not path.exists():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path in {"/api/itinerary/start", "/api/itinerary/event"}:
            return self._handle_itinerary_post(path)
        if path != "/api/plan":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            user_input = payload.get("user_input", "")
            context = get_mock_context()
            task, gpt_logs = plan_with_gpt(user_input, context)
            task, discovered_places, discovery_logs = discover_places_with_model(task, context, user_input)
            routes, amap_logs = build_route(task, context)
            ranked = rank_routes(routes, task, context)
            enriched, search_logs = enrich_routes_with_recommendations(task, ranked, context, user_input, discovered_places)
            self._json(
                {
                    "task": task,
                    "routes": enriched,
                    "reply": build_planner_reply(task, enriched),
                    "logs": [*gpt_logs, *discovery_logs, *amap_logs, *search_logs],
                    "context": context,
                    "amap_js_key": os.getenv("AMAP_JS_API_KEY", ""),
                    "amap_security_js_code": os.getenv("AMAP_SECURITY_JS_CODE", ""),
                    "amap_adapter": os.getenv("AMAP_ADAPTER", "webservice"),
                    "app": _app_meta(),
                }
            )
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def _handle_itinerary_post(self, path: str) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
            if path == "/api/itinerary/start":
                return self._json(scheduler.start_demo(payload.get("user_input", "")))
            return self._json(scheduler.event(payload.get("event_type", "")))
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        print(f"[api] {self.address_string()} {format % args}")


def _app_meta() -> dict:
    return {
        "name": "Carmind导航验证demo",
        "version": APP_VERSION,
        "version_date": APP_VERSION_DATE,
        "author": "阿晓",
        "commit": APP_COMMIT,
    }


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI + AMap Navigation Assistant running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
