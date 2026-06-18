# 🥈 Task 2 — Pawse Score + logic

> **Owners: Person 3 + Person 4**

This is the "AI" moment. If the logic doesn't feel believable, judges won't buy it.

## Goal

A single function: **input data → output score + reasons.**

## The signals (keep it to 3–5)

| Signal | Meaning | Weight |
|---|---|---|
| `meetings` | Number of meetings | +up to 25 |
| `back_to_backs` | Meetings with no recovery gap | +up to 20 |
| `no_breaks` | No lunch / short longest gap | +15 |
| `low_movement` | Low step count | +20 |
| `elevated_hr` | Heart-rate spikes during meetings | +20 |

Score is clamped to **0–100** and labelled:

- **0–39** → Low strain
- **40–69** → Medium strain
- **70–100** → High strain

## Run it

```powershell
python scoring/pawse_score.py
```

Outputs the Pawse Score, label, top reasons, and recommendations for `data/alex_workday.json`.
