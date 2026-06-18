"""Fitbit client (demo: returns mock signals; real API wiring is a TODO)."""
from __future__ import annotations

from typing import Any


def get_daily_signals(date: str) -> dict[str, Any]:
    """Return normalised movement + heart-rate signals for a given day.

    Demo mode returns mock data. Replace the body with real Fitbit Web API
    calls (OAuth2 token required) when going live.
    """
    return {
        "source": "fitbit",
        "date": date,
        "steps": 700,
        "resting_hr": 62,
        "hr_samples": [
            {"time": "09:30", "bpm": 78},
            {"time": "10:30", "bpm": 96},
            {"time": "14:00", "bpm": 99},
            {"time": "19:45", "bpm": 88},
        ],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(get_daily_signals("2026-06-18"), indent=2))
