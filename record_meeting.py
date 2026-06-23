"""Simulate finishing a Teams meeting: save its biomarker summary.

Run this when a (simulated) Teams call ends. It stores one meeting that then
appears in the dashboard's "Teams meetings" panel.

    python record_meeting.py --title "Sprint Planning" --distress 64
    python record_meeting.py --title "1:1" --fatigue 40 --emotion 35 --tension 55 --voice 30

With no biomarker arguments a plausible demo meeting for *now* is saved.
This is the hook the Pawse recording app calls on "leave meeting".
"""
from __future__ import annotations

import argparse
import datetime as dt
import random

from teams_sessions import label_for, save_session


def main() -> None:
    p = argparse.ArgumentParser(description="Save a finished Teams meeting.")
    p.add_argument("--title", default="Teams meeting")
    p.add_argument("--duration", type=int, default=30, help="meeting length in minutes")
    p.add_argument("--distress", type=float, default=None, help="overall 0-100")
    p.add_argument("--fatigue", type=float, default=None)
    p.add_argument("--emotion", type=float, default=None)
    p.add_argument("--tension", type=float, default=None)
    p.add_argument("--voice", type=float, default=None)
    a = p.parse_args()

    now = dt.datetime.now()
    bm = {
        "fatigue": a.fatigue if a.fatigue is not None else random.randint(30, 75),
        "emotion": a.emotion if a.emotion is not None else random.randint(25, 75),
        "tension": a.tension if a.tension is not None else random.randint(30, 80),
        "voice": a.voice if a.voice is not None else random.randint(25, 70),
    }
    distress = a.distress if a.distress is not None else round(sum(bm.values()) / len(bm))
    start = (now - dt.timedelta(minutes=a.duration)).strftime("%H:%M")

    session = {
        "id": f"tm-{now:%Y-%m-%d-%H%M}",
        "date": now.strftime("%Y-%m-%d"),
        "title": a.title,
        "start": start,
        "end": now.strftime("%H:%M"),
        "duration_min": a.duration,
        "distress_score": round(distress),
        "label": label_for(distress),
        "biomarkers": {k: round(v) for k, v in bm.items()},
        "source": "pawse-app",
    }
    save_session(session)
    print(f"Saved '{a.title}': distress {session['distress_score']} ({session['label']}).")
    print("Refresh the dashboard to see it under 'Teams meetings'.")


if __name__ == "__main__":
    main()
