"""Focus-window analysis — *when* in the day you had capacity to do deep work.

Pawse's main score answers "how strained is today?". This companion answers a
different question: **which parts of the day were most/least conducive to
focused, productive work?**

There is no direct "productivity" sensor, so we build a transparent *proxy* for
focus capacity from the timestamped signals we already collect. For each
time-slot (one per heart-rate sample) we blend up to three components:

    1. Calm        — low physiological strain (HR, and HRV / stress if present),
                     reusing the same reference points as the strain scorer.
    2. Uninterrupted — the slot does not fall inside a meeting block.
    3. Energy      — nearest self-reported check-in ``energy_level`` (optional).

Each component is 0-100 (higher = better for focus). They are combined as a
weighted average **over whatever is present**, then slots are grouped into parts
of the day so we can name the peak window. Missing components (e.g. no check-ins,
or HR-only samples) are simply dropped and the weights renormalised — the same
graceful-degradation philosophy as the main score.

Run directly to analyse the sample day:

    python scoring/focus_windows.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

try:  # works both as a package (`scoring.focus_windows`) and as a script
    from scoring.pawse_score import (
        HR_ELEV_CALM, HR_ELEV_HIGH, HRV_CALM_MS, HRV_STRAINED_MS,
        _first, _hhmm_to_minutes, _ramp,
    )
except ImportError:  # running the file directly from inside scoring/
    from pawse_score import (  # type: ignore
        HR_ELEV_CALM, HR_ELEV_HIGH, HRV_CALM_MS, HRV_STRAINED_MS,
        _first, _hhmm_to_minutes, _ramp,
    )


# --- How much each component counts toward focus (renormalised over present) -
FOCUS_WEIGHTS = {
    "calm": 0.5,        # physiological readiness
    "uninterrupted": 0.3,
    "energy": 0.2,      # self-reported, optional
}

# Parts of the day, by minutes since midnight: (label, start, end)
DAY_PARTS = (
    ("Morning", 5 * 60, 12 * 60),
    ("Midday", 12 * 60, 14 * 60),
    ("Afternoon", 14 * 60, 17 * 60),
    ("Evening", 17 * 60, 23 * 60),
)


def _part_of_day(minute: int) -> str:
    for label, start, end in DAY_PARTS:
        if start <= minute < end:
            return label
    return "Off-hours"


def _in_meeting(minute: int, meetings: list[dict[str, Any]]) -> bool:
    """True if ``minute`` falls inside any meeting block."""
    for m in meetings:
        start = _hhmm_to_minutes(_first(m, "start", "start_time"))
        end = _hhmm_to_minutes(_first(m, "end", "end_time"))
        if start is None or end is None:
            continue
        if end < start:
            end += 24 * 60  # crosses midnight
        if start <= minute < end:
            return True
    return False


def _nearest_energy(minute: int, checkins: list[dict[str, Any]]) -> Optional[float]:
    """``energy_level`` of the check-in closest in time, or ``None`` if none."""
    best: Optional[float] = None
    best_gap = None
    for c in checkins:
        t = _hhmm_to_minutes(c.get("time"))
        energy = _first(c, "energy_level", "energy")
        if t is None or not isinstance(energy, (int, float)):
            continue
        gap = abs(minute - t)
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, float(energy)
    return best


def _calm_score(sample: dict[str, Any], resting_hr: float) -> Optional[float]:
    """Physiological calm (0-100, higher = calmer) for one sample.

    Blends whatever the sample carries: heart rate is the common case; HRV and a
    pre-computed ``stress_level`` (0-100) are folded in when present.
    """
    parts: list[float] = []
    bpm = _first(sample, "bpm", "heart_rate")
    if isinstance(bpm, (int, float)):
        parts.append(100 - _ramp(bpm - resting_hr, HR_ELEV_CALM, HR_ELEV_HIGH))
    hrv = _first(sample, "hrv", "hrv_ms", "hrv_avg")
    if isinstance(hrv, (int, float)):
        parts.append(100 - _ramp(hrv, HRV_CALM_MS, HRV_STRAINED_MS))
    stress = _first(sample, "stress_level", "stress")
    if isinstance(stress, (int, float)):
        parts.append(100 - max(0.0, min(100.0, float(stress))))
    if not parts:
        return None
    return sum(parts) / len(parts)


def _combine(calm: Optional[float], uninterrupted: float,
             energy: Optional[float]) -> float:
    """Weighted focus score over the components that are present."""
    components = {"calm": calm, "uninterrupted": uninterrupted, "energy": energy}
    total_w = sum(FOCUS_WEIGHTS[k] for k, v in components.items() if v is not None)
    if not total_w:
        return 0.0
    return sum(FOCUS_WEIGHTS[k] * v for k, v in components.items() if v is not None) / total_w


def focus_timeline(data: dict[str, Any]) -> dict[str, Any]:
    """Build a per-slot focus timeline and identify the peak/low windows.

    Returns a dict with:
      - ``slots``: list of ``{time, part, focus, calm, uninterrupted, energy}``
      - ``by_part``: average focus per part of the day (only parts with data)
      - ``peak_window`` / ``low_window``: best/worst part of the day
      - ``peak_slot``: the single highest-focus slot, with a one-line reason
      - ``available``: whether there was enough timestamped data to analyse
    """
    wearable = data.get("wearable", {}) or {}
    samples = wearable.get("hr_samples", []) or []
    meetings = data.get("meetings", []) or []
    checkins = data.get("checkins", []) or []
    resting_hr = _first(wearable, "resting_hr", "baseline_heart_rate") or 60

    slots: list[dict[str, Any]] = []
    for s in samples:
        minute = _hhmm_to_minutes(s.get("time"))
        if minute is None:
            continue
        calm = _calm_score(s, resting_hr)
        in_mtg = _in_meeting(minute, meetings)
        uninterrupted = 0.0 if in_mtg else 100.0
        energy = _nearest_energy(minute, checkins)
        focus = _combine(calm, uninterrupted, energy)
        slots.append({
            "time": s.get("time"),
            "part": _part_of_day(minute),
            "focus": round(focus),
            "calm": round(calm) if calm is not None else None,
            "uninterrupted": not in_mtg,
            "energy": round(energy) if energy is not None else None,
        })

    if not slots:
        return {
            "available": False,
            "slots": [],
            "by_part": {},
            "peak_window": None,
            "low_window": None,
            "peak_slot": None,
            "summary": "Not enough timestamped data to map your focus through the day.",
        }

    # Average focus per part of the day (preserve natural day order).
    by_part: dict[str, float] = {}
    for label, _, _ in DAY_PARTS:
        part_slots = [s["focus"] for s in slots if s["part"] == label]
        if part_slots:
            by_part[label] = round(sum(part_slots) / len(part_slots))

    peak_window = max(by_part, key=by_part.get) if by_part else None
    low_window = min(by_part, key=by_part.get) if by_part else None
    peak_slot = max(slots, key=lambda s: s["focus"])

    summary = (
        f"Your most productive window was the {peak_window.lower()} "
        f"(peak around {peak_slot['time']}) — {_peak_reason(peak_slot)}."
        if peak_window else
        "Not enough timestamped data to map your focus through the day."
    )

    return {
        "available": True,
        "slots": slots,
        "by_part": by_part,
        "peak_window": peak_window,
        "low_window": low_window,
        "peak_slot": peak_slot,
        "summary": summary,
    }


def _peak_reason(slot: dict[str, Any]) -> str:
    """One-line explanation of why a slot scored as a focus window."""
    bits = []
    if slot.get("calm") is not None and slot["calm"] >= 60:
        bits.append("calm physiology")
    if slot.get("uninterrupted"):
        bits.append("a meeting-free gap")
    if slot.get("energy") is not None and slot["energy"] >= 60:
        bits.append("high self-reported energy")
    return ", ".join(bits) if bits else "the most favourable mix of signals that day"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sample = root / "data" / "alex_workday.json"
    result = focus_timeline(_load(sample))
    print(json.dumps(result, indent=2, ensure_ascii=False))
