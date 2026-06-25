"""Pawse biomarker store — per-meeting voice + face biomarkers for the MCP server.

For the demo the data is **mocked** (``data/biomarker_mock.json``): five meetings
with voice (F0/jitter/shimmer/HNR/spectral) and face (FER+ emotion mix) signals,
each rolled up into a single ``stress_index`` (0..1). This mirrors the shape the
real pipeline writes to ``data/media_signals.json`` so swapping the mock for live
recordings later changes nothing for callers.

The loader is robust by design: if the requested date has no mocked data it falls
back to the most recent mocked day, so an agent connecting to the MCP server
**always** gets biomarkers to reason over — exactly like ``google_tokens.json``
makes wearable data available without a fresh OAuth flow each time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_STORE = _ROOT / "data" / "biomarker_mock.json"


def _strain_label(stress: float) -> str:
    if stress >= 0.75:
        return "high"
    if stress >= 0.6:
        return "elevated"
    if stress >= 0.4:
        return "steady"
    return "calm"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"days": {}}


def _summarize(date: str, meetings: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up the per-meeting biomarkers into a day-level summary."""
    indices = [
        m["stress_index"]
        for m in meetings
        if isinstance(m.get("stress_index"), (int, float))
    ]
    avg = round(sum(indices) / len(indices), 2) if indices else None
    peak = max(meetings, key=lambda m: m.get("stress_index", 0.0)) if meetings else None
    return {
        "date": date,
        "source": "mock",
        "available": bool(meetings),
        "meeting_count": len(meetings),
        "avg_stress_index": avg,
        "day_strain_label": _strain_label(avg) if avg is not None else None,
        "peak_meeting": (
            {
                "meeting": peak.get("meeting"),
                "start": peak.get("start"),
                "stress_index": peak.get("stress_index"),
            }
            if peak
            else None
        ),
        "meetings": meetings,
        "disclaimer": (
            "Experimental, on-device signal. Not a diagnosis or a statement about "
            "how the user feels — use only as soft context for energy coaching."
        ),
    }


def for_date(date: str | None = None) -> dict[str, Any]:
    """Biomarkers for a date. Falls back to the most recent mocked day so the
    agent always has data. Returns a day-level summary plus per-meeting signals."""
    days = _load().get("days", {})
    if not days:
        return _summarize(date or "", [])

    if date and date in days:
        chosen = date
    else:
        chosen = sorted(days.keys())[-1]  # most recent mocked day
    return _summarize(chosen, days.get(chosen, []))


def for_meeting(title: str, date: str | None = None) -> dict[str, Any] | None:
    """Biomarkers for a single meeting on a day (case-insensitive title match)."""
    day = for_date(date)
    needle = (title or "").strip().lower()
    for m in day.get("meetings", []):
        if (m.get("meeting") or "").strip().lower() == needle:
            return m
    return None
