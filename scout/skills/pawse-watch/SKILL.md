---
name: Pawse Watch
description: Proactively check Pawse on a heartbeat and drain its reschedule queue — auto-apply self-only focus/lunch blocks on my real calendar, and surface meetings that need my OK. Use on a schedule/heartbeat, or when I ask "anything I should handle?", "check Pawse", "any energy alerts?", or "work my Pawse queue".
---

# Pawse Watch (heartbeat executor)

Run this on a heartbeat (every 30 min during work hours) or when I ask for a
proactive check. It turns Pawse's recommendations into **real calendar changes**
through the task queue. The Pawse MCP server exposes the queue; you apply the
changes with your native Microsoft 365 calendar tools (`m365_*`).

## Loop

1. **Refresh the queue** — call the **pawse** MCP tool **`sync_queue`** (optionally
   pass a `date`). It enqueues any new recommendations. Read the returned
   `queue` summary.

2. **Drain auto-applicable tasks** — repeat until empty:
   - Call **`claim_next_task`** with `auto_only: true`. It returns one self-only
     task (`protect_focus` / `protect_lunch`) and marks it `claimed`.
   - If `task` is `null`, stop the loop.
   - **Apply it on my real calendar** with your `m365_*` calendar tools: create an
     event titled `title`, from `to` to `end`, set me **Busy**. (Self-only — no
     attendees, no emails.)
   - On success call **`complete_task`** with the task `id` (put the new event id
     in `note`). On any error call **`fail_task`** with the `id` and the error —
     it re-queues for the next heartbeat. **Never leave a task `claimed`.**

3. **Surface, don't apply, shared moves** — call **`list_tasks`** with
   `status: "needs_approval"`. These touch other attendees. In heartbeat you are
   unattended, so **do not move them**. Briefly tell me they're waiting (meeting
   `title`, the suggested `to`–`end`, and `reason`) so I can approve later.

4. **Stay quiet when nothing happened** — if you applied nothing and there is
   nothing waiting for approval, send **no message**.

## Summary
End with a one-line recap: what you **auto-applied** and what is **waiting for my
approval**.

## Notes
- The queue **de-duplicates**, so the same action is never applied twice.
- Heartbeat applies **only** self-only blocks. Anything involving other people
  waits for my explicit approval (see the **Pawse Reschedule** skill).
- Pawse is a **performance/energy** helper — never imply a diagnosis.
