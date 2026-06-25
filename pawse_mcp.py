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
get_biomarkers(date?)       → per-meeting voice + face biomarkers (+ day rollup)
get_meeting_biomarkers(...) → biomarkers for one meeting by title

Task queue (Pawse recommends → Scout executes)
----------------------------------------------
sync_queue(date?)           → enqueue today's new recommendations as tasks
claim_next_task(auto_only?) → claim the next executable task (heartbeat-safe)
complete_task(id, note?)    → mark a task done after applying it
fail_task(id, error)        → record a failed apply (re-queues by default)
approve_task(id)/reject_task(id) → gate shared moves on explicit user OK
list_tasks(status?, date?)  → inspect the queue
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


# --- Task queue (Pawse recommends → Scout executes) -------------------------
# The heartbeat loop is: sync_queue → claim_next_task → (apply on the calendar)
# → complete_task. Self-only blockers are auto-applicable; shared moves wait in
# needs_approval until approve_task is called.


@mcp.tool()
def sync_queue(date: str | None = None) -> dict[str, Any]:
    """Refresh the task queue from today's recommendations and return its summary.

    Computes the day's reschedule recommendations and **enqueues any new ones**
    (idempotent — never duplicates). Self-only blockers (protect_focus /
    protect_lunch) enter as ``ready`` + ``auto_apply=true``; moves that affect
    other attendees enter as ``needs_approval``. Call this first on a heartbeat,
    then drain the queue with ``claim_next_task``. ``date`` is YYYY-MM-DD
    (defaults to today)."""
    import pawse_queue
    from scoring.meeting_optimizer import recommend

    day = _scored_day(date)
    data = day.get("data", {})
    d = data.get("date") or date
    recs = recommend(data.get("meetings", []), date=d, score=day.get("pawse_score"))
    enqueued = [pawse_queue.enqueue(r, date=d, source="agent") for r in recs]
    return {"date": d, "enqueued_or_existing": len(enqueued), "queue": pawse_queue.summary(d)}


@mcp.tool()
def list_tasks(status: str | None = None, date: str | None = None) -> dict[str, Any]:
    """List queued reschedule tasks, optionally filtered by ``status``
    (needs_approval / ready / claimed / done / failed / rejected) and/or ``date``.
    Each task has: id, type, title, from, to, end, reason, auto_apply, affects,
    priority, status, source."""
    import pawse_queue

    return {"tasks": pawse_queue.list_tasks(status=status, date=date)}


@mcp.tool()
def claim_next_task(auto_only: bool = True) -> dict[str, Any]:
    """Claim the next executable task for the agent to apply, or report empty.

    Returns one ``ready`` task and marks it ``claimed`` so no other run grabs it.
    With ``auto_only=true`` (the safe heartbeat default) only **self-only**
    blockers are handed out — an unattended run never touches a meeting with other
    people. Set ``auto_only=false`` in an interactive session to also drain
    approved shared moves. After applying the change on the real calendar, call
    ``complete_task``; on error call ``fail_task``. Returns ``{task: null}`` when
    nothing is claimable."""
    import pawse_queue

    task = pawse_queue.claim_next(auto_only=auto_only)
    return {"task": task}


@mcp.tool()
def complete_task(task_id: str, note: str | None = None) -> dict[str, Any]:
    """Mark a claimed task ``done`` after the calendar change was applied
    successfully. ``note`` is an optional short result (e.g. the new event id)."""
    import pawse_queue

    task = pawse_queue.complete(task_id, result=note)
    return {"ok": task is not None, "task": task}


@mcp.tool()
def fail_task(task_id: str, error: str, requeue: bool = True) -> dict[str, Any]:
    """Record that applying a task failed. By default it is re-queued (back to
    ``ready``) for a later retry; pass ``requeue=false`` to park it as ``failed``."""
    import pawse_queue

    task = pawse_queue.fail(task_id, error=error, requeue=requeue)
    return {"ok": task is not None, "task": task}


@mcp.tool()
def approve_task(task_id: str) -> dict[str, Any]:
    """Approve a proposed (``needs_approval``) task so it becomes claimable.

    Call this only after the user explicitly said yes to moving a meeting that
    involves other attendees. The task moves to ``ready`` and the next
    ``claim_next_task`` (auto_only=false) can apply it."""
    import pawse_queue

    task = pawse_queue.approve(task_id)
    return {"ok": task is not None, "task": task}


@mcp.tool()
def reject_task(task_id: str) -> dict[str, Any]:
    """Decline a proposed task (the user said no). It leaves the active queue."""
    import pawse_queue

    task = pawse_queue.reject(task_id)
    return {"ok": task is not None, "task": task}


@mcp.tool()
def reset_queue(date: str | None = None) -> dict[str, Any]:
    """Clear the task queue (all days, or just ``date``). For demos/testing."""
    import pawse_queue

    pawse_queue.reset(date)
    return {"ok": True}


@mcp.tool()
def get_biomarkers(date: str | None = None) -> dict[str, Any]:
    """Per-meeting voice + face biomarkers for a workday, with a day-level rollup.

    For each meeting returns voice signals (F0, jitter, shimmer, HNR, spectral
    shape, pitch variability, pause ratio) and face emotion mix, each summarized
    into a ``stress_index`` (0..1, higher = more strain). The day rollup has
    ``avg_stress_index``, ``day_strain_label`` and the ``peak_meeting``.

    ``date`` is YYYY-MM-DD (defaults to today); if that day has no data it falls
    back to the most recent available day so there is always something to read.

    These are **experimental, on-device** signals — soft context for energy
    coaching only, never a diagnosis or a claim about how the user feels.
    """
    import pawse_biomarkers

    return pawse_biomarkers.for_date(date)


@mcp.tool()
def get_meeting_biomarkers(title: str, date: str | None = None) -> dict[str, Any]:
    """Voice + face biomarkers for a single meeting by title (case-insensitive).

    ``title`` is the meeting name (e.g. "Sprint planning"); ``date`` is optional
    (YYYY-MM-DD). Returns ``{found: false}`` when no biomarkers exist for that
    meeting. Same privacy caveat as ``get_biomarkers``: experimental on-device
    context only, never a diagnosis."""
    import pawse_biomarkers

    m = pawse_biomarkers.for_meeting(title, date)
    if m is None:
        return {"found": False, "title": title, "date": date}
    return {"found": True, **m}


if __name__ == "__main__":
    import sys

    # Warm the wearable cache in the background at startup so the very first
    # tool call returns live data (e.g. Google Health from google_tokens.json)
    # fast, instead of doing a slow cold fetch that an agent might time out on.
    # Uses the same wearable as build_live_day; a no-op when not logged in.
    try:
        from server import prewarm

        prewarm()
    except Exception:
        pass

    if "--http" in sys.argv:
        # Remote MCP over streamable HTTP — for Copilot Studio / cloud agents.
        # Serves http://<host>:<port>/mcp. Default port 8765 (8000 is the web app).
        # Override with:  python pawse_mcp.py --http --port 8765
        port = 8765
        if "--port" in sys.argv:
            try:
                port = int(sys.argv[sys.argv.index("--port") + 1])
            except (ValueError, IndexError):
                pass
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # local stdio — Microsoft Scout, GitHub Copilot CLI
