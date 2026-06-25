---
name: Pawse Reschedule
description: Rebalance my workday with Pawse — protect focus time and lunch, ease back-to-back stretches, and reschedule or decline meetings, always with my approval. Use when I ask to optimize my day, rebalance my calendar, protect my focus, fix my schedule, or "use Pawse" on my calendar.
---

# Pawse Reschedule (interactive executor)

When I ask to optimize my day, rebalance my calendar, or protect my focus. You
apply real changes via the Pawse task queue + your Microsoft 365 calendar tools
(`m365_*`).

1. **Build the queue** — call the **pawse** MCP tool **`sync_queue`** (optionally a
   `date`, default today). For my score/energy use **`get_day`**. Then call
   **`list_tasks`** to see what's queued.

2. **Walk me through it** — for each task tell me briefly what it is and its
   `reason`. Group self-only blocks (`protect_focus` / `protect_lunch`) and shared
   moves (`reschedule` / `move_after_hours` / `add_buffer`) separately.

3. **Apply only what I approve:**
   - **Self-only blocks** — once I say go, call **`claim_next_task`**
     (`auto_only: true`), create the event titled `title` from `to` to `end` set
     **Busy** with your `m365_*` tools, then **`complete_task`** with the `id`.
   - **Shared moves** — ask a clear yes/no that names the meeting and the exact
     change ("Move 'Project sync' from 09:30 to 08:00?"). On an explicit **yes**:
     call **`approve_task`** with the task `id`, then **`claim_next_task`**
     (`auto_only: false`), move the meeting `title` to the `to`–`end` slot, add a
     short courteous note to the organizer ("Rebalancing my day to protect focus —
     does this new time work?"), then **`complete_task`**. On **no**, call
     **`reject_task`** and change nothing. **Never** change the agenda, subject, or
     attendees. If a meeting truly can't move, offer to **decline** it politely
     instead — only on my approval.
   - On any apply error, call **`fail_task`** with the `id` and the error.

4. Summarize what you changed (and what you skipped) in one short list.

## Guardrails
- Pawse is a **performance/energy** helper, not a medical tool — never imply a
  diagnosis or label how I feel.
- Anything that touches **other people** is **proposed**, never auto-applied —
  it only moves after I explicitly approve (`approve_task`). Be brief, warm, and
  professional.
