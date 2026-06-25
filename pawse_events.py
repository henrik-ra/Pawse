"""Pawse event detection — turn a scored day into de-duplicated "pending actions".

So an agent heartbeat (Microsoft Scout) can poll Pawse and only ever surface
*new* events: when something genuinely changed (a fresh back-to-back overload, a
lost lunch break, an after-hours meeting), an action appears; once surfaced it
won't repeat. State is per-day in ``data/.pending_actions.json``.

Used by the ``get_pending_actions`` MCP tool.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_STATE = _ROOT / "data" / ".pending_actions.json"

# Recommendation types that count as an *event* worth waking the agent for.
# protect_focus is intentionally excluded — it's a nice-to-have, not an alert.
_EVENT_TYPES = {"reschedule", "move_after_hours", "protect_lunch", "add_buffer"}
_HIGH = {"reschedule", "move_after_hours"}


def _action_id(date: str, rec: dict[str, Any]) -> str:
    raw = f"{date}|{rec.get('type')}|{rec.get('title')}|{rec.get('to')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def detect(date: str, score: int | None, recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build event objects (stable id + priority) from a day's recommendations."""
    events: list[dict[str, Any]] = []
    for rec in recommendations:
        if rec.get("type") not in _EVENT_TYPES:
            continue
        events.append({
            "id": _action_id(date, rec),
            "date": date,
            "score": score,
            "priority": "high" if rec.get("type") in _HIGH else "normal",
            **rec,
        })
    return events


def _load() -> dict[str, Any]:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(state: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def pending(
    date: str,
    score: int | None,
    recommendations: list[dict[str, Any]],
    *,
    mark: bool = True,
) -> list[dict[str, Any]]:
    """Return NEW (not-yet-surfaced) events for ``date``.

    State resets automatically on a new day. When ``mark`` is True, the returned
    events are recorded as surfaced so a later poll won't repeat them.
    """
    events = detect(date, score, recommendations)
    state = _load()
    if state.get("date") != date:
        state = {"date": date, "surfaced": []}
    surfaced = set(state.get("surfaced", []))
    new = [e for e in events if e["id"] not in surfaced]
    if mark and new:
        state["surfaced"] = sorted(surfaced | {e["id"] for e in new})
        state["updatedAt"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        _save(state)
    return new


def reset() -> None:
    """Forget what has been surfaced (so the next poll re-emits today's events)."""
    if _STATE.exists():
        try:
            _STATE.unlink()
        except OSError:
            pass
