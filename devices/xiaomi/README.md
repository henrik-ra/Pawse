# ⌚ Xiaomi Watch — Gadgetbridge backend

This branch adds Xiaomi smartwatch support. The **Redmi Watch 4** uses Xiaomi's
encrypted, authenticated proprietary protocol, so the reliable way to read it is
via **[Gadgetbridge](https://gadgetbridge.org)** — an open-source Android app
that pairs with the watch and stores every sample in a local SQLite database.
Pawse reads that database and returns the normalised signal dict (see
[`../README.md`](../README.md)), falling back to realistic **demo data** so the
dashboard never breaks.

[`xiaomi_client.py`](xiaomi_client.py) is the **unified entry point** Pawse
imports; it routes to [`gadgetbridge_client.py`](gadgetbridge_client.py).

> Other approaches (direct BLE from the PC, the Zepp/Huami cloud, and the Mi
> Fitness data export) were prototyped but don't work for the Redmi Watch 4:
> it won't broadcast standard BLE heart rate, it pairs to Mi Fitness via Xiaomi
> SSO (no Huami email/password), and the Mi Fitness export takes ~15 days. Those
> backends were removed in favour of Gadgetbridge.

---

## Run the dashboard against the Xiaomi watch

```powershell
$env:PAWSE_WEARABLE = "xiaomi"       # use the Xiaomi watch instead of Google Health
python server.py                     # → http://localhost:8000
```

Check a day's signals directly:

```powershell
python devices/xiaomi/xiaomi_client.py            # today
python devices/xiaomi/xiaomi_client.py 2026-06-18 # a specific day
```

---

## Gadgetbridge setup

1. Install [Gadgetbridge](https://gadgetbridge.org) on Android and pair the
   watch (the Redmi Watch 4 needs the Xiaomi auth key — see the Gadgetbridge
   [pairing docs](https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/)).
2. **Settings → Database management → Export Data.**
3. Copy the file here, or point Pawse at it:

```powershell
$env:GADGETBRIDGE_DB = "C:\path\to\Gadgetbridge.db"
python devices/xiaomi/gadgetbridge_client.py            # today
python devices/xiaomi/gadgetbridge_client.py --tables   # inspect the schema
```

Gadgetbridge already did the watch's Bluetooth auth handshake, so the data is
complete — it's just only as fresh as your last export (auto-export can keep it
current).

### Automated sync ([`sync_gadgetbridge.ps1`](sync_gadgetbridge.ps1))

Instead of exporting and copying by hand, this script pulls the database from
the phone over **adb** — and with `-Trigger` it also tells Gadgetbridge to sync
the watch and export the DB first, so the run is fully hands-free.

> **Prerequisite:** Android Debug Bridge (`adb`) on PATH — it's a system tool,
> not a pip package. Install once with:
>
> ```powershell
> winget install Google.PlatformTools   # (adb)
> ```
>
> For `-Trigger`, enable in Gadgetbridge under *Settings → Developer options →
> Intent API*: **Allow activity sync trigger** and **Allow database export**.

```powershell
.\devices\xiaomi\sync_gadgetbridge.ps1 -Trigger                       # USB cable
.\devices\xiaomi\sync_gadgetbridge.ps1 -Trigger -Wireless 192.168.1.50:5555  # wireless adb
```

---

## Output shape

The backend returns:

```python
{
  "source": "xiaomi-gadgetbridge",
  "mode": "live",               # or "demo"
  "backend": "gadgetbridge",    # set by xiaomi_client
  "steps": 700,
  "resting_hr": 62,
  "hr_samples": [{"time": "09:30", "bpm": 88}, ...],
  "hr_avg": 84, "hr_min": 58, "hr_max": 142, "hr_current": 88,
  "hr_zones": {"out": 61, "fat_burn": 27, "cardio": 9, "peak": 3},
  "steps_by_hour": [...24...],
  "calories": 540, "distance_km": 0.53, "active_minutes": 18,
  "spo2_avg": 96, "hrv_avg": 42,
  "note": "…"                   # present in demo mode: why it fell back
}
```
