# ⌚ Devices — Live Wearable Integration

**Live device data is a core hackathon element.**
Showing real heart rate from a Fitbit or Apple Watch during the demo is the
moment that separates Pawse from every slide-only competitor.

All clients share the same interface and fall back to **realistic mock data**
when no credentials are present — the demo never breaks.

---

## Normalised output (all adapters)

```python
{
  "source": "fitbit",          # or "google-health", "apple-watch"
  "steps": 700,
  "resting_hr": 62,
  "hr_samples": [
    { "time": "09:30", "bpm": 88 },
    { "time": "10:30", "bpm": 96 },
    { "time": "14:00", "bpm": 99 }
  ]
}
```

---

## Available adapters

| Folder | Device | Live status | Recommended for |
|---|---|---|---|
| [`fitbit/`](fitbit/) | Fitbit (Charge, Versa, Sense, Luxe …) | ✅ Live + mock | **Hackathon primary** |
| [`google_health/`](google_health/) | Fitbit / Pixel Watch via Google Health API | ✅ Live + mock | Alternative / future-proof |
| [`apple-watch/`](apple-watch/) | Apple Watch (iOS Shortcut push) | 🟡 Option B ready | iPhone users |

---

## Quickstart — Fitbit (recommended)

```powershell
# 1. Get credentials at https://dev.fitbit.com/apps
$env:FITBIT_CLIENT_ID     = "YOUR_CLIENT_ID"
$env:FITBIT_CLIENT_SECRET = "YOUR_CLIENT_SECRET"

# 2. One-time browser login
python devices/fitbit/fitbit_auth.py

# 3. Use from anywhere
python server.py    # dashboard shows ● LIVE (Fitbit)
```

Full setup guide → [`fitbit/README.md`](fitbit/README.md)

---

## Quickstart — Apple Watch

No server-side Apple API exists. Instead, an **iOS Shortcut** pushes data
directly to the Pawse API once a day.

Full setup guide → [`apple-watch/README.md`](apple-watch/README.md)

---

## Demo mode (no device)

All clients activate mock data automatically when no token file is present:

```python
from devices.fitbit.fitbit_client import get_daily_signals

signals = get_daily_signals("2026-06-20")
# Returns mock data if fitbit_tokens.json doesn't exist — no crash, no setup
```

Mock data is deliberately realistic (HR spikes during meetings, low steps on
desk-heavy days) so the demo story holds even without a physical device.

---

## Adding a new adapter

Implement one function, return the normalised dict:

```python
# devices/my_device/my_device_client.py
def get_daily_signals(date: str) -> dict:
    return {
        "source": "my_device",
        "steps": ...,
        "resting_hr": ...,
        "hr_samples": [{"time": "HH:MM", "bpm": ...}, ...]
    }
```

Register it in `server.py` by importing and calling `get_daily_signals`.
The scoring engine and dashboard pick it up automatically.
