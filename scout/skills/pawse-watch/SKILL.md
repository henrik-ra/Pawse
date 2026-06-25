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
3. If there are pending actions, for **each** one:
   - Tell me briefly what it is and its `reason`.
   - Offer to handle it, and **only after my explicit approval**, apply it with
     your Calendar Management skill:
     - move or decline meetings (with a short, courteous note to the organizer;
       never change the agenda or attendees), or
     - create `protect_focus` / `protect_lunch` holds (these affect only me).
4. Summarize what you changed.

## Notes
- Pawse **de-duplicates** these actions, so you won't surface the same one twice.
- Never act on a meeting that involves other people without my approval.
- Pawse is a **performance/energy** helper — never imply a diagnosis.
