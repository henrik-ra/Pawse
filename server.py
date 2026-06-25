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
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from devices.outlook.calendar_client import _derive_meetings, get_meetings
from scoring.meeting_optimizer import recommend as recommend_meetings
from scoring.pawse_score import score_day

# Pick the wearable source. Defaults to Google Health (Fitbit / Pixel Watch);
# set PAWSE_WEARABLE=xiaomi to read a Xiaomi watch instead. The chosen
# module just has to expose get_daily_signals(date) + prewarm().
_WEARABLE = (os.environ.get("PAWSE_WEARABLE") or "google-health").strip().lower()
if _WEARABLE == "xiaomi":
    from devices.xiaomi.xiaomi_client import get_daily_signals, prewarm
else:
    from devices.google_health.google_health_client import get_daily_signals, prewarm

_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "app"
_SAMPLE = _ROOT / "data" / "alex_workday.json"

PORT = 8000

# Actions the user applied from the dashboard (move a meeting, protect lunch …).
# Stored locally so the change is reflected everywhere — the Pawse Score, the
# tiles and the Rebalance card all recompute as if the calendar had really
# changed. Delete the file (or POST /api/reset-actions) to reset for a new take.
_ACTIONS_PATH = _ROOT / "data" / ".applied_actions.json"
_MOVE_TYPES = {"move_after_hours", "reschedule", "add_buffer"}


def _load_actions() -> dict[str, list[dict[str, Any]]]:
    try:
        return json.loads(_ACTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_actions(store: dict[str, list[dict[str, Any]]]) -> None:
    _ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ACTIONS_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _record_action(date: str, action: dict[str, Any]) -> None:
    store = _load_actions()
    day = store.setdefault(date, [])
    key = (action.get("type"), action.get("title"))
    day[:] = [a for a in day if (a.get("type"), a.get("title")) != key]
    day.append(action)
    _save_actions(store)


def _clear_actions(date: str | None = None) -> None:
    if date is None:
        _save_actions({})
        return
    store = _load_actions()
    store.pop(date, None)
    _save_actions(store)


def _apply_actions(
    meetings: list[dict[str, Any]], breaks: dict[str, Any], date: str
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Reflect the user's applied actions in the day's meetings + breaks.

    Moves rewrite the meeting's start/end (flags are re-derived so back-to-back /
    after-hours and the Pawse Score recompute); lunch holds mark the break as
    protected. Returns ``(meetings, breaks, applied)``.
    """
    actions = _load_actions().get(date, [])
    if not actions:
        return meetings, breaks, []

    raw = [
        {"title": m["title"], "start": m["start"], "end": m["end"],
         "is_blocker": m.get("is_blocker", False)}
        for m in meetings
    ]
    breaks = dict(breaks or {})
    applied: list[dict[str, Any]] = []
    for a in actions:
        kind = a.get("type")
        if kind in _MOVE_TYPES and a.get("to") and a.get("end"):
            for r in raw:
                if r["title"] == a.get("title"):
                    r["start"], r["end"] = a["to"], a["end"]
                    applied.append(a)
                    break
        elif kind == "protect_lunch":
            breaks["lunch_break"] = True
            applied.append(a)
        elif kind == "protect_focus":
            applied.append(a)

    return _derive_meetings(raw), breaks, applied


def build_live_day(date: str | None = None) -> dict[str, Any]:
    """Merge live wearable signals into the workday and score it."""
    day = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    # Default to today so real (live) wearable data is pulled; the sample's
    # own date is only a fallback when there is no live connection.
    date = date or _dt.date.today().isoformat()

    signals = get_daily_signals(date)
    day["date"] = date
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
    meetings, breaks, applied = _apply_actions(
        calendar["meetings"], calendar["breaks"], date
    )
    day["meetings"] = meetings
    day["breaks"] = breaks
    day["calendar_source"] = calendar["calendar_source"]
    day["applied_actions"] = applied

    result = score_day(day)
    result["data"] = day
    result["mode"] = day["wearable"]["mode"]
    result["calendar_source"] = day["calendar_source"]
    return result


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/api/live-day"):
            self._serve_live_day()
            return
        if self.path.startswith("/api/recommendations"):
            self._serve_recommendations()
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/api/apply"):
            self._apply_action()
            return
        if self.path.startswith("/api/reset-actions"):
            self._reset_actions()
            return
        self.send_response(404)
        self.end_headers()

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

    def _serve_recommendations(self) -> None:
        """Reschedule recommendations for a day (powers the Cowork skill too)."""
        try:
            date = None
            if "?" in self.path:
                from urllib.parse import parse_qs, urlparse

                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            day = build_live_day(date)
            data = day.get("data", {})
            recs = recommend_meetings(
                data.get("meetings", []),
                date=data.get("date") or date,
                score=day.get("pawse_score"),
            )
            body = json.dumps(
                {"date": data.get("date"), "recommendations": recs}
            ).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def _apply_action(self) -> None:
        """Record a one-click action from the dashboard and recompute the day."""
        try:
            payload = self._read_json_body()
            date = payload.get("date") or _dt.date.today().isoformat()
            action = {
                "type": payload.get("type"),
                "title": payload.get("title"),
                "from": payload.get("from"),
                "to": payload.get("to"),
                "end": payload.get("end"),
            }
            _record_action(date, action)
            day = build_live_day(date)
            self._write_json({
                "ok": True,
                "date": date,
                "applied": action,
                "pawse_score": day.get("pawse_score"),
                "label": day.get("label"),
            })
        except Exception as exc:
            self._write_json({"ok": False, "error": str(exc)}, status=500)

    def _reset_actions(self) -> None:
        try:
            payload = self._read_json_body()
            _clear_actions(payload.get("date"))
            self._write_json({"ok": True})
        except Exception as exc:
            self._write_json({"ok": False, "error": str(exc)}, status=500)

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
