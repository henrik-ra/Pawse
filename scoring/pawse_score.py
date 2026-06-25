"""Pawse Score engine (Task 2).

Turns a workday data object into a Pawse Score (0-100), a strain label,
the top reasons, and recommendations.

Run directly to score the sample day:

    python scoring/pawse_score.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# --- Tunable thresholds & weights ------------------------------------------

LOW_STEPS_THRESHOLD = 3000
ELEVATED_HR_DELTA = 25  # bpm above resting counts as a spike

WEIGHTS = {
    "meetings": 25,
    "back_to_backs": 20,
    "no_breaks": 15,
    "low_movement": 20,
    "elevated_hr": 20,
}


def _score_meetings(data: dict[str, Any]) -> tuple[int, str | None]:
    count = len(data.get("meetings", []))
    if count >= 6:
        return WEIGHTS["meetings"], f"Heavy meeting load ({count} meetings)"
    if count >= 4:
        return WEIGHTS["meetings"] // 2, f"Busy meeting day ({count} meetings)"
    return 0, None


def _score_back_to_backs(data: dict[str, Any]) -> tuple[int, str | None]:
    b2b = sum(1 for m in data.get("meetings", []) if m.get("back_to_back"))
    if b2b >= 3:
        return WEIGHTS["back_to_backs"], f"{b2b} back-to-back meetings — little recovery time"
    if b2b >= 1:
        return WEIGHTS["back_to_backs"] // 2, f"{b2b} back-to-back meeting(s)"
    return 0, None


def _score_breaks(data: dict[str, Any]) -> tuple[int, str | None]:
    breaks = data.get("breaks", {})
    if not breaks.get("lunch_break", True):
        return WEIGHTS["no_breaks"], "No lunch break — poor recovery"
    return 0, None


def _score_movement(data: dict[str, Any]) -> tuple[int, str | None]:
    steps = data.get("wearable", {}).get("steps", 0)
    if steps < LOW_STEPS_THRESHOLD:
        return WEIGHTS["low_movement"], f"Low movement (only {steps} steps)"
    return 0, None


def _score_heart_rate(data: dict[str, Any]) -> tuple[int, str | None]:
    wearable = data.get("wearable", {})
    resting = wearable.get("resting_hr", 60)
    spikes = [s for s in wearable.get("hr_samples", []) if s.get("bpm", 0) - resting >= ELEVATED_HR_DELTA]
    if spikes:
        return WEIGHTS["elevated_hr"], f"Heart-rate spikes during {len(spikes)} meeting(s) — possible strain"
    return 0, None


SCORERS = (
    _score_meetings,
    _score_back_to_backs,
    _score_breaks,
    _score_movement,
    _score_heart_rate,
)


def _label(score: int) -> str:
    if score >= 70:
        return "High strain"
    if score >= 40:
        return "Medium strain"
    return "Low strain"


def _recommendations(reasons: list[str], data: dict[str, Any] | None = None) -> list[str]:
    recs: list[str] = []
    joined = " ".join(reasons).lower()
    if "meeting" in joined:
        recs.append("Block 30 minutes of recovery time tomorrow.")
        recs.append("Turn one meeting into an async update.")
    if "back-to-back" in joined:
        recs.append("Add 10-minute buffers between meetings.")
        # Smart Meeting Timing: suggest rescheduling when back-to-backs are detected
        if data and _has_movable_meetings(data):
            recs.append("Consider finding a time with more availability for all participants.")
    if "movement" in joined:
        recs.append("Take one walking 1:1.")
    if "lunch" in joined:
        recs.append("Protect a real lunch break.")
        if data and _has_movable_meetings(data):
            recs.append("Your calendar has limited prep or follow-up space around some meetings.")
    # Smart Meeting Timing: suggest moves for heavy meeting days
    if data and _should_suggest_meeting_move(data):
        recs.append("This meeting may be more effective in a lower-pressure slot.")
        recs.append("Moving a meeting could create better execution space.")
    return recs or ["Your day looks balanced — keep it up!"]


def _has_movable_meetings(data: dict[str, Any]) -> bool:
    """Check if there are meetings that could potentially be moved."""
    meetings = data.get("meetings", [])
    # At least one meeting that's back-to-back or in a dense cluster
    return any(m.get("back_to_back") for m in meetings)


def _should_suggest_meeting_move(data: dict[str, Any]) -> bool:
    """Determine if a meeting-move suggestion is warranted.

    Triggers when the day is heavily loaded (many meetings, poor breaks)
    without referencing any health/stress data.
    """
    meetings = data.get("meetings", [])
    breaks = data.get("breaks", {})
    if len(meetings) >= 5 and not breaks.get("lunch_break", True):
        return True
    b2b = sum(1 for m in meetings if m.get("back_to_back"))
    if b2b >= 3:
        return True
    return False


def score_day(data: dict[str, Any]) -> dict[str, Any]:
    """Score a single workday. Returns score, label, reasons, recommendations."""
    total = 0
    reasons: list[str] = []
    for scorer in SCORERS:
        points, reason = scorer(data)
        total += points
        if reason:
            reasons.append(reason)

    score = max(0, min(100, total))
    return {
        "user": data.get("user"),
        "date": data.get("date"),
        "pawse_score": score,
        "label": _label(score),
        "reasons": reasons,
        "recommendations": _recommendations(reasons, data),
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sample = Path(__file__).resolve().parent.parent / "data" / "alex_workday.json"
    result = score_day(_load(sample))
    print(json.dumps(result, indent=2, ensure_ascii=False))
