---
name: Pawse Watch
description: Proactively check Pawse for NEW urgent workday actions — a fresh back-to-back overload, a lost lunch break, or an after-hours meeting — and surface them. Use on a schedule/heartbeat, or when I ask "anything I should handle?", "check Pawse", "any energy alerts?", or "what changed on my calendar?".
---

# Pawse Watch

Run this on a heartbeat (e.g. every 30 minutes during work hours) or when I ask
for a proactive check.

1. Call the **pawse** MCP tool **`get_pending_actions`** (optionally pass a `date`).
2. If `count` is **0**, do **nothing** — stay silent. Do **not** message me with
   "nothing to do".
3. For **each** pending action, branch on `auto_apply`:
   - **`auto_apply: true`** (self-only — `protect_focus` / `protect_lunch`):
     **create the blocker automatically** with your Calendar Management skill
     (title `title`, from `to` to `end`, set me *Busy*). No approval needed — it
     only touches my own calendar. Just tell me you did it.
   - **`auto_apply: false`** (affects other attendees — `reschedule` /
     `move_after_hours` / `add_buffer`): **propose** it with its `reason` and
     apply only after my **explicit approval**; add a courteous note to the
     organizer and never change the agenda or attendees.
4. Summarize what you **auto-created** and what you **proposed**.

## Notes
- Pawse **de-duplicates** these actions, so you won't surface the same one twice.
- Never act on a meeting that involves other people without my approval.
- Pawse is a **performance/energy** helper — never imply a diagnosis.
