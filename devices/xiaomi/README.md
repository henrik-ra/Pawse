# ⌚ Xiaomi Watch — Gadgetbridge backend

This branch adds Xiaomi smartwatch support. The **Redmi Watch 4** uses Xiaomi's
encrypted, authenticated proprietary protocol, so the reliable way to read it is
via **[Gadgetbridge](https://gadgetbridge.org)**.

## What is Gadgetbridge?

**Gadgetbridge** is a free, open-source (AGPLv3) Android app that talks to your
watch or fitness band **directly over Bluetooth**, fully replacing the vendor's
app (Mi Fitness / Zepp / Huawei Health / etc.). It performs the proprietary
pairing and authentication handshake itself, then stores every sample it
receives — heart rate, steps, sleep, SpO₂, HRV, workouts — in a **local SQLite
database on the phone**. No vendor account, no cloud sign-in, and no internet
connection are required for it to work.

Pawse reads that database and returns the normalised signal dict (see
[`../README.md`](../README.md)), falling back to realistic **demo data** so the
dashboard never breaks. [`xiaomi_client.py`](xiaomi_client.py) is the **unified
entry point** Pawse imports; it routes to
[`gadgetbridge_client.py`](gadgetbridge_client.py).

> Other approaches (direct BLE from the PC, the Zepp/Huami cloud, and the Mi
> Fitness data export) were prototyped but don't work for the Redmi Watch 4:
> it won't broadcast standard BLE heart rate, it pairs to Mi Fitness via Xiaomi
> SSO (no Huami email/password), and the Mi Fitness export takes ~15 days. Those
> backends were removed in favour of Gadgetbridge.

## Your data stays local — no privacy trade-off

The **entire pipeline runs on hardware you own**, end to end — your health data
never touches a third-party server:

```
Watch ──BLE──▶ Gadgetbridge (your phone) ──adb pull──▶ your laptop ──▶ Pawse
```

- **No vendor cloud.** Gadgetbridge never uploads your biometrics to Xiaomi,
  Google, Fitbit or anyone else. Nothing leaves your devices.
- **No account or login.** No Mi Account, no Zepp SSO, no OAuth tokens to leak.
- **You own the raw data.** It's a plain SQLite file you can read, back up,
  query or delete at will — not locked behind a vendor API or app.
- **Works offline.** The sync runs over a USB cable or your local Wi-Fi; the
  public internet is never in the loop.
- **Auditable & open source.** Both Gadgetbridge and Pawse are open, so you can
  verify exactly what happens to your health data.

This is what lets Pawse stay **private, opt-in, and not a medical diagnosis** —
the biometrics that drive your score live and die on your own machines.

## Supported watches

Gadgetbridge is **not** Xiaomi-only: it supports **490+ devices from ~70
vendors** (see the always-current [device list](https://gadgetbridge.org/gadgets/)),
so this same local backend works far beyond the Redmi Watch 4. Supported watch
and band families include:

| Vendor | Example models |
| --- | --- |
| **Xiaomi / Redmi** | Redmi Watch 3/4/5, Mi Band 4–9, Smart Band 7–9, Watch S1/S3, Mi Watch |
| **Amazfit (Huami)** | Bip / Bip 3/5, GTR, GTS, T-Rex, Active, Balance, Band 5/7 |
| **Huawei / Honor** | Watch GT 2/3/4, Band 6/7/8/9, Magic Watch, Honor Band |
| **Garmin** | Forerunner, Fenix, Venu, Vívoactive, Instinct, Epix (+ HRM straps) |
| **Fossil / Skagen** | Hybrid HR, Gen 6 |
| **Pebble** | Pebble, Time, Time Steel, Round, Pebble 2 |
| **Withings** | Steel HR, ScanWatch |
| **Polar** | various HR-capable watches |
| **Nothing / CMF** | CMF Watch Pro, Watch 2 |
| **Casio** | G-Shock / GBD series |
| **Open-source watches** | PineTime (Pine64), Bangle.js, wasp-os |
| **Budget & niche** | Haylou, Colmi/Yawell, MyKronoz, Da Fit (Moyoung), SMA, HPlus, GloryFit, Lenovo, Sony, Soundbrenner, Ultrahuman, Coospo, FitPro, Keep Health, … |

> Support level varies by model: many are fully supported, a few are partial
> (some features still need the vendor app). Check the
> [official list](https://gadgetbridge.org/gadgets/) for your exact model.

To use a non-Xiaomi watch with Pawse, just pair it in Gadgetbridge — the
[`gadgetbridge_client.py`](gadgetbridge_client.py) backend reads whatever the
app has stored, regardless of brand.

---

## Run the dashboard against the Xiaomi watch

**One command (server + live background sync):**

```powershell
.\start.ps1                          # → http://localhost:8000, auto-syncs the watch
.\start.ps1 -IntervalSeconds 120     # slower sync cadence
.\start.ps1 -NoSync                  # serve the existing DB only, no live pulling
```

`start.ps1` launches the [`sync_gadgetbridge.ps1`](sync_gadgetbridge.ps1) loop
in the background (so the dashboard keeps getting fresh watch data) and the
server in the foreground. Press Ctrl+C to stop both.

**Server only** (serves whatever `Gadgetbridge.db` is already on disk — does
*not* pull fresh data):

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
