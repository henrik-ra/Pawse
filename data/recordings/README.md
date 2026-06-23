# 🎙️ Recordings drop folder (local only)

Drop meeting recordings (`.mp4`, `.m4a`, `.wav`, …) here to have the Pawse
media agent analyse them. Files in this folder are **git-ignored** — they never
leave your machine; only the derived numbers (voice stress, facial-expression
mix) are uploaded.

You usually don't need to copy anything here: the agent also reads your **Teams
recordings** straight from the OneDrive-synced folder
(`%OneDrive%\Recordings`).

## Run it

```powershell
# one-off analysis of all recordings (OneDrive + this folder)
python voice-analysis/media_analyzer.py

# watch for new recordings and push results to the cloud dashboard
$env:PAWSE_API_URL = "https://<your-container-app>"
python agent/recording_watcher.py --once     # single pass
python agent/recording_watcher.py            # keep watching
```

Decoding `.mp4`/`.m4a` needs an ffmpeg backend (no system install required):

```powershell
pip install imageio-ffmpeg
```

`.wav` files are analysed directly with numpy — no extra dependency.
