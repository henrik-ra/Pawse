# 🎙️ Voice analysis

Detect stress / burnout signals from **voice biomarkers** in Teams meetings.

## Pipeline

```
Teams recording (.mp4)
        │  video_extraction/extract_audio.py
        ▼
   audio (.wav)
        │  voice_biomarkers/analyze_voice.py
        ▼
  stress index (0..1) + features  ──▶  fed into the Pawse Score
```

| Folder | Purpose |
|---|---|
| [`video_extraction/`](video_extraction/) | Extract the audio track from Teams meeting recordings |
| [`voice_biomarkers/`](voice_biomarkers/) | Analyse voice features (pitch, jitter, pauses, energy) → stress index |

## Voice biomarkers we look at

| Feature | Why it matters |
|---|---|
| **Pitch (F0) variability** | Rises under stress |
| **Jitter / shimmer** | Vocal instability under cognitive load |
| **Speech rate & pauses** | Fewer pauses / rushing = pressure |
| **Energy / loudness** | Tension correlates with vocal effort |

## Privacy

Voice is sensitive. This is **opt-in**, processed locally where possible, and used only to
produce an aggregate stress index — **never a medical diagnosis**.

> Heavy audio deps (`librosa`, `moviepy`, `soundfile`) are commented out in
> `requirements.txt` — enable them when you implement the real pipeline. The stubs run
> without them.
