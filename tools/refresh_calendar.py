"""Refresh the local calendar cache from a WorkIQ calendarView export.

On a locked-down corporate tenant, WorkIQ (M365 Copilot) is the only thing that
can read the real calendar (no Graph consent, New-Outlook has no COM). The flow:

  1. In the assistant, pull   /me/calendarView?startDateTime=...&endDateTime=...
  2. Save that JSON to a file.
  3. Run this script -> it converts UTC times to local, drops all-day / multi-day
     events, and merges the result into data/calendar_cache.json (the source the
     dashboard and the agent read).

Usage:
    python tools/refresh_calendar.py workiq_calendar.json [--tz-offset 2]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CACHE = _ROOT / "data" / "calendar_cache.json"
# The account whose calendar is pulled — used to tell "blocker" (personal block,
# no other people) events apart from real meetings with attendees.
_SELF_EMAIL = "t-hrathai@microsoft.com"


def _is_blocker(ev: dict) -> bool:
    """True if the event has no other human attendees — a personal block that is
    safe to move (you can't unilaterally reschedule a meeting with other people).

    Honors an explicit ``is_blocker`` field if present, else derives it from the
    ``attendees`` list (room/equipment resources don't count as people).
    """
    if "is_blocker" in ev:
        return bool(ev["is_blocker"])
    others = [
        a for a in (ev.get("attendees") or [])
        if a.get("type") != "resource"
        and (a.get("emailAddress") or {}).get("address", "").lower() != _SELF_EMAIL
    ]
    return not others


def _local(iso_utc: str, offset_h: float) -> _dt.datetime:
    """Parse a (UTC) ISO timestamp and shift to local time."""
    s = iso_utc.split(".")[0].rstrip("Z")
    return _dt.datetime.fromisoformat(s) + _dt.timedelta(hours=offset_h)


def _events(raw) -> list:
    """Pull the event list out of the various WorkIQ/Graph response shapes."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("value"), list):
            return raw["value"]
        if isinstance(raw.get("data"), dict):
            return raw["data"].get("value", [])
    return []


def convert(events: list, offset_h: float) -> dict[str, list]:
    """Turn calendarView events into {date: [{title,start,end}]}, local time."""
    days: dict[str, list] = {}
    for ev in events:
        if ev.get("isAllDay"):
            continue
        # Skip cancelled events — either the Graph ``isCancelled`` flag or a
        # "Canceled:" / "Abgesagt:" subject prefix (used when the flag wasn't
        # part of the WorkIQ $select). They are not real commitments.
        if ev.get("isCancelled"):
            continue
        subject_lc = (ev.get("subject") or "").lstrip().lower()
        if subject_lc.startswith(("canceled:", "cancelled:", "abgesagt:")):
            continue
        start, end = ev.get("start"), ev.get("end")
        s_iso = start.get("dateTime") if isinstance(start, dict) else start
        e_iso = end.get("dateTime") if isinstance(end, dict) else end
        if not s_iso or not e_iso:
            continue
        s, e = _local(s_iso, offset_h), _local(e_iso, offset_h)
        if s.date() != e.date():  # drop multi-day spans
            continue
        title = (ev.get("subject") or "Meeting").strip()
        days.setdefault(s.strftime("%Y-%m-%d"), []).append({
            "title": title,
            "start": s.strftime("%H:%M"),
            "end": e.strftime("%H:%M"),
            "is_blocker": _is_blocker(ev),
        })
    for d in days:
        days[d].sort(key=lambda m: m["start"])
    return days


def main() -> None:
    ap = argparse.ArgumentParser(description="WorkIQ calendarView -> calendar_cache.json")
    ap.add_argument("json_file", help="saved WorkIQ /me/calendarView response")
    ap.add_argument("--tz-offset", type=float, default=2.0,
                    help="hours to add to UTC for local time (CEST=2, CET=1)")
    args = ap.parse_args()

    raw = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    day_meetings = convert(_events(raw), args.tz_offset)

    cache = {"days": {}}
    if _CACHE.exists():
        try:
            cache = json.loads(_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {"days": {}}
    cache.setdefault("days", {})
    for d, meetings in day_meetings.items():
        cache["days"][d] = {"meetings": meetings, "source": "workiq"}
    _CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    if not day_meetings:
        print("No timed meetings found in the export.")
    for d, meetings in sorted(day_meetings.items()):
        print(f"{d}: {len(meetings)} meetings")
        for m in meetings:
            print(f"  {m['start']}-{m['end']}  {m['title'][:60]}")


if __name__ == "__main__":
    main()
