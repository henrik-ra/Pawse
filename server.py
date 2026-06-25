"""Pawse live server.

Serves the dashboard (app/) and a small live API that combines your real
Fitbit data with the calendar/meeting data and computes the Pawse Score.

Run it:

    python server.py

For a Xiaomi watch this also auto-syncs in the background (watch -> phone ->
laptop DB). Flags:

    python server.py --wearable xiaomi   # force the Xiaomi watch (e.g. first run)
    python server.py --interval 300      # slower sync cadence (seconds)
    python server.py --no-sync           # serve the existing DB only

Then open http://localhost:8000 in your browser.

Endpoints:
    GET /                 -> the dashboard (app/index.html)
    GET /api/live-day     -> { score, label, reasons, recommendations, data }

Live Fitbit data is used automatically once you have run
``python devices/google_health/google_auth.py``; otherwise demo data is returned.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as _dt
import json
import os
import shutil
import subprocess
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from devices.outlook.calendar_client import get_meetings
from scoring.pawse_score import score_day
from teams_sessions import save_session, sessions_for

# Pick the wearable source. With PAWSE_WEARABLE unset (or "auto") Pawse detects
# it: a synced Gadgetbridge DB -> Xiaomi watch, otherwise Google Health
# (Fitbit / Pixel Watch). Force one with --wearable or PAWSE_WEARABLE.
# The chosen module just has to expose get_daily_signals(date) + prewarm().
_WEARABLE = "google-health"
get_daily_signals: Any = None  # bound by _load_backend()
prewarm: Any = None


def _detect_wearable() -> str:
    explicit = (os.environ.get("PAWSE_WEARABLE") or "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    gb_db = os.environ.get("GADGETBRIDGE_DB") or (
        Path.home() / "Pawse" / "data" / "gadgetbridge-db" / "Gadgetbridge.db"
    )
    if Path(gb_db).exists():
        return "xiaomi"
    return "google-health"


def _load_backend() -> None:
    """Resolve the wearable source and import its client into module globals."""
    global _WEARABLE, get_daily_signals, prewarm
    _WEARABLE = _detect_wearable()
    print(f"[pawse] wearable source: {_WEARABLE}")
    if _WEARABLE == "xiaomi":
        from devices.xiaomi.xiaomi_client import get_daily_signals as _g, prewarm as _p
    else:
        from devices.google_health.google_health_client import get_daily_signals as _g, prewarm as _p
    get_daily_signals, prewarm = _g, _p

_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "app"
_SAMPLE = _ROOT / "data" / "alex_workday.json"

# Local Gadgetbridge DB that the watch sync loop writes and the Xiaomi backend
# reads. Mirrors the path used by devices/xiaomi/sync_gadgetbridge.ps1.
_GADGETBRIDGE_DB = Path.home() / "Pawse" / "data" / "gadgetbridge-db" / "Gadgetbridge.db"

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
        if self.path.startswith("/api/teams-sessions"):
            self._serve_teams_sessions()
            return
        if self.path.startswith("/api/live-day"):
            self._serve_live_day()
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/api/teams-sessions"):
            self._save_teams_session()
            return
        self._write_json({"error": "not found"}, 404)

    # ----- JSON helper -------------------------------------------------
    def _write_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass  # browser navigated away / refreshed mid-response

    # ----- Teams meeting biomarker sessions ----------------------------
    def _serve_teams_sessions(self) -> None:
        try:
            date = None
            if "?" in self.path:
                from urllib.parse import parse_qs, urlparse

                date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            self._write_json(sessions_for(date), 200)
        except Exception as exc:
            self._write_json({"error": str(exc)}, 500)

    def _save_teams_session(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            stored = save_session(payload)
            self._write_json({"ok": True, "session": stored}, 201)
        except Exception as exc:
            self._write_json({"error": str(exc)}, 400)

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


def _ensure_adb_on_path() -> bool:
    """Make sure `adb` is callable; locate the winget install if needed."""
    if shutil.which("adb"):
        return True
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        for exe in base.rglob("adb.exe"):
            os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


def _stop_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _start_watch_sync() -> subprocess.Popen | None:
    """Launch the Gadgetbridge sync loop in the background (Xiaomi watch only).

    Puts adb on PATH and runs sync_gadgetbridge.ps1 -Trigger -Loop so the served
    DB stays fresh. The loop is stopped automatically when the server exits.
    Disable with --no-sync or PAWSE_NO_SYNC=1.
    """
    if _WEARABLE != "xiaomi" or os.environ.get("PAWSE_NO_SYNC"):
        return None

    interval = os.environ.get("PAWSE_SYNC_INTERVAL", "120")
    if not _ensure_adb_on_path():
        print("[pawse] adb not found \u2014 serving existing DB without live sync.")
        print("        install with: winget install Google.PlatformTools")
        return None

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        print("[pawse] PowerShell not found \u2014 skipping live sync.")
        return None

    script = _ROOT / "devices" / "xiaomi" / "sync_gadgetbridge.ps1"
    proc = subprocess.Popen(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Trigger", "-Loop", "-NoRun", "-IntervalSeconds", str(interval)],
        cwd=str(_ROOT),
    )
    atexit.register(_stop_proc, proc)
    print(f"[pawse] watch sync loop started (every {interval}s, pid {proc.pid}).")
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Pawse live server.")
    parser.add_argument(
        "--wearable", choices=["auto", "xiaomi", "google-health"],
        help="Wearable source to read (default: auto-detect).",
    )
    parser.add_argument(
        "--interval", type=int, metavar="SECONDS",
        help="Seconds between Xiaomi watch syncs (default 120).",
    )
    parser.add_argument(
        "--no-sync", action="store_true",
        help="Don't auto-sync the watch; serve whatever DB is already on disk.",
    )
    args = parser.parse_args()
    if args.wearable:
        os.environ["PAWSE_WEARABLE"] = args.wearable
    if args.interval:
        os.environ["PAWSE_SYNC_INTERVAL"] = str(args.interval)
    if args.no_sync:
        os.environ["PAWSE_NO_SYNC"] = "1"

    # Resolve the wearable source (and import its client) now that flags/env are set.
    _load_backend()

    # For the Xiaomi watch, point the backend at the synced DB and start the
    # background sync loop so a single `python server.py` shows live data.
    if _WEARABLE == "xiaomi":
        os.environ.setdefault("GADGETBRIDGE_DB", str(_GADGETBRIDGE_DB))
    _start_watch_sync()

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
