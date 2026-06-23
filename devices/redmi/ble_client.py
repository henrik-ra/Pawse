"""Option A — BLE direct from this PC (real-time heart rate).

Connects to the Redmi/Xiaomi watch over Bluetooth Low Energy from the machine
running Pawse and subscribes to the **standard BLE Heart Rate Service** so you
get a live, ticking heart-rate number — no phone, no cloud, no account.

    Heart Rate Service         0x180D
    Heart Rate Measurement     0x2A37  (notify)

Reality check for Xiaomi/Redmi:
- Many models broadcast the standard HR characteristic while a **workout** is
  running on the watch, or when "Broadcast heart rate" is enabled in settings.
  Start a workout / enable broadcast, then run this.
- Some newer models wrap everything in a proprietary, authenticated service
  (``0xFEE0``/``0xFEE1``) and will not emit standard HR notifications. If that's
  your watch, use the Gadgetbridge backend instead.

Anything missing (no ``bleak``, Bluetooth off, watch out of range, auth-locked
model) degrades gracefully to demo data so the dashboard never breaks.

CLI:
    python devices/redmi/ble_client.py            # scan + 20s live HR
    python devices/redmi/ble_client.py --scan     # just list nearby devices
    python devices/redmi/ble_client.py --address AA:BB:.. --seconds 30
"""
from __future__ import annotations

import asyncio
import datetime as _dt
from typing import Any, Callable

try:  # works as a package import and as a direct script
    from ._common import demo_signals, enrich
except ImportError:
    from _common import demo_signals, enrich

# Standard SIG UUIDs (16-bit shorthand expanded to full 128-bit form).
HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"

# Names Redmi/Xiaomi wearables advertise themselves under.
_NAME_HINTS = ("redmi", "xiaomi", "mi watch", "mi band", "mi smart", "amazfit", "zepp")

SOURCE = "redmi-ble"


def _have_bleak() -> bool:
    try:
        import bleak  # noqa: F401
        return True
    except Exception:
        return False


def _parse_hr_measurement(data: bytearray | bytes) -> int | None:
    """Decode a Heart Rate Measurement payload per the BLE spec.

    Byte 0 is a flags field; bit 0 selects the HR value format
    (0 = uint8 in byte 1, 1 = uint16 little-endian in bytes 1-2).
    """
    if not data:
        return None
    flags = data[0]
    if flags & 0x01:
        if len(data) < 3:
            return None
        return int.from_bytes(data[1:3], "little")
    if len(data) < 2:
        return None
    return data[1]


async def scan(timeout: float = 8.0) -> list[dict[str, Any]]:
    """Return nearby BLE devices, Redmi/Xiaomi-looking ones first."""
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices: list[dict[str, Any]] = []
    for dev, adv in found.values():
        name = (dev.name or adv.local_name or "").strip()
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        looks_like = any(h in name.lower() for h in _NAME_HINTS)
        has_hr = HR_SERVICE in uuids
        devices.append({
            "address": dev.address,
            "name": name or "(unknown)",
            "rssi": adv.rssi,
            "has_hr_service": has_hr,
            "likely_redmi": looks_like,
        })
    # Most relevant first: Redmi-named, then HR-capable, then strongest signal.
    devices.sort(key=lambda d: (d["likely_redmi"], d["has_hr_service"], d["rssi"] or -999), reverse=True)
    return devices


async def _find_watch(timeout: float = 8.0) -> str | None:
    for d in await scan(timeout):
        if d["likely_redmi"] or d["has_hr_service"]:
            return d["address"]
    return None


async def stream_hr(
    address: str,
    seconds: float = 20.0,
    on_sample: Callable[[int], None] | None = None,
) -> list[dict[str, Any]]:
    """Connect and collect live HR samples for ``seconds``.

    Returns a list of ``{"time": "HH:MM:SS", "bpm": int}``. ``on_sample`` (if
    given) is called with each bpm as it arrives — handy for a live readout.
    """
    from bleak import BleakClient

    samples: list[dict[str, Any]] = []

    def _handler(_char: Any, data: bytearray) -> None:
        bpm = _parse_hr_measurement(data)
        if not bpm:
            return
        samples.append({"time": _dt.datetime.now().strftime("%H:%M:%S"), "bpm": bpm})
        if on_sample:
            on_sample(bpm)

    async with BleakClient(address) as client:
        await client.start_notify(HR_MEASUREMENT, _handler)
        try:
            await asyncio.sleep(seconds)
        finally:
            try:
                await client.stop_notify(HR_MEASUREMENT)
            except Exception:
                pass
    return samples


def get_live_hr(seconds: float = 20.0, address: str | None = None) -> list[dict[str, Any]]:
    """Blocking helper: find the watch (if needed) and capture live HR samples."""
    async def _run() -> list[dict[str, Any]]:
        addr = address or await _find_watch()
        if not addr:
            return []
        return await stream_hr(addr, seconds=seconds)

    return asyncio.run(_run())


def get_daily_signals(date: str, seconds: float = 15.0, address: str | None = None) -> dict[str, Any]:
    """Normalised signals for ``date`` (interface-compatible with other devices).

    BLE gives *real-time* data, not stored history, so for the requested day we
    capture a short live HR window and report the current reading. Steps are not
    exposed over the standard HR service, so they are left at 0 here (use the
    Gadgetbridge or Zepp backend for full daily step history).
    """
    today = _dt.date.today().isoformat()
    if not _have_bleak():
        return demo_signals(date, SOURCE, note="bleak not installed — pip install bleak")
    if date != today:
        return demo_signals(date, SOURCE, note="BLE is real-time only; no stored history for past days")

    try:
        samples = get_live_hr(seconds=seconds, address=address)
    except Exception as exc:
        return demo_signals(date, SOURCE, note=f"BLE connection failed: {exc}")

    if not samples:
        return demo_signals(date, SOURCE, note="No Redmi watch found / no HR broadcast — start a workout or enable HR broadcast")

    # Collapse the live samples (HH:MM:SS) to the dashboard's HH:MM resolution.
    hr_samples = [{"time": s["time"][:5], "bpm": s["bpm"]} for s in samples]
    resting_hr = min(s["bpm"] for s in samples)
    return enrich(
        source=SOURCE,
        mode="live",
        date=date,
        steps=0,
        resting_hr=resting_hr,
        hr_samples=hr_samples,
        extra={"live_samples": len(samples), "steps_unavailable": True},
    )


def prewarm(date: str | None = None) -> None:
    """No-op: BLE captures on demand (a live connection can't be pre-warmed)."""
    return None


def _cli() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Redmi BLE live heart rate")
    parser.add_argument("--scan", action="store_true", help="list nearby BLE devices and exit")
    parser.add_argument("--address", help="connect straight to this BLE address")
    parser.add_argument("--seconds", type=float, default=20.0, help="how long to stream HR")
    args = parser.parse_args()

    if not _have_bleak():
        print("bleak is not installed. Run:  pip install bleak")
        return

    if args.scan:
        for d in asyncio.run(scan()):
            tag = "  <- Redmi?" if d["likely_redmi"] else ("  (HR service)" if d["has_hr_service"] else "")
            print(f"{d['address']}  rssi={d['rssi']:>4}  {d['name']}{tag}")
        return

    print(f"Streaming live HR for {args.seconds:.0f}s … (Ctrl+C to stop)")
    try:
        samples = get_live_hr(seconds=args.seconds, address=args.address)
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return
    if not samples:
        print("No Redmi watch found or no HR broadcast. Start a workout / enable 'Broadcast heart rate'.")
        return
    for s in samples:
        print(f"  {s['time']}  {s['bpm']} bpm")
    print(json.dumps(get_daily_signals(_dt.date.today().isoformat()), indent=2))


if __name__ == "__main__":
    _cli()
