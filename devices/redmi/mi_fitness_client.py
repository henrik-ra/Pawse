"""Option D — Mi Fitness export (Redmi Watch 4's real companion app).

The Redmi Watch 4 syncs to **Mi Fitness** (``com.xiaomi.wearable``), which stores
data in **Xiaomi's** cloud behind Xiaomi-account SSO. Unlike Huami/Zepp, Xiaomi
exposes no usable unofficial API — but the app (and Xiaomi's privacy portal) can
**export your data**, and this backend parses that export.

How to get the export:
- In the app: **Profile → Settings (gear) → Privacy → Export data**, or
- Xiaomi privacy portal: https://privacy.mi.com → *Request/Export my data*
  (choose the wearable / Mi Fitness data).

You'll receive a ``.zip`` (or a folder) of CSV/JSON files. Point Pawse at it::

    set MI_FITNESS_EXPORT=C:/path/to/mi_fitness_export.zip   # or a folder
    python devices/redmi/mi_fitness_client.py --inspect      # see what's inside
    python devices/redmi/mi_fitness_client.py 2026-06-23     # parse a day

The export schema varies by region/version, so the parser is **heuristic**: it
finds files whose columns look like heart-rate or steps data plus a timestamp.
Run ``--inspect`` and share the output if a day comes back empty — the column
hints below can then be tuned to your export.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

try:  # works as a package import and as a direct script
    from ._common import demo_signals, enrich
except ImportError:
    from _common import demo_signals, enrich

SOURCE = "redmi-mifitness"

_HERE = Path(__file__).resolve().parent
_DEFAULT_EXPORT = _HERE / "mi_fitness_export"

# Column-name hints (case-insensitive substrings) used to recognise fields.
_HR_HINTS = ("heart_rate", "heartrate", "heart rate", "bpm", "hr_value", "hrvalue")
_STEPS_HINTS = ("steps", "step_count", "stepcount", "totalsteps", "step")
_TIME_HINTS = ("timestamp", "time", "date", "datetime", "start_time", "recordtime", "createtime")


def _export_path() -> Path | None:
    env = os.environ.get("MI_FITNESS_EXPORT")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    return _DEFAULT_EXPORT if _DEFAULT_EXPORT.exists() else None


# --- File discovery (folder or zip) ----------------------------------------

def _iter_csv_files(root: Path) -> Iterator[tuple[str, list[dict[str, str]]]]:
    """Yield (name, rows) for every CSV inside a folder or zip."""
    if root.is_file() and root.suffix.lower() == ".zip":
        with zipfile.ZipFile(root) as zf:
            for info in zf.infolist():
                if info.filename.lower().endswith(".csv"):
                    with zf.open(info) as fh:
                        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                        yield info.filename, list(csv.DictReader(text))
                elif info.filename.lower().endswith(".json"):
                    with zf.open(info) as fh:
                        yield info.filename, _rows_from_json(fh.read())
    elif root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() == ".csv":
                with path.open(encoding="utf-8", errors="replace", newline="") as fh:
                    yield str(path.relative_to(root)), list(csv.DictReader(fh))
            elif path.suffix.lower() == ".json":
                yield str(path.relative_to(root)), _rows_from_json(path.read_bytes())


def _rows_from_json(raw: bytes) -> list[dict[str, str]]:
    """Flatten a JSON file into a list of string-valued row dicts (best effort)."""
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return []
    if isinstance(data, dict):
        for value in data.values():  # e.g. {"data": [ ... ]}
            if isinstance(value, list):
                data = value
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    rows: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({k: ("" if v is None else str(v)) for k, v in item.items()})
    return rows


# --- Column detection & value parsing --------------------------------------

def _find_col(fieldnames: list[str], hints: tuple[str, ...]) -> str | None:
    lowered = {name.lower(): name for name in fieldnames}
    # Prefer an exact-ish hint match, then any substring match.
    for hint in hints:
        for low, original in lowered.items():
            if low == hint:
                return original
    for hint in hints:
        for low, original in lowered.items():
            if hint in low:
                return original
    return None


def _parse_time(value: str) -> _dt.datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    # Pure numbers: unix seconds (10 digits) or milliseconds (13 digits).
    if re.fullmatch(r"\d{10,13}", value):
        ts = int(value)
        if ts > 10_000_000_000:  # milliseconds
            ts //= 1000
        try:
            return _dt.datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(value[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:  # last resort: ISO 8601 with offset/zone
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _to_int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# --- Public API ------------------------------------------------------------

def get_daily_signals(date: str) -> dict[str, Any]:
    """Normalised signals for ``date`` parsed from a Mi Fitness export."""
    root = _export_path()
    if root is None:
        return demo_signals(
            date, SOURCE,
            note="No Mi Fitness export found — export from the app and set MI_FITNESS_EXPORT",
        )

    target = _dt.date.fromisoformat(date)
    hr_samples: list[dict[str, Any]] = []
    steps_total = 0
    steps_by_hour = [0] * 24
    saw_steps = False

    try:
        for _name, rows in _iter_csv_files(root):
            if not rows:
                continue
            fields = list(rows[0].keys())
            time_col = _find_col(fields, _TIME_HINTS)
            hr_col = _find_col(fields, _HR_HINTS)
            steps_col = _find_col(fields, _STEPS_HINTS)
            if not time_col or (not hr_col and not steps_col):
                continue

            for row in rows:
                when = _parse_time(row.get(time_col, ""))
                if not when or when.date() != target:
                    continue
                if hr_col:
                    bpm = _to_int(row.get(hr_col, ""))
                    if bpm and 0 < bpm < 250:
                        hr_samples.append({"time": when.strftime("%H:%M"), "bpm": bpm})
                if steps_col:
                    s = _to_int(row.get(steps_col, ""))
                    if s and s >= 0:
                        saw_steps = True
                        steps_total += s
                        steps_by_hour[when.hour] += s
    except Exception as exc:
        return demo_signals(date, SOURCE, note=f"Could not read export: {exc}")

    if not hr_samples and not saw_steps:
        return demo_signals(
            date, SOURCE,
            note="Export found but no HR/steps for this day — run --inspect and share the columns",
        )

    resting_hr = min((s["bpm"] for s in hr_samples), default=60)
    return enrich(
        source=SOURCE,
        mode="live",
        date=date,
        steps=steps_total,
        resting_hr=resting_hr,
        hr_samples=hr_samples,
        steps_by_hour=steps_by_hour if saw_steps else None,
    )


def prewarm(date: str | None = None) -> None:
    """No-op: reading the local export is already fast."""
    return None


def inspect() -> None:
    """Print every file in the export with its columns — to tune the parser."""
    root = _export_path()
    if root is None:
        print("No Mi Fitness export found. Set MI_FITNESS_EXPORT to the .zip or folder, "
              "or place it at devices/redmi/mi_fitness_export/.")
        return
    print(f"Inspecting: {root}\n")
    any_file = False
    for name, rows in _iter_csv_files(root):
        any_file = True
        cols = list(rows[0].keys()) if rows else []
        hr = _find_col(cols, _HR_HINTS) if cols else None
        steps = _find_col(cols, _STEPS_HINTS) if cols else None
        tcol = _find_col(cols, _TIME_HINTS) if cols else None
        tags = []
        if tcol:
            tags.append(f"time={tcol}")
        if hr:
            tags.append(f"hr={hr}")
        if steps:
            tags.append(f"steps={steps}")
        marker = "  <-- usable" if (tcol and (hr or steps)) else ""
        print(f"{name}  ({len(rows)} rows){marker}")
        if cols:
            print(f"    columns: {', '.join(cols)}")
        if tags:
            print(f"    detected: {', '.join(tags)}")
        if rows:
            print(f"    sample:  {rows[0]}")
        print()
    if not any_file:
        print("No .csv or .json files found inside the export.")


def _cli() -> None:
    import sys

    if "--inspect" in sys.argv:
        inspect()
        return
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    date = args[0] if args else _dt.date.today().isoformat()
    print(json.dumps(get_daily_signals(date), indent=2))


if __name__ == "__main__":
    _cli()
