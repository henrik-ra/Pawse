# Google Health API (Fitbit data via Google)

Reads daily **steps** and **heart-rate** through the **Google Health API** —
the official successor of the Fitbit Web API (the legacy Fitbit Web API shuts
down in **September 2026**).

- **Demo mode:** `google_health_client.py` returns mock data (no network, no OAuth).
  Active automatically while there is no `google_tokens.json`.
- **Live mode:** real Google Health API, used automatically once you have logged in.

> Your Fitbit / Pixel Watch keeps syncing to the Fitbit app as before — Pawse
> just reads that data through Google's API instead of the old Fitbit one.

## Go live in 5 steps

### 1. Create a Google Cloud project
Go to https://console.cloud.google.com/ → create a new project (e.g. `pawse`).

### 2. Enable the Health API
APIs & Services → **Enable APIs and Services** → search **"Health API"**
(`health.googleapis.com`) → **Enable**.

### 3. Configure the OAuth consent screen
APIs & Services → **OAuth consent screen**:
- User type: **External**
- Add your own Google account under **Test users** (this lets you use the
  sensitive health scopes without going through Google's full app verification).
- Add the scopes (these are the verified Google Health scopes):
    - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
    - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`

### 4. Create OAuth client credentials
APIs & Services → **Credentials** → **Create credentials** → **OAuth client ID**:
- Application type: **Web application**
- Authorised redirect URI: `http://localhost:8721/callback`

You now get a **Client ID** and **Client Secret** — you need both.

### 5. Log in once, then run the dashboard
```powershell
pip install -r requirements.txt

$env:GOOGLE_CLIENT_ID = "PASTE_CLIENT_ID.apps.googleusercontent.com"
$env:GOOGLE_CLIENT_SECRET = "PASTE_CLIENT_SECRET"

python devices/google_health/google_auth.py   # browser login -> google_tokens.json
python server.py                                # open http://localhost:8000
```
The header badge switches to **● LIVE** and the dashboard refreshes every 60s.

## Endpoints used (Google Health API v4)
- `GET /v4/users/me/dataTypes/steps/dataPoints` → steps (summed for the day)
- `GET /v4/users/me/dataTypes/daily-resting-heart-rate/dataPoints` → resting HR
- `GET /v4/users/me/dataTypes/heart-rate/dataPoints` → heart-rate samples

Base URL: `https://health.googleapis.com`. Data-type names are kebab-case in the
path (e.g. `daily-resting-heart-rate`).

Reference: https://developers.google.com/health/reference/rest

> The exact value field per data type can vary; the client extracts numeric
> readings defensively. If a field looks off after your first real response,
> check it with the parity tool: https://developers.google.com/health/migration/parity-tool

## Usage (from Python)
```python
from devices.google_health.google_health_client import get_daily_signals

signals = get_daily_signals("2026-06-18")  # live if logged in, else demo
```

## Security
`google_tokens.json` and `.env` contain secrets and are git-ignored — never
commit them.
