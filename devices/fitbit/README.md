# ⌚ Fitbit Integration

Reads live **steps**, **resting heart rate**, and **intraday heart-rate samples**
directly from the Fitbit Web API.

**This is the recommended primary device integration for the hackathon.**
A real Fitbit HR spike during the demo is the moment that makes the Pawse Score feel
undeniably real — no slide can replace it.

- **Demo mode:** returns realistic mock data automatically (no OAuth needed).
- **Live mode:** activates automatically once you have run `fitbit_auth.py`.

> **Transition note:** The Fitbit Web API is scheduled to shut down in September 2026.
> The [`google_health/`](../google_health/README.md) adapter reads the same Fitbit
> data via Google Health API and is the long-term path. For the hackathon, the direct
> Fitbit API is simpler to set up and fully functional today.

---

## Go live in 4 steps

### 1. Create a Fitbit developer app

Go to [dev.fitbit.com/apps](https://dev.fitbit.com/apps) → **Register a new app**:

| Field | Value |
|---|---|
| Application Name | Pawse |
| OAuth 2.0 Application Type | **Personal** |
| Callback URL | `http://localhost:8721/callback` |
| Default Access Type | **Read Only** |

After saving you get a **Client ID** and **Client Secret**.

### 2. Set credentials

```powershell
$env:FITBIT_CLIENT_ID     = "PASTE_CLIENT_ID"
$env:FITBIT_CLIENT_SECRET = "PASTE_CLIENT_SECRET"
```

Or create a `.env` file (see `.env.example` in this folder — never commit it).

### 3. Authenticate once

```powershell
pip install -r requirements.txt
python devices/fitbit/fitbit_auth.py
```

Your browser opens → log in → **Allow**. A `fitbit_tokens.json` is saved locally.
Tokens refresh automatically from then on.

### 4. Run the live dashboard

```powershell
python server.py
# open http://localhost:8000
```

The header badge shows **● LIVE (Fitbit)** and the dashboard refreshes every 60 s
with real heart-rate data.

---

## API endpoints used

| Endpoint | Data |
|---|---|
| `GET /1/user/-/activities/date/{date}.json` | Steps + resting HR |
| `GET /1/user/-/activities/heart/date/{date}/1d.json` | Intraday heart rate |

> Per-minute intraday heart rate requires extra Fitbit developer approval.
> Without it you still get steps + resting HR; the HR chart shows fewer points
> but the demo still works.

---

## Usage from Python

```python
from devices.fitbit.fitbit_client import get_daily_signals

signals = get_daily_signals("2026-06-20")
# Live if fitbit_tokens.json exists, otherwise returns mock data

print(signals["resting_hr"])     # e.g. 62
print(signals["hr_samples"])     # e.g. [{"time": "09:30", "bpm": 88}, ...]
```

---

## What the live badge looks like

```
┌──────────────────────────────┐
│  🐼 Pawse          ● LIVE (Fitbit)  │
│                                │
│  Score: 82 / 100               │
│  High Strain                   │
└──────────────────────────────┘
```

---

## Security

`fitbit_tokens.json` and `.env` contain secrets and are git-ignored.
Never commit them.
