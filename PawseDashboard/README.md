# Pawse Streamlit Dashboard

Pawse is a panda-themed wellbeing dashboard for the intern hackathon prototype. It uses replaceable CSV files in `data/` so fake data can be swapped with real calendar, Teams, wearable, and check-in exports later.

## Run

```powershell
cd "C:\Users\t-melshaer\OneDrive - Microsoft\Dokumente\Microsoft Scout\PawseDashboard"
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Data replacement

Replace rows in these files while keeping the same column names:

- `data/calendar/meetings.csv`
- `data/teams/meeting_metadata.csv`
- `data/wearable/wearable_signals.csv`
- `data/checkins/mood_checkins.csv`

Column details are in `data/data_schema.md`.
