"""Apple Watch client (demo: returns mock signals; HealthKit export parsing is a TODO)."""
from __future__ import annotations

from typing import Any


def get_daily_signals(date: str) -> dict[str, Any]:
    """Return normalised movement + heart-rate signals for a given day.

    Demo mode returns mock data. Replace the body with parsing of an Apple
    Health `export.xml`, or a HealthKit companion-app feed, when going live.
    """
    return {
        "source": "apple_watch",
        "date": date,
        "steps": 1200,
        "resting_hr": 58,
        "hr_samples": [
            {"time": "09:30", "bpm": 74},
            {"time": "10:30", "bpm": 91},
            {"time": "14:00", "bpm": 95},
            {"time": "19:45", "bpm": 83},
        ],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(get_daily_signals("2026-06-18"), indent=2))
