"""Extract an audio track (or the audio of a video) to 16 kHz mono WAV.

Retrospective/offline use: turn a Teams ``.mp4`` (or ``.m4a``/``.mp3`` …) into a
plain PCM WAV that :mod:`analyze_voice` can read with nothing but numpy.

Backends, tried in order (graceful — never hard-crashes the pipeline):
  1. system ``ffmpeg`` on PATH
  2. the static binary bundled with the ``imageio-ffmpeg`` pip package
  3. none available  → raises :class:`AudioExtractionUnavailable`

Usage:
    python voice-analysis/video_extraction/extract_audio.py meeting.mp4
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class AudioExtractionUnavailable(RuntimeError):
    """Raised when no ffmpeg backend is available to decode the media."""


def _resolve_ffmpeg() -> str | None:
    """Return a path to an ffmpeg executable, or None if none is available."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def audio_backend_available() -> bool:
    """True when audio decoding (ffmpeg) is available."""
    return _resolve_ffmpeg() is not None


def extract_audio(
    media_path: str | Path,
    out_path: str | Path | None = None,
    sample_rate: int = 16000,
) -> Path:
    """Extract audio from ``media_path`` to a mono WAV and return its path.

    Raises FileNotFoundError if the input is missing, or
    AudioExtractionUnavailable if no ffmpeg backend can be found.
    """
    media = Path(media_path)
    if not media.exists():
        raise FileNotFoundError(f"Media not found: {media}")

    out = Path(out_path) if out_path else media.with_suffix(".wav")
    ffmpeg = _resolve_ffmpeg()
    if ffmpeg is None:
        raise AudioExtractionUnavailable(
            "No ffmpeg backend found. Install one with:  pip install imageio-ffmpeg"
        )

    cmd = [
        ffmpeg, "-y", "-i", str(media),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "wav", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise AudioExtractionUnavailable(
            f"ffmpeg failed to extract audio from {media.name}: "
            f"{proc.stderr.strip()[-300:]}"
        )
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "recordings/meeting.mp4"
    try:
        result = extract_audio(src)
        print(f"Audio written to: {result}")
    except (AudioExtractionUnavailable, FileNotFoundError) as exc:
        print(f"[skip] {exc}")
