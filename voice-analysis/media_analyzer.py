"""Pawse media analyzer — turn meeting recordings into voice + face signals.

Retrospective/offline: scans the local Teams **Recordings** folder (synced by
OneDrive) plus ``data/recordings/``, runs the voice and face analyzers on each
file, and aggregates one ``voice``/``face`` signal per calendar day into
``data/media_signals.json``.

Everything degrades gracefully (see the analyzer modules), so it never crashes:
  - ``.wav``                      → analysed directly with numpy
  - other audio / video           → audio extracted via ffmpeg / imageio-ffmpeg
  - no audio backend              → recorded as "unavailable" (no crash)

Usage:
    python voice-analysis/media_analyzer.py                 # scan default folders
    python voice-analysis/media_analyzer.py <file|folder>   # scan a specific path
    python voice-analysis/media_analyzer.py --date 2026-06-23 <file>   # force date
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

_HERE = Path(__file__).resolve().parent          # voice-analysis/
_ROOT = _HERE.parent                              # repo root
for _sub in ("voice_biomarkers", "video_extraction", "face_analysis"):
    sys.path.insert(0, str(_HERE / _sub))

from analyze_voice import analyze_voice            # type: ignore  # noqa: E402
from analyze_face import analyze_face              # type: ignore  # noqa: E402
from extract_audio import (                        # type: ignore  # noqa: E402
    AudioExtractionUnavailable,
    audio_backend_available,
    extract_audio,
)

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS

_EMOTION_KEYS = ("neutral", "happy", "sad", "angry", "fear", "surprise", "disgust")
_MEDIA_CACHE = _ROOT / "data" / "media_signals.json"

# Windows "Files On-Demand" placeholder attributes. A OneDrive recording that
# hasn't been downloaded yet is a cloud-only placeholder; ffmpeg can't decode it
# until the bytes are pulled to disk. Reading the file forces the OS to hydrate.
_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_CLOUD_ONLY_MASK = _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def is_cloud_only(path: str | Path) -> bool:
    """True if ``path`` is a OneDrive cloud-only placeholder (not yet on disk)."""
    if os.name != "nt":
        return False
    try:
        attrs = Path(path).stat().st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & _CLOUD_ONLY_MASK)


def _env_local_only() -> bool:
    """Default local-only setting from the ``PAWSE_LOCAL_ONLY`` env var.

    When local-only is on, cloud-only OneDrive placeholders are *skipped* (never
    downloaded). Only recordings already present on disk are analysed, so no
    video bytes are ever pulled from (or pushed to) the cloud.
    """
    return (os.environ.get("PAWSE_LOCAL_ONLY") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def ensure_local(path: str | Path) -> bool:
    """Force a cloud-only OneDrive placeholder to download so ffmpeg can read it.

    Reading the bytes triggers Windows Cloud Files on-demand hydration. Returns
    True once the file is present locally, False if it couldn't be hydrated
    (e.g. OneDrive is offline). No-op for already-local files and non-Windows.
    """
    path = Path(path)
    if not is_cloud_only(path):
        return True
    try:
        with open(path, "rb") as fh:
            while fh.read(8 * 1024 * 1024):
                pass
    except OSError:
        return not is_cloud_only(path)
    return not is_cloud_only(path)


def default_recording_dirs() -> list[Path]:
    """Teams recordings (OneDrive) + the repo's local drop folder."""
    dirs: list[Path] = []
    onedrive = os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive")
    if onedrive:
        rec = Path(onedrive) / "Recordings"
        if rec.exists():
            dirs.append(rec)
    dirs.append(_ROOT / "data" / "recordings")
    return dirs


def _date_for(path: Path) -> str:
    """Best-effort meeting date: from the filename, else the file's mtime."""
    name = path.name
    m = re.search(r"(\d{8})[_-]\d{6}", name)        # ...-20260416_160000-...
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
        except ValueError:
            pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)      # ...2026-04-16...
    if m:
        return m.group(1)
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def find_media(paths: list[Path], skip_cloud_only: bool = False) -> list[Path]:
    """Collect media files from the given files/folders (recursive).

    When ``skip_cloud_only`` is True, OneDrive cloud-only placeholders are
    excluded so they are never downloaded — only on-disk recordings are returned.
    """
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [f for f in p.rglob("*")
                      if f.is_file() and f.suffix.lower() in MEDIA_EXTS]
        elif p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            files.append(p)
    files = sorted(set(files))
    if skip_cloud_only:
        files = [f for f in files if not is_cloud_only(f)]
    return files


def analyze_recording(
    path: str | Path,
    date_override: str | None = None,
    local_only: bool | None = None,
) -> dict[str, Any]:
    """Analyse one recording → {file, date, voice, face}. Never raises.

    ``local_only`` (defaults to the ``PAWSE_LOCAL_ONLY`` env var) keeps the video
    on this machine: cloud-only OneDrive placeholders are skipped rather than
    downloaded, so no bytes ever leave or enter via OneDrive.
    """
    path = Path(path)
    ext = path.suffix.lower()
    date = date_override or _date_for(path)
    tmp_wav: Path | None = None
    if local_only is None:
        local_only = _env_local_only()

    if is_cloud_only(path):
        if local_only:
            msg = "cloud-only recording skipped (local-only mode — not downloaded)"
            return {
                "file": path.name, "date": date,
                "voice": {"source": "skipped", "stress_index": None, "note": msg},
                "face": analyze_face(None),
                "skipped": True,
            }
        if not ensure_local(path):
            msg = "cloud-only recording could not be downloaded (is OneDrive running and online?)"
            return {
                "file": path.name, "date": date,
                "voice": {"source": "unavailable", "stress_index": None, "note": msg},
                "face": analyze_face(None),
            }

    try:
        if ext == ".wav":
            wav: Path | None = path
        elif audio_backend_available():
            tmp_wav = Path(tempfile.gettempdir()) / f"pawse_{path.stem}.wav"
            wav = extract_audio(path, out_path=tmp_wav)
        else:
            wav = None

        if wav is not None:
            voice = analyze_voice(wav)
        else:
            voice = {
                "source": "unavailable",
                "stress_index": None,
                "note": "no audio backend — run: pip install imageio-ffmpeg",
            }

        # Facial expression is analysed from the actual video frames, never voice.
        face = analyze_face(path if ext in VIDEO_EXTS else None)
    except (AudioExtractionUnavailable, FileNotFoundError) as exc:
        voice = {"source": "error", "stress_index": None, "note": str(exc)}
        face = analyze_face(None)
    finally:
        if tmp_wav is not None and tmp_wav.exists():
            try:
                tmp_wav.unlink()
            except OSError:
                pass

    return {"file": path.name, "date": date, "voice": voice, "face": face}


def aggregate_signals(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate per-file results into one voice/face signal per day."""
    by_day: dict[str, dict[str, list]] = {}
    for r in results:
        bucket = by_day.setdefault(r["date"], {"voice": [], "face": []})
        if r.get("voice") and r["voice"].get("stress_index") is not None:
            bucket["voice"].append(r["voice"])
        if r.get("face"):
            bucket["face"].append(r["face"])

    out: dict[str, dict[str, Any]] = {}
    for date, bucket in by_day.items():
        entry: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc).isoformat()}
        vl = bucket["voice"]
        if vl:
            stress = round(mean(v["stress_index"] for v in vl), 2)
            src = vl[0].get("source")
            entry["voice"] = {
                "source": src,
                "avg_stress_index": stress,
                "stressIndex": stress,
                "arousal": stress,
                "segments": sum(v.get("analyzed_segments", 1) for v in vl),
                "files": len(vl),
                "features": vl[-1].get("features", {}),
                "notes": f"From {len(vl)} recording(s) · on-device {src} analysis",
            }
        fl = bucket["face"]
        if fl:
            emo = {k: round(mean(f.get("emotions", {}).get(k, 0.0) for f in fl), 3)
                   for k in _EMOTION_KEYS}
            entry["face"] = {
                "source": fl[0].get("source"),
                "available": any(f.get("available") for f in fl),
                "dominant": max(emo, key=emo.get),
                "negativeRatio": round(mean(f.get("negative_ratio", 0.0) for f in fl), 3),
                "emotions": emo,
                "files": len(fl),
            }
        out[date] = entry
    return out


def merge_cache(day_signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge new per-day signals into data/media_signals.json and save it."""
    cache: dict[str, Any] = {}
    if _MEDIA_CACHE.exists():
        try:
            cache = json.loads(_MEDIA_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache.update(day_signals)
    _MEDIA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _MEDIA_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def analyze_paths(
    paths: list[Path],
    date_override: str | None = None,
    local_only: bool | None = None,
) -> dict[str, Any]:
    """Analyse all media under ``paths`` and return the per-day aggregate.

    With ``local_only`` (defaults to ``PAWSE_LOCAL_ONLY``), cloud-only OneDrive
    placeholders are skipped — only on-disk recordings are analysed.
    """
    if local_only is None:
        local_only = _env_local_only()
    media = find_media(paths, skip_cloud_only=local_only)
    results = [analyze_recording(f, date_override=date_override, local_only=local_only)
               for f in media]
    return aggregate_signals(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse meeting recordings → voice/face signals")
    parser.add_argument("paths", nargs="*", help="files/folders (default: OneDrive Recordings + data/recordings)")
    parser.add_argument("--date", help="force this date (YYYY-MM-DD) for all files")
    parser.add_argument("--json", action="store_true", help="print the aggregate as JSON")
    parser.add_argument("--local-only", action="store_true",
                        help="skip cloud-only OneDrive recordings (never download videos)")
    args = parser.parse_args()

    local_only = args.local_only or _env_local_only()
    paths = [Path(p) for p in args.paths] if args.paths else default_recording_dirs()
    media = find_media(paths, skip_cloud_only=local_only)
    if not media:
        print("No recordings found in: " + ", ".join(str(p) for p in paths))
        if local_only:
            print("(local-only mode: cloud-only OneDrive recordings were skipped)")
        if not audio_backend_available():
            print("Tip: audio decode backend missing — run: pip install imageio-ffmpeg")
        return

    if not audio_backend_available():
        print("[warn] No ffmpeg backend — .mp4/.m4a can't be decoded. "
              "Run: pip install imageio-ffmpeg  (.wav still works)")

    results = [analyze_recording(f, date_override=args.date, local_only=local_only)
               for f in media]
    day_signals = aggregate_signals(results)
    merge_cache(day_signals)

    if args.json:
        print(json.dumps(day_signals, indent=2))
        return

    print(f"Analysed {len(results)} recording(s) → {len(day_signals)} day(s):")
    for r in results:
        v = r["voice"] or {}
        si = v.get("stress_index")
        si_s = f"{si:.2f}" if isinstance(si, (int, float)) else "n/a"
        print(f"  {r['date']}  {r['file'][:48]:48}  voice={v.get('source','?'):12} stress={si_s}")
    print(f"\nWritten to {_MEDIA_CACHE}")


if __name__ == "__main__":
    main()
