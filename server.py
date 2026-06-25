"""Pawse live server.

Serves the dashboard (app/) and a small live API that combines your real
Fitbit data with the calendar/meeting data and computes the Pawse Score.

Run it:

    python server.py

Then open http://localhost:8000 in your browser.

Endpoints:
    GET /                 -> the dashboard (app/index.html)
    GET /api/live-day     -> { score, label, reasons, recommendations, data }
    GET /api/calendar/day?date=YYYY-MM-DD -> calendar events with full metadata
    POST /api/meetings/{id}/availability  -> find alternative time slots
    POST /api/meetings/{id}/reschedule    -> reschedule (organizer + confirmed only)
    POST /api/meetings/{id}/draft-reschedule-request -> draft email for non-organizers

Live Fitbit data is used automatically once you have run
``python devices/google_health/google_auth.py``; otherwise demo data is returned.

Microsoft 365 calendar features work after running
``python devices/outlook/ms_auth.py``.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from devices.google_health.google_health_client import get_daily_signals, prewarm
from devices.outlook.calendar_client import get_meetings
from devices.outlook.graph_calendar import (
    GraphAPIError,
    GraphAuthError,
    MeetingPermissionError,
    create_reschedule_request_draft,
    find_available_times,
    get_calendar_events,
    get_reschedule_request_text,
    reschedule_meeting,
)
from scoring.meeting_scorer import recommend as scorer_recommend
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
        if self.path.startswith("/api/calendar/day"):
            self._serve_calendar_day()
            return
        if self.path.startswith("/api/recommendations"):
            self._serve_recommendations()
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        # Route: POST /api/meetings/{id}/availability
        m = re.match(r"/api/meetings/([^/]+)/availability", self.path)
        if m:
            self._serve_availability(m.group(1))
            return
        # Route: POST /api/meetings/{id}/reschedule
        m = re.match(r"/api/meetings/([^/]+)/reschedule", self.path)
        if m:
            self._serve_reschedule(m.group(1))
            return
        # Route: POST /api/meetings/{id}/draft-reschedule-request
        m = re.match(r"/api/meetings/([^/]+)/draft-reschedule-request", self.path)
        if m:
            self._serve_draft_reschedule_request(m.group(1))
            return
        self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):  # noqa: N802 (CORS preflight)
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}

    def _serve_live_day(self) -> None:
        try:
            date = None
            if "?" in self.path:
                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            self._send_json(build_live_day(date))
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_calendar_day(self) -> None:
        """GET /api/calendar/day?date=YYYY-MM-DD — full meeting metadata from Graph."""
        try:
            date = None
            if "?" in self.path:
                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            if not date:
                date = _dt.date.today().isoformat()

            meetings = get_calendar_events(date)
            self._send_json({
                "date": date,
                "meetings": [asdict(m) for m in meetings],
                "count": len(meetings),
            })
        except GraphAuthError as e:
            self._send_json({"error": str(e), "code": "auth_required"}, 401)
        except GraphAPIError as e:
            self._send_json({"error": str(e), "code": e.error_code}, e.status_code or 502)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_availability(self, meeting_id: str) -> None:
        """POST /api/meetings/{id}/availability — find alternative times."""
        try:
            body = self._read_body()
            date = body.get("date", _dt.date.today().isoformat())

            # First fetch the meeting details
            meetings = get_calendar_events(date)
            meeting = next((m for m in meetings if m.id == meeting_id), None)
            if not meeting:
                self._send_json({"error": "Meeting not found for the given date."}, 404)
                return

            # Search window: default to same day 08:00-18:00, or use provided window
            search_start = body.get("search_start", f"{date}T08:00:00")
            search_end = body.get("search_end", f"{date}T18:00:00")
            max_suggestions = body.get("max_suggestions", 3)

            slots = find_available_times(meeting, search_start, search_end, max_suggestions)
            self._send_json({
                "meeting_id": meeting_id,
                "meeting_title": meeting.title,
                "current_time": f"{meeting.start_time_local}–{meeting.end_time_local}",
                "is_organizer": meeting.is_organizer,
                "suggestions": [asdict(s) for s in slots],
            })
        except GraphAuthError as e:
            self._send_json({"error": str(e), "code": "auth_required"}, 401)
        except GraphAPIError as e:
            self._send_json({"error": str(e), "code": e.error_code}, e.status_code or 502)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_reschedule(self, meeting_id: str) -> None:
        """POST /api/meetings/{id}/reschedule — move the meeting (organizer only)."""
        try:
            body = self._read_body()
            new_start = body.get("new_start")
            new_end = body.get("new_end")
            confirmed = body.get("confirmed", False)
            date = body.get("date", _dt.date.today().isoformat())

            if not new_start or not new_end:
                self._send_json({"error": "new_start and new_end are required."}, 400)
                return

            # Verify meeting exists and check organizer status
            meetings = get_calendar_events(date)
            meeting = next((m for m in meetings if m.id == meeting_id), None)
            if not meeting:
                self._send_json({"error": "Meeting not found for the given date."}, 404)
                return

            result = reschedule_meeting(
                meeting_id=meeting_id,
                new_start=new_start,
                new_end=new_end,
                is_organizer=meeting.is_organizer,
                user_confirmed=confirmed,
            )
            status = 200 if result.success else 403
            self._send_json(asdict(result), status)
        except GraphAuthError as e:
            self._send_json({"error": str(e), "code": "auth_required"}, 401)
        except MeetingPermissionError as e:
            self._send_json({"error": str(e), "code": "permission_denied"}, 403)
        except GraphAPIError as e:
            self._send_json({"error": str(e), "code": e.error_code}, e.status_code or 502)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_draft_reschedule_request(self, meeting_id: str) -> None:
        """POST /api/meetings/{id}/draft-reschedule-request — for non-organizers."""
        try:
            body = self._read_body()
            suggested_start = body.get("suggested_start")
            suggested_end = body.get("suggested_end")
            reason = body.get("reason")
            date = body.get("date", _dt.date.today().isoformat())
            create_draft = body.get("create_draft", True)

            if not suggested_start or not suggested_end:
                self._send_json({"error": "suggested_start and suggested_end are required."}, 400)
                return

            meetings = get_calendar_events(date)
            meeting = next((m for m in meetings if m.id == meeting_id), None)
            if not meeting:
                self._send_json({"error": "Meeting not found for the given date."}, 404)
                return

            if meeting.is_organizer:
                self._send_json({
                    "error": "You are the organizer. Use the reschedule endpoint instead.",
                    "code": "is_organizer",
                }, 400)
                return

            if create_draft:
                result = create_reschedule_request_draft(
                    meeting, suggested_start, suggested_end, reason
                )
                self._send_json(asdict(result), 200 if result.success else 500)
            else:
                text = get_reschedule_request_text(
                    meeting, suggested_start, suggested_end, reason
                )
                self._send_json({
                    "success": True,
                    "message": "Suggested reschedule request text generated.",
                    "text": text,
                })
        except GraphAuthError as e:
            self._send_json({"error": str(e), "code": "auth_required"}, 401)
        except GraphAPIError as e:
            self._send_json({"error": str(e), "code": e.error_code}, e.status_code or 502)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_recommendations(self) -> None:
        """GET /api/recommendations?date=YYYY-MM-DD — scored reschedule suggestions."""
        try:
            date = None
            if "?" in self.path:
                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]

            # Build the day data (same as live-day) for scoring context
            day = build_live_day(date)
            data = day.get("data", {})
            wearable = data.get("wearable", {}) or {}
            meetings = data.get("meetings", [])

            # Run the meeting scorer
            recs = scorer_recommend(
                meetings,
                date=data.get("date") or date,
                wearable=wearable if wearable.get("mode") == "live" else None,
                hrv=wearable.get("hrv"),
            )

            self._send_json({
                "date": data.get("date"),
                "pawse_score": day.get("pawse_score"),
                "recommendations": recs,
                "count": len(recs),
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

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
