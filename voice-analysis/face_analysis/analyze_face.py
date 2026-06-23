"""Facial-expression analysis from a meeting recording — real, image-based.

Runs real on-device FER (ffmpeg frames -> UltraFace face detection -> FER+
emotion, all via ONNX; see ``fer_onnx.py``). It does **not** derive expressions
from the voice. When onnxruntime or the models are unavailable it returns an
honest "unavailable" result instead.

Result schema:
    {
      "source": "onnx-ferplus" | "unavailable",
      "available": bool,                 # True only for a real visual model
      "dominant": "neutral",
      "negative_ratio": 0.0..1.0,        # angry+sad+fear+disgust share
      "emotions": { "neutral": .., "happy": .., "sad": .., "angry": ..,
                    "fear": .., "surprise": .., "disgust": .. },
      "frames_analyzed": int, "faces_found": int
    }
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_KEYS = ["neutral", "happy", "sad", "angry", "fear", "surprise", "disgust"]
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _unavailable(note: str) -> dict[str, Any]:
    return {
        "source": "unavailable", "available": False,
        "dominant": "neutral", "negative_ratio": 0.0,
        "emotions": {k: (1.0 if k == "neutral" else 0.0) for k in _KEYS},
        "frames_analyzed": 0, "faces_found": 0, "note": note,
    }


def analyze_face(video_path: str | Path | None = None) -> dict[str, Any]:
    """Return an image-based facial-expression summary. Never raises.

    Facial expressions are analysed from the actual video frames (ONNX FER) —
    never inferred from the voice. Returns an "unavailable" result when there is
    no video or the FER runtime/models are missing.
    """
    if video_path is None:
        return _unavailable("no video for this recording")
    path = Path(video_path)
    if not path.exists() or path.suffix.lower() not in _VIDEO_EXTS:
        return _unavailable("no video stream")

    try:
        import fer_onnx  # sibling module (on sys.path via media_analyzer)

        result = fer_onnx.analyze_video(path)
    except Exception as exc:
        return _unavailable(f"FER error: {type(exc).__name__}")
    return result if result is not None else _unavailable(
        "onnxruntime/model missing — pip install onnxruntime"
    )


if __name__ == "__main__":
    import json

    src = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(analyze_face(src), indent=2))
