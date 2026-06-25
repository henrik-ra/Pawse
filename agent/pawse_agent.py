"""Pawse unified edge agent — the full automatic collector.

One scheduled run keeps the cloud dashboard current with **everything** that is
automatable on a locked-down corporate machine:

  1. LIVE DAY  — real meetings (WorkIQ-refreshed calendar cache) + wearable
                 (Google Health)            -> POST /api/days
  2. RECORDINGS — voice biomarkers + real facial-expression FER from any new
                  Teams recording           -> POST /api/days/media

(The calendar cache itself is refreshed from WorkIQ via tools/refresh_calendar.py,
the one source that can read the corporate calendar without admin consent.)

Usage:
    $env:PAWSE_API_URL = "https://<container-app>"
    python agent/pawse_agent.py --once          # one pass, then exit
    python agent/pawse_agent.py                  # watch loop (poll)
    python agent/pawse_agent.py --days 3         # also refresh the last 3 days
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "agent"))

from server import build_live_day            # type: ignore  # noqa: E402
import recording_watcher as rw               # type: ignore  # noqa: E402

_DEFAULT_API = "http://localhost:8000"


def _post(url: str, payload: dict, api_key: str | None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push_day(date: str, api_url: str, api_key: str | None) -> bool:
    """Build the live day (calendar + wearable), score it, push to the cloud."""
    scored = build_live_day(date)
    day = scored["data"]
    payload = {
        "user": os.environ.get("PAWSE_USER", "me"),
        "date": day.get("date", date),
        "meetings": day.get("meetings", []),
        "wearable": day.get("wearable", {}),
        "breaks": day.get("breaks", {}),
    }
    try:
        res = _post(f"{api_url}/api/days", payload, api_key)
        print(f"  day {payload['date']}: score={res.get('pawse_score')} "
              f"({res.get('label')})  meetings={len(payload['meetings'])} "
              f"calendar={day.get('calendar_source')}")
        return True
    except urllib.error.HTTPError as exc:
        print(f"  ! day push failed ({exc.code}): {exc.read().decode('utf-8', 'replace')[:150]}")
    except urllib.error.URLError as exc:
        print(f"  ! cannot reach {api_url}: {exc.reason}")
    return False


def run_once(api_url: str, api_key: str | None, days: int, state: dict) -> None:
    today = _dt.date.today()
    print("Live day(s) [calendar + wearable]:")
    for i in range(days):
        push_day((today - _dt.timedelta(days=i)).isoformat(), api_url, api_key)
    print("Recordings [voice + facial expression]:")
    n = rw.scan_once(rw.ma.default_recording_dirs(), api_url, api_key, None, state)
    if n == 0:
        print("  (no new recordings)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pawse unified edge agent")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--interval", type=int, default=900, help="poll seconds (default 900)")
    ap.add_argument("--days", type=int, default=1, help="recent days to refresh (incl. today)")
    ap.add_argument("--reset", action="store_true", help="reprocess all recordings")
    args = ap.parse_args()

    api_url = os.environ.get("PAWSE_API_URL", _DEFAULT_API).rstrip("/")
    api_key = os.environ.get("PAWSE_API_KEY")
    if args.reset and rw._STATE_PATH.exists():
        rw._STATE_PATH.unlink()

    print(f"Pawse agent -> {api_url}")
    state = rw._load_state()
    days = max(1, args.days)
    run_once(api_url, api_key, days, state)
    if args.once:
        return

    print(f"\nPolling every {args.interval}s (Ctrl+C to stop)...")
    try:
        while True:
            time.sleep(args.interval)
            run_once(api_url, api_key, days, state)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
