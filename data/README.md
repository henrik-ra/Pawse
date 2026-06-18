# 🥇 Task 1 — Core demo scenario (data)

> **Owners: Person 1 + Person 2**

This is the **single most important** part. It defines the entire story, score, and demo.

## Goal

Build **one perfect user story** — "Alex", a typical overloaded workday — combining:

- a full-day **calendar** (6–8 meetings, back-to-backs, no breaks, maybe after-hours)
- **wearable signals** (heart-rate spikes during 2 meetings, low step count)
- the **expected outcome** (high strain, e.g. 80+)

## Files

| File | What it is |
|---|---|
| [`alex_workday.json`](alex_workday.json) | The canonical sample day fed into the scoring engine |

## Data shape

```jsonc
{
  "user": "Alex",
  "date": "2026-06-18",
  "meetings": [ { "title", "start", "end", "back_to_back", "after_hours" } ],
  "wearable": {
    "steps": 0,
    "resting_hr": 0,
    "hr_samples": [ { "time", "bpm" } ]
  },
  "breaks": { "lunch_break": false, "longest_gap_minutes": 0 }
}
```

> No real user data is needed for the demo — everything here is synthetic.
