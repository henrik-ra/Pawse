# 🥈 Task 2 — Pawse Score + logic

> **Owners: Person 3 + Person 4**

This is the "AI" moment. If the logic doesn't feel believable, judges won't buy it.

## Goal

A single function: **input data → output score + reasons.**

## How the score works

The Pawse Score is a **fusion model** in the spirit of the stress scores from
Garmin (HRV-driven *Stress Level*), Whoop (*strain / recovery*) and Fitbit
(*Stress Management Score*). It blends three streams of signals, mapping each
to a 0–100 strain sub-score and combining them as a **weighted average over the
signals that are actually present**.

> **Optional signals are truly optional.** Missing inputs (no HRV, voice
> analysis off, the opt-in face analysis disabled, …) are dropped and their
> weight is redistributed — the score stays on the same 0–100 scale no matter
> how many sensors a user has enabled.

### The signals

| Stream | Signal | What it measures | Weight |
|---|---|---|---|
| Physiology | `hrv` | Heart-rate variability (RMSSD) — best recovery biomarker | 0.22 |
| Physiology | `heart_rate` | Elevation above resting + spikes during the day | 0.18 |
| Physiology | `sleep` | Previous-night sleep duration | 0.10 |
| Physiology | `movement` | Step count (sedentary = little recovery) | 0.08 |
| Physiology | `spo2` | Blood-oxygen dips | 0.05 |
| Behaviour | `meeting_load` | Total meeting time + count (+ after-hours) | 0.12 |
| Behaviour | `recovery` | Back-to-backs + no breaks | 0.10 |
| Perception | `voice` | Voice-biomarker stress index (opt-in) | 0.08 |
| Perception | `face` | Facial-expression stress index (**opt-in**) | 0.07 |

Each component reference threshold lives at the top of
[`pawse_score.py`](pawse_score.py) and is easy to tune per user.

Score is clamped to **0–100** and labelled:

- **0–39** → Low strain
- **40–69** → Medium strain
- **70–100** → High strain

### Opt-in face & voice analysis

`voice` and `face` are perception signals fed in from the analysis jobs as a
`stress_index` (0..1). They are **opt-in**: just add the block to the workday
JSON (an explicit `_consent: { "face": false }` can still veto it). The score
is fully valid with or without them.

```jsonc
"face": { "source": "webcam", "analyzed_frames": 120, "stress_index": 0.66 }
```

### Personalised baselines

A 35 ms HRV is "low" for one person and perfectly normal for another, so the
physiological signals are scored against **the user's own baseline** once we
have enough history. The flow is:

1. **Cold start (no baseline yet)** — the score still works immediately, using
   the population reference points at the top of `pawse_score.py`.
2. **Calibration window** — after the first `CALIBRATION_DAYS` (default **7**)
   a baseline is *established* and the score switches to personalised.
3. **Keeps improving** — it does **not** freeze at 7 days and is **not** limited
   to the last 7. The baseline is a **rolling, recency-weighted** estimate:
   - Only the last `BASELINE_WINDOW_DAYS` (default **60**) count, so stale data
     drops out and the baseline tracks the user's *current* normal.
   - Within that window each day decays exponentially
     (`BASELINE_HALF_LIFE_DAYS`, default **21** — a day's weight halves every 3
     weeks), so recent days matter more, yet more history still makes the
     estimate steadier.
   - A `confidence` value (0..1) grows from establishment up to a full window.

Personalised metrics: `hrv`, `spo2`, `sleep`, `steps` (each gets its own
ramp), plus a personal resting-HR baseline. Behavioural and perception signals
keep their fixed scale. Each per-metric anchor is clamped to a sane range so an
odd calibration window can't produce an absurd threshold.

Re-run calibration whenever new days arrive (e.g. nightly) — it recomputes from
the rolling window, so the baseline gets steadier over time without going
stale:

```powershell
python scoring/pawse_score.py calibrate data/history
```

This writes `data/baselines/<user>.json`. From then on `score_day()` (and the
live server) **auto-loads** it — no wiring needed — and the result reports the
state:

```jsonc
"baseline": {
  "status": "personalized",          // or "population" before calibration
  "days_collected": 42,              // days inside the rolling window
  "days_required": 7,
  "window_days": 60,
  "confidence": 0.66,                // grows as more history accumulates
  "personalized_metrics": ["hrv", "resting_hr", "sleep", "spo2", "steps"]
}
```

To personalise programmatically instead:

```python
from scoring.pawse_score import compute_baselines, score_day
baselines = compute_baselines(history)         # list of past workday dicts
result = score_day(today, baselines=baselines) # explicit override
```

## Run it

```powershell
python scoring/pawse_score.py
```

Outputs the Pawse Score, label, top reasons, recommendations, a
`component_scores` breakdown, and the `baseline` status for
`data/alex_workday.json`.
