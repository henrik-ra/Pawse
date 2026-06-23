"""Unified Redmi client — picks a backend and always returns normalised signals.

This is the single entry point the rest of Pawse imports. It mirrors the
interface of the other device clients (``get_daily_signals(date)`` + ``prewarm``)
so it is a drop-in replacement in ``server.py``.

Choose a backend with the ``REDMI_BACKEND`` env var:

    REDMI_BACKEND=ble           # Option A — real-time BLE from this PC
    REDMI_BACKEND=gadgetbridge  # Option B — Gadgetbridge SQLite export
    REDMI_BACKEND=zepp          # Option C — Zepp Life / Mi Fitness cloud
    REDMI_BACKEND=auto          # (default) try each; first with live data wins

Every backend degrades to realistic demo data, so the dashboard never breaks.

Compare all three at once:
    python devices/redmi/redmi_client.py            # today, all backends
    python devices/redmi/redmi_client.py 2026-06-18 # a specific day
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Callable

try:  # works as a package import and as a direct script
    from . import ble_client, gadgetbridge_client, mi_fitness_client, zepp_client
    from ._common import demo_signals
except ImportError:
    import ble_client  # type: ignore[no-redef]
    import gadgetbridge_client  # type: ignore[no-redef]
    import mi_fitness_client  # type: ignore[no-redef]
    import zepp_client  # type: ignore[no-redef]
    from _common import demo_signals  # type: ignore[no-redef]

SOURCE = "redmi"

# Backend registry: name -> module exposing get_daily_signals / prewarm.
_BACKENDS: dict[str, Any] = {
    "ble": ble_client,
    "gadgetbridge": gadgetbridge_client,
    "mifitness": mi_fitness_client,
    "zepp": zepp_client,
}
# Order tried in "auto" mode: reliable history first, real-time last.
_AUTO_ORDER = ("gadgetbridge", "mifitness", "zepp", "ble")


def _selected() -> str:
    return (os.environ.get("REDMI_BACKEND") or "auto").strip().lower()


def _is_live(signals: dict[str, Any]) -> bool:
    return signals.get("mode") == "live"


def get_daily_signals(date: str) -> dict[str, Any]:
    """Return normalised signals for ``date`` from the selected Redmi backend."""
    choice = _selected()

    if choice in _BACKENDS:
        signals = _BACKENDS[choice].get_daily_signals(date)
        signals.setdefault("backend", choice)
        return signals

    # auto: try each backend; return the first that produced live data,
    # otherwise fall back to a single demo payload.
    last_demo: dict[str, Any] | None = None
    for name in _AUTO_ORDER:
        try:
            signals = _BACKENDS[name].get_daily_signals(date)
        except Exception:
            continue
        signals.setdefault("backend", name)
        if _is_live(signals):
            return signals
        last_demo = last_demo or signals

    if last_demo is not None:
        last_demo["backend"] = "auto"
        return last_demo
    return demo_signals(date, SOURCE, note="No Redmi backend available")


def prewarm(date: str | None = None) -> None:
    """Pre-warm whichever backend(s) are in play so the first load is fast."""
    date = date or _dt.date.today().isoformat()
    choice = _selected()
    targets = [choice] if choice in _BACKENDS else list(_AUTO_ORDER)
    for name in targets:
        warm: Callable[..., None] | None = getattr(_BACKENDS[name], "prewarm", None)
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

    print(f"Comparing Redmi backends for {date}\n")
    for name, module in _BACKENDS.items():
        try:
            s = module.get_daily_signals(date)
        except Exception as exc:
            print(f"[{name:>12}]  ERROR: {exc}")
            continue
        mode = s.get("mode")
        note = f"  — {s['note']}" if s.get("note") else ""
        print(f"[{name:>12}]  {mode:>4}  steps={s.get('steps'):>6}  "
              f"hr_current={s.get('hr_current')}  samples={len(s.get('hr_samples', []))}{note}")

    print("\nSelected backend result (REDMI_BACKEND=%s):" % _selected())
    print(json.dumps(get_daily_signals(date), indent=2))


if __name__ == "__main__":
    _cli()
