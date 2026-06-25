---
name: Pawse Reschedule
description: Rebalances my workday using Pawse's energy + calendar recommendations — protects focus time and lunch, eases back-to-back stretches, and reschedules or declines meetings, always with my approval.
---

# Pawse Reschedule

Use this skill when I ask to "optimize my day", "rebalance my calendar",
"protect my focus", or "reschedule with Pawse".

## 1. Get the recommendations

Fetch today's recommendations from Pawse:

- If the **Pawse** plugin is installed, call its `getRecommendations` action
  (optionally pass a `date` in `YYYY-MM-DD`; default is today).
- Otherwise, ask me to paste the JSON from
  `https://<my-pawse-host>/api/recommendations` (or open it in Edge and read it).

Each recommendation has these fields:

| field | meaning |
| --- | --- |
| `type` | `reschedule`, `add_buffer`, `move_after_hours`, `protect_lunch`, `protect_focus` |
| `title` | meeting title, or `Focus time` / `Lunch break` for new holds |
| `from` | current start time (`null` for new holds) |
| `to` / `end` | suggested new start / end time |
| `reason` | short human-readable why |

## 2. Propose, then act only on approval

For each recommendation:

1. Show me the proposed change in plain language with its `reason`.
2. **Wait for my explicit approval.** These actions change my calendar — and
   some affect other people — so never proceed without it.

## 3. Apply by type (use your Calendar Management skill)

- **`protect_focus` / `protect_lunch`** — create a new event titled `title`
  from `to` to `end`, mark me as *Busy*. These affect only me.
- **`add_buffer` / `reschedule` / `move_after_hours`** — move the meeting
  titled `title` from `from` to the `to`–`end` slot.
  - If the meeting has **other attendees**, include a short, courteous note to
    the organizer (e.g. "Rebalancing my day to protect focus — does this new
    time work?"). **Never** change the agenda, subject, or attendee list.
  - If a meeting truly cannot move, offer to **decline** it with a polite reason
    instead — only on my approval.

## 4. Wrap up

Summarize exactly what you changed (and what you skipped) in one short list.

## Guardrails

- Pawse is a **performance/energy** helper, not a medical tool — never imply a
  diagnosis. Frame everything as protecting focus and sustainable performance.
- Always prefer **proposing** over auto-applying for anything that touches other
  people. Be brief, warm, and professional.
