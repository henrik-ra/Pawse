"""Pawse live server.

Serves the dashboard (app/) and a small live API that combines your real
Fitbit data with the calendar/meeting data and computes the Pawse Score.

Run it:

    python server.py

Then open http://localhost:8000 in your browser.

Endpoints:
    GET /                 -> the dashboard (app/index.html)
    GET /api/live-day     -> { score, label, reasons, recommendations, data }

Live Fitbit data is used automatically once you have run
``python devices/google_health/google_auth.py``; otherwise demo data is returned.
"""
from __future__ import annotations

import datetime as _dt
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from devices.google_health.google_health_client import get_daily_signals, prewarm
from devices.outlook.calendar_client import get_meetings
from scoring.pawse_score import score_day

_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "app"
_SAMPLE = _ROOT / "data" / "alex_workday.json"

PORT = 8000


def build_live_day(date: str | None = None) -> dict[str, Any]:
    """Merge live wearable signals into the workday and score it."""
    day = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    # Default to today so real (live) wearable data is pulled; the sample's
    # own date is only a fallback when there is no live connection.
    date = date or _dt.date.today().isoformat()

    signals = get_daily_signals(date)
    day["date"] = date
    # A wearable only counts as *connected* when it returns real (live) data.
    # Without a device the client returns demo data; we keep it for display but
    # must NOT let that fabricated biodata influence the Pawse Score.
    connected = signals.get("mode") == "live"
    # Pass through every metric the client computed (steps, resting/avg/peak HR,
    # HR zones, steps-by-hour, calories, distance, active minutes, SpO2, HRV, …)
    # while keeping the core keys the scorer relies on.
    wearable = {k: v for k, v in signals.items() if k != "cache_age_s"}
    wearable.setdefault("source", "google-health")
    wearable.setdefault("mode", "demo")
    day["wearable"] = wearable

    # Real calendar (meetings + breaks) for this date, pulled from Microsoft 365
    # via WorkIQ and cached. Falls back to the sample day when not cached.
    calendar = get_meetings(date)
    day["meetings"] = calendar["meetings"]
    day["breaks"] = calendar["breaks"]
    day["calendar_source"] = calendar["calendar_source"]

    # Only a connected wearable contributes biodata to the score. With no device
    # the day is scored from the calendar (and any opt-in voice/face) alone — the
    # scoring engine simply drops the missing biometric signals and renormalises.
    scored_day = day if connected else {k: v for k, v in day.items() if k != "wearable"}
    result = score_day(scored_day)
    result["data"] = day
    result["mode"] = day["wearable"]["mode"]
    result["wearable_connected"] = connected
    result["calendar_source"] = day["calendar_source"]
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
    # Start fetching today's live data right away so the first page load is fast.
    prewarm()
    handler = partial(_Handler, directory=str(_APP_DIR))
    with ThreadingHTTPServer(("localhost", PORT), handler) as httpd:
        print(f"Pawse running at http://localhost:{PORT}")
        print("API:           http://localhost:%d/api/live-day" % PORT)
        print("Warming live Fitbit data in the background\u2026")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
