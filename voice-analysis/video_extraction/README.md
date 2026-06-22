# Video extraction

Extract the audio track from a Teams meeting recording so it can be analysed.

- **Stub mode:** `extract_audio.py` describes the steps and validates paths.
- **Real mode (local):** uses `moviepy` (or `ffmpeg`) to write a `.wav` next to the `.mp4`.
- **Real mode (Azure, planned):** mp4 lands in Azure Blob Storage via MS Graph Webhook
  → Event Grid automatically triggers the `voice-analysis` Container Apps Job.

```powershell
# local real mode needs: pip install moviepy
python voice-analysis/video_extraction/extract_audio.py meeting.mp4
```

## Getting Teams recordings (planned)

Two paths:
1. **Manual:** download the Teams recording from OneDrive → process it locally.
2. **Automatic (Azure):** MS Graph `OnlineMeetings` API + Change Notification Webhook
   → Pawse is notified when a new recording appears in OneDrive
   → automatically copied to Blob Storage → the pipeline starts.

> Put local recordings in a `recordings/` folder — it is git-ignored so large media
> never gets committed.
