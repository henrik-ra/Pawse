"""Shared helpers for the Redmi backends.

Every backend returns the same normalised signal dict that the rest of Pawse
expects (see ``devices/README.md``). This module centralises the demo payload
and the enrichment maths (HR stats, zones, distance/calorie estimates) so the
three backends stay thin and consistent.
"""
from __future__ import annotations

from typing import Any

# Average stride length (m) for estimating distance from steps.
_STRIDE_M = 0.762
# Nominal max heart rate used only for splitting samples into display zones.
_MAX_HR = 190
# Steps below this (over a full day) read as a desk-bound, low-movement day.
LOW_STEPS_THRESHOLD = 3000


def _hr_zone(bpm: int) -> str:
    """Bucket a heart-rate sample into a display zone."""
    if bpm >= _MAX_HR * 0.85:
        return "peak"
    if bpm >= _MAX_HR * 0.70:
        return "cardio"
    if bpm >= _MAX_HR * 0.50:
        return "fat_burn"
    return "out"


def enrich(
    *,
    source: str,
    mode: str,
    date: str,
    steps: int,
    resting_hr: int,
    hr_samples: list[dict[str, Any]],
    steps_by_hour: list[int] | None = None,
    spo2_avg: int | None = None,
    spo2_latest: int | None = None,
    hrv_avg: int | None = None,
    hrv_latest: int | None = None,
    calories: int | None = None,
    distance_km: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full normalised signal dict from a backend's raw readings.

    Only ``steps``, ``resting_hr`` and ``hr_samples`` are required; everything
    else is derived (HR stats/zones) or estimated (calories/distance) when the
    watch did not provide it, so the dashboard always looks complete.
    """
    hr_samples = sorted(
        ({"time": s["time"], "bpm": int(s["bpm"])} for s in hr_samples if s.get("bpm")),
        key=lambda s: s["time"],
    )
    bpms = [s["bpm"] for s in hr_samples]

    hr_avg = round(sum(bpms) / len(bpms)) if bpms else resting_hr
    hr_min = min(bpms) if bpms else resting_hr
    hr_max = max(bpms) if bpms else resting_hr
    hr_current = bpms[-1] if bpms else resting_hr

    zone_counts = {"out": 0, "fat_burn": 0, "cardio": 0, "peak": 0}
    for bpm in bpms:
        zone_counts[_hr_zone(bpm)] += 1
    total_z = sum(zone_counts.values()) or 1
    hr_zones = {k: round(v * 100 / total_z) for k, v in zone_counts.items()}

    calories_estimated = calories is None
    if calories_estimated:
        calories = round(steps * 0.045)

    distance_estimated = distance_km is None
    if distance_estimated:
        distance_km = round(steps * _STRIDE_M / 1000, 2)

    signals: dict[str, Any] = {
        "source": source,
        "mode": mode,
        "date": date,
        "steps": int(steps),
        "resting_hr": int(resting_hr),
        "hr_samples": hr_samples or _demo_hr(),
        "hr_avg": hr_avg,
        "hr_min": hr_min,
        "hr_max": hr_max,
        "hr_current": hr_current,
        "hr_zones": hr_zones,
        "steps_by_hour": steps_by_hour or [0] * 24,
        "calories": calories,
        "calories_estimated": calories_estimated,
        "distance_km": distance_km,
        "distance_estimated": distance_estimated,
        "active_minutes": zone_counts["fat_burn"] + zone_counts["cardio"] + zone_counts["peak"],
        "spo2_avg": spo2_avg,
        "spo2_latest": spo2_latest,
        "hrv_avg": hrv_avg,
        "hrv_latest": hrv_latest,
    }
    if extra:
        signals.update(extra)
    return signals


def _demo_hr() -> list[dict[str, Any]]:
    return [
        {"time": "09:30", "bpm": 78},
        {"time": "10:30", "bpm": 96},
        {"time": "14:00", "bpm": 99},
        {"time": "19:45", "bpm": 88},
    ]


def demo_signals(date: str, source: str, note: str | None = None) -> dict[str, Any]:
    """Realistic, deterministic demo data with light per-day variation.

    Used whenever a backend has no live connection so the demo never breaks.
    """
    try:
        seed = sum(int(x) for x in date.split("-"))
    except Exception:
        seed = 0
    wiggle = (seed % 7) - 3  # -3..+3
    steps = max(200, 700 + wiggle * 220)
    resting_hr = 62 + (seed % 5) - 2

    signals = enrich(
        source=source,
        mode="demo",
        date=date,
        steps=steps,
        resting_hr=resting_hr,
        hr_samples=_demo_hr(),
        steps_by_hour=[0, 0, 0, 0, 0, 0, 20, 80, 140, 60, 40, 90,
                       30, 50, 40, 70, 30, 60, 20, 10, 0, 0, 0, 0],
        spo2_avg=96,
        spo2_latest=95,
        hrv_avg=42 + wiggle * 2,
        hrv_latest=39 + wiggle * 2,
    )
    if note:
        signals["note"] = note
    return signals
