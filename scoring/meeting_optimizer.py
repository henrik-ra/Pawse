"""Pawse meeting optimizer — turn a day's meetings + energy into concrete,
actionable reschedule recommendations.

This is the *brain* behind the reschedule advisor: it never touches a calendar
itself. It emits structured recommendations that two consumers can act on:

  * the dashboard / Teams bot  → render a card + 1-click Outlook deeplink
  * Microsoft 365 Copilot Cowork → execute the move on the user's behalf
    (with the user's approval), using the structured fields below.

Each recommendation is::

    {
      "type": "reschedule" | "add_buffer" | "protect_lunch" |
              "move_after_hours" | "protect_focus",
      "title": "<meeting title or focus block>",
      "from": "10:30",            # current start (None for new holds)
      "to": "15:00",              # suggested start
      "end": "15:30",             # suggested end
      "reason": "human-readable why",
      "outlook_url": "https://outlook.office.com/calendar/..."
    }

Run directly to see recommendations for sample meetings.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

# Work window and thresholds (mirrors devices/outlook/calendar_client.py).
_DAY_START = 8 * 60          # 08:00
_DAY_END = 18 * 60           # 18:00
_LUNCH_WINDOW = (11 * 60 + 30, 14 * 60 + 30)   # 11:30–14:30
_LUNCH_NEEDED = 30
_B2B_GAP = 5                 # gap <= 5 min counts as back-to-back
_FOCUS_MIN = 90             # a free block this long is worth protecting
_MAX_RECS = 4


def _to_min(hhmm: str) -> int:
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _ordered(meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (m for m in meetings if m.get("start") and m.get("end")),
        key=lambda m: _to_min(m["start"]),
    )


def _free_slots(
    meetings: list[dict[str, Any]], day_start: int = _DAY_START, day_end: int = _DAY_END
) -> list[tuple[int, int]]:
    """Free [start, end) gaps (minutes) within the work window."""
    busy = sorted(
        (max(day_start, _to_min(m["start"])), min(day_end, _to_min(m["end"])))
        for m in meetings
        if _to_min(m["end"]) > day_start and _to_min(m["start"]) < day_end
    )
    slots: list[tuple[int, int]] = []
    cursor = day_start
    for start, end in busy:
        if start > cursor:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if day_end > cursor:
        slots.append((cursor, day_end))
    return slots


def _longest_slot(slots: list[tuple[int, int]]) -> tuple[int, int] | None:
    return max(slots, key=lambda s: s[1] - s[0]) if slots else None


def _compose_url(subject: str, date: str | None, start: int, end: int) -> str:
    """Outlook deeplink that opens a pre-filled *new* event (focus/lunch hold)."""
    if not date:
        return "https://outlook.office.com/calendar/"
    startdt = f"{date}T{_to_hhmm(start)}:00"
    enddt = f"{date}T{_to_hhmm(end)}:00"
    return (
        "https://outlook.office.com/calendar/0/deeplink/compose?"
        f"subject={quote(subject)}&startdt={quote(startdt)}&enddt={quote(enddt)}"
    )


def _calendar_url(date: str | None) -> str:
    """Deeplink that just opens the calendar (user drags the meeting)."""
    return "https://outlook.office.com/calendar/view/day"


def _has_lunch(meetings: list[dict[str, Any]]) -> bool:
    lo, hi = _LUNCH_WINDOW
    cursor = lo
    free = 0
    for start, end in sorted(
        (max(lo, _to_min(m["start"])), min(hi, _to_min(m["end"])))
        for m in meetings
        if _to_min(m["end"]) > lo and _to_min(m["start"]) < hi
    ):
        if start > cursor:
            free = max(free, start - cursor)
        cursor = max(cursor, end)
    free = max(free, hi - cursor)
    return free >= _LUNCH_NEEDED


def _back_to_back_count(ordered: list[dict[str, Any]]) -> int:
    count = 0
    prev_end: int | None = None
    for m in ordered:
        start, end = _to_min(m["start"]), _to_min(m["end"])
        if prev_end is not None and (start - prev_end) <= _B2B_GAP:
            count += 1
        prev_end = end if prev_end is None else max(prev_end, end)
    return count


def recommend(
    meetings: list[dict[str, Any]],
    *,
    date: str | None = None,
    score: int | None = None,
) -> list[dict[str, Any]]:
    """Return prioritised, actionable reschedule recommendations (max 4)."""
    ordered = _ordered(meetings)
    if not ordered:
        return []

    slots = _free_slots(ordered)
    longest = _longest_slot(slots)
    recs: list[dict[str, Any]] = []

    # 1) After-hours *blocker* → pull into the work day's longest free slot.
    #    Only personal blocks (no other attendees) may be moved.
    for m in ordered:
        start = _to_min(m["start"])
        if m.get("is_blocker") and (start < _DAY_START or start >= _DAY_END) and longest:
            dur = _to_min(m["end"]) - start
            new_start = longest[0]
            recs.append({
                "type": "move_after_hours",
                "title": m.get("title", "Meeting"),
                "from": m["start"],
                "to": _to_hhmm(new_start),
                "end": _to_hhmm(new_start + dur),
                "reason": "Outside work hours — move into your day to protect your evening.",
                "outlook_url": _calendar_url(date),
            })

    # 2) Overloaded / low-energy day → reschedule a *blocker* (a personal block
    #    with no other attendees) out of the crunch. You can't unilaterally move
    #    a meeting that involves other people, so only blockers are candidates;
    #    pick the shortest one and drop it into the longest free slot (capped to
    #    the slot so it doesn't create a new overlap).
    b2b = _back_to_back_count(ordered)
    if (b2b >= 2 or (isinstance(score, (int, float)) and score < 50)) and longest:
        slot_start, slot_end = longest
        candidates: list[tuple[int, dict[str, Any]]] = []
        prev_end: int | None = None
        for m in ordered:
            s, e = _to_min(m["start"]), _to_min(m["end"])
            crunch = prev_end is not None and (s - prev_end) <= _B2B_GAP
            if m.get("is_blocker") and crunch and not (slot_start <= s < slot_end):
                candidates.append((e - s, m))
            prev_end = e if prev_end is None else max(prev_end, e)
        if candidates:
            dur, movable = min(candidates, key=lambda c: c[0])
            new_end = min(slot_start + dur, slot_end)
            recs.append({
                "type": "reschedule",
                "title": movable.get("title", "Meeting"),
                "from": movable["start"],
                "to": _to_hhmm(slot_start),
                "end": _to_hhmm(new_end),
                "reason": "Solo block with no other attendees — move it to ease your back-to-back crunch.",
                "outlook_url": _calendar_url(date),
            })

    # 3) No lunch break → propose a 30-min lunch hold in a free lunch sub-slot.
    if not _has_lunch(ordered):
        lo, hi = _LUNCH_WINDOW
        lunch_slot = next(
            (s for s in _free_slots(ordered, lo, hi) if s[1] - s[0] >= _LUNCH_NEEDED),
            None,
        )
        start = lunch_slot[0] if lunch_slot else 12 * 60
        recs.append({
            "type": "protect_lunch",
            "title": "Lunch break",
            "from": None,
            "to": _to_hhmm(start),
            "end": _to_hhmm(start + _LUNCH_NEEDED),
            "reason": "No lunch break today — block 30 min to recover.",
            "outlook_url": _compose_url("Lunch break", date, start, start + _LUNCH_NEEDED),
        })

    # 4) A long free block exists → protect it as focus time.
    if longest and (longest[1] - longest[0]) >= _FOCUS_MIN:
        f_start, f_end = longest[0], min(longest[0] + 120, longest[1])
        recs.append({
            "type": "protect_focus",
            "title": "Focus time",
            "from": None,
            "to": _to_hhmm(f_start),
            "end": _to_hhmm(f_end),
            "reason": "You have a clear block — protect it for deep work.",
            "outlook_url": _compose_url("Focus time", date, f_start, f_end),
        })

    return recs[:_MAX_RECS]


if __name__ == "__main__":
    import json

    sample = [
        {"title": "F1V", "start": "09:30", "end": "10:45"},
        {"title": "Welcome Kick-Off", "start": "10:00", "end": "10:15"},
        {"title": "Fireside Chat", "start": "10:15", "end": "10:30"},
        {"title": "Intern Spotlight", "start": "10:30", "end": "11:00"},
        {"title": "Late sync", "start": "18:30", "end": "19:00"},
    ]
    print(json.dumps(recommend(sample, date="2026-06-25", score=42), indent=2))
