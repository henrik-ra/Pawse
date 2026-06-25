"""Pawse meeting scorer — per-meeting pressure × movability scoring.

Scores every meeting in a day on two axes and outputs prioritised,
actionable recommendations for the reschedule advisor.

Pressure Score (0–100): How much scheduling strain does this meeting cause?
  - Calendar structure: back-to-back, clusters, after-hours, lunch, focus
  - Wearable signals: HR spikes during meeting, elevated avg HR, no recovery
  - Peak window: meeting occupies user's calmest time-of-day block

Movability Score (0–100): Can this meeting realistically be moved?
  - Graph metadata: organizer status, attendees, recurring, private, responses

Final ranking: pressure × movability → top candidates get recommended.

This module NEVER touches a calendar. It emits structured recommendations
consumed by:
  - Scout / Copilot MCP → agent executes with user approval
  - Dashboard UI → shows suggestions + Outlook deeplinks
  - Desktop pet → clickable nudge

Health/stress data is NEVER included in recommendation text or sent externally.

Run directly to score the sample day:
    python scoring/meeting_scorer.py
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

# --- Thresholds ---------------------------------------------------------------

_DAY_START = 8 * 60          # 08:00
_DAY_END = 18 * 60           # 18:00
_LUNCH_WINDOW = (11 * 60 + 30, 14 * 60 + 30)  # 11:30–14:30
_LUNCH_NEEDED = 30
_B2B_GAP = 5                 # gap ≤ 5 min = back-to-back
_FOCUS_MIN = 90              # free block worth protecting
_HR_SPIKE_DELTA = 25         # bpm above resting = spike
_HR_ELEVATED_DELTA = 15      # bpm above resting = elevated avg
_HR_RECOVERY_DELTA = 10      # bpm above resting = not recovered
_MAX_RECS = 4
_PRESSURE_THRESHOLD = 30     # minimum to suggest a move
_MOVABILITY_THRESHOLD = 20   # minimum to suggest a move


# --- Utility ------------------------------------------------------------------

def _to_min(hhmm: str) -> int:
    """'13:45' -> 825 minutes since midnight. Also handles ISO datetimes."""
    # Handle ISO datetime like '2026-06-25T13:45:00'
    if "T" in str(hhmm):
        hhmm = str(hhmm).split("T")[1][:5]
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _clamp(val: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, val))


def _ordered(meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (m for m in meetings if m.get("start") and m.get("end")),
        key=lambda m: _to_min(m["start"]),
    )


def _free_slots(
    meetings: list[dict[str, Any]], day_start: int = _DAY_START, day_end: int = _DAY_END
) -> list[tuple[int, int]]:
    """Free [start, end) gaps in minutes within the work window."""
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


def _calendar_url(date: str | None) -> str:
    return "https://outlook.office.com/calendar/view/day"


def _compose_url(subject: str, date: str | None, start: int, end: int) -> str:
    """Outlook deeplink for a pre-filled new event (focus/lunch hold)."""
    if not date:
        return "https://outlook.office.com/calendar/"
    startdt = f"{date}T{_to_hhmm(start)}:00"
    enddt = f"{date}T{_to_hhmm(end)}:00"
    return (
        "https://outlook.office.com/calendar/0/deeplink/compose?"
        f"subject={quote(subject)}&startdt={quote(startdt)}&enddt={quote(enddt)}"
    )


# --- HR helpers ---------------------------------------------------------------

def _get_hr_in_window(
    hr_samples: list[dict[str, Any]], start_min: int, end_min: int
) -> list[float]:
    """Extract HR values that fall within a time window (minutes since midnight)."""
    values = []
    for sample in hr_samples:
        t = sample.get("time")
        if not t:
            continue
        try:
            sample_min = _to_min(t) if ":" in str(t) else int(t)
        except (ValueError, TypeError):
            continue
        if start_min <= sample_min < end_min:
            bpm = sample.get("bpm", 0)
            if bpm > 0:
                values.append(float(bpm))
    return values


def _find_calmest_hours(hr_samples: list[dict[str, Any]], resting_hr: float) -> list[int]:
    """Find the hours with lowest average HR (user's natural peak window).

    Returns list of hours (0-23) sorted by calmness.
    """
    if not hr_samples or not resting_hr:
        return []

    hour_avgs: dict[int, list[float]] = {}
    for sample in hr_samples:
        t = sample.get("time")
        if not t:
            continue
        try:
            sample_min = _to_min(t) if ":" in str(t) else int(t)
            hour = sample_min // 60
        except (ValueError, TypeError):
            continue
        bpm = sample.get("bpm", 0)
        if bpm > 0 and _DAY_START // 60 <= hour < _DAY_END // 60:
            hour_avgs.setdefault(hour, []).append(float(bpm))

    if not hour_avgs:
        return []

    # Sort hours by average HR (lowest = calmest)
    avg_by_hour = {h: sum(v) / len(v) for h, v in hour_avgs.items() if v}
    sorted_hours = sorted(avg_by_hour.keys(), key=lambda h: avg_by_hour[h])
    # Return the calmest 2-3 hours
    return sorted_hours[:3]


# --- Pressure scoring ---------------------------------------------------------

def score_pressure(
    meeting: dict[str, Any],
    all_meetings: list[dict[str, Any]],
    wearable: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    """Score how much scheduling pressure a single meeting causes.

    Returns (score 0-100, list of contributing signal names).
    """
    score = 0.0
    signals: list[str] = []
    ordered = _ordered(all_meetings)

    m_start = _to_min(meeting["start"])
    m_end = _to_min(meeting["end"])
    m_dur = m_end - m_start

    # Find this meeting's position and neighbors
    prev_end: int | None = None
    next_start: int | None = None
    for i, m in enumerate(ordered):
        s, e = _to_min(m["start"]), _to_min(m["end"])
        if s == m_start and e == m_end:
            # Look for previous meeting end
            if i > 0:
                prev_end = _to_min(ordered[i - 1]["end"])
            # Look for next meeting start
            if i < len(ordered) - 1:
                next_start = _to_min(ordered[i + 1]["start"])
            break

    gap_before = (m_start - prev_end) if prev_end is not None else 999
    gap_after = (next_start - m_end) if next_start is not None else 999
    b2b_before = gap_before <= _B2B_GAP
    b2b_after = gap_after <= _B2B_GAP

    # Signal 1 & 2: Back-to-back
    if b2b_before and b2b_after:
        score += 35
        signals.append("double_back_to_back")
    elif b2b_before or b2b_after:
        score += 25
        signals.append("back_to_back")

    # Signal 3: Duration in cluster (≥45 min and adjacent)
    if m_dur >= 45 and (b2b_before or b2b_after):
        score += 15
        signals.append("long_in_cluster")

    # Signal 4: No prep time (organizer, ≥30 min)
    is_organizer = meeting.get("is_organizer", False)
    attendee_count = len(meeting.get("attendees", []))

    if gap_before < 10 and m_dur >= 30:
        if is_organizer:
            score += 10
            signals.append("no_prep_organizer")
        elif attendee_count <= 6 and meeting.get("response", "") in ("accepted", "organizer"):
            score += 5
            signals.append("no_prep_small_collab")

    # Signal 6: No prep for long meetings (≥60 min, any role)
    if gap_before < 10 and m_dur >= 60:
        score += 10
        signals.append("no_prep_long_meeting")

    # Signal 7: After-hours
    if m_start < _DAY_START or m_start >= _DAY_END:
        score += 20
        signals.append("after_hours")

    # Signal 8: Blocks lunch
    if not _has_lunch(all_meetings):
        lo, hi = _LUNCH_WINDOW
        if m_end > lo and m_start < hi:
            score += 15
            signals.append("blocks_lunch")

    # Signal 9: Fragments focus
    # Would a ≥90 min block exist if this meeting were removed?
    without_this = [m for m in all_meetings if m is not meeting]
    slots_without = _free_slots(without_this)
    slots_with = _free_slots(all_meetings)
    longest_without = _longest_slot(slots_without)
    longest_with = _longest_slot(slots_with)
    if longest_without and longest_with:
        if (longest_without[1] - longest_without[0]) >= _FOCUS_MIN and \
           (longest_with[1] - longest_with[0]) < _FOCUS_MIN:
            score += 10
            signals.append("fragments_focus")

    # Signals 10-12: HR-based (only if wearable data available)
    if wearable:
        resting_hr = wearable.get("resting_hr", 0)
        hr_samples = wearable.get("hr_samples", [])

        if resting_hr and hr_samples:
            meeting_hr = _get_hr_in_window(hr_samples, m_start, m_end)

            # Signal 10: HR spike during meeting
            if meeting_hr:
                peak_hr = max(meeting_hr)
                if peak_hr - resting_hr >= _HR_SPIKE_DELTA:
                    score += 15
                    signals.append("hr_spike")

                # Signal 11: Elevated average HR
                avg_hr = sum(meeting_hr) / len(meeting_hr)
                if avg_hr - resting_hr >= _HR_ELEVATED_DELTA:
                    score += 10
                    signals.append("hr_elevated_avg")

            # Signal 12: No HR recovery before next meeting
            if next_start and next_start - m_end <= 15:
                transition_hr = _get_hr_in_window(hr_samples, m_end, next_start)
                if transition_hr:
                    transition_avg = sum(transition_hr) / len(transition_hr)
                    if transition_avg - resting_hr >= _HR_RECOVERY_DELTA:
                        score += 10
                        signals.append("no_hr_recovery")

            # Signal 13: Occupies peak readiness window
            calmest = _find_calmest_hours(hr_samples, resting_hr)
            meeting_hour = m_start // 60
            if calmest and meeting_hour in calmest[:2]:
                score += 10
                signals.append("occupies_peak_window")

    return int(_clamp(score)), signals


# --- Movability scoring -------------------------------------------------------

def score_movability(meeting: dict[str, Any]) -> tuple[int, list[str]]:
    """Score how easy it is to actually move this meeting.

    Returns (score 0-100, list of contributing signal names).
    """
    score = 0.0
    signals: list[str] = []

    # Signal 1: User is organizer
    if meeting.get("is_organizer", False):
        score += 30
        signals.append("is_organizer")

    # Signal 2: Small attendee count (≤3)
    attendees = meeting.get("attendees", [])
    if len(attendees) <= 3:
        score += 20
        signals.append("small_attendee_count")

    # Signal 3: Not recurring
    if not meeting.get("is_recurring", False):
        score += 20
        signals.append("not_recurring")

    # Signal 4: Not private/sensitive
    if not meeting.get("is_private", False):
        score += 10
        signals.append("not_private")

    # Signal 5: Optional attendees exist
    optional = [a for a in attendees if a.get("type") == "optional"]
    if optional:
        score += 5
        signals.append("has_optional_attendees")

    # Signal 6: Short duration (≤30 min)
    m_dur = _to_min(meeting.get("end", "0:30")) - _to_min(meeting.get("start", "0:00"))
    if m_dur <= 30:
        score += 10
        signals.append("short_duration")

    # Signal 7: Tentative/no responses
    responses = meeting.get("response_statuses", {})
    if responses:
        uncommitted = sum(1 for r in responses.values() if r in ("tentativelyAccepted", "none", "notResponded"))
        if uncommitted > len(responses) * 0.5:
            score += 5
            signals.append("uncommitted_attendees")

    return int(_clamp(score)), signals


# --- Recommendation generation ------------------------------------------------

# Professional reasons — no health/stress language
_REASONS = {
    "double_back_to_back": "No buffer before or after — limits preparation and follow-up.",
    "back_to_back": "Back-to-back with another meeting — limited transition time.",
    "long_in_cluster": "Long meeting in a dense cluster — consider spacing it out.",
    "no_prep_organizer": "You're organizing this meeting with no preparation buffer.",
    "no_prep_small_collab": "Collaborative meeting with no lead-in time.",
    "no_prep_long_meeting": "Extended meeting with no preparation buffer.",
    "after_hours": "Outside core hours — moving it could protect your evening.",
    "blocks_lunch": "This meeting blocks your lunch window.",
    "fragments_focus": "Removing this creates a long focus block.",
    "hr_spike": "This time slot has historically been high-pressure.",
    "hr_elevated_avg": "This slot tends to be demanding.",
    "no_hr_recovery": "Limited recovery time between this and the next session.",
    "occupies_peak_window": "This slot could be better used for deep-focus work.",
}


def _build_reason(signals: list[str]) -> str:
    """Pick the most relevant professional reason from the signals."""
    # Priority order
    priority = [
        "double_back_to_back", "after_hours", "blocks_lunch",
        "fragments_focus", "occupies_peak_window", "long_in_cluster",
        "back_to_back", "no_prep_organizer", "no_prep_long_meeting",
        "hr_spike", "no_hr_recovery", "hr_elevated_avg",
        "no_prep_small_collab",
    ]
    for sig in priority:
        if sig in signals:
            return _REASONS[sig]
    return "Moving this meeting could create better execution space."


def recommend(
    meetings: list[dict[str, Any]],
    *,
    date: str | None = None,
    wearable: dict[str, Any] | None = None,
    hrv: float | None = None,
) -> list[dict[str, Any]]:
    """Score all meetings and return prioritised reschedule recommendations.

    Args:
        meetings: List of meeting dicts with at least start, end, title.
        date: YYYY-MM-DD for deeplinks.
        wearable: Wearable data dict with resting_hr, hr_samples, etc.
        hrv: Daily HRV value (if available). Low HRV = lower thresholds.

    Returns:
        List of structured recommendations (max _MAX_RECS).
    """
    ordered = _ordered(meetings)
    if not ordered:
        return []

    # On low-HRV days, be more protective
    pressure_threshold = _PRESSURE_THRESHOLD
    if hrv is not None and hrv < 30:  # low HRV = depleted
        pressure_threshold = 25

    # Score every meeting
    scored: list[tuple[dict, int, int, list[str], list[str]]] = []
    for m in ordered:
        p_score, p_signals = score_pressure(m, meetings, wearable)
        m_score, m_signals = score_movability(m)
        scored.append((m, p_score, m_score, p_signals, m_signals))

    # Find free slots for suggesting destinations
    slots = _free_slots(ordered)
    longest = _longest_slot(slots)

    recs: list[dict[str, Any]] = []

    # --- Reschedule recommendations (pressure × movability) ---
    ranked = sorted(scored, key=lambda x: x[1] * x[2], reverse=True)
    for m, p_score, m_score, p_signals, m_signals in ranked:
        if p_score < pressure_threshold or m_score < _MOVABILITY_THRESHOLD:
            continue
        if len(recs) >= 2:  # max 2 reschedule recs
            break

        m_start = _to_min(m["start"])
        m_end = _to_min(m["end"])
        m_dur = m_end - m_start

        # Find a suitable destination slot
        dest = None
        for slot_start, slot_end in slots:
            if (slot_end - slot_start) >= m_dur and slot_start != m_start:
                dest = (slot_start, slot_start + m_dur)
                break

        if not dest:
            continue

        rec_type = "move_after_hours" if "after_hours" in p_signals else "reschedule"
        recs.append({
            "type": rec_type,
            "title": m.get("title", "Meeting"),
            "from": m["start"],
            "to": _to_hhmm(dest[0]),
            "end": _to_hhmm(dest[1]),
            "reason": _build_reason(p_signals),
            "pressure_score": p_score,
            "movability_score": m_score,
            "priority": p_score * m_score,
            "is_organizer": m.get("is_organizer", False),
            "outlook_url": _calendar_url(date),
            "auto_apply": False,  # affects others → needs user approval
        })

    # --- Protect lunch (self-only, auto-apply safe) ---
    if not _has_lunch(ordered):
        lo, hi = _LUNCH_WINDOW
        lunch_slots = _free_slots(ordered, lo, hi)
        lunch_slot = next(
            (s for s in lunch_slots if s[1] - s[0] >= _LUNCH_NEEDED), None
        )
        start = lunch_slot[0] if lunch_slot else 12 * 60
        recs.append({
            "type": "protect_lunch",
            "title": "Lunch break",
            "from": None,
            "to": _to_hhmm(start),
            "end": _to_hhmm(start + _LUNCH_NEEDED),
            "reason": "No lunch break today — block 30 min to recover.",
            "pressure_score": None,
            "movability_score": None,
            "priority": None,
            "is_organizer": True,
            "outlook_url": _compose_url("Lunch break", date, start, start + _LUNCH_NEEDED),
            "auto_apply": True,  # self-only
        })

    # --- Protect peak focus (self-only, wearable-informed) ---
    if longest and (longest[1] - longest[0]) >= _FOCUS_MIN:
        # Check if this block is in the user's calmest hours
        is_peak = False
        if wearable:
            resting_hr = wearable.get("resting_hr", 0)
            hr_samples = wearable.get("hr_samples", [])
            if resting_hr and hr_samples:
                calmest = _find_calmest_hours(hr_samples, resting_hr)
                block_hour = longest[0] // 60
                is_peak = block_hour in calmest[:3]

        f_start, f_end = longest[0], min(longest[0] + 120, longest[1])
        reason = (
            "You have a clear high-energy block — protect it for deep work."
            if is_peak else
            "You have a clear block — protect it for deep work."
        )
        recs.append({
            "type": "protect_peak_focus" if is_peak else "protect_focus",
            "title": "Focus time",
            "from": None,
            "to": _to_hhmm(f_start),
            "end": _to_hhmm(f_end),
            "reason": reason,
            "pressure_score": None,
            "movability_score": None,
            "priority": None,
            "is_organizer": True,
            "outlook_url": _compose_url("Focus time", date, f_start, f_end),
            "auto_apply": True,  # self-only
        })

    return recs[:_MAX_RECS]


# --- CLI test -----------------------------------------------------------------

if __name__ == "__main__":
    import json

    sample_meetings = [
        {"title": "Sprint Planning", "start": "09:00", "end": "10:00",
         "is_organizer": True, "attendees": [{"name": "A"}, {"name": "B"}],
         "is_recurring": False, "is_private": False},
        {"title": "Design Review", "start": "10:00", "end": "10:45",
         "is_organizer": False, "attendees": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
         "is_recurring": False, "is_private": False},
        {"title": "1:1 with Manager", "start": "10:45", "end": "11:15",
         "is_organizer": False, "attendees": [{"name": "Manager"}],
         "is_recurring": True, "is_private": False},
        {"title": "Workshop", "start": "13:00", "end": "14:30",
         "is_organizer": True, "attendees": [{"name": f"P{i}"} for i in range(8)],
         "is_recurring": False, "is_private": False},
        {"title": "Late Sync", "start": "18:30", "end": "19:00",
         "is_organizer": True, "attendees": [{"name": "A"}],
         "is_recurring": False, "is_private": False},
    ]

    sample_wearable = {
        "resting_hr": 62,
        "hr_samples": [
            {"time": "09:10", "bpm": 78}, {"time": "09:30", "bpm": 92},
            {"time": "09:50", "bpm": 88}, {"time": "10:05", "bpm": 85},
            {"time": "10:20", "bpm": 90}, {"time": "10:40", "bpm": 82},
            {"time": "11:00", "bpm": 72}, {"time": "14:00", "bpm": 68},
            {"time": "15:00", "bpm": 65}, {"time": "16:00", "bpm": 64},
        ],
    }

    print("=== Per-meeting scores ===")
    for m in sample_meetings:
        p, ps = score_pressure(m, sample_meetings, sample_wearable)
        mv, ms = score_movability(m)
        print(f"  {m['title']:25s}  pressure={p:3d} ({', '.join(ps)})  "
              f"movability={mv:3d} ({', '.join(ms)})  priority={p * mv}")

    print("\n=== Recommendations ===")
    recs = recommend(sample_meetings, date="2026-06-25", wearable=sample_wearable)
    print(json.dumps(recs, indent=2))
