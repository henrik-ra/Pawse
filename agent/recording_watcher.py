"""Pawse recording watcher — the edge agent for retrospective media analysis.

Watches the Teams **Recordings** folder (synced locally by OneDrive) plus
``data/recordings/``. When a new (or changed) recording appears it:

  1. analyses voice + face   (voice-analysis/media_analyzer.py)
  2. merges the per-day signal into data/media_signals.json
  3. pushes it to the cloud   (POST /api/days/media) so the **online dashboard**
     gains a Voice-stress + Facial-expression reading for that day.

No third-party deps: a simple, restartable poll loop with a small JSON state
file (``data/.media_state.json``) so each file is processed once.

Usage:
    $env:PAWSE_API_URL = "https://<your-container-app>"
    python agent/recording_watcher.py --once          # single pass, then exit
    python agent/recording_watcher.py                 # watch forever (poll)
    python agent/recording_watcher.py --interval 120  # poll every 120 s
    python agent/recording_watcher.py --date 2026-06-23   # force-date (demo)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "voice-analysis"))

import media_analyzer as ma  # type: ignore  # noqa: E402

_STATE_PATH = _ROOT / "data" / ".media_state.json"
_DEFAULT_API = "http://localhost:8000"


def _load_state() -> dict[str, float]:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict[str, float]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _push_media(date: str, entry: dict[str, Any], api_url: str, api_key: str | None) -> bool:
    """POST one day's voice/face signal to the cloud. Returns True on success."""
    payload = {"user": os.environ.get("PAWSE_USER", "me"), "date": date}
    if "voice" in entry:
        payload["voice"] = entry["voice"]
    if "face" in entry:
        payload["face"] = entry["face"]

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{api_url}/api/days/media", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("x-api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read().decode("utf-8"))
        return True
    except urllib.error.HTTPError as exc:
        print(f"  ! push failed ({exc.code}): {exc.read().decode('utf-8', 'replace')[:160]}")
    except urllib.error.URLError as exc:
        print(f"  ! cannot reach {api_url}: {exc.reason}")
    return False


def scan_once(
    dirs: list[Path],
    api_url: str,
    api_key: str | None,
    date_override: str | None,
    state: dict[str, float],
) -> int:
    """Analyse any new/changed recordings and push their day signals. Returns count."""
    media = ma.find_media(dirs)
    fresh = []
    for f in media:
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if state.get(str(f)) != mtime:
            fresh.append((f, mtime))

    if not fresh:
        return 0

    print(f"Found {len(fresh)} new/changed recording(s):")
    results = []
    for f, mtime in fresh:
        print(f"  · analysing {f.name[:60]}")
        results.append((f, mtime, ma.analyze_recording(f, date_override=date_override)))

    day_signals = ma.aggregate_signals([r for _, _, r in results])
    ma.merge_cache(day_signals)

    pushed_dates = set()
    for date, entry in day_signals.items():
        ok = _push_media(date, entry, api_url, api_key)
        v = entry.get("voice", {})
        print(f"  → {date}: voice stress={v.get('stressIndex', 'n/a')} "
              f"face={entry.get('face', {}).get('dominant', 'n/a')} "
              f"{'pushed' if ok else 'NOT pushed'}")
        if ok:
            pushed_dates.add(date)

    # Only mark files done once their day was successfully pushed.
    for f, mtime, r in results:
        if r["date"] in pushed_dates:
            state[str(f)] = mtime
    _save_state(state)
    return len(fresh)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Teams recordings → analyse → push to cloud")
    parser.add_argument("--once", action="store_true", help="single pass, then exit")
    parser.add_argument("--interval", type=int, default=300, help="poll seconds (default 300)")
    parser.add_argument("--folder", action="append", help="extra folder to watch (repeatable)")
    parser.add_argument("--date", help="force this date for all files (demo)")
    parser.add_argument("--reset", action="store_true", help="clear state and reprocess everything")
    args = parser.parse_args()

    api_url = os.environ.get("PAWSE_API_URL", _DEFAULT_API).rstrip("/")
    api_key = os.environ.get("PAWSE_API_KEY")

    dirs = ma.default_recording_dirs()
    if args.folder:
        dirs += [Path(p) for p in args.folder]

    if args.reset and _STATE_PATH.exists():
        _STATE_PATH.unlink()

    print(f"Pawse watcher → {api_url}")
    print("Watching:")
    for d in dirs:
        print(f"  - {d}  {'(exists)' if Path(d).exists() else '(missing)'}")
    if not ma.audio_backend_available():
        print("[warn] no ffmpeg backend — .mp4/.m4a skipped. Run: pip install imageio-ffmpeg")

    state = _load_state()
    n = scan_once(dirs, api_url, api_key, args.date, state)
    if args.once:
        if n == 0:
            print("No new recordings.")
        return

    print(f"\nPolling every {args.interval}s (Ctrl+C to stop)…")
    try:
        while True:
            time.sleep(args.interval)
            scan_once(dirs, api_url, api_key, args.date, state)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
