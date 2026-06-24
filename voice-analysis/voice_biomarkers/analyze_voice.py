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


def _analyze_with_librosa(path: Path) -> dict[str, Any] | None:
    """Tier 1 — full feature extraction via librosa. None if librosa absent."""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None

    y, sr = librosa.load(str(path), sr=None)

    f0 = librosa.yin(y, fmin=70, fmax=400, sr=sr)
    pitch_variability = float(np.clip(np.std(f0) / 100.0, 0, 1))

    rms = librosa.feature.rms(y=y)[0]
    energy = float(np.clip(np.mean(rms) * 10, 0, 1))
    pause_ratio = float(np.mean(rms < (np.mean(rms) * 0.4)))

    onsets = librosa.onset.onset_detect(y=y, sr=sr)
    duration = max(len(y) / sr, 1e-6)
    speech_rate = float(np.clip(len(onsets) / duration / 5.0, 0, 1))

    features = {
        "pitch_variability": round(pitch_variability, 2),
        "speech_rate": round(speech_rate, 2),
        "pause_ratio": round(pause_ratio, 2),
        "energy": round(energy, 2),
    }
    return {
        "source": "librosa",
        "analyzed_segments": max(1, int(duration // 30)),
        "duration_s": round(duration, 1),
        "features": features,
        "stress_index": _stress_index(features),
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
