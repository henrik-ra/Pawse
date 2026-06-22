# 🔬 Prior Art & Opportunities — Research across all Pawse areas

> **Pure research / planning** — what is possible, what would be cool, **where proven approaches already exist**,
> on which Pawse can build (or which it can beat).
> Complements [`azure-architecture.md`](azure-architecture.md), [`product-vision.md`](product-vision.md)
> and [`ml-and-teams-integration.md`](ml-and-teams-integration.md). As of June 2026.

Pawse doesn't reinvent the wheel — almost every **individual** building block exists as a product or research.
The **new** part is the **combination**: calendar + wearable + voice → **one** explainable score → **one action** in the calendar, embodied by a **companion**. This document shows, per area, what we build on.

---

## 1. Wearable stress score — the science & the products

### 1.1 What the score is physiologically based on (robust)

The central, scientifically well-documented marker is **HRV (Heart Rate Variability)** — the variation in the intervals between heartbeats:

| Fact (documented) | Meaning for Pawse |
|---|---|
| **Stress lowers HRV** — under acute time pressure & emotional tension, the **HF component** in particular drops | Falling HRV over the day = a hard, objective overload marker |
| **High HRV** = parasympathetic ("rest") activity; **low HRV** = sympathetic ("stress") activity | Allows "you're recovering right now" vs. "you're in fight mode" |
| HRV is linked to **emotion regulation, attention, decision quality** | Supports statements like "after the 4th meeting you make worse decisions" |
| Repeatedly low HRV correlates with **exhaustion/burnout tendency** | Justifies the long-term burnout trend (non-medical!) |

**Standard HRV measures** (all computable from the RR intervals — well documented):

| Measure | What it is | Practice |
|---|---|---|
| **RMSSD** | Root Mean Square of the intervals between successive beats | 🥇 Best short-term stress marker, even from ~1 min of data |
| **SDNN** | Standard deviation of the NN intervals | Overall variability (more long-term) |
| **pNN50** | Proportion of beat pairs that differ by > 50 ms | Simple, intuitive |
| **LF/HF ratio** | Ratio of low-/high-frequency components | "Stress balance" — but contested, use with caution |

> **Concretely for Pawse:** When the wearable API provides **RR intervals** or HRV (Apple Watch, Fitbit/Pixel via Health Connect, Garmin, Oura, Polar), we compute **RMSSD** and compare it against the user's **personal baseline**. "Today 30% below your normal" is more honest than an absolute value.

### 1.2 Existing product scores (exactly our model — and what we do better)

| Product | Score | Based on | What Pawse does differently |
|---|---|---|---|
| **Whoop** | *Strain* & *Recovery* | HRV (RMSSD), resting heart rate, sleep | Whoop knows **no calendar** → Pawse explains the *why* (meetings) |
| **Oura Ring** | *Readiness* | Nighttime HRV, temperature, sleep | Oura is retrospective/in the morning → Pawse reacts **intraday** |
| **Garmin** | *Body Battery* | HRV, stress, activity | Garmin = sports focus → Pawse = **work context** |
| **Apple Watch** | *Vitals*, "mindful minutes" | HRV (SDNN), heart rate | Apple doesn't act → Pawse **blocks focus time** |
| **Samsung / Fitbit** | *Stress Management / Body Energy* | EDA (skin conductance), HRV | The Fitbit API dies in 2026 → our adapter strategy kicks in |

**Takeaway:** A "strain/recovery" score from HRV is **proven and accepted**. Pawse copies the concept and adds the **missing context** (why was the day hard?) + the **missing action** (what to do?). That's our gap in the market.

### 1.3 Pawse's device strategy in competitive comparison

| Device | Competitor uses | Pawse uses it differently |
|---|---|---|
| **Fitbit** | Own app (Health Dashboard) | Fitbit HR + calendar = explainable score + action |
| **Apple Watch** | Health app (isolated) | iOS Shortcut push → Pawse combines with meetings |
| **Garmin / Polar** | Sports focus | Roadmap adapter, same interface |

**Core unique selling point:** We're not aware of any competitor that simultaneously reads device data **and** calendar
and derives a **calendar action** from them. That's the gap Pawse fills.

### 1.4 Cool & feasible: HRV biofeedback as a recovery action

Well documented: **Resonance breathing with HRV biofeedback demonstrably reduces stress/anxiety** (meta-analysis, large effect size).

→ **Feature idea:** When the panda turns red (HR spike detected), it offers a
**60-second breathing exercise** (slow inhale/exhale ~6 breaths/min).
This is the most scientifically supported immediate intervention and fits
perfectly with the "acting guardian angel" — and can be demonstrated live in the demo
when the Fitbit provides real HR data.

---

## 2. Voice biomarkers — research & ready-made building blocks

> Details on models/datasets in [`ml-and-teams-integration.md`](ml-and-teams-integration.md). Here the **prior-art classification**.

| Area | Proven approach | Maturity |
|---|---|---|
| **Acoustic features** | openSMILE **eGeMAPS** (88 features) is an established feature set for emotion/stress from voice | 🟢 common in research |
| **Pretrained models** | `audeering` wav2vec2 (Arousal/Valence) — directly usable | 🟢 production-ready |
| **Depression/distress detection** | The DAIC-WOZ corpus is *the* reference (PHQ-8 labels) | 🟡 research, application required |
| **Commercial** | Companies like *Ellipsis Health*, *Kintsugi*, *Sonde Health* build exactly "mental health from voice" | 🟢 shows the market exists & works |

**Takeaway:** "Stress from voice" is **not a pipe dream** — there's an entire industry segment (Kintsugi, Sonde, Ellipsis). That's strong pitch material ("established research field"), but also a reminder to be **cautious/ethical** (not a diagnostic tool, opt-in, EU GDPR).

---

## 3. Calendar intelligence — the most mature market

This is where there's the **most** competition — good, because it proves demand and provides patterns to borrow.

| Product | What it can do | What Pawse adds |
|---|---|---|
| **Reclaim.ai** | Auto-blocks focus time, protects habits, "Smart 1:1s" | Reclaim knows **no body** → we block on *real* HRV stress |
| **Clockwise** | Optimizes team calendars, creates "Focus Time", Flexible Meetings | Clockwise is team-/efficiency-driven → Pawse is **well-being**-driven |
| **Microsoft Viva Insights** | Focus-time booking, "Quiet Time", burnout hints — **native in M365** | Viva is aggregated/retrospective → Pawse is **intraday + individual + multimodal** |
| **Cal.com / Motion** | AI day planning, prioritization | No health signal |

**Takeaway & strategically important:** **Microsoft Viva Insights already does focus time & burnout hints** — that's competition *and* a setup. Our pitch: "Viva tells you *after* the week that it was hard. Pawse sees it *during* — from your pulse and your voice — and protects you *before* you tip over." Reclaim/Clockwise show that **auto-blocking of focus time** is an accepted, desired feature → our "protect tomorrow" button stands on proven ground.

---

## 4. The companion (panda) — gamification prior art

The emotional companion is Pawse's differentiation. There are **proven models** for this too:

| Model | Mechanic | What Pawse adopts |
|---|---|---|
| **Tamagotchi / Virtual Pet** | The animal reflects your "care state" | Panda emotion reflects your score — you want to keep it "healthy" |
| **Forest (app)** | A tree grows when you stay focused | Positive reinforcement instead of guilt |
| **Finch** | Self-care bird that "grows" with your habits | Companion as a gentle guide, not a controller |
| **Duolingo (Duo)** | Character with personality, well-timed nudges | Emotional character > sober charts; but **nudge hygiene** (don't be annoying!) |
| **Clippy (counterexample!)** | Intrusive assistant | **Lesson:** What NOT to do — timing & restraint are everything |

**Takeaway:** The "virtual companion that reacts to your state" is a **proven, beloved** pattern (Finch, Forest, Tamagotchi). The psychological strength: an animal that "should be okay" motivates more durably than a number. **The biggest danger is Clippy syndrome** — which is why the strict pop-up discipline (max. 2–3/day, never while speaking) is already in [`product-vision.md`](product-vision.md).

> **Cool, feasible detail:** The panda can give **micro-rewards** — if the user keeps a suggested break, the panda gets "bamboo" / a happy animation. That's the Forest/Finch mechanic and costs little build effort, but creates attachment.

---

## 5. Data-source standards — what we technically build on

| Standard / API | Provides | Relevance |
|---|---|---|
| **Apple HealthKit** | HRV (SDNN), HR, sleep | iPhone users; export via Shortcuts/XML (see [`devices/apple-watch/`](../devices/apple-watch/README.md)) |
| **Android Health Connect** | Central hub for Fitbit/Pixel/Samsung/Garmin | **Successor** to dying individual APIs — one adapter, many devices |
| **Google Health / Fitbit Web API** | Steps, HR, HRV | Our current primary route (see [`devices/google_health/`](../devices/google_health/README.md)) |
| **Microsoft Graph** | Calendar, transcripts, presence | Context + action + visibility |
| **FHIR / SMART on FHIR** | Clinical health-data standard | If Pawse ever goes "serious health" — interoperability |

**Takeaway:** **Android Health Connect** and **Apple HealthKit** are the two big aggregators. Instead of maintaining N device APIs, the most robust strategy long-term is **"one HealthKit adapter + one Health Connect adapter"** — it fits exactly our adapter pattern and survives the Fitbit API shutdown in 2026.

---

## 6. What would be really cool — prioritized ideas from the research

By impact (demo + product) vs. effort:

| Idea | Source/prior art | Impact | Effort |
|---|---|---|---|
| **HRV baseline instead of absolute value** ("30% below your normal") | HRV research | 🟢🟢🟢 credibility | 🟢 low |
| **60-sec breathing exercise when panda is red** | HRV biofeedback meta-analysis | 🟢🟢🟢 real help | 🟢 low |
| **Panda reward for kept breaks** | Forest/Finch | 🟢🟢 attachment | 🟢 low |
| **"Protect tomorrow" button (block focus time)** | Reclaim/Clockwise/Viva | 🟢🟢🟢 closes the loop | 🟡 medium |
| **Multimodal score (calendar+HRV+voice)** | Whoop + SER research | 🟢🟢🟢 unique selling point | 🟡 medium |
| **Predictive: "Friday you'll tip over"** | Time series (Prophet) | 🟢🟢 wow | 🟡 medium |
| **Team aggregate traffic light (anonymous)** | Viva Insights | 🟢🟢 B2B story | 🔴 high (data privacy) |
| **Voice live bot in the meeting** | Teams Real-time Media | 🟢 wow | 🔴 very high |

### Recommendation for the hackathon (max impact, low effort)
1. ⌚ **Live Fitbit or Apple Watch** — a real pulse makes the score undeniably real.
2. **HRV baseline comparison** in the score — instantly more credible than an absolute value.
3. **Panda red on HR spike → 60-sec breathing exercise** — the scientifically best immediate action.
4. **"Protect tomorrow" button** — the visible "acting guardian angel" moment.
5. **Reward mechanic** for the panda — emotional attachment in the demo.

---

## 7. Honesty & ethics (runs through all areas)

The research makes two things clear:
- **The markers are real** (HRV↔stress, voice↔affect are scientifically supported) — good for credibility.
- **But they are not diagnostic.** HRV is prone to artifacts and depends heavily on individual/context; voice affect is probability, not truth.

→ Pawse consistently positions itself as a **supportive companion, not a medical device**: opt-in, personal baseline, data minimization, deletion paths, **no** sharing of individual values. That is also exactly the trustworthy pitch.

---

## 8. One-sentence summary of the research

> Every building block of Pawse already exists individually and proven — HRV scores (Whoop/Oura), voice affect (Kintsugi/openSMILE), focus-time automation (Reclaim/Viva), companion gamification (Finch/Forest). **What's new about Pawse is the combination: it fuses these signals into one explainable score — fed by real device data (Fitbit / Apple Watch) — and derives from it a protective action in the calendar, embodied by a panda that should be okay.**

```
Whoop knows your pulse — but not your calendar.
Reclaim knows your calendar — but not your body.
Pawse knows both — and acts for you.
```
