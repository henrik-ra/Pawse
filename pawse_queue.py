"""Pawse task queue — the bridge between "Pawse recommends" and "Scout executes".

Pet/Dashboard (or the agent itself) **enqueue** reschedule tasks here; Microsoft
Scout's heartbeat **claims** them, applies the change on the real Microsoft 365
calendar with its native ``m365_*`` calendar tools, then marks them **done**.

State lives in ``data/.task_queue.json`` (per day). Tasks carry a stable id (so
the same action is never queued twice) and a lifecycle:

    needs_approval ──approve──► ready ──claim──► claimed ──complete──► done
            │                      ▲                 │
          reject                 fail (requeue) ◄────┘
            │
            ▼
         rejected

Self-only blockers (``protect_focus`` / ``protect_lunch``) enqueue straight to
``ready`` with ``auto_apply=True`` — safe for the heartbeat to apply unattended.
Anything that touches other attendees enqueues as ``needs_approval`` and waits
for an explicit human OK before it becomes claimable.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from pawse_events import _SELF_ONLY, _HIGH, _action_id  # reuse the same classification

_ROOT = Path(__file__).resolve().parent
_STATE = _ROOT / "data" / ".task_queue.json"

# A claimed task whose executor never reported back becomes claimable again after
# this long, so a crashed/abandoned heartbeat run can't block the queue forever.
_CLAIM_TTL_S = 900  # 15 minutes

# Statuses that mean "this action is still live" (used for de-duplication).
_ACTIVE = {"needs_approval", "ready", "claimed"}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": []}
    return {"tasks": []}


def _save(state: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _classify(rec_type: str) -> tuple[bool, str, str]:
    """(auto_apply, affects, initial_status) for a recommendation type."""
    if rec_type in _SELF_ONLY:
        return True, "self", "ready"
    return False, "others", "needs_approval"


def _public(task: dict[str, Any]) -> dict[str, Any]:
    """A copy safe to hand to an agent (no internal-only churn)."""
    return dict(task)


def enqueue(rec: dict[str, Any], *, date: str, source: str = "dashboard") -> dict[str, Any]:
    """Add a reschedule task to the queue (idempotent on the action id).

    ``rec`` is a recommendation dict (type, title, from, to, end, reason). Returns
    the task. If an active task with the same id already exists it is returned
    unchanged (no duplicate), so the dashboard, the pet and the agent can all
    enqueue the same suggestion safely.
    """
    rec_type = rec.get("type")
    tid = _action_id(date, rec)
    state = _load()
    tasks: list[dict[str, Any]] = state.setdefault("tasks", [])

    for t in tasks:
        if t["id"] == tid and t["status"] in _ACTIVE:
            return _public(t)

    auto_apply, affects, status = _classify(rec_type or "")
    task = {
        "id": tid,
        "date": date,
        "type": rec_type,
        "title": rec.get("title"),
        "from": rec.get("from"),
        "to": rec.get("to"),
        "end": rec.get("end"),
        "reason": rec.get("reason"),
        "outlook_url": rec.get("outlook_url"),
        "auto_apply": auto_apply,
        "affects": affects,
        "priority": "high" if rec_type in _HIGH else "normal",
        "status": status,
        "approved": False,
        "source": source,
        "enqueued_at": _now(),
        "updated_at": _now(),
        "claimed_at": None,
        "result": None,
        "error": None,
    }
    tasks.append(task)
    _save(state)
    return _public(task)


def _reclaim_stale(tasks: list[dict[str, Any]]) -> bool:
    """Revert claimed-but-abandoned tasks back to ready. Returns True if changed."""
    changed = False
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=_CLAIM_TTL_S)
    for t in tasks:
        if t["status"] == "claimed" and t.get("claimed_at"):
            try:
                claimed = _dt.datetime.fromisoformat(t["claimed_at"])
            except ValueError:
                continue
            if claimed < cutoff:
                t["status"] = "ready"
                t["claimed_at"] = None
                t["updated_at"] = _now()
                changed = True
    return changed


def list_tasks(status: str | None = None, date: str | None = None) -> list[dict[str, Any]]:
    """All tasks, optionally filtered by status and/or date (newest enqueue first)."""
    state = _load()
    tasks = state.get("tasks", [])
    if _reclaim_stale(tasks):
        _save(state)
    out = [
        _public(t)
        for t in tasks
        if (status is None or t["status"] == status)
        and (date is None or t["date"] == date)
    ]
    return sorted(out, key=lambda t: t.get("enqueued_at") or "", reverse=True)


def claim_next(*, auto_only: bool = True, executor: str = "scout") -> dict[str, Any] | None:
    """Claim the next executable task (and mark it ``claimed``), or None.

    A task is claimable when its status is ``ready``. With ``auto_only=True`` (the
    safe heartbeat default) only self-only ``auto_apply`` tasks **or** tasks a
    human has explicitly ``approved`` are handed out, so an unattended run never
    touches a meeting with other people that nobody OK'd. High-priority tasks are
    served first.
    """
    state = _load()
    tasks = state.get("tasks", [])
    _reclaim_stale(tasks)

    candidates = [
        t for t in tasks
        if t["status"] == "ready"
        and (not auto_only or t.get("auto_apply") or t.get("approved"))
    ]
    if not candidates:
        _save(state)
        return None

    # high priority first, then oldest enqueue.
    candidates.sort(key=lambda t: (t.get("priority") != "high", t.get("enqueued_at") or ""))
    task = candidates[0]
    task["status"] = "claimed"
    task["executor"] = executor
    task["claimed_at"] = _now()
    task["updated_at"] = _now()
    _save(state)
    return _public(task)


def _find(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    return next((t for t in tasks if t["id"] == task_id), None)


def complete(task_id: str, *, result: str | None = None) -> dict[str, Any] | None:
    """Mark a task ``done`` after the calendar change has been applied."""
    state = _load()
    task = _find(state.get("tasks", []), task_id)
    if task is None:
        return None
    task["status"] = "done"
    task["result"] = result or "applied"
    task["updated_at"] = _now()
    _save(state)
    return _public(task)


def fail(task_id: str, *, error: str, requeue: bool = True) -> dict[str, Any] | None:
    """Record a failed execution. By default the task goes back to ``ready`` for a
    later retry; set ``requeue=False`` to leave it parked in ``failed``."""
    state = _load()
    task = _find(state.get("tasks", []), task_id)
    if task is None:
        return None
    task["error"] = error
    task["status"] = "ready" if requeue else "failed"
    task["claimed_at"] = None
    task["updated_at"] = _now()
    _save(state)
    return _public(task)


def approve(task_id: str) -> dict[str, Any] | None:
    """Promote a ``needs_approval`` task to ``ready`` (human said yes)."""
    state = _load()
    task = _find(state.get("tasks", []), task_id)
    if task is None:
        return None
    if task["status"] == "needs_approval":
        task["status"] = "ready"
        task["approved"] = True
        task["updated_at"] = _now()
        _save(state)
    return _public(task)


def reject(task_id: str) -> dict[str, Any] | None:
    """Decline a proposed task — it leaves the active set (status ``rejected``)."""
    state = _load()
    task = _find(state.get("tasks", []), task_id)
    if task is None:
        return None
    task["status"] = "rejected"
    task["updated_at"] = _now()
    _save(state)
    return _public(task)


def summary(date: str | None = None) -> dict[str, Any]:
    """Counts per status (optionally for one day) — a compact queue health view."""
    tasks = list_tasks(date=date)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {
        "date": date,
        "total": len(tasks),
        "counts": counts,
        "ready": counts.get("ready", 0),
        "needs_approval": counts.get("needs_approval", 0),
    }


def reset(date: str | None = None) -> None:
    """Clear the queue (all, or just one day) — for demos/testing."""
    if date is None:
        if _STATE.exists():
            try:
                _STATE.unlink()
            except OSError:
                pass
        return
    state = _load()
    state["tasks"] = [t for t in state.get("tasks", []) if t["date"] != date]
    _save(state)
