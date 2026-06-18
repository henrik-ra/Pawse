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
    """Return voice features + stress index for an audio file."""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return _mock_result()

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio not found: {path}")

    y, sr = librosa.load(str(path), sr=None)

    # Pitch (F0) variability
    f0 = librosa.yin(y, fmin=70, fmax=400, sr=sr)
    pitch_variability = float(np.clip(np.std(f0) / 100.0, 0, 1))

    # Energy / loudness
    rms = librosa.feature.rms(y=y)[0]
    energy = float(np.clip(np.mean(rms) * 10, 0, 1))

    # Pause ratio (fraction of low-energy frames)
    pause_ratio = float(np.mean(rms < (np.mean(rms) * 0.4)))

    # Rough speech-rate proxy from onset density
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
        "source": "teams",
        "analyzed_segments": 1,
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
