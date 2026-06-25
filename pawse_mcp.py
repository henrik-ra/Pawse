"""Pawse MCP server — exposes Pawse's day + reschedule recommendations as tools.

A **local stdio** MCP server so agents (Microsoft Scout, GitHub Copilot CLI,
VS Code Copilot) can pull Pawse's energy/calendar recommendations and act on
them. No deploy, no tunnel — it runs on your machine, right next to the agent,
and computes everything from your local calendar cache + score engine.

Register in Microsoft Scout
---------------------------
Extensions (⋯ bottom-right) → MCP Servers → **+ Add Server** → **Command**:

    "C:\\Users\\<you>\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe" "C:\\Users\\<you>\\Github\\Pawse\\pawse_mcp.py"

Then in Scout: "Optimize my day with Pawse" → it calls ``get_recommendations``
and reschedules with your approval.

Tools
-----
get_recommendations(date?)  → concrete reschedule suggestions for a day
get_day(date?)              → the scored Pawse day (score, label, meetings, …)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("pawse")


def _scored_day(date: str | None) -> dict[str, Any]:
    """Build today's (or a given day's) scored Pawse day from local data."""
    from server import build_live_day  # imported lazily; never starts the server

    return build_live_day(date)


@mcp.tool()
def get_recommendations(date: str | None = None) -> dict[str, Any]:
    """Concrete reschedule recommendations for a workday.

    Protects focus time and lunch, eases back-to-back stretches, and moves
    after-hours meetings. ``date`` is YYYY-MM-DD (defaults to today). Each
    recommendation has: type, title, from, to, end, reason, outlook_url.
    """
    from scoring.meeting_optimizer import recommend

    day = _scored_day(date)
    data = day.get("data", {})
    recs = recommend(
        data.get("meetings", []),
        date=data.get("date") or date,
        score=day.get("pawse_score"),
    )
    return {"date": data.get("date"), "recommendations": recs}


@mcp.tool()
def get_day(date: str | None = None) -> dict[str, Any]:
    """The scored Pawse day: score, label, reasons, recommendations, and a
    compact summary of meetings, wearable and breaks. ``date`` is YYYY-MM-DD
    (defaults to today)."""
    day = _scored_day(date)
    data = day.get("data", {})
    wearable = data.get("wearable", {}) or {}
    return {
        "date": data.get("date"),
        "pawse_score": day.get("pawse_score"),
        "label": day.get("label"),
        "reasons": day.get("reasons", []),
        "recommendations": day.get("recommendations", []),
        "meetings": [
            {
                "title": m.get("title"),
                "start": m.get("start"),
                "end": m.get("end"),
                "back_to_back": m.get("back_to_back"),
                "after_hours": m.get("after_hours"),
            }
            for m in data.get("meetings", [])
        ],
        "wearable": {
            "steps": wearable.get("steps"),
            "resting_hr": wearable.get("resting_hr"),
        },
        "breaks": data.get("breaks", {}),
    }


@mcp.tool()
def get_pending_actions(date: str | None = None) -> dict[str, Any]:
    """For an agent heartbeat: return only NEW, not-yet-surfaced urgent actions
    for the day (reschedule / move after-hours / protect lunch). Returns an empty
    list when nothing new — so a periodic poll stays quiet until something changes.
    Calling this marks the returned actions as surfaced so they aren't repeated.
    Each item has: id, priority, type, title, from, to, end, reason."""
    import pawse_events
    from scoring.meeting_optimizer import recommend

    day = _scored_day(date)
    data = day.get("data", {})
    d = data.get("date") or date
    score = day.get("pawse_score")
    recs = recommend(data.get("meetings", []), date=d, score=score)
    new = pawse_events.pending(d, score, recs, mark=True)
    return {"date": d, "score": score, "count": len(new), "pending": new}


@mcp.tool()
def reset_pending_actions() -> dict[str, Any]:
    """Forget which actions were already surfaced, so the next get_pending_actions
    re-emits today's events. Useful for testing/demos."""
    import pawse_events

    pawse_events.reset()
    return {"ok": True}


if __name__ == "__main__":
    mcp.run()
