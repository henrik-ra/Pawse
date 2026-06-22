# 🍎 Apple Watch Integration

Reads **steps**, **resting heart rate**, and **heart-rate samples** from Apple Health (HealthKit).

- **Demo mode:** `apple_watch_client.py` returns realistic mock data — no setup needed.
- **Live mode (Option B — recommended):** An iOS Shortcut on your iPhone pushes
  data to the Pawse API once a day. No Apple server access required.

Apple does not offer a public cloud REST API for HealthKit, so Pawse uses a
**push-based approach**: the watch pushes data to us, rather than us pulling.

---

## Option B — iOS Shortcut push (recommended for live demo)

This is the fastest path to live Apple Watch data. The Shortcut runs automatically
at a set time each day and sends a JSON payload to the Pawse API.

### What you need

- iPhone with Apple Watch paired
- iOS Shortcuts app (pre-installed)
- Pawse server running (locally or on Azure)

### Step 1 — Add the Shortcut

1. Open **Shortcuts** on your iPhone
2. Tap **+** → **Add Action**
3. Search for **Get Health Sample** (Scripting > Health)
4. Add these three actions:

| Action | Health Type | Time Range |
|---|---|---|
| Get Health Sample | **Step Count** | Today |
| Get Health Sample | **Heart Rate** | Today |
| Get Health Sample | **Resting Heart Rate** | Today |

5. Add a **Dictionary** action to build the payload:
   ```
   source       → "apple-watch"
   steps        → [Steps result]
   resting_hr   → [Resting HR result]
   hr_samples   → [Heart Rate result as list]
   date         → [Current Date, formatted: YYYY-MM-DD]
   ```

6. Add a **Get Contents of URL** action:
   ```
   URL:    http://localhost:8000/api/wearable   (or your Azure URL)
   Method: POST
   Body:   JSON (the Dictionary from above)
   ```

7. Add **Automation** → **Time of Day** → 07:00 → Run this Shortcut

### Step 2 — Enable the Pawse API endpoint

`server.py` already handles `POST /api/wearable` and stores the payload for the
current day. Run the server before the Shortcut fires.

### Payload format the Shortcut should send

```json
{
  "source": "apple-watch",
  "date": "2026-06-20",
  "steps": 3420,
  "resting_hr": 58,
  "hr_samples": [
    { "time": "09:00", "bpm": 72 },
    { "time": "10:30", "bpm": 91 },
    { "time": "12:00", "bpm": 85 },
    { "time": "14:00", "bpm": 98 }
  ]
}
```

Once received, the dashboard shows **● LIVE (Apple Watch)** on the next refresh.

---

## Option A — HealthKit XML export (offline / batch)

1. On iPhone: **Health app → your avatar → Export All Health Data**
2. Unzip the archive, copy `apple_health_export/export.xml` to this folder
3. The parser reads steps + heart-rate samples from the XML:

```powershell
python devices/apple-watch/apple_watch_client.py --file export.xml --date 2026-06-20
```

Good for demoing a historical day. Not real-time.

---

## Usage from Python

```python
from devices.apple_watch.apple_watch_client import get_daily_signals

signals = get_daily_signals("2026-06-20")
# Returns pushed data if available, otherwise realistic mock data

print(signals["resting_hr"])    # e.g. 58
print(signals["hr_samples"])    # e.g. [{"time": "09:00", "bpm": 72}, ...]
```

---

## Mock data (no device)

When no live data has been pushed for the requested date, the client returns:

```python
{
    "source": "apple-watch-mock",
    "steps": 1200,
    "resting_hr": 58,
    "hr_samples": [
        {"time": "09:00", "bpm": 72},
        {"time": "10:30", "bpm": 88},
        {"time": "14:00", "bpm": 95},
        {"time": "16:00", "bpm": 79}
    ]
}
```

---

## Full architecture (production)

For the cloud deployment the Shortcut sends to the Azure Container Apps endpoint.
Payload is stored in Cosmos DB under the day document.
See [`docs/azure-architecture.md`](../../docs/azure-architecture.md) — Section 3a.
