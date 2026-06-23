# ⌚ Redmi / Xiaomi Watch — three live backends

This branch adds Redmi smartwatch support with **three interchangeable
backends** so you can see which one works best for your watch + setup. All three
return the same normalised signal dict (see [`../README.md`](../README.md)) and
all fall back to realistic **demo data**, so the dashboard never breaks.

| Backend | Real-time? | Needs | Best when |
|---|---|---|---|
| **A · BLE direct** ([`ble_client.py`](ble_client.py)) | ✅ Yes, live HR | PC Bluetooth + watch nearby | Live demo "the body doesn't lie" moment |
| **B · Gadgetbridge** ([`gadgetbridge_client.py`](gadgetbridge_client.py)) | ❌ As of last export | Android phone + Gadgetbridge | Most reliable; auth-locked models; full history |
| **C · Zepp / Mi Fit** ([`zepp_client.py`](zepp_client.py)) | ❌ Sync lag | Zepp Life / Mi Fit email login | Watches paired to **Zepp Life** |
| **D · Mi Fitness export** ([`mi_fitness_client.py`](mi_fitness_client.py)) | ❌ As of last export | Mi Fitness data export (zip/folder) | **Redmi Watch 4** (pairs to Mi Fitness) |

[`redmi_client.py`](redmi_client.py) is the **unified entry point** Pawse imports.
Pick a backend with `REDMI_BACKEND` (`ble` / `gadgetbridge` / `zepp` / `mifitness` / `auto`).

> **Redmi Watch 4 note:** it pairs to **Mi Fitness**, not Zepp Life, and uses
> Xiaomi's authenticated proprietary BLE protocol. That means **Option A (BLE)**
> only works if the watch has a *"Broadcast heart rate"* workout mode enabled,
> and **Option C (Zepp)** does *not* apply. Use **Option D (Mi Fitness export)**
> or **Option B (Gadgetbridge)** for real Redmi Watch 4 data.

---

## Compare all three at once

```powershell
python devices/redmi/redmi_client.py            # today
python devices/redmi/redmi_client.py 2026-06-18 # a specific day
```

This prints one line per backend (live vs demo, steps, current HR, sample count)
so you can immediately see which one is actually talking to your watch.

---

## Run the dashboard against the Redmi watch

```powershell
$env:PAWSE_WEARABLE = "redmi"        # use the Redmi watch instead of Google Health
$env:REDMI_BACKEND  = "auto"         # or ble / gadgetbridge / zepp
python server.py                     # → http://localhost:8000
```

---

## A · BLE direct (real-time)

```powershell
pip install bleak

python devices/redmi/ble_client.py --scan           # find your watch
python devices/redmi/ble_client.py --seconds 30     # stream live HR
```

Reads the **standard BLE Heart Rate Service** (`0x180D` / `0x2A37`).

- On the watch, **start a workout** or enable **Settings → Broadcast heart rate**
  so it advertises the standard HR characteristic.
- Steps are not exposed over this service — use backend B or C for daily steps.
- Some newer Redmi models use a proprietary, authenticated protocol and won't
  emit standard HR notifications. If `--scan` shows your watch but no HR arrives,
  use **Gadgetbridge** instead.

## B · Gadgetbridge (most reliable)

1. Install [Gadgetbridge](https://gadgetbridge.org) on Android and pair the watch.
2. **Settings → Database management → Export DB.**
3. Copy the file here, or point Pawse at it:

```powershell
$env:GADGETBRIDGE_DB = "C:\path\to\Gadgetbridge.db"
python devices/redmi/gadgetbridge_client.py            # today
python devices/redmi/gadgetbridge_client.py --tables   # inspect the schema
```

Gadgetbridge already did the watch's Bluetooth auth handshake, so the data is
complete — it's just only as fresh as your last export (auto-export can keep it
current).

## C · Zepp Life / Mi Fit cloud (unofficial)

Works for **Zepp Life / Mi Fit accounts that log in with a native email +
password** (not phone-number or Mi-account/Xiaomi-SSO logins). Uses an unofficial
Huami endpoint that may change or rate-limit.

> ⚠️ If you sign in to Zepp Life with **"Sign in with Mi account"** (Xiaomi SSO),
> this backend **cannot** authenticate — there's no Huami email/password to use.
> Use the **Mi Fitness export (D)** or **Gadgetbridge (B)** instead.

```powershell
$env:ZEPP_EMAIL    = "you@example.com"
$env:ZEPP_PASSWORD = "..."
python devices/redmi/zepp_client.py
```

Credentials can also go in a local `.env` next to the script (see
[`.env.example`](.env.example)). The login token is cached in `zepp_tokens.json`.

> ⚠️ This backend logs into a third-party cloud with your account password.
> It is unofficial and best-effort — prefer A or B if you can.

## D · Mi Fitness export (Redmi Watch 4)

The Redmi Watch 4 syncs to **Mi Fitness**, whose data lives in Xiaomi's cloud
with **no usable API**. Instead, export your data and let Pawse parse it:

1. In **Mi Fitness → Profile → Settings (gear) → Privacy → Export data**, or use
   the Xiaomi privacy portal <https://privacy.mi.com> → *Export my data* and pick
   the wearable / Mi Fitness data.
2. You'll get a `.zip` (or folder) of CSV/JSON files. Point Pawse at it:

```powershell
$env:MI_FITNESS_EXPORT = "C:\path\to\mi_fitness_export.zip"   # or a folder
python devices/redmi/mi_fitness_client.py --inspect            # see the files/columns
python devices/redmi/mi_fitness_client.py 2026-06-23           # parse a day
```

The export schema varies by region/version, so the parser is **heuristic** — it
looks for columns that resemble heart-rate/steps plus a timestamp. If a day comes
back empty, run `--inspect` and share the column names so the hints can be tuned.

---

## Output shape

Every backend returns:

```python
{
  "source": "redmi-ble",        # or redmi-gadgetbridge / redmi-zepp / redmi-mifitness
  "mode": "live",               # or "demo"
  "backend": "ble",             # which backend produced this (via redmi_client)
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
