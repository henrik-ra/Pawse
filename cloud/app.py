"""Pawse cloud API (FastAPI).

Endpoints
---------
GET  /healthz                       liveness probe
GET  /api/live-day?userId&date      stored scored day (generates+stores a demo
                                    day on first request for that date)
POST /api/days                      ingest a real workday from a local collector
                                    (the machine with wearable + calendar access)
GET  /api/history?userId&days       recent Pawse Scores for trend charts

Telemetry
---------
The Pawse Score is emitted as the ``pawse.score`` custom metric to Application
Insights, so you can chart organisational wellbeing live in the Azure portal.

Auth to Cosmos is via managed identity (see pawse_store) — no keys anywhere.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from scoring.pawse_score import score_day

from . import pawse_store

# --- Telemetry: Application Insights custom metric ---------------------------

_record_score = None
try:
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import metrics

        configure_azure_monitor()
        _meter = metrics.get_meter("pawse")
        _score_histogram = _meter.create_histogram(
            name="pawse.score",
            description="Pawse Score (0-100) per scored day",
            unit="score",
        )

        def _record_score(value: int, user_id: str) -> None:  # noqa: E301
            _score_histogram.record(value, {"userId": user_id})
except Exception:  # telemetry must never break the API
    _record_score = None


app = FastAPI(title="Pawse API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Optional shared-secret auth for ingestion. When PAWSE_API_KEY is set (by the
# Bicep deployment), POST /api/days requires a matching x-api-key header.
_API_KEY = os.environ.get("PAWSE_API_KEY")


def _require_api_key(provided: str | None) -> None:
    if _API_KEY and provided != _API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing x-api-key")


# --- Models -----------------------------------------------------------------

class Meeting(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = "Meeting"
    start: str
    end: str
    back_to_back: bool = False
    after_hours: bool = False


class Wearable(BaseModel):
    # Keep the keys the scorer relies on, but preserve every extra metric the
    # local collector computed (calories, distance, hr_avg/max, hr_zones,
    # steps_by_hour, spo2, hrv, active-zone minutes, …) so the dashboard tiles
    # render real values instead of blanks.
    model_config = ConfigDict(extra="allow")
    source: str = "manual"
    steps: int = 0
    resting_hr: int = 60
    hr_samples: list[dict[str, Any]] = Field(default_factory=list)


class Breaks(BaseModel):
    model_config = ConfigDict(extra="allow")
    lunch_break: bool = True
    longest_gap_minutes: int = 0


class WorkdayIn(BaseModel):
    user: str = "me"
    date: str | None = None
    meetings: list[Meeting] = Field(default_factory=list)
    wearable: Wearable = Field(default_factory=Wearable)
    breaks: Breaks = Field(default_factory=Breaks)


class MediaSignalsIn(BaseModel):
    """Retrospective voice/face signals from a meeting recording (edge agent)."""
    model_config = ConfigDict(extra="allow")
    user: str = "me"
    date: str | None = None
    voice: dict[str, Any] | None = None
    face: dict[str, Any] | None = None


# --- Helpers ----------------------------------------------------------------

def _today() -> str:
    return _dt.date.today().isoformat()


def _demo_day(user_id: str, date: str) -> dict[str, Any]:
    """Deterministic, plausible day so a fresh environment still has data."""
    seed = int(hashlib.sha256(f"{user_id}{date}".encode()).hexdigest(), 16)
    meeting_count = 2 + seed % 6
    steps = 500 + (seed >> 8) % 9000
    resting = 58 + (seed >> 16) % 8

    meetings = []
    hour = 9
    for i in range(meeting_count):
        start = f"{hour:02d}:00"
        end = f"{hour:02d}:30"
        meetings.append({
            "title": f"Meeting {i + 1}",
            "start": start,
            "end": end,
            "back_to_back": i > 0 and i % 2 == 0,
            "after_hours": hour >= 18,
        })
        hour += 1

    return {
        "user": user_id,
        "date": date,
        "meetings": meetings,
        "wearable": {
            "source": "demo",
            "mode": "demo",
            "steps": steps,
            "resting_hr": resting,
            "hr_samples": [],
        },
        "breaks": {"lunch_break": steps > 3000, "longest_gap_minutes": 45},
        "calendar_source": "demo",
    }


def _score_and_store(day: dict[str, Any], user_id: str, date: str) -> dict[str, Any]:
    result = score_day(day)
    result["data"] = day
    result["mode"] = day.get("wearable", {}).get("mode", "demo")
    result["calendar_source"] = day.get("calendar_source", "demo")

    pawse_store.upsert_day(user_id, date, result)
    if _record_score is not None and result.get("pawse_score") is not None:
        _record_score(result["pawse_score"], user_id)
    return result


# --- Routes -----------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "cosmos": pawse_store.is_enabled()}


@app.get("/api/live-day")
def live_day(userId: str = "me", date: str | None = None) -> dict[str, Any]:
    date = date or _today()
    stored = pawse_store.get_day(userId, date)
    if stored is not None:
        return stored
    return _score_and_store(_demo_day(userId, date), userId, date)


@app.post("/api/days")
def ingest_day(
    day: WorkdayIn,
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Ingest a real workday collected on a user's machine, score and store it."""
    _require_api_key(x_api_key)
    payload = day.model_dump()
    date = payload.get("date") or _today()
    payload["date"] = date
    payload.setdefault("wearable", {}).setdefault("mode", "live")
    payload.setdefault("calendar_source", "ingested")

    # Preserve any retrospective media signals already attached to this day so a
    # later wearable/calendar upload does not wipe the recording analysis.
    prev = pawse_store.get_day(payload.get("user", "me"), date)
    if prev:
        prev_data = prev.get("data", {})
        for key in ("voice", "face"):
            if key not in payload and prev_data.get(key):
                payload[key] = prev_data[key]

    return _score_and_store(payload, payload.get("user", "me"), date)


@app.post("/api/days/media")
def ingest_media(
    media: MediaSignalsIn,
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Merge voice/face signals from a recording into a day (augments the dashboard).

    Reads the stored day (creating a demo day if none exists yet), folds in the
    voice/face signals and re-stores it — wearable and calendar data are kept.
    """
    _require_api_key(x_api_key)
    user = media.user or "me"
    date = media.date or _today()

    stored = pawse_store.get_day(user, date)
    if stored is None:
        stored = _score_and_store(_demo_day(user, date), user, date)

    data = stored.setdefault("data", {})
    signals = stored.setdefault("signals", {})
    if media.voice:
        data["voice"] = media.voice
        signals["voice"] = media.voice
    if media.face:
        data["face"] = media.face
        signals["face"] = media.face
    stored["media_updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    pawse_store.upsert_day(user, date, stored)
    return stored


@app.get("/api/history")
def history(userId: str = "me", days: int = 30) -> dict[str, Any]:
    return {"userId": userId, "days": days, "history": pawse_store.list_history(userId, days)}


@app.post("/api/messages")
async def messages(request: Request):
    """Microsoft Teams bot endpoint (Azure Bot Service forwards activities here).

    Inactive until the bot is configured (``MicrosoftAppId`` set), so the rest of
    the API is unaffected before the Azure Bot resource exists.
    """
    try:
        from . import pawse_bot
    except Exception as exc:  # botbuilder not installed
        raise HTTPException(status_code=503, detail=f"bot unavailable: {exc}")
    if not pawse_bot.is_configured():
        raise HTTPException(status_code=503, detail="Teams bot not configured")

    body = await request.json()
    auth_header = request.headers.get("Authorization", "")
    invoke_response = await pawse_bot.process(auth_header, body)
    if invoke_response is not None:
        return JSONResponse(status_code=invoke_response.status, content=invoke_response.body)
    return Response(status_code=201)


# Serve the dashboard (app/) from the same origin as the API, so the relative
# /api/* calls in app.js work locally and in the container alike.
_DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "app"
if _DASHBOARD_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_DASHBOARD_DIR), html=True), name="dashboard")
