"""Manually trigger one Pawse cycle — the heartbeat, on demand.

Instead of waiting for Scout's heartbeat, this runs the whole chain once and
shows exactly what would happen:

    real calendar (cache)  →  Pawse Score  →  recommendations  →  task queue

and prints the next task Scout would claim & apply. Use it to test the loop end
to end with a real meeting you just created.

Examples
--------
    # Just trigger today's cycle and show the queue:
    python tools/trigger_cycle.py

    # Inject a test meeting first (so you don't have to wait for a WorkIQ pull),
    # then trigger. A "blocker" has no other attendees → Pawse may move it and
    # Scout can apply it automatically.
    python tools/trigger_cycle.py --add "Test block,19:00,19:45,blocker"

    # Clear today's queue before triggering (fresh demo run):
    python tools/trigger_cycle.py --reset --add "Late sync,19:00,19:45,blocker"
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CACHE = _ROOT / "data" / "calendar_cache.json"


def _inject(date: str, specs: list[str]) -> None:
    """Add test meetings to the calendar cache for ``date``.

    Each spec is "Title,HH:MM,HH:MM" with an optional ",blocker" suffix marking
    it as a personal block (no other attendees → safe to move automatically).
    """
    cache = {"days": {}}
    if _CACHE.exists():
        cache = json.loads(_CACHE.read_text(encoding="utf-8"))
    cache.setdefault("days", {})
    day = cache["days"].setdefault(date, {"meetings": [], "source": "manual-test"})
    day.setdefault("meetings", [])
    for spec in specs:
        parts = [p.strip() for p in spec.split(",")]
        title, start, end = parts[0], parts[1], parts[2]
        is_blocker = len(parts) > 3 and parts[3].lower() in ("blocker", "self", "true", "1")
        # replace a same-title entry so re-running is idempotent
        day["meetings"] = [m for m in day["meetings"] if m.get("title") != title]
        day["meetings"].append(
            {"title": title, "start": start, "end": end, "is_blocker": is_blocker}
        )
        print(f"  + injected {'blocker' if is_blocker else 'meeting'}: {title} {start}-{end}")
    day["meetings"].sort(key=lambda m: m["start"])
    _CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Trigger one Pawse cycle on demand.")
    ap.add_argument("--date", default=_dt.date.today().isoformat(), help="YYYY-MM-DD (default today)")
    ap.add_argument("--add", action="append", default=[], metavar="SPEC",
                    help='Inject a test meeting "Title,HH:MM,HH:MM[,blocker]" (repeatable)')
    ap.add_argument("--reset", action="store_true", help="Clear the day's queue first")
    ap.add_argument("--claim", action="store_true",
                    help="Also claim the next auto-applicable task (show what Scout would apply)")
    args = ap.parse_args()

    import pawse_queue
    from scoring.meeting_optimizer import recommend
    from server import build_live_day

    date = args.date
    print(f"\n=== Pawse cycle for {date} ===")

    if args.add:
        print("Injecting test meeting(s) into the calendar cache:")
        _inject(date, args.add)

    if args.reset:
        pawse_queue.reset(date)
        print("Queue reset for the day.")

    # 1. Calendar → Score
    day = build_live_day(date)
    data = day.get("data", {})
    print(f"\nPawse Score: {day.get('pawse_score')}  ({day.get('label')})")
    print(f"Calendar source: {day.get('calendar_source')}  ·  {len(data.get('meetings', []))} meetings")

    # 2. Recommendations
    recs = recommend(data.get("meetings", []), date=date, score=day.get("pawse_score"))
    print(f"\nRecommendations ({len(recs)}):")
    for r in recs:
        print(f"  - [{r.get('type')}] {r.get('title')} → {r.get('to')}–{r.get('end')}  ({r.get('reason')})")
    if not recs:
        print("  (none — nothing to rebalance)")

    # 3. Enqueue (same as the agent's sync_queue) + show the queue
    for r in recs:
        pawse_queue.enqueue(r, date=date, source="manual-trigger")
    summary = pawse_queue.summary(date)
    print(f"\nQueue: {summary['total']} task(s) — ready={summary['ready']}, "
          f"needs_approval={summary['needs_approval']}")
    for t in pawse_queue.list_tasks(date=date):
        flag = "AUTO" if t["auto_apply"] else ("APPROVED" if t.get("approved") else "needs approval")
        print(f"  • [{t['status']:<13}] {t['title']:<22} {t['to']}–{t['end']}  ({flag})  id={t['id']}")

    # 4. Optionally show what Scout's heartbeat would grab next
    if args.claim:
        task = pawse_queue.claim_next(auto_only=True)
        print("\nNext task Scout's heartbeat would apply (auto_only):")
        if task:
            print(f"  → CREATE/MOVE '{task['title']}' to {task['to']}–{task['end']}  (id={task['id']})")
            print("    (Scout applies this on the real calendar via m365_* tools, then complete_task)")
        else:
            print("  → nothing auto-applicable (only shared moves waiting for approval)")

    print("\nDone. Scout's Pawse Watch skill will drain this queue on its next heartbeat.\n")


if __name__ == "__main__":
    main()
