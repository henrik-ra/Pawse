"""Storage for finished Teams-meeting biomarker sessions.

When a (simulated) Teams call ends, the Pawse recording app saves a compact
summary here: per-biomarker averages plus the overall distress score. The
dashboard reads these to show a "Teams meetings" panel.

Privacy by design: only derived scores are stored, never raw audio/video.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meeting_insights import analyze_session

_ROOT = Path(__file__).resolve().parent
SESSIONS_FILE = _ROOT / "data" / "teams_sessions.json"

_LABELS = ((70, "High strain"), (40, "Medium strain"), (0, "Low strain"))


def label_for(score: float) -> str:
    for thr, lab in _LABELS:
        if score >= thr:
            return lab
    return "Low strain"


def load_sessions() -> list[dict[str, Any]]:
    if not SESSIONS_FILE.exists():
        return []
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_session(session: dict[str, Any]) -> dict[str, Any]:
    """Append one finished meeting and persist it. Returns the stored session."""
    session = dict(session)
    score = float(session.get("distress_score", 0))
    session.setdefault("label", label_for(score))
    sessions = load_sessions()
    sessions.append(session)
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    return session


def sessions_for(date: str | None = None) -> dict[str, Any]:
    """Return sessions for a date, plus a recent fallback and a small summary."""
    alls = sorted(load_sessions(),
                  key=lambda s: (s.get("date", ""), s.get("start", "")))
    for_date = [s for s in alls if not date or s.get("date") == date]
    recent = list(reversed(alls))[:5]
    shown = for_date if for_date else recent
    for s in shown:
        s["insights"] = analyze_session(s)
    avg = round(sum(float(s.get("distress_score", 0)) for s in shown) / len(shown)) if shown else 0
    return {
        "sessions": shown,
        "is_fallback": (not for_date) and bool(recent),
        "summary": {"count": len(shown), "avg_distress": avg, "label": label_for(avg)},
    }
