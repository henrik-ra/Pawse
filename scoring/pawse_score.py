"""Pawse Score engine.

Turns a workday data object into a **Pawse Score** (0-100, higher = more
strain), a strain label, the top reasons, and recommendations.

The score is a *fusion model* in the spirit of the stress scores shipped by
Garmin (HRV-driven "Stress Level"), Whoop (strain/recovery) and Fitbit
(Stress Management Score). It blends three streams:

    1. Physiology   — HRV, heart-rate response, blood oxygen, sleep, movement
    2. Behaviour    — meeting load and lack of recovery (calendar)
    3. Perception   — voice biomarkers and (opt-in) facial-expression analysis

Each signal is mapped to a 0-100 strain sub-score, then combined as a
weighted average **over the signals that are actually present**. Missing
signals (e.g. no wearable HRV, or the opt-in face/voice analysis turned off)
are simply dropped and their weight is redistributed — so the score is always
on the same 0-100 scale regardless of how many sensors a user has enabled.

Run directly to score the sample day:

    python scoring/pawse_score.py
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# --- Reference points (population-level; tune per-user later) ----------------
# Heart rate
ELEVATED_HR_DELTA = 25      # bpm above resting that counts as a stress spike
HR_ELEV_CALM = 8            # mean elevation (bpm) treated as no strain
HR_ELEV_HIGH = 35           # mean elevation (bpm) treated as full strain
HR_SPIKE_RATIO_LOW = 0.10   # share of readings that are spikes -> no strain
HR_SPIKE_RATIO_HIGH = 0.60  # share of readings that are spikes -> full strain

# Heart-rate variability (RMSSD, ms) — lower HRV = more autonomic strain
HRV_CALM_MS = 55            # rested HRV -> no strain
HRV_STRAINED_MS = 20        # suppressed HRV -> full strain

# Blood-oxygen saturation (%) — dips can accompany strain / poor recovery
SPO2_NORMAL = 97            # healthy -> no strain
SPO2_LOW = 92               # notable dip -> full strain

# Sleep (hours, previous night) — recovery debt carries into the day
SLEEP_RESTED_H = 7.5        # well rested -> no strain
SLEEP_DEPRIVED_H = 4.5      # deprived -> full strain

# Movement (steps so far) — sedentary days offer little physical recovery
STEPS_ACTIVE = 6000         # active -> no strain
STEPS_SEDENTARY = 500       # sedentary -> full strain

# Calendar
MEET_LIGHT = 2              # meetings -> no strain
MEET_HEAVY = 7              # meetings -> full strainMEET_MIN_LIGHT = 90        # total meeting minutes/day -> no strain (1.5 h)
MEET_MIN_HEAVY = 360       # total meeting minutes/day -> full strain (6 h)B2B_HEAVY = 4               # back-to-back meetings -> full strain

# --- Relative importance of each signal (renormalised over what's available) -
WEIGHTS = {
    "hrv": 0.22,            # best single biomarker for recovery/overload
    "heart_rate": 0.18,
    "meeting_load": 0.12,
    "recovery": 0.10,
    "sleep": 0.10,
    "movement": 0.08,
    "voice": 0.08,          # opt-in
    "face": 0.07,           # opt-in
    "spo2": 0.05,
}


@dataclass
class Component:
    """One scored signal feeding the fusion model."""

    key: str
    label: str
    weight: float
    strain: float = 0.0        # 0-100, higher = more strain
    available: bool = False
    reason: Optional[str] = None
    optional: bool = False     # True for opt-in modalities (voice / face)

    @property
    def contribution(self) -> float:
        return self.weight * self.strain if self.available else 0.0


# --- Helpers ----------------------------------------------------------------

def _ramp(value: float, zero_at: float, full_at: float) -> float:
    """Map ``value`` onto 0-100.

    ``zero_at`` -> 0 strain, ``full_at`` -> 100 strain, linear in between and
    clamped outside. Works in either direction (``full_at`` may be lower than
    ``zero_at`` for "smaller is worse" signals like HRV or SpO2).
    """
    if full_at == zero_at:
        return 0.0
    frac = (value - zero_at) / (full_at - zero_at)
    return max(0.0, min(100.0, frac * 100.0))


def _first(d: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-null value among ``keys``."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _consent(data: dict[str, Any], modality: str) -> bool:
    """Whether an opt-in modality is allowed.

    Presence of the data block already implies opt-in; an explicit
    ``_consent`` flag (e.g. ``{"face": false}``) can still veto it.
    """
    consent = data.get("_consent")
    if isinstance(consent, dict) and modality in consent:
        return bool(consent[modality])
    return True


# --- Personalised baselines -------------------------------------------------
#
# Some signals are far more meaningful relative to *that person's* normal than
# to a population constant: 35 ms HRV is low for one person and normal for
# another. We therefore calibrate per-user reference points over an initial
# window (``CALIBRATION_DAYS``). Until enough days are collected the score uses
# the population reference points above; afterwards it switches to personalised
# ones automatically.
#
# The baseline is *not* frozen after calibration and is *not* limited to the
# last 7 days. It keeps improving as more history arrives — but as a rolling,
# recency-weighted estimate: only the last ``BASELINE_WINDOW_DAYS`` count, and
# within that window recent days weigh more (exponential decay with
# ``BASELINE_HALF_LIFE_DAYS``). More days => steadier, more confident baseline;
# stale days => dropped, so it tracks the user's *current* normal.

CALIBRATION_DAYS = 7            # days of history before a baseline is "established"
MIN_METRIC_SAMPLES = 3          # min readings for a single metric to personalise
BASELINE_WINDOW_DAYS = 60       # rolling look-back; older days drop out (adapts to change)
BASELINE_HALF_LIFE_DAYS = 21    # recency decay: a day's weight halves every 21 days

# Metrics we personalise, and sane bounds for the "no strain" anchor so an
# unusual calibration window can't produce an absurd threshold.
BASELINE_METRICS = ("hrv", "spo2", "sleep", "steps")
_BASELINE_ZERO_BOUNDS = {
    "hrv": (25.0, 90.0),
    "spo2": (94.0, 99.0),
    "sleep": (5.0, 9.0),
    "steps": (2000.0, 12000.0),
}


@dataclass
class Baselines:
    """Personalised reference points derived from a user's recent history."""

    refs: dict[str, tuple[float, float]]   # metric -> (zero_at, full_at) ramp ends
    values: dict[str, float]               # scalar baselines (e.g. resting_hr)
    days_used: int = 0
    min_days: int = CALIBRATION_DAYS
    window_days: int = BASELINE_WINDOW_DAYS

    @property
    def established(self) -> bool:
        return self.days_used >= self.min_days and bool(self.refs or self.values)

    @property
    def confidence(self) -> float:
        """0..1 — grows from the moment it's established up to a full window."""
        if not self.established:
            return 0.0
        span = max(1, self.window_days - self.min_days)
        return round(min(1.0, (self.days_used - self.min_days) / span), 2)

    def ramp_points(self, metric: str, default_zero: float, default_full: float) -> tuple[float, float]:
        """Personalised ramp ends if calibrated for this metric, else defaults."""
        if self.established and metric in self.refs:
            return self.refs[metric]
        return default_zero, default_full


def _empty_baselines() -> Baselines:
    return Baselines(refs={}, values={}, days_used=0)


def _metric_values(day: dict[str, Any]) -> dict[str, Optional[float]]:
    w = day.get("wearable", {})
    return {
        "hrv": _first(w, "hrv", "hrv_avg", "hrv_ms", "avg_hrv"),
        "spo2": _first(w, "spo2", "spo2_avg", "oxygen_saturation"),
        "sleep": _first(w, "sleep_hours", "sleep"),
        "steps": _first(w, "steps"),
        "resting_hr": _first(w, "resting_hr", "baseline_heart_rate"),
    }


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    wsum = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / wsum if wsum else 0.0


def _weighted_std(pairs: list[tuple[float, float]], mean: float) -> float:
    wsum = sum(w for _, w in pairs)
    if wsum <= 0:
        return 0.0
    var = sum(w * (v - mean) ** 2 for v, w in pairs) / wsum
    return var ** 0.5


def _derive_endpoints(metric: str, pairs: list[tuple[float, float]]) -> tuple[float, float]:
    mean = _weighted_mean(pairs)
    sd = _weighted_std(pairs, mean) if len(pairs) > 1 else 0.0
    lo, hi = _BASELINE_ZERO_BOUNDS[metric]
    zero = min(max(mean, lo), hi)
    if metric == "steps":
        full = max(zero * 0.12, 300.0)
    elif metric == "hrv":
        full = max(zero - 1.5 * sd, zero * 0.55)
    else:  # spo2, sleep — lower is worse, modest spread
        full = zero - max(2.0, 1.5 * sd)
    return round(zero, 2), round(full, 2)


def _parse_date(value: Any) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _ages_in_days(history: list[dict[str, Any]]) -> list[int]:
    """Age of each day (in days) relative to the most recent day in history.

    Uses real dates when every day has one; otherwise falls back to list order
    (treating the last item as the most recent).
    """
    dates = [_parse_date(d.get("date")) for d in history]
    if history and all(dates):
        ref = max(d for d in dates if d is not None)
        return [(ref - d).days for d in dates if d is not None]
    n = len(history)
    return [n - 1 - i for i in range(n)]


def compute_baselines(
    history: list[dict[str, Any]],
    min_days: int = CALIBRATION_DAYS,
    window_days: int = BASELINE_WINDOW_DAYS,
    half_life: float = BASELINE_HALF_LIFE_DAYS,
) -> Baselines:
    """Derive personalised baselines from a user's recent workday history.

    The baseline is a **rolling, recency-weighted** estimate:

    * Only days within the last ``window_days`` are considered, so it tracks the
      user's *current* normal instead of drifting on stale data.
    * Within that window each day is weighted by an exponential decay
      (``half_life`` days), so recent days count more — yet more history still
      yields a steadier, more confident estimate.
    """
    ages = _ages_in_days(history)
    series: dict[str, list[tuple[float, float]]] = {m: [] for m in (*BASELINE_METRICS, "resting_hr")}
    days_used = 0
    for age, day in zip(ages, history):
        if age > window_days:
            continue
        days_used += 1
        weight = 0.5 ** (age / half_life) if half_life > 0 else 1.0
        for metric, value in _metric_values(day).items():
            if isinstance(value, (int, float)):
                series[metric].append((float(value), weight))

    refs = {
        metric: _derive_endpoints(metric, series[metric])
        for metric in BASELINE_METRICS
        if len(series[metric]) >= MIN_METRIC_SAMPLES
    }
    values: dict[str, float] = {}
    if len(series["resting_hr"]) >= MIN_METRIC_SAMPLES:
        values["resting_hr"] = round(_weighted_mean(series["resting_hr"]), 1)
    return Baselines(
        refs=refs, values=values, days_used=days_used,
        min_days=min_days, window_days=window_days,
    )


# --- Baseline persistence ---------------------------------------------------

_BASELINE_DIR = Path(__file__).resolve().parent.parent / "data" / "baselines"


def _baseline_path(user: Optional[str]) -> Path:
    safe = (user or "default").strip().lower().replace(" ", "_") or "default"
    return _BASELINE_DIR / f"{safe}.json"


def baselines_to_dict(b: Baselines) -> dict[str, Any]:
    return {
        "refs": {k: list(v) for k, v in b.refs.items()},
        "values": b.values,
        "days_used": b.days_used,
        "min_days": b.min_days,
        "window_days": b.window_days,
    }


def baselines_from_dict(d: dict[str, Any]) -> Baselines:
    return Baselines(
        refs={k: (float(v[0]), float(v[1])) for k, v in d.get("refs", {}).items()},
        values={k: float(v) for k, v in d.get("values", {}).items()},
        days_used=int(d.get("days_used", 0)),
        min_days=int(d.get("min_days", CALIBRATION_DAYS)),
        window_days=int(d.get("window_days", BASELINE_WINDOW_DAYS)),
    )


def load_saved_baselines(user: Optional[str]) -> Baselines:
    """Load a saved baseline for the user, or an empty (population) one."""
    path = _baseline_path(user)
    if path.exists():
        try:
            return baselines_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return _empty_baselines()


def save_baselines(b: Baselines, user: Optional[str]) -> Path:
    _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = _baseline_path(user)
    path.write_text(json.dumps(baselines_to_dict(b), indent=2), encoding="utf-8")
    return path


def calibrate(history: list[dict[str, Any]], user: Optional[str],
              min_days: int = CALIBRATION_DAYS) -> Baselines:
    """Compute baselines from history and persist them for the user."""
    baselines = compute_baselines(history, min_days)
    save_baselines(baselines, user)
    return baselines


def load_history(directory: Path | str) -> list[dict[str, Any]]:
    """Load every ``*.json`` workday object in a directory (sorted by name)."""
    directory = Path(directory)
    if not directory.exists():
        return []
    history: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            history.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return history


# --- Physiological signals --------------------------------------------------

def _score_heart_rate(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    w = data.get("wearable", {})
    baseline = _first(w, "resting_hr", "baseline_heart_rate") or baselines.values.get("resting_hr") or 60
    samples = [s.get("bpm") for s in w.get("hr_samples", []) if isinstance(s.get("bpm"), (int, float))]
    if not samples:
        avg = _first(w, "hr_avg")
        if avg is None:
            return Component("heart_rate", "Heart-rate response", weight)
        samples = [avg]

    elevations = [max(0.0, bpm - baseline) for bpm in samples]
    mean_elev = sum(elevations) / len(elevations)
    spikes = sum(1 for e in elevations if e >= ELEVATED_HR_DELTA)
    spike_ratio = spikes / len(samples)

    elev_strain = _ramp(mean_elev, HR_ELEV_CALM, HR_ELEV_HIGH)
    spike_strain = _ramp(spike_ratio, HR_SPIKE_RATIO_LOW, HR_SPIKE_RATIO_HIGH)
    strain = 0.6 * elev_strain + 0.4 * spike_strain

    reason = None
    if strain >= 45:
        if spikes:
            reason = (f"Heart rate spiked ≥{ELEVATED_HR_DELTA} bpm above resting "
                      f"in {spikes} reading(s) — likely stress response")
        else:
            reason = f"Heart rate ran ~{round(mean_elev)} bpm above your resting baseline"
    return Component("heart_rate", "Heart-rate response", weight, strain, True, reason)


def _score_hrv(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    w = data.get("wearable", {})
    hrv = _first(w, "hrv", "hrv_avg", "hrv_ms", "avg_hrv")
    if hrv is None:
        return Component("hrv", "Recovery (HRV)", weight)
    zero_at, full_at = baselines.ramp_points("hrv", HRV_CALM_MS, HRV_STRAINED_MS)
    strain = _ramp(hrv, zero_at, full_at)
    reason = None
    if strain >= 50:
        if baselines.established and "hrv" in baselines.refs:
            reason = f"Heart-rate variability ({round(hrv)} ms) is below your personal baseline — under-recovered"
        else:
            reason = f"Heart-rate variability is low ({round(hrv)} ms) — your body is under-recovered"
    return Component("hrv", "Recovery (HRV)", weight, strain, True, reason)


def _score_spo2(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    w = data.get("wearable", {})
    spo2 = _first(w, "spo2", "spo2_avg", "oxygen_saturation")
    if spo2 is None:
        return Component("spo2", "Blood oxygen", weight)
    zero_at, full_at = baselines.ramp_points("spo2", SPO2_NORMAL, SPO2_LOW)
    strain = _ramp(spo2, zero_at, full_at)
    reason = f"Blood-oxygen dipped to {round(spo2)}%" if strain >= 50 else None
    return Component("spo2", "Blood oxygen", weight, strain, True, reason)


def _score_sleep(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    w = data.get("wearable", {})
    sleep = _first(w, "sleep_hours", "sleep")
    if sleep is None:
        return Component("sleep", "Sleep recovery", weight)
    zero_at, full_at = baselines.ramp_points("sleep", SLEEP_RESTED_H, SLEEP_DEPRIVED_H)
    strain = _ramp(sleep, zero_at, full_at)
    reason = (f"Only {sleep:g} h sleep last night — recovery debt carries into today"
              if strain >= 45 else None)
    return Component("sleep", "Sleep recovery", weight, strain, True, reason)


def _score_movement(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    w = data.get("wearable", {})
    steps = _first(w, "steps")
    if steps is None:
        return Component("movement", "Movement", weight)
    zero_at, full_at = baselines.ramp_points("steps", STEPS_ACTIVE, STEPS_SEDENTARY)
    strain = _ramp(steps, zero_at, full_at)
    reason = (f"Low movement (~{int(steps)} steps) — little physical recovery between calls"
              if strain >= 50 else None)
    return Component("movement", "Movement", weight, strain, True, reason)


# --- Behavioural signals (calendar) -----------------------------------------

def _hhmm_to_minutes(value: Any) -> Optional[int]:
    """Parse a ``"HH:MM"`` clock string into minutes since midnight."""
    try:
        hours, minutes = str(value).split(":")[:2]
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def _meeting_minutes(meeting: dict[str, Any]) -> Optional[float]:
    """Duration of one meeting in minutes.

    Uses an explicit ``duration_minutes``/``minutes`` field when present,
    otherwise derives it from ``start``/``end`` clock times (handling a meeting
    that crosses midnight).
    """
    explicit = _first(meeting, "duration_minutes", "minutes")
    if isinstance(explicit, (int, float)):
        return max(0.0, float(explicit))
    start = _hhmm_to_minutes(meeting.get("start"))
    end = _hhmm_to_minutes(meeting.get("end"))
    if start is None or end is None:
        return None
    duration = end - start
    if duration < 0:
        duration += 24 * 60  # crosses midnight
    return float(duration)


def _score_meetings(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    if "meetings" not in data:
        return Component("meeting_load", "Meeting load", weight)
    meetings = data.get("meetings", [])
    count = len(meetings)
    durations = [d for d in (_meeting_minutes(m) for m in meetings) if d is not None]
    total_minutes = sum(durations)

    # Total time in meetings is the primary load signal (a 2 h meeting is not a
    # 5 min one); the count adds the context-switching cost of many meetings.
    count_strain = _ramp(count, MEET_LIGHT, MEET_HEAVY)
    if durations:
        duration_strain = _ramp(total_minutes, MEET_MIN_LIGHT, MEET_MIN_HEAVY)
        strain = 0.7 * duration_strain + 0.3 * count_strain
    else:
        strain = count_strain

    after_hours = sum(1 for m in meetings if m.get("after_hours"))
    if after_hours:
        strain = min(100.0, strain + 12 * after_hours)

    desc = f"{count} meetings, {total_minutes / 60:.1f} h" if durations else f"{count} meetings"
    reason = None
    if strain >= 60:
        reason = f"Heavy meeting load ({desc})"
    elif strain >= 33:
        reason = f"Busy meeting day ({desc})"
    if after_hours and reason:
        reason += f", {after_hours} after hours"
    return Component("meeting_load", "Meeting load", weight, strain, True, reason)


def _score_recovery(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    if "meetings" not in data and "breaks" not in data:
        return Component("recovery", "Recovery time", weight)
    meetings = data.get("meetings", [])
    breaks = data.get("breaks", {})
    b2b = sum(1 for m in meetings if m.get("back_to_back"))
    no_lunch = breaks.get("lunch_break", True) is False

    strain = 0.55 * _ramp(b2b, 0, B2B_HEAVY)
    if no_lunch:
        strain += 40
    strain = min(100.0, strain)

    bits = []
    if b2b >= 1:
        bits.append(f"{b2b} back-to-back meeting(s) — little recovery time")
    if no_lunch:
        bits.append("no lunch break")
    reason = ", ".join(bits).capitalize() if bits and strain >= 40 else None
    return Component("recovery", "Recovery time", weight, strain, True, reason)


# --- Perceptual signals (opt-in) --------------------------------------------

def _score_voice(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    voice = data.get("voice")
    if not isinstance(voice, dict) or not _consent(data, "voice"):
        return Component("voice", "Voice biomarkers", weight, optional=True)
    idx = _first(voice, "avg_stress_index", "stress_index")
    if idx is None:
        return Component("voice", "Voice biomarkers", weight, optional=True)
    strain = max(0.0, min(100.0, float(idx) * 100.0))
    reason = (f"Voice biomarkers flagged tension in meetings (stress index {float(idx):.2f})"
              if strain >= 50 else None)
    return Component("voice", "Voice biomarkers", weight, strain, True, reason, optional=True)


def _score_face(data: dict[str, Any], weight: float, baselines: Baselines) -> Component:
    """Opt-in facial-expression stress signal.

    Accepts ``stress_index`` (0..1) or a 0..100 ``score``. Entirely optional —
    when absent its weight is redistributed across the other signals.
    """
    face = data.get("face")
    if not isinstance(face, dict) or not _consent(data, "face"):
        return Component("face", "Facial expression", weight, optional=True)
    idx = _first(face, "avg_stress_index", "stress_index")
    if idx is None:
        score = _first(face, "score")
        idx = float(score) / 100.0 if score is not None else None
    if idx is None:
        return Component("face", "Facial expression", weight, optional=True)
    strain = max(0.0, min(100.0, float(idx) * 100.0))
    reason = (f"Facial-expression analysis detected tension (stress index {float(idx):.2f})"
              if strain >= 50 else None)
    return Component("face", "Facial expression", weight, strain, True, reason, optional=True)


SCORERS: tuple[tuple[str, Callable[[dict[str, Any], float, Baselines], Component]], ...] = (
    ("hrv", _score_hrv),
    ("heart_rate", _score_heart_rate),
    ("meeting_load", _score_meetings),
    ("recovery", _score_recovery),
    ("sleep", _score_sleep),
    ("movement", _score_movement),
    ("spo2", _score_spo2),
    ("voice", _score_voice),
    ("face", _score_face),
)


# --- Label & recommendations ------------------------------------------------

def _label(score: int) -> str:
    if score >= 70:
        return "High strain"
    if score >= 40:
        return "Medium strain"
    return "Low strain"


_RECOMMENDATIONS = {
    "hrv": "Protect 7-8 h of sleep tonight to rebuild HRV and recovery.",
    "sleep": "Wind down earlier — sleep is the biggest lever on tomorrow's score.",
    "heart_rate": "Try a 3-minute breathing reset before your next call.",
    "meeting_load": "Block 30 minutes of recovery time tomorrow, or turn one meeting into an async update.",
    "recovery": "Add 10-minute buffers between back-to-back meetings and protect a real lunch break.",
    "movement": "Take a short walk, or make one 1:1 a walking meeting.",
    "spo2": "Pause for a few slow breaths near some fresh air.",
    "voice": "Your voice showed tension today — step away for a proper break.",
    "face": "Your expression showed tension today — take a screen break and reset.",
}


def _recommendations(components: list[Component]) -> list[str]:
    flagged = sorted(
        (c for c in components if c.available and c.strain >= 45),
        key=lambda c: c.contribution,
        reverse=True,
    )
    recs: list[str] = []
    for c in flagged:
        rec = _RECOMMENDATIONS.get(c.key)
        if rec and rec not in recs:
            recs.append(rec)
    return recs[:4] or ["Your day looks balanced — keep it up!"]


# --- Public API -------------------------------------------------------------

def score_day(data: dict[str, Any], baselines: Optional[Baselines] = None) -> dict[str, Any]:
    """Score a single workday.

    Pass an explicit ``baselines`` to personalise the score, or leave it ``None``
    to auto-load the saved baseline for ``data["user"]`` (falling back to the
    population reference points until a baseline has been calibrated).

    Returns the Pawse Score, label, top reasons, recommendations, a per-signal
    ``component_scores`` breakdown, and which signals were used (including the
    opt-in voice/face modalities and the baseline personalisation state).
    """
    if baselines is None:
        baselines = load_saved_baselines(data.get("user"))

    components = [scorer(data, WEIGHTS[key], baselines) for key, scorer in SCORERS]
    available = [c for c in components if c.available]

    total_weight = sum(c.weight for c in available)
    raw = sum(c.contribution for c in available) / total_weight if total_weight else 0.0
    score = int(round(max(0, min(100, raw))))

    reasons = [
        c.reason
        for c in sorted(available, key=lambda c: c.contribution, reverse=True)
        if c.reason
    ][:4]

    return {
        "user": data.get("user"),
        "date": data.get("date"),
        "pawse_score": score,
        "label": _label(score),
        "reasons": reasons,
        "recommendations": _recommendations(components),
        "component_scores": {c.key: round(c.strain) for c in available},
        "signals_used": [c.key for c in available],
        "optional_signals": {
            "voice": any(c.key == "voice" and c.available for c in components),
            "face": any(c.key == "face" and c.available for c in components),
        },
        "baseline": {
            "status": "personalized" if baselines.established else "population",
            "days_collected": baselines.days_used,
            "days_required": baselines.min_days,
            "window_days": baselines.window_days,
            "confidence": baselines.confidence,
            "personalized_metrics": (
                sorted(set(baselines.refs) | set(baselines.values))
                if baselines.established else []
            ),
        },
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parent.parent

    # `python scoring/pawse_score.py calibrate [history_dir]`
    #   builds + saves a personalised baseline from a folder of workday JSONs.
    if len(sys.argv) >= 2 and sys.argv[1] == "calibrate":
        hist_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else root / "data" / "history"
        history = load_history(hist_dir)
        if not history:
            print(f"No workday JSON files found in {hist_dir}")
            raise SystemExit(1)
        user = history[0].get("user")
        baselines = calibrate(history, user)
        if baselines.established:
            print(f"Personalised baseline saved for {user!r} "
                  f"({baselines.days_used} days in window, confidence "
                  f"{baselines.confidence}): {baselines_to_dict(baselines)}")
        else:
            print(f"Collected {baselines.days_used}/{baselines.min_days} days for {user!r} "
                  f"— still using population defaults until calibration completes.")
        raise SystemExit(0)

    sample = root / "data" / "alex_workday.json"
    result = score_day(_load(sample))
    print(json.dumps(result, indent=2, ensure_ascii=False))
