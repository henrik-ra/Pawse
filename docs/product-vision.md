# 🐼 Pawse — Product Vision & Hackathon Focus

> Strategic document: *What* makes Pawse unique and *how* it wins the hackathon.
> Complements the technical [`azure-architecture.md`](azure-architecture.md).

---

## 1. The Core in One Sentence

> **Pawse is not your stress dashboard. Pawse is your guardian angel that acts before you burn out.**

The decisive difference: from **information** ("your score is 82") to **action**
("I've protected 90 minutes of focus time for you tomorrow morning") — based on
**real body signals** from your Fitbit or Apple Watch.

---

## 2. The Three Heroes of the Demo

### ⌚ Hero 1 — The Live Device Signal (the credibility moment)
```
Real heart rate from the Fitbit / Apple Watch
  → Score rises live to 82
  → "Today: 8 meetings, HR peak 99 bpm at 14:00 — exactly during the stakeholder review"
```
This is the moment when the jury sees: this is not a mockup. The body doesn't lie.
**We know of no tool that combines calendar context with real biometric data.**

### 🛡️ Hero 2 — The "Protect Moment" (closed loop)
```
Score high  →  Pawse asks: "Should I protect tomorrow?"
            →  one click
            →  a real event appears in Outlook
            →  measurably better next week
```
This is the differentiation from any fitness tracker: **Pawse closes the loop
all the way into your real calendar.**

### 🐼 Hero 3 — The Panda Companion
The Panda is not the logo — it is an **emotional companion** that makes your state
*tangible*, speaks up on its own, and "lives" with your data.

---

## 3. The Panda Companion (Desktop / Tray / Browser)

### 3a. Emotional States (instead of line charts)
The Panda **reflects your score as a feeling**:

| Score | Panda State | Visual |
|---|---|---|
| 0–39 (Low) | 😌 relaxed, chewing bamboo | green, calm |
| 40–69 (Medium) | 😐 alert, a bit tired | yellow |
| 70–100 (High) | 😵 exhausted, coffee, dark circles | red, "needs a pawse" |

> People remember emotions, not numbers. That is the branding asset.

### 3b. "Pop-up" Behavior (proactive, not annoying)
The Panda **pops up at the right time** — like a friendly colleague:

| Trigger | Pop-up Moment |
|---|---|
| 3 back-to-backs detected | "You just had 3 calls in a row 🐼 — a 5-minute break?" |
| HR spike above baseline + 25 bpm | "Your pulse was just 99 bpm — stand up for a moment?" |
| HRV drops below personal baseline | "Your recovery is dropping. Bamboo time? 🎋" |
| Day over, high score | "Today was a lot. Shall I protect focus time for you tomorrow?" |
| No break at midday | "No lunch break yet — bamboo time? 🎋" |
| Weekly limit reached | "Your social energy budget is almost empty." |

**Design principle:** Max. 2–3 pop-ups per day. Never while you're speaking (respect the Teams
status `InAMeeting`). Always with *one* clear action option.

### 3c. Technical Implementation Options

| Variant | Tech | Advantage |
|---|---|---|
| **Browser dashboard** (now) | existing `app/` + Web Notifications API | available immediately, no install |
| **Desktop tray companion** | Electron / Tauri | lives in the system tray, pops up natively |
| **Teams bot** | Bot Framework + Adaptive Cards | meets the user where they work |
| **Outlook add-in** | Office.js | appears when creating an event |

Hackathon recommendation: **Browser dashboard with web notifications** for the demo
(zero install, instantly showable) + concept slides for tray/Teams as the vision.

---

## 4. The Stats Cockpit (what you see in the Panda app)

More than just the score — a **narrative** view:

| Area | Content |
|---|---|
| **Today** | Large score + Panda emotion + top 3 reasons |
| **Live signal** | ⌚ Current HR value straight from the device (badge: "● LIVE Fitbit") |
| **Pawse budget** | "6h of social energy left this week" (more tangible than 0–100) |
| **Weekly story** | "Wednesday was your limit. Here's why." — narrative, not just a chart |
| **HR trend** | Heart rate over the day, peaks marked at meetings |
| **Suggestions** | Active recommendations with a 1-click action ("Protect tomorrow") |
| **What-if** | Cancel a meeting → live score preview, *before* the decision |

---

## 5. Functional Levers (Impact vs. Effort)

| Idea | Why it's strong | Effort |
|---|---|---|
| **Live Fitbit / Apple Watch in the dashboard** | Credibility — a real body, no mockup | low (setup) |
| **Protect button → real Outlook event** | The demo-winning moment | medium |
| **Panda emotional states** | Branding, memorable | low |
| **Pop-up companion** | Proactive instead of passive = "alive" | medium |
| **Pawse budget** | More tangible than an abstract score | low |
| **Weekly story** | Emotional memory instead of numbers | low |
| **What-if simulator** | Shows impact before the decision | medium |
| **Voice stress demo** | "Wow, that's possible?" moment, unique | medium |
| **Team mode (anonymous)** | B2B selling point | medium |

---

## 6. Focus Discipline for the Hackathon

> ⚠️ Pawse has a **breadth risk**: Wearables + Voice + Calendar + ML + Azure is a
> year-long roadmap. Juries reward *one* magical thing, not ten half-finished ones.

**Separate pitch vs. demo:**
- **Pitch (slides):** the full Azure design as "This is how it scales to 1 million users" (vision).
- **Demo (live):** dashboard + real Fitbit/Apple Watch data + Panda emotion + protect button.

**Three real things > ten planned ones.**
Real HR data + a real score + a real Outlook event beats any architecture slide.

---

## 7. Prioritized Build Plan (demo impact)

1. ⌚ **Live device online** → set Fitbit credentials, run `fitbit_auth.py` *(immediately)*
2. 🛡️ **"Protect tomorrow" button** → writes a real Outlook event *(the closing-the-loop moment)*
3. 🐼 **Panda emotional states** → 3 visuals based on score *(the branding)*
4. 🔔 **Pop-up companion** → web notification on HR spike or 3 back-to-backs *(alive)*
5. 📊 **Pawse budget + weekly story** → tangible stats *(depth)*
6. 🎙️ **Voice stress sample** → a prepared meeting that can be played *(wow)*

---

## 8. The Elevator Pitch

> "Your calendar looks full — but your Fitbit tells a different story.
> Pawse reads both: meetings *and* real signals like heart rate and voice.
> It makes invisible stress visible — and acts before it's too late.
> The Panda speaks up when your pulse stays too high for too long, and protects focus time for you
> directly in Outlook. So you stay in flow — and know when you need to pause."

---

## 9. Why Real Device Data Is Irreplaceable

Every competitor (Whoop, Oura, Reclaim, Viva) solves *one* part of the problem.
Pawse connects **all three**:

```
Whoop knows your pulse — but not your calendar.
Reclaim knows your calendar — but not your body.
Pawse knows both — and acts for you.
```

A Fitbit HR spike that correlates live with a past meeting
makes this statement **provable** in the demo — no slide, no mock can replace that.

---

## 10. Pitch Framing & Use Cases

How to tell Pawse on stage — **Problem → Person → Moment → Impact**.
A jury doesn't buy features, it buys a **story it recognizes**.

### 10.1 The Pitch Structure (the through-line)

```
1. HOOK      "Your calendar looks full — your Fitbit tells a different story."
2. PROBLEM   Overload is invisible until it's too late. Tools show data — no one acts.
3. INSIGHT   The body knows first: pulse, HRV, voice. We read what the calendar hides.
4. SOLUTION  An explainable score from 3 sources → an acting companion (Panda).
5. PROOF     Live demo: real HR peak → Panda speaks up → one click → Outlook focus time.
6. VISION    Scales via Azure to every M365 user. Wellbeing that acts.
7. CALL      "Viva shows you the past. Pawse protects your future."
```

> **Rule:** Step 5 is the winner. Everything before leads up to it, everything after builds on it.
> If only 60 seconds remain: **only** steps 1 + 5 + 7.

### 10.2 The Three Pillars as a Pitch Image

```
        📅 CALENDAR            ⌚ BODY                🎙️ VOICE
        (what happened)      (how it reacts)       (how you sounded)
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   ▼
                        🐼 PAWSE SCORE (0–100)
                       explains · acts · protects
```

> One sentence for it: *"Three signals no one has ever brought together — into a single number
> that doesn't just warn, but acts."*

### 10.3 Use Cases (Personas → Moment → Impact)

Four scenarios that make the problem **tangible**. For the demo, Persona 1 is enough — the
others are pitch slides ("and here's how it also helps …").

#### 👩‍💼 Persona 1 — Alex, IC with a meeting marathon *(main demo)*
- **Situation:** 8 meetings, 4 of them back-to-back, no lunch.
- **Moment:** At 14:00 the pulse shoots up to 99 bpm (stakeholder review). The Pawse score jumps to 82.
  The Panda turns red and speaks up: *"Your pulse was elevated for 30 min — 5 min of bamboo time? 🎋"*
- **Impact:** In the evening Pawse asks: *"Shall I protect 90 min of focus time for you tomorrow?"* → one click →
  the Outlook event is set. Next week: measurably fewer red days.
- **Pitch line:** *"Alex didn't have to track anything, enter anything. Pawse saw it — and acted."*

#### 👨‍💻 Persona 2 — Sam, team lead with a duty of care *(B2B slide)*
- **Situation:** Sam doesn't see that half the team is chronically overloaded — until someone quits.
- **Moment:** Pawse shows an **anonymous, aggregated** team traffic-light signal: *"Team load this week: high.
  3 of 6 persistently in the red zone."* — **never** per person.
- **Impact:** Sam moves a recurring meeting, Pawse suggests a shared
  meeting-free morning (`findMeetingTimes`).
- **Pitch line:** *"Care without surveillance — burnout prevention at the team level, privacy-compliant."*

#### 🧑‍🔬 Persona 3 — Maya, returning from burnout *(emotional slide)*
- **Situation:** Maya was burned out and doesn't want to fall back into the same pattern.
- **Moment:** Pawse learns her **personal baseline** and warns early: *"Your recovery trend has been
  falling for 3 days — like last autumn. Let's steer against it."* (predictive)
- **Impact:** Pawse proactively protects breaks before the spiral begins.
- **Pitch line:** *"For Maya, Pawse isn't a gadget — it's an early-warning system she didn't have before."*

#### 🌍 Persona 4 — Jordan, hybrid & across time zones *(scaling slide)*
- **Situation:** Calls until 10 PM with the US, the calendar looks "normal," the body doesn't.
- **Moment:** Pawse detects after-hours load + falling HRV and flags **chronic** rather than acute overload.
- **Impact:** A suggestion for asynchronous alternatives + protected morning hours.
- **Pitch line:** *"Modern work is borderless. Pawse gives the boundary back."*

### 10.4 Market / Impact Framing (for the "Why now?" question)

| Level | Statement |
|---|---|
| **Individual** | Less burnout, more focus time, self-awareness without extra effort |
| **Team** | Early indicator of overload, better meeting hygiene, retention |
| **Organization** | Wellbeing becomes *measurable & acting* instead of just a survey once a year |
| **Microsoft** | Extends the Viva/M365 story with **real-time + biometrics + action** |

### 10.5 The Objection Answers (what the jury will definitely ask)

| Objection | Answer in one sentence |
|---|---|
| *"Doesn't Viva already do this?"* | "Viva shows aggregated & retrospective — Pawse measures individually, in real time, at the body, and **acts**." |
| *"Isn't this surveillance?"* | "Opt-in, personal baseline, individual values never leave the device — for the team only anonymous aggregates." |
| *"Is this a medical device?"* | "No — a supportive companion. No diagnosis, just gentle nudges." |
| *"Why is it feasible now?"* | "Wearables are standard, Graph opens up calendar+transcript, pretrained voice models exist." |
| *"Does it really work?"* | *(Live demo instead of an answer: real HR peak → action in Outlook.)* |

### 10.6 Title / Tagline Options

- **"Pawse — Wellbeing that acts."**
- **"Your calendar lies. Your body doesn't."**
- **"Protects your future instead of showing your past."**
- **"The guardian angel for your workday — with a Panda you want to keep happy."**

> Related research on market & prior art: [`research-prior-art.md`](research-prior-art.md).
> Technical feasibility of the use cases: [`ml-and-teams-integration.md`](ml-and-teams-integration.md).
