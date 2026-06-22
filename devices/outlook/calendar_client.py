"""Outlook / Microsoft 365 calendar — meetings for a given day.

Live calendar access via Microsoft Graph needs an Azure AD app registration,
which isn't available on this tenant (no admin rights). Instead the real
calendar is pulled through Microsoft 365 Copilot (WorkIQ) at author time and
cached in ``data/calendar_cache.json`` (times already converted to local
Europe/Berlin and cleaned of all-day / multi-day / cancelled events).

This module reads that cache and turns a day's raw meetings into the shape the
Pawse scorer and dashboard expect, deriving the busy-day signals
(back-to-back, after-hours, lunch break, longest gap) from the start/end times
so the logic lives in code rather than being baked into the data.

Days without a cached entry fall back to the static sample workday so the
dashboard still renders.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_PATH = _ROOT / "data" / "calendar_cache.json"
_SAMPLE_PATH = _ROOT / "data" / "alex_workday.json"

# A meeting starting within this many minutes of the previous one's end counts
# as "back-to-back" (negatives mean they overlap).
_B2B_GAP_MIN = 5
# Anything starting before 08:00 or at/after 18:00 local is "after hours".
_DAY_START_MIN = 8 * 60
_DAY_END_MIN = 18 * 60
# Lunch is "protected" if there is a free block this long within the window.
_LUNCH_WINDOW = (11 * 60 + 30, 14 * 60 + 30)  # 11:30–14:30
_LUNCH_NEEDED_MIN = 30


def _to_min(hhmm: str) -> int:
    """'13:45' -> 825 minutes since midnight."""
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 60 + int(minutes)


def _derive_meetings(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add back_to_back / after_hours flags, sorted by start time."""
    ordered = sorted(raw, key=lambda m: _to_min(m["start"]))
    out: list[dict[str, Any]] = []
    prev_end: int | None = None
    for m in ordered:
        start, end = _to_min(m["start"]), _to_min(m["end"])
        back_to_back = prev_end is not None and (start - prev_end) <= _B2B_GAP_MIN
        after_hours = start < _DAY_START_MIN or start >= _DAY_END_MIN
        out.append({
            "title": m.get("title", "Meeting"),
            "start": m["start"],
            "end": m["end"],
            "back_to_back": back_to_back,
            "after_hours": after_hours,
        })
        prev_end = end if prev_end is None else max(prev_end, end)
    return out


def _has_lunch_break(raw: list[dict[str, Any]]) -> bool:
    """True if a free block of >= _LUNCH_NEEDED_MIN exists in the lunch window."""
    lo, hi = _LUNCH_WINDOW
    busy = sorted(
        (max(lo, _to_min(m["start"])), min(hi, _to_min(m["end"])))
        for m in raw
        if _to_min(m["end"]) > lo and _to_min(m["start"]) < hi
    )
    cursor = lo
    free = 0
    for start, end in busy:
        if start > cursor:
            free = max(free, start - cursor)
        cursor = max(cursor, end)
    free = max(free, hi - cursor)
    return free >= _LUNCH_NEEDED_MIN


def _longest_gap_minutes(raw: list[dict[str, Any]]) -> int:
    """Largest free gap (minutes) between consecutive meetings in work hours."""
    ordered = sorted(raw, key=lambda m: _to_min(m["start"]))
    cursor = _DAY_START_MIN
    longest = 0
    for m in ordered:
        start, end = _to_min(m["start"]), _to_min(m["end"])
        if start > cursor:
            longest = max(longest, start - cursor)
        cursor = max(cursor, end)
    longest = max(longest, _DAY_END_MIN - cursor)
    return max(0, longest)


def _load_cache() -> dict[str, Any]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8")).get("days", {})
    except Exception:
        return {}


def _fallback_from_sample() -> dict[str, Any]:
    """Static demo meetings/breaks when a day has no real calendar entry."""
    try:
        sample = json.loads(_SAMPLE_PATH.read_text(encoding="utf-8"))
    except Exception:
        sample = {}
    return {
        "meetings": sample.get("meetings", []),
        "breaks": sample.get("breaks", {"lunch_break": True, "longest_gap_minutes": 0}),
        "calendar_source": "demo",
    }


def get_meetings(date: str) -> dict[str, Any]:
    """Return real (WorkIQ) meetings + derived breaks for ``date``.

    Falls back to the static sample workday for days that were never cached.
    """
    entry = _load_cache().get(date)
    if entry is None or "meetings" not in entry:
        return _fallback_from_sample()

    raw = entry["meetings"]
    return {
        "meetings": _derive_meetings(raw),
        "breaks": {
            "lunch_break": _has_lunch_break(raw),
            "longest_gap_minutes": _longest_gap_minutes(raw),
        },
        "calendar_source": entry.get("source", "workiq"),
    }


if __name__ == "__main__":
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else "2026-06-22"
    print(json.dumps(get_meetings(day), indent=2, ensure_ascii=False))
