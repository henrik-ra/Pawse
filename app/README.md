# 🥉 Task 3 — Pawse app (dashboard + connection)

> **Owners: Person 5 + Person 6**

The panda app. This is what judges see in the demo — they decide in **5 seconds**.

## What it shows

- 🧠 **Pawse Score** (big + central) with the strain label
- 📊 2–3 small charts (meeting density, heart-rate trend)
- 🐼 Panda branding + friendly tone
- 💡 Recommendations card

## Run it

Just open the page — it's a self-contained static site (charts via Chart.js CDN).

```powershell
start app/index.html
```

It reads `../data/alex_workday.json` and applies the same scoring rules as
`scoring/pawse_score.py`. To wire it to live Python output later, have the scoring
script write a `result.json` the page can fetch.

## Files

| File | Purpose |
|---|---|
| `index.html` | Layout + structure |
| `style.css` | Panda theme |
| `app.js` | Loads data, computes score, renders charts |
