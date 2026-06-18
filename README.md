# 🐼 Pawse

> **Stay in flow — and know when to pawse.**

Your calendar might look full, but your energy tells a completely different story.
**pawse** reads both — combining meeting patterns with real-world signals like heart rate
and movement.

It turns invisible stress into clear insights and smarter decisions for your workday.

So instead of reacting too late, you know exactly when it's time to pawse.

---

Pawse is a wellbeing tool that reads signals from your **calendar**, **meetings**, and
**wearable devices** (heart rate, movement) plus **voice biomarkers** from meetings to
detect overload, give your day a **Pawse Score (0–100)**, explain *why*, and suggest
helpful recovery actions.

> ⚠️ Pawse is **private, opt-in, and not a medical diagnosis.**

---

## 🧭 The flow

1. **Data** → sample workday (calendar + wearable + voice signals)
2. **Score** → turn signals into a Pawse Score + reasons
3. **App** → show it visually with the panda dashboard

```
┌────────────┐     ┌──────────────┐     ┌──────────────┐
│   data/    │ ──▶ │   scoring/   │ ──▶ │     app/     │
│ (Task 1)   │     │  (Task 2)    │     │   (Task 3)   │
└────────────┘     └──────────────┘     └──────────────┘
       ▲                  ▲
       │                  │
┌────────────┐     ┌──────────────────┐
│  devices/  │     │ voice-analysis/  │
│ fitbit /   │     │ teams video +    │
│ apple-watch│     │ voice biomarkers │
└────────────┘     └──────────────────┘
```

---

## 📁 Project structure

| Folder | Purpose | Owners |
|---|---|---|
| [`data/`](data/) | **Task 1** — Sample workday data ("Alex", an overloaded day) | Person 1 + 2 |
| [`scoring/`](scoring/) | **Task 2** — Pawse Score + logic (signals → score + reasons) | Person 3 + 4 |
| [`app/`](app/) | **Task 3** — Panda dashboard / connection UI | Person 5 + 6 |
| [`devices/`](devices/) | Wearable integrations (Fitbit, Apple Watch) | — |
| [`voice-analysis/`](voice-analysis/) | Teams video → audio → voice biomarkers (stress/burnout) | — |

---

## 🚀 Quick start

```powershell
# (optional) create a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# install Python dependencies
pip install -r requirements.txt

# run the scoring demo on the sample data
python scoring/pawse_score.py

# open the dashboard
start app/index.html
```

---

## 🎯 Hackathon tasks

- **🥇 Task 1 — Core demo scenario** → `data/` (one perfect overloaded-workday story)
- **🥈 Task 2 — Pawse Score + logic** → `scoring/` (3–5 signals → score + reasons)
- **🥉 Task 3 — Demo dashboard** → `app/` (big score, 2–3 charts, panda, recommendations)