# Video extraction

Extract the audio track from a Teams meeting recording so it can be analysed.

- **Stub mode:** `extract_audio.py` describes the steps and validates paths.
- **Real mode:** uses `moviepy` (or `ffmpeg`) to write a `.wav` next to the `.mp4`.

```powershell
# real mode needs: pip install moviepy
python voice-analysis/video_extraction/extract_audio.py meeting.mp4
```

> Put recordings in a local `recordings/` folder — it is git-ignored so large media
> never gets committed.
