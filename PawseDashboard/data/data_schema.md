# Pawse data inputs

Replace the sample CSV rows with real exported data later, but keep the column names unchanged so the dashboard continues to work.

| File | Purpose | Required columns |
|---|---|---|
| `data/calendar/meetings.csv` | Calendar blocks and meeting load | `date`, `meeting_id`, `title`, `start_time`, `end_time`, `meeting_type`, `organizer`, `is_required`, `is_after_hours` |
| `data/teams/meeting_metadata.csv` | Teams-style meeting intensity signals | `date`, `meeting_id`, `total_minutes`, `speaking_minutes`, `chat_messages`, `action_items`, `interruptions`, `sentiment_score`, `stress_keywords` |
| `data/wearable/wearable_signals.csv` | Smartwatch/device-style wellbeing signals | `date`, `time`, `heart_rate`, `baseline_heart_rate`, `steps`, `hrv_ms`, `stress_level`, `sleep_hours` |
| `data/checkins/mood_checkins.csv` | Optional user self-check-ins | `date`, `time`, `energy_level`, `mood`, `notes` |
