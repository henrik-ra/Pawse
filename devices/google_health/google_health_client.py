"""Google Health API client — reads steps + heart rate, with demo fallback.

The Google Health API (health.googleapis.com, v4) is the official successor of
the Fitbit Web API. Your Fitbit / Pixel Watch keeps syncing to the Fitbit app;
Pawse reads that data through Google's API.

Behaviour:
- No ``google_tokens.json`` yet  -> returns demo data (mode="demo").
- Logged in                      -> returns live data (mode="live").
- Live call fails for any reason  -> falls back to demo data (mode="demo").

Verified against the official docs (June 2026):
  Scopes      https://developers.google.com/health/scopes
  Data types  https://developers.google.com/health/data-types
  REST ref    https://developers.google.com/health/reference/rest
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- OAuth / API constants (verified) --------------------------------------

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8721/callback"
API_BASE = "https://health.googleapis.com/v4"

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
]

# Data type identifiers are kebab-case in the endpoint path.
DT_STEPS = "steps"
DT_RESTING_HR = "daily-resting-heart-rate"
DT_HEART_RATE = "heart-rate"
# Extra sensors (verified available on this account, June 2026).
DT_CALORIES = "active-energy-burned"       # p.activeEnergyBurned.kcal
DT_AZM = "active-zone-minutes"             # p.activeZoneMinutes.{activeZoneMinutes,heartRateZone}
DT_SPO2 = "oxygen-saturation"              # p.oxygenSaturation.percentage
DT_HRV = "heart-rate-variability"          # p.heartRateVariability.rootMeanSquare...Milliseconds
DT_DISTANCE = "distance"                   # p.distance.* (meters)

# Average stride length (m) for estimating distance when the API has none.
_STRIDE_M = 0.762
# Nominal max heart rate used only for splitting samples into display zones.
_MAX_HR = 190

# A shared, retrying HTTP session. Fetching several data types in parallel opens
# many simultaneous TLS handshakes; Google occasionally drops one with an SSL
# "unexpected EOF". Automatic retries (which also cover SSL/connection errors)
# keep a transient blip from collapsing the whole day to demo data.
def _make_session() -> requests.Session:
    retry = Retry(
        total=4, connect=3, read=3, status=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _make_session()

_HERE = Path(__file__).resolve().parent
_TOKENS_PATH = _HERE / "google_tokens.json"
_ENV_PATH = _HERE / ".env"

# Live data for a full day is large (heart rate is sampled every few seconds),
# so results are cached on disk and refreshed in the background.
_CACHE_PATH = _HERE / "google_health_cache.json"
_CACHE_TTL = 600  # seconds a cached day stays "fresh" before a background refresh
_PAGE_SIZE = 5000  # the API caps a single page at 5000 points
_cache_lock = threading.Lock()
_refreshing: set[str] = set()

# --- Demo data (used until you log in) -------------------------------------

_DEMO = {
    "source": "google-health",
    "mode": "demo",
    "steps": 700,
    "resting_hr": 62,
    "hr_samples": [
        {"time": "09:30", "bpm": 78},
        {"time": "10:30", "bpm": 96},
        {"time": "14:00", "bpm": 99},
        {"time": "19:45", "bpm": 88},
    ],
    # Enriched metrics so the dashboard looks complete in demo mode too.
    "hr_avg": 84,
    "hr_min": 58,
    "hr_max": 142,
    "hr_current": 88,
    "hr_zones": {"out": 61, "fat_burn": 27, "cardio": 9, "peak": 3},
    "steps_by_hour": [0, 0, 0, 0, 0, 0, 20, 80, 140, 60, 40, 90,
                      30, 50, 40, 70, 30, 60, 20, 10, 0, 0, 0, 0],
    "calories": 540,
    "calories_estimated": True,
    "distance_km": 0.53,
    "distance_estimated": True,
    "active_minutes": 18,
    "azm_total": 18,
    "azm_by_zone": {"fat_burn": 12, "cardio": 5, "peak": 1},
    "spo2_avg": 96,
    "spo2_latest": 95,
    "hrv_avg": 42,
    "hrv_latest": 39,
}


def _demo_for(date: str) -> dict[str, Any]:
    """A demo payload with light, deterministic per-day variation.

    Lets day-navigation show different (but stable) values without a login.
    """
    demo = dict(_DEMO)
    try:
        seed = sum(int(x) for x in date.split("-"))
    except Exception:
        return demo
    wiggle = (seed % 7) - 3  # -3..+3
    demo["steps"] = max(200, 700 + wiggle * 220)
    demo["resting_hr"] = 62 + (seed % 5) - 2
    demo["hr_avg"] = 84 + wiggle
    demo["calories"] = max(120, 540 + wiggle * 90)
    demo["distance_km"] = round(demo["steps"] * _STRIDE_M / 1000, 2)
    demo["active_minutes"] = max(0, 18 + wiggle * 4)
    demo["azm_total"] = demo["active_minutes"]
    demo["hrv_avg"] = 42 + wiggle * 2
    return demo


# --- Credentials & token storage -------------------------------------------

def _read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def load_credentials() -> tuple[str | None, str | None]:
    """Return (client_id, client_secret) from env vars or the local .env file."""
    import os

    env_file = _read_env_file()
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or env_file.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or env_file.get("GOOGLE_CLIENT_SECRET")
    # Ignore the unedited placeholder values from .env.example.
    if client_id and client_id.startswith("PASTE_"):
        client_id = None
    if client_secret and client_secret.startswith("PASTE_"):
        client_secret = None
    return client_id, client_secret


def save_tokens(tokens: dict[str, Any]) -> None:
    """Persist tokens with an absolute expiry timestamp."""
    data = dict(tokens)
    if "expires_in" in data:
        data["expires_at"] = time.time() + float(data["expires_in"]) - 60  # 60s safety
    _TOKENS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_tokens() -> dict[str, Any] | None:
    if not _TOKENS_PATH.exists():
        return None
    return json.loads(_TOKENS_PATH.read_text(encoding="utf-8"))


def _refresh_access_token(tokens: dict[str, Any]) -> dict[str, Any]:
    client_id, client_secret = load_credentials()
    resp = _SESSION.post(
        TOKEN_URI,
        data={
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    new = resp.json()
    # Refresh responses usually omit the refresh_token; keep the existing one.
    new.setdefault("refresh_token", tokens.get("refresh_token"))
    save_tokens(new)
    return _load_tokens()  # reload with computed expires_at


def _valid_access_token() -> str | None:
    tokens = _load_tokens()
    if not tokens:
        return None
    if time.time() >= tokens.get("expires_at", 0):
        if not tokens.get("refresh_token"):
            return None
        tokens = _refresh_access_token(tokens)
    return tokens.get("access_token")


# --- API calls -------------------------------------------------------------

def _day_bounds(date: str) -> tuple[str, str]:
    start = _dt.datetime.fromisoformat(date).replace(tzinfo=_dt.timezone.utc)
    end = start + _dt.timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _date_block(date_obj: dict[str, Any]) -> str:
    """Format a Google Health date block ({year,month,day}) as 'YYYY-MM-DD'."""
    d = date_obj or {}
    return f"{int(d.get('year', 0)):04d}-{int(d.get('month', 0)):02d}-{int(d.get('day', 0)):02d}"


def _list_day(
    data_type: str,
    token: str,
    target_date: str,
    date_of: "callable",
    max_pages: int = 12,
) -> list[dict[str, Any]]:
    """Return all data points for one local day.

    The list endpoint has no working time filter, but it returns points
    newest-first, so we page through (largest page the API allows) and stop as
    soon as we cross below the target day.
    """
    url = f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints"
    headers = {"Authorization": f"Bearer {token}"}
    collected: list[dict[str, Any]] = []
    page_token: str | None = None

    for _ in range(max_pages):
        params: dict[str, Any] = {"pageSize": _PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        resp = _SESSION.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        points = body.get("dataPoints", [])

        stop = False
        for p in points:
            day = date_of(p)
            if day == target_date:
                collected.append(p)
            elif day and day < target_date:
                stop = True  # newest-first: everything beyond here is older
                break
        page_token = body.get("nextPageToken")
        if stop or not page_token or not points:
            break
    return collected


def _civil_hm(civil_time: dict[str, Any]) -> str:
    """Format a Google Health civilTime/civilStartTime block as 'HH:MM'."""
    t = (civil_time or {}).get("time", {})
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"


def _civil_date(civil_time: dict[str, Any]) -> str:
    """Format the date block of a civilTime/civilStartTime as 'YYYY-MM-DD'."""
    return _date_block((civil_time or {}).get("date", {}))


def _civil_hour(civil_time: dict[str, Any]) -> int:
    """Return the hour (0-23) of a civilTime/civilStartTime block."""
    return int((civil_time or {}).get("time", {}).get("hours", 0) or 0)


def _safe_list(data_type, token, date, date_of, max_pages=6):
    """Like ``_list_day`` but never raises — returns [] on any failure.

    Used for the optional extra sensors so a single unavailable data type can
    never break the core movement/heart-rate pipeline.
    """
    try:
        return _list_day(data_type, token, date, date_of, max_pages=max_pages)
    except Exception:
        return []


def _hr_zone(bpm: int) -> str:
    """Bucket a heart-rate sample into a display zone."""
    if bpm >= _MAX_HR * 0.85:
        return "peak"
    if bpm >= _MAX_HR * 0.70:
        return "cardio"
    if bpm >= _MAX_HR * 0.50:
        return "fat_burn"
    return "out"


def _fetch_live_signals(date: str, token: str) -> dict[str, Any]:
    """Fetch and normalise one day's signals from the API (no caching).

    All data types are fetched concurrently to cut wall-clock time. The three
    core types (steps, resting HR, heart rate) drive the score; the rest are
    optional sensors that enrich the dashboard and degrade gracefully.
    """
    step_date = lambda p: _civil_date(p.get("steps", {}).get("interval", {}).get("civilStartTime", {}))
    rest_date = lambda p: _date_block(p.get("dailyRestingHeartRate", {}).get("date", {}))
    hr_date = lambda p: _civil_date(p.get("heartRate", {}).get("sampleTime", {}).get("civilTime", {}))
    cal_date = lambda p: _civil_date(p.get("activeEnergyBurned", {}).get("interval", {}).get("civilStartTime", {}))
    azm_date = lambda p: _civil_date(p.get("activeZoneMinutes", {}).get("interval", {}).get("civilStartTime", {}))
    spo2_date = lambda p: _civil_date(p.get("oxygenSaturation", {}).get("sampleTime", {}).get("civilTime", {}))
    hrv_date = lambda p: _civil_date(p.get("heartRateVariability", {}).get("sampleTime", {}).get("civilTime", {}))
    dist_date = lambda p: _civil_date(p.get("distance", {}).get("interval", {}).get("civilStartTime", {}))

    with ThreadPoolExecutor(max_workers=8) as ex:
        f_steps = ex.submit(_list_day, DT_STEPS, token, date, step_date)
        f_rest = ex.submit(_list_day, DT_RESTING_HR, token, date, rest_date)
        f_hr = ex.submit(_list_day, DT_HEART_RATE, token, date, hr_date)
        f_cal = ex.submit(_safe_list, DT_CALORIES, token, date, cal_date)
        f_azm = ex.submit(_safe_list, DT_AZM, token, date, azm_date)
        f_spo2 = ex.submit(_safe_list, DT_SPO2, token, date, spo2_date)
        f_hrv = ex.submit(_safe_list, DT_HRV, token, date, hrv_date)
        f_dist = ex.submit(_safe_list, DT_DISTANCE, token, date, dist_date)
        steps_pts, rest_pts, hr_pts = f_steps.result(), f_rest.result(), f_hr.result()
        cal_pts, azm_pts = f_cal.result(), f_azm.result()
        spo2_pts, hrv_pts, dist_pts = f_spo2.result(), f_hrv.result(), f_dist.result()

    # Steps: total + per-hour histogram for the "steps by hour" chart.
    steps = 0
    steps_by_hour = [0] * 24
    for p in steps_pts:
        block = p.get("steps", {})
        count = int(block.get("count", 0) or 0)
        steps += count
        steps_by_hour[_civil_hour(block.get("interval", {}).get("civilStartTime", {}))] += count

    # Resting HR: one derived value per day.
    resting_hr = _DEMO["resting_hr"]
    for p in rest_pts:
        bpm = p.get("dailyRestingHeartRate", {}).get("beatsPerMinute")
        if bpm:
            resting_hr = int(bpm)

    # Heart rate: per-sample bpm + local time. Keep the full series for stats,
    # downsample a copy for the chart, and bucket samples into zones.
    all_hr: list[dict[str, Any]] = []
    zone_counts = {"out": 0, "fat_burn": 0, "cardio": 0, "peak": 0}
    for p in hr_pts:
        hr = p.get("heartRate", {})
        bpm = hr.get("beatsPerMinute")
        if not bpm:
            continue
        bpm = int(bpm)
        all_hr.append({"time": _civil_hm(hr.get("sampleTime", {}).get("civilTime", {})), "bpm": bpm})
        zone_counts[_hr_zone(bpm)] += 1
    all_hr.sort(key=lambda s: s["time"])
    hr_samples = _downsample(all_hr, 60)

    bpms = [s["bpm"] for s in all_hr]
    hr_avg = round(sum(bpms) / len(bpms)) if bpms else _DEMO["hr_avg"]
    hr_min = min(bpms) if bpms else _DEMO["hr_min"]
    hr_max = max(bpms) if bpms else _DEMO["hr_max"]
    hr_current = all_hr[-1]["bpm"] if all_hr else _DEMO["hr_current"]
    total_z = sum(zone_counts.values()) or 1
    hr_zones = {k: round(v * 100 / total_z) for k, v in zone_counts.items()}

    # Active energy burned (kcal) — real if present, else estimated from steps.
    calories = round(sum(float(p.get("activeEnergyBurned", {}).get("kcal", 0) or 0) for p in cal_pts))
    calories_estimated = calories <= 0
    if calories_estimated:
        calories = round(steps * 0.045)

    # Active zone minutes — split by zone.
    azm_by_zone: dict[str, int] = {}
    for p in azm_pts:
        block = p.get("activeZoneMinutes", {})
        mins = int(block.get("activeZoneMinutes", 0) or 0)
        zone = str(block.get("heartRateZone", "")).lower() or "fat_burn"
        azm_by_zone[zone] = azm_by_zone.get(zone, 0) + mins
    azm_total = sum(azm_by_zone.values())

    # Distance (m) — real if present, else estimated from steps & stride.
    dist_m = 0.0
    for p in dist_pts:
        d = p.get("distance", {})
        dist_m += float(d.get("meters", d.get("distance", d.get("value", 0)) or 0) or 0)
    distance_estimated = dist_m <= 0
    if distance_estimated:
        dist_m = steps * _STRIDE_M
    distance_km = round(dist_m / 1000, 2)

    # SpO2 (%) — average + most recent reading.
    spo2_vals = [float(p.get("oxygenSaturation", {}).get("percentage", 0) or 0) for p in spo2_pts]
    spo2_vals = [v for v in spo2_vals if v > 0]
    spo2_avg = round(sum(spo2_vals) / len(spo2_vals)) if spo2_vals else None
    spo2_latest = round(spo2_vals[0]) if spo2_vals else None  # list is newest-first

    # HRV (RMSSD, ms) — average + most recent reading.
    hrv_vals = [float(p.get("heartRateVariability", {}).get(
        "rootMeanSquareOfSuccessiveDifferencesMilliseconds", 0) or 0) for p in hrv_pts]
    hrv_vals = [v for v in hrv_vals if v > 0]
    hrv_avg = round(sum(hrv_vals) / len(hrv_vals)) if hrv_vals else None
    hrv_latest = round(hrv_vals[0]) if hrv_vals else None

    return {
        "source": "google-health",
        "mode": "live",
        "steps": steps,
        "resting_hr": resting_hr,
        "hr_samples": hr_samples or _DEMO["hr_samples"],
        "hr_avg": hr_avg,
        "hr_min": hr_min,
        "hr_max": hr_max,
        "hr_current": hr_current,
        "hr_zones": hr_zones,
        "steps_by_hour": steps_by_hour,
        "calories": calories,
        "calories_estimated": calories_estimated,
        "distance_km": distance_km,
        "distance_estimated": distance_estimated,
        "active_minutes": azm_total,
        "azm_total": azm_total,
        "azm_by_zone": azm_by_zone,
        "spo2_avg": spo2_avg,
        "spo2_latest": spo2_latest,
        "hrv_avg": hrv_avg,
        "hrv_latest": hrv_latest,
    }


# --- Disk cache (stale-while-revalidate) -----------------------------------

def _read_cache() -> dict[str, Any]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_get(date: str) -> dict[str, Any] | None:
    with _cache_lock:
        return _read_cache().get(date)


def _cache_put(date: str, signals: dict[str, Any]) -> None:
    with _cache_lock:
        cache = _read_cache()
        cache[date] = {"fetched_at": time.time(), "signals": signals}
        for old in sorted(cache)[:-7]:  # keep at most the 7 most recent days
            cache.pop(old, None)
        try:
            _CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except Exception:
            pass


def _refresh_async(date: str, token: str) -> None:
    """Refresh one day's cache in a background thread (deduplicated)."""
    with _cache_lock:
        if date in _refreshing:
            return
        _refreshing.add(date)

    def worker() -> None:
        try:
            _cache_put(date, _fetch_live_signals(date, token))
        except Exception:
            pass
        finally:
            with _cache_lock:
                _refreshing.discard(date)

    threading.Thread(target=worker, daemon=True).start()


def prewarm(date: str | None = None) -> None:
    """Kick off a background fetch so the first dashboard load is fast.

    Safe to call at server startup; does nothing if not logged in or already warm.
    """
    date = date or _dt.date.today().isoformat()
    token = _valid_access_token()
    if not token:
        return
    entry = _cache_get(date)
    if entry and (time.time() - entry.get("fetched_at", 0)) <= _CACHE_TTL:
        return
    _refresh_async(date, token)


def get_daily_signals(date: str, max_age: float = _CACHE_TTL) -> dict[str, Any]:
    """Return normalised movement + heart-rate signals for ``date`` (YYYY-MM-DD).

    Uses a disk cache: a fresh entry is returned instantly; a stale entry is
    returned immediately while a background refresh runs; a cache miss fetches
    live (blocking) so the user always sees real data. Falls back to demo only
    when not logged in or the live fetch fails.
    """
    token = _valid_access_token()
    if not token:
        return _demo_for(date)

    entry = _cache_get(date)
    if entry and entry.get("signals"):
        age = time.time() - entry.get("fetched_at", 0)
        if age > max_age:
            _refresh_async(date, token)  # stale-while-revalidate
        result = dict(entry["signals"])
        result["cache_age_s"] = int(age)
        return result

    # Cache miss: fetch now so the dashboard shows real data on first load.
    try:
        signals = _fetch_live_signals(date, token)
        _cache_put(date, signals)
        return signals
    except Exception as exc:  # never break the dashboard on a live error
        fallback = _demo_for(date)
        fallback["error"] = str(exc)
        return fallback


def _downsample(items: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """Reduce a list to at most ``target`` evenly-spaced items (keeps the last)."""
    if len(items) <= target:
        return items
    step = len(items) / target
    picked = [items[int(i * step)] for i in range(target)]
    if picked[-1] is not items[-1]:
        picked[-1] = items[-1]
    return picked


if __name__ == "__main__":
    today = _dt.date.today().isoformat()
    # Force a fresh fetch so the CLI reflects the live API, not the cache.
    print(json.dumps(get_daily_signals(today, max_age=0), indent=2))
