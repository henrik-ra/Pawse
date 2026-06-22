"""Pawse mock server.

Serves the dashboard (app/) and a small API that scores the bundled sample
workday from ``data/alex_workday.json``. This is the offline/demo backend;
live wearable and calendar integrations are wired in later.

Run it:

    python server.py

Then open http://localhost:8000 in your browser.

Endpoints:
    GET /                 -> the dashboard (app/index.html)
    GET /api/live-day     -> { pawse_score, label, reasons, recommendations, data }
"""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scoring.pawse_score import score_day

_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "app"
_SAMPLE = _ROOT / "data" / "alex_workday.json"

PORT = 8000


def build_live_day(date: str | None = None) -> dict[str, Any]:
    """Score the bundled sample workday (demo data)."""
    day = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    if date:
        day["date"] = date

    result = score_day(day)
    result["data"] = day
    result["mode"] = "demo"
    return result


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/api/live-day"):
            self._serve_live_day()
            return
        super().do_GET()

    def _serve_live_day(self) -> None:
        try:
            # Optional ?date=YYYY-MM-DD override.
            date = None
            if "?" in self.path:
                from urllib.parse import parse_qs, urlparse

                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            body = json.dumps(build_live_day(date)).encode("utf-8")
            self.send_response(200)
        except Exception as exc:  # surface errors to the browser console
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass  # browser navigated away / refreshed mid-response — ignore

    def log_message(self, fmt, *args):  # noqa: N802 (http.server API)
        pass  # quiet access log; errors still print


def main() -> None:
    handler = partial(_Handler, directory=str(_APP_DIR))
    with ThreadingHTTPServer(("localhost", PORT), handler) as httpd:
        print(f"Pawse running at http://localhost:{PORT}")
        print("API:           http://localhost:%d/api/live-day" % PORT)
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
