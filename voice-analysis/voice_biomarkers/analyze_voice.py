"""Analyse voice biomarkers from an audio file → stress index (0..1).

Stub-friendly: if `librosa` is not installed, returns mock features so the
pipeline still produces output for the demo.

Usage:
    python voice-analysis/voice_biomarkers/analyze_voice.py meeting.wav
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _mock_result() -> dict[str, Any]:
    return {
        "source": "teams",
        "analyzed_segments": 2,
        "features": {
            "pitch_variability": 0.71,
            "speech_rate": 0.66,
            "pause_ratio": 0.22,
            "energy": 0.69,
        },
        "stress_index": 0.74,
        "note": "mock output (librosa not installed)",
    }


def _stress_index(features: dict[str, float]) -> float:
    """Combine features into a single 0..1 stress index (simple weighted blend)."""
    weights = {
        "pitch_variability": 0.35,
        "speech_rate": 0.25,
        "pause_ratio": -0.20,  # more pauses = calmer
        "energy": 0.20,
    }
    raw = sum(features.get(k, 0.0) * w for k, w in weights.items())
    return round(max(0.0, min(1.0, raw + 0.2)), 2)


def analyze_voice(audio_path: str | Path) -> dict[str, Any]:
    """Return voice features + stress index for an audio file.

    Tiered, with graceful degradation so it never crashes:
      1. librosa (richest, many formats)        — if installed
      2. numpy + stdlib ``wave`` (real, WAV)     — no extra deps
      3. mock output                             — last resort
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio not found: {path}")

    result = _analyze_with_librosa(path)
    if result is not None:
        return result

    result = _analyze_wav_numpy(path)
    if result is not None:
        return result

    return _mock_result()


def _stress_index_v2(core: dict[str, float], bio: dict[str, float]) -> float:
    """Stress 0..1 from core + extended acoustic biomarkers.

    Higher pitch perturbation (jitter/shimmer), brighter spectrum, faster
    speech, higher energy variability and fewer pauses push stress up; more
    pauses and a higher harmonic-to-noise ratio (calmer, clearer voice) pull
    it down. Weights sum to 1.0.
    """
    contributions = [
        (core.get("pitch_variability", 0.0), 0.16),
        (core.get("speech_rate", 0.0), 0.12),
        (core.get("energy", 0.0), 0.08),
        (1.0 - core.get("pause_ratio", 0.0), 0.10),       # fewer pauses → tenser
        (bio.get("jitter", 0.0), 0.16),
        (bio.get("shimmer", 0.0), 0.10),
        (bio.get("spectral_centroid_norm", 0.0), 0.10),
        (bio.get("energy_variability", 0.0), 0.08),
        (1.0 - bio.get("hnr_norm", 0.5), 0.10),           # low HNR → tenser
    ]
    raw = sum(v * w for v, w in contributions)
    return round(max(0.0, min(1.0, raw)), 2)


def _analyze_with_librosa(path: Path) -> dict[str, Any] | None:
    """Tier 1 — rich biomarker extraction via librosa. None if librosa absent.

    Extracts a full acoustic-biomarker set (F0/jitter/shimmer, spectral shape,
    harmonic-to-noise ratio, MFCC timbre) on top of the four core features that
    the rest of the pipeline (stress index, dashboard) already understands.
    Every block is guarded so a single failing feature never sinks the analysis.
    """
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None

    try:
        y, sr = librosa.load(str(path), sr=22050, mono=True)
    except Exception:
        return None
    if y is None or y.size < sr // 5:                       # < 0.2 s of audio
        return None

    eps = 1e-9
    duration = max(len(y) / sr, eps)

    # --- energy / RMS dynamics -------------------------------------------
    rms = librosa.feature.rms(y=y)[0]
    mean_rms = float(np.mean(rms)) + eps
    energy = float(np.clip(mean_rms * 10.0, 0, 1))
    energy_variability = float(np.clip(np.std(rms) / mean_rms, 0, 1))
    pause_ratio = float(np.mean(rms < mean_rms * 0.4))
    shimmer = float(np.clip(np.mean(np.abs(np.diff(rms))) / mean_rms, 0, 1))

    # --- pitch via YIN (fast) with an RMS voicing gate -------------------
    f0_mean = 0.0
    pitch_variability = 0.5
    pitch_range = 0.0
    jitter = 0.0
    voiced_fraction = 0.0
    try:
        hop = 512
        f0 = librosa.yin(y, fmin=70, fmax=400, sr=sr,
                         frame_length=2048, hop_length=hop)
        rms_f = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
        n = min(len(f0), len(rms_f))
        f0, rms_f = f0[:n], rms_f[:n]
        voiced = ((rms_f > np.mean(rms_f) * 0.5)
                  & np.isfinite(f0) & (f0 > 70) & (f0 < 400))
        voiced_fraction = float(np.mean(voiced)) if voiced.size else 0.0
        f0v = f0[voiced]
        if f0v.size >= 2:
            f0_mean = float(np.mean(f0v))
            pitch_variability = float(np.clip(np.std(f0v) / 60.0, 0, 1))
            pitch_range = float(np.clip(
                (np.percentile(f0v, 95) - np.percentile(f0v, 5)) / 200.0, 0, 1))
            jitter = float(np.clip(
                np.mean(np.abs(np.diff(f0v))) / (f0_mean + eps) * 8.0, 0, 1))
    except Exception:
        pass

    # --- spectral shape ---------------------------------------------------
    def _safe_mean(fn) -> float:
        try:
            return float(np.mean(fn()))
        except Exception:
            return 0.0

    centroid_hz = _safe_mean(lambda: librosa.feature.spectral_centroid(y=y, sr=sr))
    bandwidth_hz = _safe_mean(lambda: librosa.feature.spectral_bandwidth(y=y, sr=sr))
    rolloff_hz = _safe_mean(lambda: librosa.feature.spectral_rolloff(y=y, sr=sr))
    flatness = _safe_mean(lambda: librosa.feature.spectral_flatness(y=y))
    zcr = _safe_mean(lambda: librosa.feature.zero_crossing_rate(y))
    nyquist = sr / 2.0
    spectral_centroid_norm = float(np.clip(centroid_hz / nyquist, 0, 1))
    spectral_bandwidth_norm = float(np.clip(bandwidth_hz / nyquist, 0, 1))
    spectral_rolloff_norm = float(np.clip(rolloff_hz / nyquist, 0, 1))

    # --- speech rate via onsets ------------------------------------------
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr)
        speech_rate = float(np.clip(len(onsets) / duration / 4.0, 0, 1))
    except Exception:
        speech_rate = float(np.clip(zcr * 4.0, 0, 1))

    # --- harmonic-to-noise ratio (approx via HPSS) -----------------------
    hnr_db = 0.0
    hnr_norm = 0.5
    try:
        y_h, y_p = librosa.effects.hpss(y)
        h = float(np.sum(y_h ** 2)) + eps
        p = float(np.sum(y_p ** 2)) + eps
        hnr_db = float(10.0 * np.log10(h / p))
        hnr_norm = float(np.clip((hnr_db + 10.0) / 40.0, 0, 1))   # ~-10..30 dB
    except Exception:
        pass

    # --- MFCC timbre summary (first 5 coefficient means) -----------------
    try:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        mfcc_means = [round(float(m), 2) for m in np.mean(mfcc, axis=1)[:5]]
    except Exception:
        mfcc_means = []

    core = {
        "pitch_variability": round(pitch_variability, 2),
        "speech_rate": round(speech_rate, 2),
        "pause_ratio": round(pause_ratio, 2),
        "energy": round(energy, 2),
    }
    biomarkers = {
        "f0_mean_hz": round(f0_mean, 1),
        "pitch_range": round(pitch_range, 2),
        "jitter": round(jitter, 3),
        "shimmer": round(shimmer, 3),
        "voiced_fraction": round(voiced_fraction, 2),
        "energy_variability": round(energy_variability, 2),
        "zero_crossing_rate": round(zcr, 3),
        "spectral_centroid_hz": round(centroid_hz, 0),
        "spectral_centroid_norm": round(spectral_centroid_norm, 2),
        "spectral_bandwidth_norm": round(spectral_bandwidth_norm, 2),
        "spectral_rolloff_norm": round(spectral_rolloff_norm, 2),
        "spectral_flatness": round(flatness, 3),
        "hnr_db": round(hnr_db, 1),
        "hnr_norm": round(hnr_norm, 2),
        "mfcc_means": mfcc_means,
    }
    return {
        "source": "librosa",
        "analyzed_segments": max(1, int(duration // 30)),
        "duration_s": round(duration, 1),
        "features": core,
        "biomarkers": biomarkers,
        "stress_index": _stress_index_v2(core, biomarkers),
    }


def _autocorr_pitch(frame, sr: int, np, fmin: int = 70, fmax: int = 400):
    """Estimate fundamental frequency (Hz) of one frame via autocorrelation."""
    frame = frame - np.mean(frame)
    corr = np.correlate(frame, frame, mode="full")
    corr = corr[len(corr) // 2:]
    min_lag, max_lag = int(sr / fmax), int(sr / fmin)
    if min_lag < 1 or max_lag >= len(corr):
        return None
    segment = corr[min_lag:max_lag]
    if segment.size == 0:
        return None
    peak = int(np.argmax(segment)) + min_lag
    return sr / peak if peak > 0 else None


def _analyze_wav_numpy(path: Path) -> dict[str, Any] | None:
    """Tier 2 — real acoustic features from a WAV using only numpy + ``wave``.

    Returns None when the file is not a readable PCM WAV or numpy is missing,
    so the caller can fall back to mock output.
    """
    if path.suffix.lower() != ".wav":
        return None
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return None

    import contextlib
    import wave

    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except Exception:
        return None

    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
    dtype = dtype_map.get(sampwidth)
    if dtype is None or not raw or framerate <= 0:
        return None

    data = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if sampwidth == 1:  # 8-bit PCM is unsigned, centre it
        data -= 128.0
    data /= float(2 ** (8 * sampwidth - 1))
    if n_channels > 1:  # down-mix to mono
        data = data.reshape(-1, n_channels).mean(axis=1)
    if data.size < framerate // 10:  # < 0.1 s of audio
        return None

    win = max(1024, framerate // 20)  # ~50 ms window
    hop = win // 2
    rms = np.array([
        float(np.sqrt(np.mean(data[s:s + win] ** 2)))
        for s in range(0, max(1, len(data) - win), hop)
    ])
    if rms.size == 0:
        rms = np.array([float(np.sqrt(np.mean(data ** 2)))])
    mean_rms = float(np.mean(rms)) or 1e-9

    energy = float(np.clip(mean_rms * 4.0, 0, 1))
    pause_ratio = float(np.mean(rms < (mean_rms * 0.4)))
    zcr = float(np.mean((np.abs(np.diff(np.sign(data))) > 0).astype(np.float64)))
    speech_rate = float(np.clip(zcr * 4.0, 0, 1))

    pitches = []
    for s in range(0, max(1, len(data) - win), hop * 2):
        frame = data[s:s + win]
        if np.sqrt(np.mean(frame ** 2)) < mean_rms * 0.5:
            continue
        f0 = _autocorr_pitch(frame, framerate, np)
        if f0:
            pitches.append(f0)
    pitch_variability = (
        float(np.clip(np.std(pitches) / 80.0, 0, 1)) if len(pitches) >= 2 else 0.5
    )

    features = {
        "pitch_variability": round(pitch_variability, 2),
        "speech_rate": round(speech_rate, 2),
        "pause_ratio": round(pause_ratio, 2),
        "energy": round(energy, 2),
    }
    duration = len(data) / framerate
    return {
        "source": "wav-numpy",
        "analyzed_segments": max(1, int(duration // 30)),
        "duration_s": round(duration, 1),
        "features": features,
        "stress_index": _stress_index(features),
    }


if __name__ == "__main__":
    import json

    src = sys.argv[1] if len(sys.argv) > 1 else "recordings/meeting.wav"
    try:
        out = analyze_voice(src)
    except FileNotFoundError:
        out = _mock_result()
    print(json.dumps(out, indent=2))
