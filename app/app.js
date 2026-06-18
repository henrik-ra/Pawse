// Pawse dashboard — loads the sample day, computes the Pawse Score, renders charts.
// The scoring rules mirror scoring/pawse_score.py so the UI is self-contained.

const LOW_STEPS_THRESHOLD = 3000;
const ELEVATED_HR_DELTA = 25;
const WEIGHTS = { meetings: 25, back_to_backs: 20, no_breaks: 15, low_movement: 20, elevated_hr: 20 };

function scoreDay(data) {
  let total = 0;
  const reasons = [];

  const meetings = data.meetings || [];
  if (meetings.length >= 6) { total += WEIGHTS.meetings; reasons.push(`Heavy meeting load (${meetings.length} meetings)`); }
  else if (meetings.length >= 4) { total += WEIGHTS.meetings / 2; reasons.push(`Busy meeting day (${meetings.length} meetings)`); }

  const b2b = meetings.filter(m => m.back_to_back).length;
  if (b2b >= 3) { total += WEIGHTS.back_to_backs; reasons.push(`${b2b} back-to-back meetings — little recovery time`); }
  else if (b2b >= 1) { total += WEIGHTS.back_to_backs / 2; reasons.push(`${b2b} back-to-back meeting(s)`); }

  if (data.breaks && data.breaks.lunch_break === false) { total += WEIGHTS.no_breaks; reasons.push("No lunch break — poor recovery"); }

  const w = data.wearable || {};
  if ((w.steps || 0) < LOW_STEPS_THRESHOLD) { total += WEIGHTS.low_movement; reasons.push(`Low movement (only ${w.steps} steps)`); }

  const resting = w.resting_hr || 60;
  const spikes = (w.hr_samples || []).filter(s => (s.bpm - resting) >= ELEVATED_HR_DELTA);
  if (spikes.length) { total += WEIGHTS.elevated_hr; reasons.push(`Heart-rate spikes during ${spikes.length} meeting(s) — possible strain`); }

  const score = Math.max(0, Math.min(100, Math.round(total)));
  return { score, label: labelFor(score), reasons, recommendations: recommend(reasons), data };
}

function labelFor(score) {
  if (score >= 70) return "High strain";
  if (score >= 40) return "Medium strain";
  return "Low strain";
}

function recommend(reasons) {
  const joined = reasons.join(" ").toLowerCase();
  const recs = [];
  if (joined.includes("meeting")) { recs.push("Block 30 minutes of recovery time tomorrow."); recs.push("Turn one meeting into an async update."); }
  if (joined.includes("back-to-back")) recs.push("Add 10-minute buffers between meetings.");
  if (joined.includes("movement")) recs.push("Take one walking 1:1.");
  if (joined.includes("lunch")) recs.push("Protect a real lunch break.");
  return recs.length ? recs : ["Your day looks balanced — keep it up!"];
}

function render(result) {
  document.getElementById("score").textContent = result.score;
  const labelEl = document.getElementById("label");
  labelEl.textContent = result.label;
  labelEl.className = "label " + result.label.split(" ")[0].toLowerCase();
  document.getElementById("for").textContent = `${result.data.user} • ${result.data.date}`;

  fillList("reasons", result.reasons);
  fillList("recommendations", result.recommendations);

  renderMeetingsChart(result.data);
  renderHrChart(result.data);
}

function fillList(id, items) {
  const ul = document.getElementById(id);
  ul.innerHTML = "";
  items.forEach(t => { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); });
}

function renderMeetingsChart(data) {
  const meetings = data.meetings || [];
  new Chart(document.getElementById("meetingsChart"), {
    type: "bar",
    data: {
      labels: meetings.map(m => m.start),
      datasets: [{
        label: "Meeting (1 = busy)",
        data: meetings.map(() => 1),
        backgroundColor: meetings.map(m => m.back_to_back ? "#e74c3c" : "#6c5ce7"),
      }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { display: false } } },
  });
}

function renderHrChart(data) {
  const samples = (data.wearable || {}).hr_samples || [];
  new Chart(document.getElementById("hrChart"), {
    type: "line",
    data: {
      labels: samples.map(s => s.time),
      datasets: [{
        label: "Heart rate (bpm)",
        data: samples.map(s => s.bpm),
        borderColor: "#e74c3c",
        tension: 0.3,
        fill: false,
      }],
    },
    options: { plugins: { legend: { display: false } } },
  });
}

async function main() {
  try {
    const res = await fetch("../data/alex_workday.json");
    const data = await res.json();
    render(scoreDay(data));
  } catch (e) {
    document.getElementById("label").textContent =
      "Could not load data — serve the folder over http (e.g. `python -m http.server`).";
    console.error(e);
  }
}

main();
