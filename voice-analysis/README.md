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
| **Speaking ratio** | Fraction of meeting time spent talking (diarization) |
| **Energy trend** | Declining energy across the day = exhaustion signal |

## ML Roadmap (planned)

Three development stages for burnout detection:

| Stage | Tool | Status |
|---|---|---|
| **1 — Classic** | `librosa` — Pitch, Jitter, Pause Ratio, Energy → Weighted Blend | ✅ Stub available |
| **2 — openSMILE** | `eGeMAPSv02` (88 features) → SVM / XGBoost | planned |
| **3 — Deep Learning** | `wav2vec 2.0` / `Whisper` + fine-tuning on DAIC-WOZ | planned (Azure ML) |

> **Concrete model & dataset recommendations** (pretrained, Hugging Face) and the
> **exact path to the Teams data** (Graph Transcript API vs. real-time bot vs. Viva/WorkIQ)
> are in [`docs/ml-and-teams-integration.md`](../docs/ml-and-teams-integration.md).

## Teams recording → Azure pipeline (planned)

```
Teams recording (mp4)
  → OneDrive/SharePoint
  → MS Graph Webhook
  → Azure Blob Storage  (TTL: 2 days — GDPR)
  → Event Grid → Service Bus
  → voice-analysis Job (Container App)
  → Feature Extraction → ML model
  → Cosmos DB (score only, no raw audio)
```

> See [`docs/azure-architecture.md`](../docs/azure-architecture.md) — Section 3b.

## Privacy

Voice is sensitive. Opt-in, raw audio is automatically deleted after 2 days (TTL),
only the computed `stress_index` is stored permanently.
**Not a medical diagnostic tool.**

> Heavy audio deps (`librosa`, `moviepy`, `soundfile`) are commented out in
> `requirements.txt` — enable them when you implement the real pipeline. The stubs run
> without them.
