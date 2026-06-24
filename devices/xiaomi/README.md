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

## Set up on your Android phone

A one-time setup gets the watch talking to Gadgetbridge and the phone talking to
your laptop. After that, `start.ps1` keeps everything in sync automatically.

### 1. Install Gadgetbridge

Install it from **[F-Droid](https://f-droid.org/app/nodomain.freeyourgadget.gadgetbridge)**
(the official, free build) or the [Gadgetbridge site](https://gadgetbridge.org).
It is **not** on the Google Play Store.

### 2. Pair the watch

1. If the watch is currently paired to **Mi Fitness / Zepp**, unpair it there
   first — only one app can hold the Bluetooth connection at a time.
2. In Gadgetbridge tap **＋ (add device)** and let it scan.
3. Xiaomi/Redmi watches are encrypted, so Gadgetbridge asks for an **auth key**.
   Follow the [Huami/Xiaomi pairing guide](https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/)
   to obtain it, and enter it prefixed with `0x` (e.g. `0x1234…`).
4. Select your watch and finish pairing — you should now see live data inside
   Gadgetbridge.

### 3. Turn on Gadgetbridge's Intent API

This lets the laptop trigger a watch sync + database export hands-free.

- Gadgetbridge → **Settings → Developer options → Intent API**, enable:
  - **Allow activity sync trigger**
  - **Allow database export**

### 4. Enable Android USB (or wireless) debugging

1. Settings → **About phone** → tap **Build number** seven times to unlock
   *Developer options*.
2. Settings → **Developer options** → enable **USB debugging** (and/or
   **Wireless debugging** if you want cable-free sync).

### 5. Connect the phone to your laptop

Make sure `adb` is installed on the laptop (one-time, puts it on PATH):

```powershell
winget install Google.PlatformTools
```

**Over USB:** plug the phone in, accept the *"Allow USB debugging?"* prompt on
the phone, then confirm it's visible:

```powershell
adb devices        # should list your phone as "device"
```

**Over Wi-Fi (Android 11+):** on the phone go to *Developer options → Wireless
debugging → Pair device with pairing code*, then:

```powershell
adb pair    <phone-ip>:<pair-port>     # enter the 6-digit code shown on the phone
adb connect <phone-ip>:<adb-port>
```

---

## Run Pawse

Once the phone is connected, start everything with **one command** (keep the
phone and watch nearby):

```powershell
.\start.ps1                          # → http://localhost:8000, auto-syncs every ~2 min
.\start.ps1 -IntervalSeconds 300     # slower cadence, gentler on battery
.\start.ps1 -NoSync                  # serve the existing DB only, no live pulling
```

`start.ps1` runs the [`sync_gadgetbridge.ps1`](sync_gadgetbridge.ps1) loop in the
background (so the dashboard keeps getting fresh watch data) and the server in
the foreground. Press **Ctrl+C** to stop both.

**One-off sync** (no loop) — over USB or Wi-Fi:

```powershell
.\devices\xiaomi\sync_gadgetbridge.ps1 -Trigger                              # USB
.\devices\xiaomi\sync_gadgetbridge.ps1 -Trigger -Wireless 192.168.1.50:5555  # wireless
```

**Server only** — serve whatever `Gadgetbridge.db` is already on disk, without
pulling new data:

```powershell
$env:PAWSE_WEARABLE = "xiaomi"
python server.py                     # → http://localhost:8000
```

**Inspect a day directly** (handy for debugging):

```powershell
python devices/xiaomi/xiaomi_client.py            # today
python devices/xiaomi/xiaomi_client.py 2026-06-18 # a specific day
```

> **No Intent API?** You can still sync manually: in Gadgetbridge use
> **Settings → Database management → Export Data**, then run the sync script
> *without* `-Trigger` (it just pulls the exported file), or point Pawse straight
> at an exported DB:
>
> ```powershell
> $env:GADGETBRIDGE_DB = "C:\path\to\Gadgetbridge.db"
> python devices/xiaomi/gadgetbridge_client.py            # today
> python devices/xiaomi/gadgetbridge_client.py --tables   # inspect the schema
> ```

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
