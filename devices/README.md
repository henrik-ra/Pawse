# ⌚ Devices

Wearable integrations that feed **movement** and **heart-rate** signals into the Pawse Score.

Each device folder exposes a small client that returns a normalised dict:

```python
{
  "source": "fitbit",
  "steps": 700,
  "resting_hr": 62,
  "hr_samples": [ { "time": "10:30", "bpm": 96 } ]
}
```

| Folder | Device | Status |
|---|---|---|
| [`fitbit/`](fitbit/) | Fitbit (e.g. Fitbit / Fitbit "air") | stub + mock data |
| [`apple-watch/`](apple-watch/) | Apple Watch (HealthKit export) | stub + mock data |

> For the hackathon, the clients return **mock data** so the demo never depends on a
> live device or OAuth. Swap `get_*` internals for real API calls later.
