from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .amap_adapter import build_route as build_route_with_webservice
from .amap_skill_adapter import build_route as build_route_with_skill
from .mock_context import get_mock_context
from .navigation_planner import plan_with_gpt
from .route_ranker import rank_routes


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


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
                }
            )
        if parsed.path == "/health":
            return self._json({"ok": True})
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
        if urlparse(self.path).path != "/api/plan":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            user_input = payload.get("user_input", "")
            context = get_mock_context()
            task, gpt_logs = plan_with_gpt(user_input, context)
            routes, amap_logs = build_route(task, context)
            ranked = rank_routes(routes, task, context)
            self._json(
                {
                    "task": task,
                    "routes": ranked,
                    "logs": [*gpt_logs, *amap_logs],
                    "context": context,
                    "amap_js_key": os.getenv("AMAP_JS_API_KEY", ""),
                    "amap_security_js_code": os.getenv("AMAP_SECURITY_JS_CODE", ""),
                    "amap_adapter": os.getenv("AMAP_ADAPTER", "webservice"),
                }
            )
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


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI + AMap Navigation Assistant running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
