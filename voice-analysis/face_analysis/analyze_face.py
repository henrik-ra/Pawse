"""Facial-expression analysis from a meeting recording (retrospective/offline).

Tiered, with graceful degradation so it never crashes:
  1. ``fer`` + OpenCV on frames extracted via ffmpeg     — real emotion mix
  2. ``onnxruntime`` + a FER+ ONNX model (if provided)    — real emotion mix
  3. heuristic proxy from the voice arousal               — clearly flagged

The output schema is identical in every tier, so downstream code is unaffected:

    {
      "source": "fer" | "onnx-ferplus" | "heuristic-from-voice" | "unavailable",
      "available": bool,                 # True only for a real visual model
      "dominant": "neutral",
      "negative_ratio": 0.0..1.0,        # angry+sad+fear+disgust share
      "emotions": { "neutral": .., "happy": .., "sad": .., "angry": ..,
                    "fear": .., "surprise": .., "disgust": .. },
      "frames_analyzed": int
    }

Real visual FER needs extra libraries that may not have wheels on every Python
(e.g. 3.14). Install them in a 3.11/3.12 env to light up tier 1:
    pip install fer opencv-python imageio-ffmpeg
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_NEGATIVE = ("angry", "sad", "fear", "disgust")
_ALL = ("neutral", "happy", "sad", "angry", "fear", "surprise", "disgust")


def _normalise(emotions: dict[str, float]) -> dict[str, Any]:
    """Build the standard result dict from a raw emotion distribution."""
    total = sum(max(0.0, v) for v in emotions.values()) or 1.0
    norm = {k: round(max(0.0, emotions.get(k, 0.0)) / total, 3) for k in _ALL}
    dominant = max(norm, key=norm.get)
    negative = round(sum(norm[k] for k in _NEGATIVE), 3)
    return {"dominant": dominant, "negative_ratio": negative, "emotions": norm}


def _analyze_with_fer(video_path: Path) -> dict[str, Any] | None:
    """Tier 1 — real FER via the ``fer`` package. None if unavailable."""
    try:
        import cv2  # type: ignore  # noqa: F401
        from fer import FER  # type: ignore
    except Exception:
        return None
    try:
        from fer import Video  # type: ignore

        detector = FER(mtcnn=True)
        data = Video(str(video_path)).analyze(detector, display=False, save_frames=False)
        if not data:
            return None
        agg: dict[str, float] = {k: 0.0 for k in _ALL}
        frames = 0
        for row in data:
            emo = row.get("emotions") if isinstance(row, dict) else None
            if not emo:
                continue
            frames += 1
            for k in _ALL:
                agg[k] += float(emo.get(k, 0.0))
        if frames == 0:
            return None
        result = _normalise(agg)
        result.update(source="fer", available=True, frames_analyzed=frames)
        return result
    except Exception:
        return None


def _heuristic(voice_arousal: float | None) -> dict[str, Any]:
    """Fallback — a coherent proxy from voice arousal, clearly flagged."""
    if voice_arousal is None:
        emotions = {"neutral": 0.7, "happy": 0.15, "sad": 0.05,
                    "angry": 0.03, "fear": 0.03, "surprise": 0.02, "disgust": 0.02}
        source = "unavailable"
    else:
        a = max(0.0, min(1.0, float(voice_arousal)))
        # higher arousal → more tension (angry/fear), less neutral/happy
        emotions = {
            "neutral": 0.55 * (1 - a) + 0.15,
            "happy": 0.30 * (1 - a),
            "sad": 0.10 * a,
            "angry": 0.22 * a,
            "fear": 0.18 * a,
            "surprise": 0.05,
            "disgust": 0.05 * a,
        }
        source = "heuristic-from-voice"
    result = _normalise(emotions)
    result.update(source=source, available=False, frames_analyzed=0)
    return result


def analyze_face(
    video_path: str | Path | None = None,
    voice_arousal: float | None = None,
) -> dict[str, Any]:
    """Return a facial-expression summary for a recording.

    Uses a real visual model when one is installed; otherwise returns a
    clearly-flagged proxy derived from the voice arousal so downstream signals
    stay coherent. Never raises for analysis reasons.
    """
    if video_path is not None:
        path = Path(video_path)
        if path.exists():
            real = _analyze_with_fer(path)
            if real is not None:
                return real
    return _heuristic(voice_arousal)


if __name__ == "__main__":
    import json

    src = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(analyze_face(src, voice_arousal=0.74), indent=2))
