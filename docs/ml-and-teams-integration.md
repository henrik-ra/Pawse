# 🧠 ML Models, Datasets & Teams/Microsoft 365 Integration

> **Pure planning / research** — none of this is built.
> Complements [`azure-architecture.md`](azure-architecture.md) (Section 3b),
> [`product-vision.md`](product-vision.md) and
> [`research-prior-art.md`](research-prior-art.md) (prior art across all areas).
> Research status: June 2026.

This document answers four questions:

1. **Which ML models** can be used for burnout/stress detection from voice — are there **pretrained** models?
2. **Which datasets** exist for fine-tuning / validating?
3. **How do you get the Teams data** (recording, transcript, meeting metadata) — is that possible, e.g., via Viva/"WorkIQ"?
4. **How do you integrate Pawse visibly** into Teams/Outlook — also **for others** (team lead, colleagues)?

---

## 1. ML Models for Stress/Burnout from Voice

### 1.1 Two signal sources — and therefore two model families

From a Teams recording you get **audio** *and* (via Graph) a **transcript**.
This enables a **multimodal** approach:

| Modality | What you measure | Model type |
|---|---|---|
| **Acoustics (audio)** | Pitch, jitter, energy, speech rate, pauses | Speech Emotion Recognition (SER) |
| **Language (transcript)** | Word choice, negativity, "I have no time", pressure | Text sentiment / NLP |
| **Behavior (metadata)** | Meeting density, back-to-backs, talk share | Classic ML (tabular) |

In the end, the **Pawse Score** is a **fusion model** that weights these three streams (already today: [`scoring/pawse_score.py`](../scoring/pawse_score.py)).

### 1.2 Pretrained audio models (Hugging Face) — yes, they exist

There are **ready-made, downloadable** models. Recommendation in 3 tiers:

| Tier | Model | What it can do | Note |
|---|---|---|---|
| **A — Ready to use** | [`audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim`](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim) | Delivers **Arousal / Dominance / Valence** (dimensional emotion, 0–1) directly from raw audio | **Perfect for us** — "Arousal" ≈ tension/stress. ~300M params. Research license (CC-BY-NC-SA), fine for a hackathon |
| **A — Alternative** | [`firdhokk/speech-emotion-recognition-with-openai-whisper-large-v3`](https://huggingface.co/firdhokk/speech-emotion-recognition-with-openai-whisper-large-v3) | 7–8 discrete emotions (angry, sad, fearful, neutral …) on a Whisper basis | Very recent, well maintained, discrete classes |
| **B — Benchmark baseline** | [`superb/wav2vec2-large-superb-er`](https://huggingface.co/superb/wav2vec2-large-superb-er) | Emotion recognition from the SUPERB benchmark (IEMOCAP-trained) | Stable, well-documented reference |

**Why `audeering` is our favorite:** it gives **continuous values** instead of just classes.
"Arousal" can be hooked directly into the Pawse Score as a **stress proxy** (0..1) — exactly the `stress_index` field that [`voice-analysis/`](../voice-analysis/README.md) already provides as a stub today.

```python
# Sketch (planned) — Audio → Arousal as stress proxy
from transformers import pipeline
clf = pipeline("audio-classification",
               model="audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim")
result = clf("meeting_segment.wav")     # → arousal/dominance/valence
stress_index = result["arousal"]        # 0..1  → in pawse_score.py
```

### 1.3 Text sentiment from the transcript (second signal source, almost free)

Since Graph delivers the **transcript** (see Section 3), you can obtain a second stress signal **without audio** processing:

| Model | Purpose |
|---|---|
| `cardiffnlp/twitter-roberta-base-sentiment-latest` | Negative/Neutral/Positive per utterance |
| `j-hartmann/emotion-english-distilroberta-base` | 7 emotions from text (anger, fear, joy …) |
| Azure AI Language — *Sentiment & Opinion Mining* | Managed, no own model needed, GDPR-compliant in EU region |

> For a hackathon, **Azure AI Language** is often the fastest route: REST call, no GPU, EU hosting.

### 1.4 Behavioral/tabular model (the actual burnout trend)

Burnout is **not a single moment** but a **trend over weeks**. For that, a classic model on the daily Pawse features:

| Approach | When |
|---|---|
| **Moving threshold / EWMA** (no ML) | MVP — "3 red days in a row" |
| **XGBoost / LightGBM** on daily features | Once a few weeks of data are available |
| **Prophet / time series** on the score trajectory | Prediction "you'll crash on Friday" |

> Details on the predictive model are in [`azure-architecture.md`](azure-architecture.md), Section 6.

### 1.5 Recommended model stack (hackathon → production)

```
Tier 1 (now, demo):      librosa features + audeering arousal   → stress_index
Tier 2 (transcript):     + Azure AI Language sentiment          → second signal
Tier 3 (production):     Fine-tune wav2vec2 on DAIC-WOZ         → own stress model
Fusion:                  Weighted combination in pawse_score.py → one score 0..100
```

---

## 2. Datasets (for fine-tuning & validating)

> **Important:** Most require an **application / EULA** and are "research only".
> For the hackathon, the **pretrained** models from 1.2 are sufficient — datasets are for the **production** roadmap.

| Dataset | Content | Suitability | Access |
|---|---|---|---|
| **DAIC-WOZ** | Clinical interviews, **depression/distress** labels (PHQ-8), audio + transcript | 🥇 Closer to "burnout" than pure emotion | Application (USC), research-only |
| **IEMOCAP** | ~12 h acted dialogues, categorical + dimensional emotion | Standard benchmark for SER | Application (USC) |
| **MSP-Podcast** | Very large, natural speech, Arousal/Valence/Dominance | Basis of the `audeering` model | License (UT Dallas) |
| **RAVDESS** | 24 speakers, 8 emotions, cleanly labeled | Easy entry point, **freely available** | Open (Zenodo) |
| **CREMA-D** | 91 speakers, 6 emotions, diverse | Free, good for robustness | Open (GitHub) |
| **MELD** | Multimodal dialogue emotion (Friends series) | Practice text+audio fusion | Open |

**Recommendation:**
- **Quick experimentation / securing the demo:** RAVDESS + CREMA-D (free).
- **Closer to actual burnout:** apply for DAIC-WOZ (for the serious production phase).

---

## 3. Getting at the Teams data — what works, what doesn't

This is the most important technical crux. There are **three ways**, with very different levels of effort.

### 3.1 Overview: three access paths

| Path | What you get | Effort | For Pawse? |
|---|---|---|---|
| **A — Graph: transcript & recording (after the fact)** | Finished transcript (VTT) + recording file *after* the meeting | 🟢 medium | ✅ **recommended** |
| **B — Graph: callRecords (metadata)** | Who/when/how long, duration, participants — **no** content | 🟢 low | ✅ complementary |
| **C — Real-time media bot (live audio)** | Raw audio live (50 frames/s) during the meeting | 🔴 very high | ❌ too expensive for a hackathon |

### 3.2 Path A — transcript & recording via Microsoft Graph (recommended)

Microsoft **explicitly** recommends **not** using the raw media bot for "meeting intelligence", but rather the **Transcript API** — exactly our case.

**Retrieve transcript** ([`callTranscript`](https://learn.microsoft.com/en-us/graph/api/resources/calltranscript)):

```http
GET /me/onlineMeetings/{meetingId}/transcripts
GET /me/onlineMeetings/{meetingId}/transcripts/{transcriptId}/content?$format=text/vtt
```

Returns, among other things:
- `content` (stream) — the actual transcript (VTT, time-coded, **with speaker**)
- `metadataContent` — time-aligned utterances
- `meetingOrganizer`, `createdDateTime`, `endDateTime`

**Delta query** (all new transcripts for a person — ideal for a background job):

```http
GET /users/{id}/onlineMeetings/getAllTranscripts/delta
```

**Required permissions (Graph):**
- `OnlineMeetingTranscript.Read.All` (Application) — background job reads transcripts
- `OnlineMeetings.Read` / `.ReadWrite` — resolve the meeting
- Prerequisite: **transcription must be enabled in the meeting** (org policy / user clicks "start transcript" or auto-transcription).

**Recording file** comes analogously via `…/recordings` or lands in OneDrive/SharePoint → pick it up from there via a Graph webhook (see pipeline in [`voice-analysis/README.md`](../voice-analysis/README.md)).

> So for the **audio biomarkers** you need the recording, for **text sentiment** only the transcript. The transcript alone is the **fastest** path to a second stress signal.

### 3.3 Path B — callRecords (meeting metadata, entirely without content)

For the **behavioral signals** (meeting density, duration, talk share), the [Call Records API](https://learn.microsoft.com/en-us/graph/api/resources/callrecords-api-overview) is sufficient — **data-minimal**, because no content:

```http
GET /communications/callRecords/{id}        # Sessions, segments, participants, duration
```

- The record is created **after** the meeting ends, **retained for 30 days**.
- Subscribable via **Change Notification** (`/communications/callRecords`) → Pawse automatically learns about every finished meeting.
- Permission: `CallRecords.Read.All` (Application).

> Combination in Pawse: **callRecords** = "how full was the day", **Transcript/Audio** = "how stressed it sounded".

### 3.4 Path C — real-time media bot (live audio) — deliberately NOT

Technically possible, but per the Microsoft docs **not recommended** for AI scenarios:

- Delivers raw audio (16 kHz, 50 frames/s) live, including "dominant speaker".
- **But:** requires **C#/.NET on Windows Server VMs, possibly GPU**, high bandwidth, media codec know-how (SILK/G.722/H.264) — a huge infrastructure effort.
- The main purpose is **compliance recording** (MiFID II/HIPAA), not wellbeing.

→ **For Pawse: leave it out.** Mention it only as a "vision/enterprise expansion" in the slides. We create the live feel via the **wearable** data (HR/HRV in real time) + post-meeting transcript.

### 3.5 And "WorkIQ" / Viva Insights — can you get the data through that?

In short: **Partially — but not what we need, and not easily.**

- **Viva Insights** (formerly Workplace Analytics / MyAnalytics; "WorkIQ" is the old brand from the VoloMetrix acquisition) delivers **aggregated collaboration metrics**: meeting hours, focus time, after-hours work, network reach.
- That is conceptually **close to Pawse** (overload indicators!), **but**:
  - Access goes through the **Analyst/Advanced Insights** interface or curated data exports, **not** through a simple "give me live values" REST API.
  - It is **aggregated & privacy-filtered** (minimum group sizes), not the granular individual real-time stream that our score needs.
  - License/tenant prerequisites (Viva Insights Advanced) — usually not available in a hackathon.

**Conclusion for Pawse:**
- **Do not** plan it as a primary data source.
- **Definitely** use it for **positioning**: "Pawse does in **real time & individually** what Viva Insights only shows **aggregated & retrospectively** — and closes the loop with an **action** (protect an appointment)."
- Optionally as **validation**: Viva Insights aggregates (meeting hours/week) are well suited to sanity-check our score against an official Microsoft metric.

> We compute our **own** meeting density directly from the **calendar** anyway (`GET /me/calendarView`) — that's live, granular, and without a Viva license.

---

## 4. Visible integration into Teams & Outlook (also for others)

Today Pawse thinks "single-player" (my dashboard, my calendar). Here are the options to **make it visible where work happens** — and to gently open it up **for the team**.

### 4.1 For myself — visible in the workflow

| Surface | What Pawse does here | Microsoft building block |
|---|---|---|
| **Outlook — Actionable Message / Adaptive Card** | Daily mail/card "Score 78 — should I block focus time tomorrow? [Yes]" with a button that **directly** writes an appointment | Actionable Messages, `POST /me/events` |
| **Outlook add-in (task pane)** | When accepting an invitation: "This would be your 5th back-to-back — add a buffer?" | Office Add-in (web) |
| **Teams — personal app (tab)** | The panda dashboard **as a tab in Teams** (instead of a separate browser) | Teams Tab (your web app in an iFrame) |
| **Teams — bot (proactive message)** | The panda checks in via chat: "5-min break? 🐼" — exactly the "pop-up" from the product vision | Bot Framework, proactive message |
| **Teams — Adaptive Card in chat** | Score + buttons ("Break", "Protect tomorrow") as an interactive card | Adaptive Cards |
| **Outlook/Teams — presence/status** | On a red score, automatically set "Focus time/Do not disturb" + a status message | Graph `presence`, `/me/reminderView`, Automatic Replies |

> **Hackathon recommendation:** Embed the existing [`app/`](../app/index.html) dashboard **as a Teams tab** (low effort, big wow) **plus** an **Outlook Adaptive Card** with a real "protect tomorrow" button (visibly closes the loop). The proactive **bot** as the next tier.

### 4.2 For others — team wellbeing (sensitive, therefore dosed)

Here **data protection** is paramount. Never leak individual stress values to supervisors. Three safe patterns:

| Pattern | Visible to | What is shared |
|---|---|---|
| **Aggregated team traffic-light dashboard** | Team lead | **Only aggregated & anonymized** (e.g., "team load this week: high", minimum size 5), never per person |
| **Shared "focus-time respect"** | Whole team | Pawse proposes **common** meeting-free slots (`/me/findMeetingTimes`, `getSchedule`) → as a team appointment |
| **Opt-in "I need a break" signal** | Self-selected colleagues | The user **actively shares** a status ("keep it short today") — pull, not push |
| **Meeting-hygiene hint to organizer** | Meeting creator | "This meeting puts 6 people back-to-back — end 5 min early?" (via **Schedule** data, without stress values) |

**Graph building blocks for the team:**
- `GET /me/findMeetingTimes` — find common free time (for protected focus slots)
- `POST /me/calendar/getSchedule` — availability of multiple people (free/busy, **without** content)
- Team aggregation job (Container App) → writes **only** anonymized metrics to Cosmos → team tab reads that

> **Guardrail (anchored in [`azure-architecture.md`](azure-architecture.md), Section 9):** Individual biomarkers stay **private**. For others there are **only** aggregates (k-anonymity) or **signals actively shared by the user**. That is also the most honest pitch story: "Pawse protects you without spying on you."

---

## 5. Summary — what we are planning

| Area | Decision |
|---|---|
| **Audio model** | Pretrained: `audeering/wav2vec2…-dim` (Arousal as stress proxy) |
| **Text model** | Azure AI Language Sentiment on the transcript (fast, EU, managed) |
| **Trend model** | EWMA/threshold → later XGBoost/Prophet on daily scores |
| **Datasets** | Demo: RAVDESS/CREMA-D (free); production: apply for DAIC-WOZ |
| **Teams data** | **Graph Transcript API** (content) + **callRecords** (metadata); **no** real-time media bot |
| **Viva/WorkIQ** | Not as a data source — as positioning & optional validation |
| **Visible (me)** | Teams tab (dashboard) + Outlook Adaptive Card with a real action button + (later) proactive bot |
| **Visible (team)** | Only **aggregated/anonymized** or **opt-in shared**; protected focus slots via `findMeetingTimes` |

> All efforts are **planning**. None of this is built. For build order & demo focus, see [`product-vision.md`](product-vision.md), section "Prioritized Build Plan".
