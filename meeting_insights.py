"""Per-meeting insight engine.

Turns the stored biomarker values of one finished meeting into:
  - human-readable REASONS (why each biomarker was measured the way it was), and
  - concrete RECOMMENDATIONS (actions to make future meetings calmer).

This is deliberately rule-based and transparent (no black box) so the dashboard
can explain itself. Pure stdlib — safe to import anywhere.
"""
from __future__ import annotations

from typing import Any

HIGH = 65
MED = 45

# marker key -> (nice label, explanation per level high/med/low)
_EXPLAIN = {
    "fatigue": (
        "Fatigue",
        "Frequent or long eye-closures (high PERCLOS) and yawning — a clear sign of tiredness or screen fatigue.",
        "Some elevated eye-closure and slower blinking — mild tiredness.",
        "Eyes stayed open and alert with a normal blink rate — little fatigue.",
    ),
    "emotion": (
        "Emotion",
        "Facial expression leaned negative (anger / worry / sadness) for noticeable stretches of the call.",
        "Occasional negative facial expressions, otherwise neutral.",
        "Mostly neutral or positive facial expression.",
    ),
    "tension": (
        "Muscle tension",
        "Frequent brow/forehead furrowing and jaw clenching (blendshapes) — concentration load or strain.",
        "Some brow furrowing now and then.",
        "Relaxed face — little brow or jaw tension.",
    ),
    "voice": (
        "Voice",
        "Raised pitch, more pitch jitter and fewer pauses — vocal signs of pressure or rushing.",
        "Slightly elevated vocal arousal at times.",
        "Calm, steady voice with natural pauses.",
    ),
}


def _level(v: float) -> str:
    return "high" if v >= HIGH else "med" if v >= MED else "low"


def _parse_hour(start: str | None) -> int | None:
    try:
        return int(str(start).split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def analyze_session(session: dict[str, Any]) -> dict[str, Any]:
    bm = session.get("biomarkers", {}) or {}
    distress = float(session.get("distress_score", 0) or 0)
    dur = int(session.get("duration_min", 0) or 0)
    hour = _parse_hour(session.get("start"))

    reasons = []
    for key, (label, hi, md, lo) in _EXPLAIN.items():
        v = round(float(bm.get(key, 0) or 0))
        lvl = _level(v)
        text = hi if lvl == "high" else md if lvl == "med" else lo
        reasons.append({"marker": key, "label": label, "value": v, "level": lvl, "text": text})

    # ----- concrete actions for next time -----
    recs: list[str] = []
    f = float(bm.get("fatigue", 0) or 0)
    e = float(bm.get("emotion", 0) or 0)
    t = float(bm.get("tension", 0) or 0)
    v = float(bm.get("voice", 0) or 0)

    if dur >= 60:
        recs.append(f"This meeting ran {dur} min — keep this type to 45 min or add a 5-min mid-point break.")
    if t >= HIGH:
        recs.append("Do a 30-second shoulder-and-jaw release just before the call to drop muscle tension.")
    if f >= HIGH:
        recs.append("Schedule demanding calls earlier in the day and take a 10-min screen break beforehand.")
    if e >= HIGH or v >= HIGH:
        recs.append("Send a short agenda with the desired outcome ahead of time — less in-call uncertainty lowers stress.")
    if v >= HIGH:
        recs.append("Build in deliberate pauses; ask one clarifying question instead of rushing to respond.")
    if hour is not None and hour >= 18:
        recs.append("This was a late meeting — try to move recurring evening calls into core hours.")
    if distress >= 70:
        recs.append("Add a 15-min recovery Pawse right after and avoid stacking another call back-to-back.")
    if not recs:
        recs.append("This meeting looked balanced — keep the same setup and cadence.")

    # ----- one-line summary -----
    drivers = sorted(
        ((r["label"], r["value"]) for r in reasons),
        key=lambda x: x[1], reverse=True,
    )
    top = ", ".join(f"{lab.lower()} ({val})" for lab, val in drivers[:2] if val >= MED)
    if distress >= 70:
        summary = f"High strain — mainly driven by {top}." if top else "High strain across several signals."
    elif distress >= MED:
        summary = f"Moderate strain — watch {top}." if top else "Moderate strain."
    else:
        summary = "Calm meeting — biomarkers stayed low."

    return {"summary": summary, "reasons": reasons, "recommendations": recs}
