"""Unified Xiaomi client — reads the watch and returns normalised signals.

This is the single entry point the rest of Pawse imports. It mirrors the
interface of the other device clients (``get_daily_signals(date)`` + ``prewarm``)
so it is a drop-in replacement in ``server.py``.

The Redmi Watch 4 uses Xiaomi's encrypted proprietary protocol, so the only
reliable path is **Gadgetbridge**: pair the watch in the Gadgetbridge Android
app, then sync its SQLite export to this machine (see
``sync_gadgetbridge.ps1``). The backend degrades to realistic demo data, so the
dashboard never breaks.

    python devices/xiaomi/xiaomi_client.py            # today
    python devices/xiaomi/xiaomi_client.py 2026-06-18 # a specific day
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

try:  # works as a package import and as a direct script
    from . import gadgetbridge_client
except ImportError:
    import gadgetbridge_client  # type: ignore[no-redef]

SOURCE = "xiaomi"

# Gadgetbridge is the one backend that works with the Redmi Watch 4's
# authenticated protocol; Pawse routes straight to it.
_BACKEND = gadgetbridge_client


def get_daily_signals(date: str) -> dict[str, Any]:
    """Return normalised signals for ``date`` from the Gadgetbridge backend."""
    signals = _BACKEND.get_daily_signals(date)
    signals.setdefault("backend", "gadgetbridge")
    return signals


def prewarm(date: str | None = None) -> None:
    """Pre-warm the backend so the first dashboard load is fast."""
    date = date or _dt.date.today().isoformat()
    warm = getattr(_BACKEND, "prewarm", None)
    if warm:
        try:
            warm(date)
        except Exception:
            pass


def _cli() -> None:
    import json
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    date = args[0] if args else _dt.date.today().isoformat()

    print(f"Xiaomi (Gadgetbridge) signals for {date}:\n")
    print(json.dumps(get_daily_signals(date), indent=2))


if __name__ == "__main__":
    _cli()
