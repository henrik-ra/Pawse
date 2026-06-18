"""Extract audio from a Teams meeting recording.

Stub-friendly: if `moviepy` is not installed, prints the planned steps instead
of failing, so the rest of the project still runs.

Usage:
    python voice-analysis/video_extraction/extract_audio.py meeting.mp4
"""
from __future__ import annotations

import sys
from pathlib import Path


def extract_audio(video_path: str | Path, out_path: str | Path | None = None) -> Path:
    """Extract the audio track of a video file to a .wav file.

    Returns the path to the (intended) audio file.
    """
    video = Path(video_path)
    out = Path(out_path) if out_path else video.with_suffix(".wav")

    try:
        from moviepy.editor import VideoFileClip  # type: ignore
    except ImportError:
        print("[stub] moviepy not installed — would extract audio from:")
        print(f"        {video}  ->  {out}")
        print("        Install with: pip install moviepy")
        return out

    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    with VideoFileClip(str(video)) as clip:
        if clip.audio is None:
            raise ValueError("Video has no audio track.")
        clip.audio.write_audiofile(str(out))
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "recordings/meeting.mp4"
    result = extract_audio(src)
    print(f"Audio target: {result}")
