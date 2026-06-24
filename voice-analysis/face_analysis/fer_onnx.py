"""Real facial-expression recognition from video frames — on-device, ONNX.

Pipeline (no cloud, no heavy frameworks):
  ffmpeg frames  →  UltraFace face detection  →  FER+ emotion (8 classes)

Models (ONNX Model Zoo) are cached under ``models/`` and auto-downloaded on
first use. Everything is optional: if onnxruntime or the models are missing the
caller falls back to an honest "unavailable" result (never voice-derived).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_MODELS = _HERE / "models"
_FER_PATH = _MODELS / "emotion-ferplus-8.onnx"
_FACE_PATH = _MODELS / "version-RFB-320.onnx"

_MODEL_URLS = {
    _FER_PATH: [
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
        "https://github.com/onnx/models/raw/main/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
    ],
    _FACE_PATH: [
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/ultraface/models/version-RFB-320.onnx",
        "https://github.com/onnx/models/raw/main/vision/body_analysis/ultraface/models/version-RFB-320.onnx",
    ],
}

# FER+ output order → our 7-key schema (contempt folded into angry).
_FERPLUS = ["neutral", "happy", "surprise", "sad", "angry", "disgust", "fear", "contempt"]
_MAP = {"neutral": "neutral", "happy": "happy", "surprise": "surprise", "sad": "sad",
        "angry": "angry", "disgust": "disgust", "fear": "fear", "contempt": "angry"}
_KEYS = ["neutral", "happy", "sad", "angry", "fear", "surprise", "disgust"]
_NEGATIVE = ("angry", "sad", "fear", "disgust")

_fer_sess = None
_face_sess = None


def _ensure_models(download: bool = True) -> bool:
    """Make sure the FER model is present (download if allowed). Face model optional."""
    import urllib.request

    if _FER_PATH.exists():
        return True
    if not download:
        return False
    _MODELS.mkdir(parents=True, exist_ok=True)
    for dest, urls in _MODEL_URLS.items():
        if dest.exists() and dest.stat().st_size > 10000:
            continue
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "pawse"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                if len(data) > 10000:
                    dest.write_bytes(data)
                    break
            except Exception:
                continue
    return _FER_PATH.exists()


def available() -> bool:
    """True when onnxruntime is importable and the FER model is present."""
    try:
        import onnxruntime  # type: ignore  # noqa: F401
    except Exception:
        return False
    return _FER_PATH.exists() or _ensure_models()


def _sessions():
    """Lazily create (and cache) the ONNX inference sessions."""
    global _fer_sess, _face_sess
    import onnxruntime as ort  # type: ignore

    opts = ort.SessionOptions()
    opts.log_severity_level = 3  # silence noisy initializer warnings
    if _fer_sess is None and _FER_PATH.exists():
        _fer_sess = ort.InferenceSession(
            str(_FER_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
    if _face_sess is None and _FACE_PATH.exists():
        _face_sess = ort.InferenceSession(
            str(_FACE_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
    return _fer_sess, _face_sess


def _extract_frames(video: Path, max_frames: int = 20):
    """Dump up to ``max_frames`` frames (~1 fps, 640px wide) to a temp dir."""
    import imageio_ffmpeg  # type: ignore

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = Path(tempfile.mkdtemp(prefix="pawse_frames_"))
    cmd = [ff, "-i", str(video), "-vf", "fps=1,scale=640:-2",
           "-frames:v", str(max_frames), "-y", str(tmp / "f_%03d.png")]
    subprocess.run(cmd, capture_output=True, text=True)
    return tmp, sorted(tmp.glob("f_*.png"))


def _detect_face(img, face_sess):
    """Return the highest-confidence face box (x1,y1,x2,y2) or None."""
    import numpy as np

    w, h = img.size
    arr = np.asarray(img.resize((320, 240))).astype(np.float32)
    arr = (arr - 127.0) / 128.0
    arr = arr.transpose(2, 0, 1)[None, :, :, :]
    iname = face_sess.get_inputs()[0].name
    outs = face_sess.run(None, {iname: arr})
    scores = next(o for o in outs if o.shape[-1] == 2)
    boxes = next(o for o in outs if o.shape[-1] == 4)
    conf = scores[0][:, 1]
    idx = int(conf.argmax())
    if conf[idx] < 0.6:
        return None
    b = boxes[0][idx]
    x1, y1, x2, y2 = int(b[0] * w), int(b[1] * h), int(b[2] * w), int(b[3] * h)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 16 or y2 - y1 < 16:
        return None
    return (x1, y1, x2, y2)


def _emotion(face_img, fer_sess):
    """Return an 8-class FER+ probability vector for a face crop."""
    import numpy as np

    g = face_img.convert("L").resize((64, 64))
    arr = np.asarray(g).astype(np.float32)[None, None, :, :]
    iname = fer_sess.get_inputs()[0].name
    logits = np.asarray(fer_sess.run(None, {iname: arr})[0]).reshape(-1)
    e = np.exp(logits - logits.max())
    return e / e.sum()


def analyze_video(video_path: str | Path) -> dict[str, Any] | None:
    """Analyse facial expressions across a video. None if FER is unavailable."""
    if not available():
        return None
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None

    fer_sess, face_sess = _sessions()
    if fer_sess is None:
        return None

    tmp, frames = _extract_frames(Path(video_path))
    try:
        agg = np.zeros(8, dtype=np.float64)
        faces = 0
        for fp in frames:
            try:
                img = Image.open(fp).convert("RGB")
            except Exception:
                continue
            box = _detect_face(img, face_sess) if face_sess is not None else None
            if box is not None:
                crop = img.crop(box)
            elif face_sess is None:
                cw, ch = img.size  # no detector → centred square crop
                s = min(cw, ch)
                crop = img.crop(((cw - s) // 2, (ch - s) // 2, (cw + s) // 2, (ch + s) // 2))
            else:
                continue
            agg += _emotion(crop, fer_sess)
            faces += 1

        if faces == 0:
            return {
                "source": "onnx-ferplus", "available": True,
                "dominant": "neutral", "negative_ratio": 0.0,
                "emotions": {k: (1.0 if k == "neutral" else 0.0) for k in _KEYS},
                "frames_analyzed": len(frames), "faces_found": 0,
                "note": "no face detected in the recording",
            }

        mean = agg / faces
        emo = {k: 0.0 for k in _KEYS}
        for i, label in enumerate(_FERPLUS):
            emo[_MAP[label]] += float(mean[i])
        total = sum(emo.values()) or 1.0
        emo = {k: round(v / total, 3) for k, v in emo.items()}
        return {
            "source": "onnx-ferplus", "available": True,
            "dominant": max(emo, key=emo.get),
            "negative_ratio": round(sum(emo[k] for k in _NEGATIVE), 3),
            "emotions": emo,
            "frames_analyzed": len(frames), "faces_found": faces,
        }
    finally:
        for fp in frames:
            try:
                fp.unlink()
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    import json
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(analyze_video(src) if src else {"available": available()}, indent=2))
