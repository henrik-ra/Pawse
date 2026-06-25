"""Push a locally-collected Pawse day up to the cloud API — no admin consent.

This is the deliberate answer to "the cloud can't read my calendar".
Your *local* machine already has the data: Google Health via your own OAuth and
the Microsoft 365 calendar via the WorkIQ cache. This script reuses the existing
``server.build_live_day`` pipeline to assemble + score today's day locally, then
POSTs the raw signals to the cloud API's ``/api/days`` endpoint. The cloud never
touches Microsoft Graph, so there is nothing to consent to.

Usage:
    # one-off (defaults to today)
    $env:PAWSE_API_URL = "https://<your-container-app-fqdn>"
    $env:PAWSE_API_KEY = "<the key you deployed with>"   # only if you set one
    py tools/upload_day.py
    py tools/upload_day.py 2026-06-20          # a specific date

Schedule it (Windows Task Scheduler) to keep the cloud fresh, e.g. hourly:
    schtasks /create /tn "Pawse upload" /tr "py %CD%\\tools\\upload_day.py" /sc hourly
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Make the repo root importable so we can reuse server.build_live_day.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import build_live_day  # noqa: E402


def _payload(date: str | None) -> dict:
    """Assemble + score the day locally, then keep only the raw signals."""
    scored = build_live_day(date)
    day = scored["data"]
    # The dashboard reads the cloud's default user ("me"), so upload under that
    # id by default. Override with PAWSE_USER if you run multi-user.
    return {
        "user": os.environ.get("PAWSE_USER", "me"),
        "date": day.get("date"),
        "meetings": day.get("meetings", []),
        "wearable": day.get("wearable", {}),
        "breaks": day.get("breaks", {}),
    }


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    api_url = os.environ.get("PAWSE_API_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("PAWSE_API_KEY")

    body = json.dumps(_payload(date)).encode("utf-8")
    request = urllib.request.Request(f"{api_url}/api/days", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("x-api-key", api_key)

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"Upload failed ({exc.code}): {exc.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach {api_url}: {exc.reason}")

    print(
        f"Uploaded {result.get('date')}: "
        f"score={result.get('pawse_score')} ({result.get('label')})"
    )


if __name__ == "__main__":
    main()
