"""Option B — Gadgetbridge SQLite export (most reliable for Xiaomi).

`Gadgetbridge <https://gadgetbridge.org>`_ is an open-source Android app that
pairs directly with Xiaomi watches over Bluetooth — including models with
the proprietary, authenticated protocol that blocks a raw PC connection. It
stores every sample in a local SQLite database you can export
(*Settings → Database management → Export DB*) and copy to this machine.

This backend reads that database. Because Gadgetbridge already did the watch
handshake, the data is complete and accurate — at the cost of not being live
(it's as fresh as your last export/auto-export).

Point Pawse at the file with the ``GADGETBRIDGE_DB`` env var, or drop it next to
this script as ``Gadgetbridge.db``.

CLI:
    python devices/xiaomi/gadgetbridge_client.py                 # today
    python devices/xiaomi/gadgetbridge_client.py 2026-06-18      # a specific day
    python devices/xiaomi/gadgetbridge_client.py --tables        # inspect schema
"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
from pathlib import Path
from typing import Any

try:  # works as a package import and as a direct script
    from ._common import demo_signals, enrich
except ImportError:
    from _common import demo_signals, enrich

SOURCE = "xiaomi-gadgetbridge"

_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE / "Gadgetbridge.db"

# Gadgetbridge stores one row per minute in a per-device "activity sample" table.
# The table name varies by device binding (e.g. MI_BAND_ACTIVITY_SAMPLE,
# XIAOMI_ACTIVITY_SAMPLE, HUAMI_EXTENDED_ACTIVITY_SAMPLE), but the columns we
# need are consistently named.
_TS_COL = "TIMESTAMP"          # unix seconds
_HR_COL = "HEART_RATE"         # bpm (255/-1/0 = "no reading")
_STEPS_COL = "STEPS"           # steps accumulated in that minute


def _db_path() -> Path | None:
    env = os.environ.get("GADGETBRIDGE_DB")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    return _DEFAULT_DB if _DEFAULT_DB.exists() else None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def list_sample_tables(conn: sqlite3.Connection) -> list[str]:
    """All tables that look like an activity-sample table (have ts + heart rate)."""
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%ACTIVITY_SAMPLE%'"
        )
    ]
    usable = []
    for t in tables:
        cols = _columns(conn, t)
        if _TS_COL in cols and _HR_COL in cols:
            usable.append(t)
    return usable


def _pick_table(conn: sqlite3.Connection, date: str) -> str | None:
    """Choose the activity-sample table holding data for ``date``."""
    candidates = list_sample_tables(conn)
    if not candidates:
        return None
    start, end = _day_bounds(date)
    best, best_rows = None, -1
    for t in candidates:
        try:
            n = conn.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE {_TS_COL} >= ? AND {_TS_COL} < ?',
                (start, end),
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if n > best_rows:
            best, best_rows = t, n
    return best


def _day_bounds(date: str) -> tuple[int, int]:
    """Local-day [start, end) as unix-second timestamps."""
    day = _dt.datetime.fromisoformat(date)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _dt.timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def _valid_hr(bpm: Any) -> bool:
    # Gadgetbridge uses 255 / -1 / 0 as "no measurement" sentinels.
    return bpm is not None and 0 < int(bpm) < 250


def get_daily_signals(date: str) -> dict[str, Any]:
    """Normalised signals for ``date`` from the Gadgetbridge export."""
    db = _db_path()
    if db is None:
        return demo_signals(
            date, SOURCE,
            note="No Gadgetbridge DB found — export it and set GADGETBRIDGE_DB or drop Gadgetbridge.db here",
        )

    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return demo_signals(date, SOURCE, note=f"Could not open DB: {exc}")

    try:
        table = _pick_table(conn, date)
        if not table:
            return demo_signals(date, SOURCE, note="No activity-sample data for this day in the DB")

        cols = _columns(conn, table)
        has_steps = _STEPS_COL in cols
        start, end = _day_bounds(date)
        select_cols = f"{_TS_COL}, {_HR_COL}" + (f", {_STEPS_COL}" if has_steps else "")
        rows = conn.execute(
            f'SELECT {select_cols} FROM "{table}" WHERE {_TS_COL} >= ? AND {_TS_COL} < ? ORDER BY {_TS_COL}',
            (start, end),
        ).fetchall()
    except sqlite3.Error as exc:
        return demo_signals(date, SOURCE, note=f"Query failed: {exc}")
    finally:
        conn.close()

    if not rows:
        return demo_signals(date, SOURCE, note="No rows for this day in the DB")

    steps_total = 0
    steps_by_hour = [0] * 24
    hr_samples: list[dict[str, Any]] = []
    hr_values: list[int] = []
    for row in rows:
        ts = int(row[0])
        bpm = row[1]
        when = _dt.datetime.fromtimestamp(ts)
        if has_steps and row[2]:
            s = int(row[2])
            steps_total += s
            steps_by_hour[when.hour] += s
        if _valid_hr(bpm):
            bpm = int(bpm)
            hr_values.append(bpm)
            hr_samples.append({"time": when.strftime("%H:%M"), "bpm": bpm})

    resting_hr = min(hr_values) if hr_values else 60
    return enrich(
        source=SOURCE,
        mode="live",
        date=date,
        steps=steps_total,
        resting_hr=resting_hr,
        hr_samples=hr_samples,
        steps_by_hour=steps_by_hour if has_steps else None,
        extra={"table": table, "rows": len(rows)},
    )


def prewarm(date: str | None = None) -> None:
    """No-op: reading a local SQLite file is already fast."""
    return None


def _cli() -> None:
    import json
    import sys

    if "--tables" in sys.argv:
        db = _db_path()
        if not db:
            print("No Gadgetbridge DB found. Set GADGETBRIDGE_DB or place Gadgetbridge.db next to this script.")
            return
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for t in list_sample_tables(conn):
                cols = sorted(_columns(conn, t))
                n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                print(f"{t}  ({n} rows)\n    {', '.join(cols)}")
        finally:
            conn.close()
        return

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    date = args[0] if args else _dt.date.today().isoformat()
    print(json.dumps(get_daily_signals(date), indent=2))


if __name__ == "__main__":
    _cli()
