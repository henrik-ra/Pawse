"""Option C — Zepp Life / Mi Fitness cloud (unofficial).

Reads the data your watch syncs to Xiaomi/Huami's servers via the Zepp Life
(formerly Mi Fit) app. No Bluetooth needed on this PC, but it is **not truly
real-time** — you only see data once the phone app has synced it, and this uses
an **unofficial** Huami endpoint that can change or rate-limit at any time.

Credentials (a Zepp Life / Mi Fit email account — *not* a phone-number or
"Mi Fitness"/Xiaomi-SSO-only login) come from env vars or a local ``.env``:

    ZEPP_EMAIL=you@example.com
    ZEPP_PASSWORD=...

.. important::
   This uses Huami's native **email + password** login. If you sign in to Zepp
   Life with **"Sign in with Mi account"** (Xiaomi SSO), there is no Huami
   email/password to use here and this backend cannot authenticate — use the
   Mi Fitness export (Option D) or Gadgetbridge (Option B) instead.

The login token is cached in ``zepp_tokens.json`` next to this file. Any failure
(bad creds, region mismatch, API change) degrades to demo data.

Flow (documented Huami API):
    1. POST email+password  -> short-lived ``access`` grant code
    2. POST grant code       -> ``app_token`` + ``user_id``
    3. GET band_data.json    -> per-day summary (steps) + minute-by-minute HR

CLI:
    python devices/redmi/zepp_client.py                # today
    python devices/redmi/zepp_client.py 2026-06-18     # a specific day
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

try:  # works as a package import and as a direct script
    from ._common import demo_signals, enrich
except ImportError:
    from _common import demo_signals, enrich

SOURCE = "redmi-zepp"

_HERE = Path(__file__).resolve().parent
_TOKENS_PATH = _HERE / "zepp_tokens.json"
_ENV_PATH = _HERE / ".env"

_LOGIN_TOKEN_URL = "https://api-user.huami.com/registrations/{email}/tokens"
_LOGIN_URL = "https://account.huami.com/v2/client/login"
_BAND_DATA_URL = "https://api-mifit.huami.com/v1/data/band_data.json"
_REDIRECT = "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html"

_TOKEN_TTL = 3600  # app_token is short-lived; re-login after an hour


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
    env_file = _read_env_file()
    email = os.environ.get("ZEPP_EMAIL") or env_file.get("ZEPP_EMAIL")
    password = os.environ.get("ZEPP_PASSWORD") or env_file.get("ZEPP_PASSWORD")
    if email and email.startswith("PASTE_"):
        email = None
    if password and password.startswith("PASTE_"):
        password = None
    return email, password


def _login() -> dict[str, Any] | None:
    """Run the two-step Huami login; cache and return ``{app_token, user_id}``."""
    email, password = load_credentials()
    if not email or not password:
        return None

    # Step 1: exchange email+password for a short-lived access grant code.
    r1 = requests.post(
        _LOGIN_TOKEN_URL.format(email=email),
        data={
            "client_id": "HuaMi",
            "password": password,
            "redirect_uri": _REDIRECT,
            "token": "access",
        },
        allow_redirects=False,
        timeout=30,
    )
    location = r1.headers.get("Location", "")
    code = parse_qs(urlparse(location).query).get("access", [None])[0]
    if not code:
        raise RuntimeError("login step 1 failed (no access code — check email/password or account type)")

    # Step 2: exchange the grant code for an app token + user id.
    r2 = requests.post(
        _LOGIN_URL,
        data={
            "app_name": "com.xiaomi.hm.health",
            "app_version": "6.3.0",
            "code": code,
            "country_code": "US",
            "device_id": "02:00:00:00:00:00",
            "device_model": "android_phone",
            "grant_type": "access_token",
            "third_name": "email",
            "source": "com.xiaomi.hm.health",
        },
        allow_redirects=False,
        timeout=30,
    )
    info = r2.json().get("token_info", {})
    app_token = info.get("app_token")
    user_id = info.get("user_id")
    if not app_token or not user_id:
        raise RuntimeError("login step 2 failed (no app_token — token may be expired or region differs)")

    tokens = {"app_token": app_token, "user_id": str(user_id), "obtained_at": time.time()}
    try:
        _TOKENS_PATH.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    except Exception:
        pass
    return tokens


def _valid_tokens() -> dict[str, Any] | None:
    if _TOKENS_PATH.exists():
        try:
            cached = json.loads(_TOKENS_PATH.read_text(encoding="utf-8"))
            if time.time() - cached.get("obtained_at", 0) < _TOKEN_TTL:
                return cached
        except Exception:
            pass
    return _login()


def _fetch_band_data(date: str, tokens: dict[str, Any]) -> dict[str, Any] | None:
    resp = requests.get(
        _BAND_DATA_URL,
        params={
            "query_type": "summary",
            "device_type": "android_phone",
            "userid": tokens["user_id"],
            "from_date": date,
            "to_date": date,
        },
        headers={"apptoken": tokens["app_token"]},
        timeout=30,
    )
    resp.raise_for_status()
    for item in resp.json().get("data", []):
        if item.get("date") == date:
            return item
    return None


def _parse_hr(data_hr_b64: str | None, date: str) -> list[dict[str, Any]]:
    """Decode the minute-by-minute HR blob (1 byte/minute from 00:00)."""
    if not data_hr_b64:
        return []
    try:
        raw = base64.b64decode(data_hr_b64)
    except Exception:
        return []
    samples: list[dict[str, Any]] = []
    for minute, bpm in enumerate(raw):
        if 0 < bpm < 250 and minute < 1440:
            samples.append({"time": f"{minute // 60:02d}:{minute % 60:02d}", "bpm": int(bpm)})
    return samples


def _parse_summary(summary_json: str | None) -> tuple[int, list[int]]:
    """Pull total steps + a per-hour histogram from the summary blob."""
    steps_by_hour = [0] * 24
    if not summary_json:
        return 0, steps_by_hour
    try:
        summary = json.loads(summary_json)
    except Exception:
        return 0, steps_by_hour
    stp = summary.get("stp", {}) or {}
    total = int(stp.get("ttl", 0) or 0)
    for stage in stp.get("stage", []) or []:
        start_min = int(stage.get("start", 0) or 0)  # minutes from 00:00
        steps = int(stage.get("step", 0) or 0)
        hour = min(23, max(0, start_min // 60))
        steps_by_hour[hour] += steps
    return total, steps_by_hour


def get_daily_signals(date: str) -> dict[str, Any]:
    """Normalised signals for ``date`` from the Zepp/Mi Fitness cloud."""
    email, password = load_credentials()
    if not email or not password:
        return demo_signals(date, SOURCE, note="No Zepp credentials — set ZEPP_EMAIL / ZEPP_PASSWORD")

    try:
        tokens = _valid_tokens()
        if not tokens:
            return demo_signals(date, SOURCE, note="Zepp login failed — check credentials")
        item = _fetch_band_data(date, tokens)
    except Exception as exc:
        return demo_signals(date, SOURCE, note=f"Zepp API error: {exc}")

    if not item:
        return demo_signals(date, SOURCE, note="No Zepp data synced for this day")

    steps, steps_by_hour = _parse_summary(item.get("summary"))
    hr_samples = _parse_hr(item.get("data_hr"), date)
    resting_hr = min((s["bpm"] for s in hr_samples), default=60)

    return enrich(
        source=SOURCE,
        mode="live",
        date=date,
        steps=steps,
        resting_hr=resting_hr,
        hr_samples=hr_samples,
        steps_by_hour=steps_by_hour if any(steps_by_hour) else None,
    )


def prewarm(date: str | None = None) -> None:
    """Refresh the login token ahead of the first dashboard load."""
    try:
        _valid_tokens()
    except Exception:
        pass


def _cli() -> None:
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    date = args[0] if args else _dt.date.today().isoformat()
    print(json.dumps(get_daily_signals(date), indent=2))


if __name__ == "__main__":
    _cli()
