# Voice biomarkers

Turn an audio file into voice features and an aggregate **stress index (0..1)**.

- **Stub mode:** `analyze_voice.py` returns mock features so the pipeline runs end-to-end.
- **Real mode:** uses `librosa` + `soundfile` to compute pitch, energy, and pause features.

```powershell
# real mode needs: pip install librosa soundfile numpy
python voice-analysis/voice_biomarkers/analyze_voice.py meeting.wav
```

## Output shape

```jsonc
{
  "source": "teams",
  "analyzed_segments": 2,
  "features": { "pitch_variability": 0.0, "speech_rate": 0.0, "pause_ratio": 0.0, "energy": 0.0 },
  "stress_index": 0.0      // 0 = calm, 1 = high stress
}
```

This `stress_index` is what gets handed to the Pawse Score engine.
