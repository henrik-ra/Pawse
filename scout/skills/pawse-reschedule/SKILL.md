---
name: Pawse Reschedule
description: Rebalance my workday with Pawse — protect focus time and lunch, ease back-to-back stretches, and reschedule or decline meetings, always with my approval. Use when I ask to optimize my day, rebalance my calendar, protect my focus, fix my schedule, or "use Pawse" on my calendar.
---

# Pawse Reschedule

When I ask to optimize my day, rebalance my calendar, or protect my focus:

1. Call the **pawse** MCP tool **`get_recommendations`** (optionally pass a `date`
   as `YYYY-MM-DD`; default is today). For my score/energy, use **`get_day`**.
2. For each recommendation, tell me briefly what it is and its `reason`.
3. **Only after my explicit approval**, apply it using your Calendar Management skill:
   - **`protect_focus` / `protect_lunch`** — create a new event titled `title`
     from `to` to `end` and set me as *Busy*. These affect only me.
   - **`reschedule` / `move_after_hours` / `add_buffer`** — move the meeting
     `title` from `from` to the `to`–`end` slot. If it has **other attendees**,
     add a short, courteous note to the organizer (e.g. "Rebalancing my day to
     protect focus — does this new time work?"). **Never** change the agenda,
     subject, or attendees. If a meeting truly can't move, offer to **decline** it
     politely instead — only on my approval.
4. Summarize what you changed (and what you skipped) in one short list.

## Guardrails
- Pawse is a **performance/energy** helper, not a medical tool — never imply a
  diagnosis or label how I feel.
- For anything that touches **other people**, always **propose** rather than
  auto-apply. Be brief, warm, and professional.
