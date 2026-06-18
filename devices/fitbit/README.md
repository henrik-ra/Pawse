# Fitbit

Reads daily **steps** and **heart-rate** samples.

- **Demo mode:** `fitbit_client.py` returns mock data (no network, no OAuth).
- **Real mode (later):** Fitbit Web API — https://dev.fitbit.com/build/reference/web-api/
  - `GET /1/user/-/activities/date/{date}.json` → steps
  - `GET /1/user/-/activities/heart/date/{date}/1d.json` → heart rate

## Usage

```python
from devices.fitbit.fitbit_client import get_daily_signals

signals = get_daily_signals("2026-06-18")
```
