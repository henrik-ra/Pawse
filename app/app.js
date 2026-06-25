// Pawse dashboard — live wearable + calendar data, day navigation, rich charts.
// The scoring rules mirror scoring/pawse_score.py so the static fallback works
// even without the backend.

const LOW_STEPS_THRESHOLD = 3000;
const ELEVATED_HR_DELTA = 25;
const WEIGHTS = { meetings: 25, back_to_backs: 20, no_breaks: 15, low_movement: 20, elevated_hr: 20 };

const nf = new Intl.NumberFormat("en-US");
const ZONE_COLORS = { out: "#cdd6cf", fat_burn: "#f4b740", cardio: "#ff7a45", peak: "#e8553e" };
const ZONE_LABELS = { out: "Light", fat_burn: "Fat burn", cardio: "Cardio", peak: "Peak" };

// ---- App state -------------------------------------------------------------
const state = { date: todayISO(), today: todayISO() };
const charts = {};

function todayISO() { return new Date().toLocaleDateString("en-CA"); } // YYYY-MM-DD (local)
function shiftDate(iso, days) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA");
}

// ---- Local scoring fallback (mirrors the Python engine) --------------------
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
  return { pawse_score: score, label: labelFor(score), reasons, recommendations: recommend(reasons), data, mode: (data.wearable || {}).mode || "demo" };
}
function labelFor(score) { return score >= 70 ? "High strain" : score >= 40 ? "Medium strain" : "Low strain"; }
function recommend(reasons) {
  const joined = reasons.join(" ").toLowerCase();
  const recs = [];
  if (joined.includes("meeting")) { recs.push("Block 30 minutes of recovery time tomorrow."); recs.push("Turn one meeting into an async update."); }
  if (joined.includes("back-to-back")) recs.push("Add 10-minute buffers between meetings.");
  if (joined.includes("movement")) recs.push("Take one walking 1:1.");
  if (joined.includes("lunch")) recs.push("Protect a real lunch break.");
  return recs.length ? recs : ["Your day looks balanced — keep it up!"];
}

// ---- Rendering -------------------------------------------------------------
function render(result) {
  const data = result.data || {};
  const w = data.wearable || {};
  const score = result.pawse_score ?? result.score ?? 0;
  const label = result.label || labelFor(score);

  showMode(result.mode || w.mode || "demo", w.source || data.source);
  showSource(result.mode || w.mode || "demo", w.source || data.source);
  renderHero(score, label, data, w);
  renderTiles(w, data);
  renderHrChart(w);
  renderZonesChart(w);
  renderStepsChart(w);
  renderMeetingsChart(data);
  renderMeetingList(data);
  fillList("reasons", result.reasons || []);
  fillList("recommendations", result.recommendations || []);
  renderVoice(data.voice);
  showUpdated();
}

function moodClass(score) { return score >= 70 ? "mood-bad" : score >= 40 ? "mood-med" : "mood-good"; }
function ringColor(score) { return score >= 70 ? "var(--bad)" : score >= 40 ? "var(--warn)" : "var(--good)"; }

const MOUTHS = {
  good: "M80 148 Q100 169 120 148",
  med: "M84 154 Q100 159 116 154",
  bad: "M82 161 Q100 144 118 161",
};

function renderHero(score, label, data, w) {
  document.getElementById("score").textContent = score;
  const labelEl = document.getElementById("label");
  labelEl.textContent = label;
  labelEl.className = "label hero-label " + label.split(" ")[0].toLowerCase();

  document.getElementById("summary").textContent = summaryFor(score, w);
  document.getElementById("chipUser").textContent = `${data.user || "You"} · ${prettyDate(data.date || state.date)}`;
  document.getElementById("chipSensors").textContent = `${countSensors(w)} live sensors`;

  // Gauge ring + panda mood.
  const gauge = document.getElementById("gauge");
  gauge.style.setProperty("--ring", ringColor(score));
  requestAnimationFrame(() => gauge.style.setProperty("--pct", score));

  const panda = document.getElementById("panda");
  panda.classList.remove("mood-good", "mood-med", "mood-bad");
  const cls = moodClass(score);
  panda.classList.add(cls);
  document.getElementById("pandaMouth").setAttribute("d", MOUTHS[cls.replace("mood-", "")]);

  const breatheBtn = document.getElementById("breatheBtn");
  if (breatheBtn) breatheBtn.classList.toggle("urgent", score >= 70);
}

// ---- Rebalance your day (actionable reschedule suggestions) ----------------
const REBALANCE_ICON = {
  protect_focus: "🛡️", protect_lunch: "🥗", reschedule: "📅",
  move_after_hours: "🌙", add_buffer: "⏳",
};
const REBALANCE_VERB = {
  protect_focus: "Protect focus", protect_lunch: "Protect lunch",
  reschedule: "Move meeting", move_after_hours: "Move into day", add_buffer: "Add buffer",
};
const REBALANCE_DONE = {
  protect_focus: "focus time protected", protect_lunch: "lunch break protected",
  reschedule: "meeting moved", move_after_hours: "moved into your day \u2014 evening protected",
  add_buffer: "buffer added",
};

async function renderRebalance(date) {
  const card = document.getElementById("rebalanceCard");
  const list = document.getElementById("rebalanceList");
  if (!card || !list) return;
  try {
    const res = await fetch(`/api/recommendations?date=${encodeURIComponent(date)}`, { cache: "no-store" });
    if (!res.ok) throw new Error("api");
    const recs = (await res.json()).recommendations || [];
    if (!recs.length) { card.hidden = true; return; }

    list.textContent = "";
    for (const r of recs) {
      const li = document.createElement("li");
      li.className = "rebalance-item";

      const ico = document.createElement("span");
      ico.className = "rb-ico";
      ico.textContent = REBALANCE_ICON[r.type] || "•";

      const text = document.createElement("span");
      text.className = "rb-text";
      const title = document.createElement("span");
      title.className = "rb-title";
      title.textContent = r.title || "Adjust";
      const when = document.createElement("span");
      when.className = "rb-when";
      when.textContent = r.from ? `${r.from} \u2192 ${r.to}` : `${r.to}\u2013${r.end}`;
      title.appendChild(when);
      const reason = document.createElement("span");
      reason.className = "rb-reason";
      reason.textContent = r.reason || "";
      text.append(title, reason);

      const action = document.createElement("button");
      action.type = "button";
      action.className = "rb-action";
      action.textContent = `${REBALANCE_VERB[r.type] || "Adjust"} \u2192`;
      action.addEventListener("click", () => applyAction(r, date, action, li));

      li.append(ico, text, action);
      list.appendChild(li);
    }
    document.getElementById("rebalanceSub").textContent =
      `${recs.length} suggestion${recs.length > 1 ? "s" : ""}`;
    card.hidden = false;
  } catch (_) {
    card.hidden = true;
  }
}

// Apply a reschedule action: tell the local server to move it, then re-fetch so
// the score, tiles and meetings all reflect the change. This is the visible
// "detect \u2192 propose \u2192 act" loop \u2014 one click really rebalances the day.
async function applyAction(r, date, button, li) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Working\u2026";
  li.classList.add("applying");
  try {
    const resp = await fetch("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date, type: r.type, title: r.title,
        from: r.from, to: r.to, end: r.end,
      }),
    });
    if (!resp.ok) throw new Error("apply");
    button.textContent = "\u2713 Done";
    li.classList.add("done");
    showToast(`\u2713 ${r.title} \u2014 ${REBALANCE_DONE[r.type] || "updated"}`);
    setTimeout(() => fetchDay(date), 750);
  } catch (_) {
    button.disabled = false;
    button.textContent = original;
    li.classList.remove("applying");
    showToast("Couldn't apply \u2014 is the local server running?");
  }
}

let _toastTimer = null;
function showToast(msg) {
  let el = document.getElementById("pawseToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "pawseToast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

// ---- Breathing exercise -----------------------------------------------------
let _breathTimer = null;

function openBreath() {
  const ov = document.getElementById("breathOverlay");
  if (!ov) return;
  ov.hidden = false;
  runBreath(0, 4);
}

function closeBreath() {
  clearTimeout(_breathTimer);
  const ov = document.getElementById("breathOverlay");
  if (ov) ov.hidden = true;
}

function runBreath(cycle, total) {
  const circle = document.getElementById("breathCircle");
  const phaseEl = document.getElementById("breathPhase");
  const countEl = document.getElementById("breathCount");
  if (!circle) return;
  if (cycle >= total) {
    phaseEl.textContent = "Well done";
    countEl.textContent = "Carry the calm with you 🐼";
    circle.style.setProperty("--bdur", "1.6s");
    requestAnimationFrame(() => { circle.style.transform = "scale(0.72)"; });
    return;
  }
  countEl.textContent = `Breath ${cycle + 1} of ${total}`;
  const phases = [
    { name: "Breathe in…", dur: 4000, scale: 1 },
    { name: "Hold", dur: 4000, scale: 1 },
    { name: "Breathe out…", dur: 6000, scale: 0.5 },
  ];
  let i = 0;
  (function step() {
    if (i >= phases.length) { runBreath(cycle + 1, total); return; }
    const p = phases[i++];
    phaseEl.textContent = p.name;
    circle.style.setProperty("--bdur", (p.dur / 1000) + "s");
    requestAnimationFrame(() => { circle.style.transform = `scale(${p.scale})`; });
    _breathTimer = setTimeout(step, p.dur);
  })();
}

document.getElementById("breatheBtn")?.addEventListener("click", openBreath);
document.getElementById("breathDone")?.addEventListener("click", closeBreath);
document.getElementById("breathOverlay")?.addEventListener("click", (e) => {
  if (e.target.id === "breathOverlay") closeBreath();
});

function summaryFor(score, w) {
  const steps = w.steps || 0;
  if (score >= 70) return `Intense day — heavy meeting load and little recovery. Only ${nf.format(steps)} steps so far. Time to pawse. 🐼`;
  if (score >= 40) return `Moderately busy day. A short walk or a protected break would lift your recovery. ${nf.format(steps)} steps logged.`;
  return `Nicely balanced day — calm heart rate and ${nf.format(steps)} steps. Keep riding the flow. ✨`;
}

function countSensors(w) {
  let n = 0;
  ["steps", "resting_hr", "hr_avg", "calories", "distance_km", "spo2_avg", "hrv_avg", "azm_total"].forEach(k => {
    if (w[k] !== undefined && w[k] !== null) n++;
  });
  return n;
}

// ---- KPI tiles -------------------------------------------------------------
function renderTiles(w, data) {
  const meetings = data.meetings || [];
  const b2b = meetings.filter(m => m.back_to_back).length;
  const stepGoal = 8000;
  const tiles = [
    { icon: "👣", label: "Steps", accent: "#3fa34d", soft: "#eaf6ec",
      value: nf.format(w.steps || 0), sub: `Goal ${nf.format(stepGoal)} · ${Math.round((w.steps || 0) / stepGoal * 100)}%`,
      spark: w.steps_by_hour },
    { icon: "🔥", label: "Active energy", accent: "#ff7a45", soft: "#ffeee6",
      value: nf.format(w.calories ?? 0), unit: "kcal", sub: w.calories_estimated ? "estimated" : "measured" },
    { icon: "📍", label: "Distance", accent: "#2f7d3a", soft: "#e9f5ec",
      value: (w.distance_km ?? 0).toFixed(2), unit: "km", sub: w.distance_estimated ? "estimated from steps" : "measured" },
    { icon: "❤️", label: "Resting HR", accent: "#e8553e", soft: "#fdecea",
      value: w.resting_hr ?? "—", unit: "bpm", sub: "daily resting" },
    { icon: "💓", label: "Avg heart rate", accent: "#ef5777", soft: "#fdeaf0",
      value: w.hr_avg ?? "—", unit: "bpm", sub: `min ${w.hr_min ?? "—"} · max ${w.hr_max ?? "—"}`,
      spark: (w.hr_samples || []).map(s => s.bpm) },
    { icon: "📈", label: "Peak HR", accent: "#d63031", soft: "#fbe9e9",
      value: w.hr_max ?? "—", unit: "bpm", sub: "today's high" },
    { icon: "🌿", label: "HRV", accent: "#3fa34d", soft: "#eaf6ec",
      value: w.hrv_avg ?? "—", unit: "ms", sub: "recovery (RMSSD)" },
    { icon: "🫁", label: "SpO₂", accent: "#4a90d9", soft: "#e8f1fb",
      value: w.spo2_avg ?? "—", unit: "%", sub: "blood oxygen" },
    { icon: "⚡", label: "Active zone min", accent: "#f4b740", soft: "#fdf3df",
      value: w.azm_total ?? w.active_minutes ?? 0, unit: "min", sub: "in HR zones" },
    { icon: "📅", label: "Meetings", accent: "#6c5ce7", soft: "#eeebfc",
      value: meetings.length, sub: `${b2b} back-to-back` },
  ];

  const root = document.getElementById("tiles");
  root.innerHTML = "";
  tiles.forEach((t, i) => {
    const el = document.createElement("div");
    el.className = "tile";
    el.style.setProperty("--tile-accent", t.accent);
    el.style.setProperty("--tile-soft", t.soft);
    el.style.animationDelay = `${i * 35}ms`;
    el.innerHTML = `
      <div class="tile-top">
        <span class="tile-icon">${t.icon}</span>
        <span class="tile-label">${t.label}</span>
      </div>
      <div class="tile-value">${t.value}${t.unit ? ` <span class="tile-unit">${t.unit}</span>` : ""}</div>
      <div class="tile-sub">${t.sub || ""}</div>
      ${t.spark && t.spark.length ? sparkSvg(t.spark, t.accent) : ""}`;
    root.appendChild(el);
  });
}

function sparkSvg(values, color) {
  const nums = values.map(Number).filter(v => !Number.isNaN(v));
  if (nums.length < 2) return "";
  const W = 100, H = 30, min = Math.min(...nums), max = Math.max(...nums), span = max - min || 1;
  const pts = nums.map((v, i) => {
    const x = (i / (nums.length - 1)) * W;
    const y = H - ((v - min) / span) * (H - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const area = `0,${H} ${pts.join(" ")} ${W},${H}`;
  const id = "g" + Math.random().toString(36).slice(2, 7);
  return `<svg class="tile-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points="${area}" fill="url(#${id})"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// ---- Charts ----------------------------------------------------------------
function destroy(name) { if (charts[name]) { charts[name].destroy(); charts[name] = null; } }

function renderHrChart(w) {
  const samples = w.hr_samples || [];
  document.getElementById("hrSub").textContent =
    samples.length ? `avg ${w.hr_avg} · min ${w.hr_min} · max ${w.hr_max} bpm` : "";
  destroy("hr");
  const ctx = document.getElementById("hrChart");
  const grad = ctx.getContext("2d").createLinearGradient(0, 0, 0, 240);
  grad.addColorStop(0, "rgba(232,85,62,0.30)");
  grad.addColorStop(1, "rgba(232,85,62,0)");
  charts.hr = new Chart(ctx, {
    type: "line",
    data: {
      labels: samples.map(s => s.time),
      datasets: [{
        data: samples.map(s => s.bpm),
        borderColor: "#e8553e", borderWidth: 2,
        backgroundColor: grad, fill: true,
        tension: 0.35, pointRadius: 0, pointHoverRadius: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { intersect: false, mode: "index" } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, color: "#8a918c" }, grid: { display: false } },
        y: { ticks: { color: "#8a918c" }, grid: { color: "#f0ece2" } },
      },
    },
  });
}

function renderZonesChart(w) {
  const z = w.hr_zones || { out: 100, fat_burn: 0, cardio: 0, peak: 0 };
  const keys = ["out", "fat_burn", "cardio", "peak"];
  destroy("zones");
  charts.zones = new Chart(document.getElementById("zonesChart"), {
    type: "doughnut",
    data: {
      labels: keys.map(k => ZONE_LABELS[k]),
      datasets: [{ data: keys.map(k => z[k] || 0), backgroundColor: keys.map(k => ZONE_COLORS[k]), borderWidth: 2, borderColor: "#fff" }],
    },
    options: {
      maintainAspectRatio: false, cutout: "62%",
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12, color: "#5c6360" } },
        tooltip: { callbacks: { label: c => `${c.label}: ${c.parsed}%` } } },
    },
  });
}

function renderStepsChart(w) {
  const byHour = w.steps_by_hour || new Array(24).fill(0);
  document.getElementById("stepsSub").textContent =
    `${nf.format(w.steps || 0)} steps · ${w.azm_total ?? 0} active min`;
  destroy("steps");
  charts.steps = new Chart(document.getElementById("stepsChart"), {
    type: "bar",
    data: {
      labels: byHour.map((_, h) => `${h}`),
      datasets: [{ data: byHour, backgroundColor: "#3fa34d", borderRadius: 5, hoverBackgroundColor: "#2f7d3a" }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => `${c[0].label}:00`, label: c => `${nf.format(c.parsed.y)} steps` } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8a918c", maxTicksLimit: 12 } },
        y: { grid: { color: "#f0ece2" }, ticks: { color: "#8a918c" }, beginAtZero: true },
      },
    },
  });
}

function parseHM(s) { const [h, m] = (s || "0:0").split(":").map(Number); return h * 60 + m; }

function renderMeetingsChart(data) {
  const meetings = data.meetings || [];
  destroy("meetings");
  charts.meetings = new Chart(document.getElementById("meetingsChart"), {
    type: "bar",
    data: {
      labels: meetings.map(m => m.start),
      datasets: [{
        data: meetings.map(m => Math.max(15, parseHM(m.end) - parseHM(m.start))),
        backgroundColor: meetings.map(m => m.after_hours ? "#1b1c1e" : m.back_to_back ? "#e8553e" : "#6c5ce7"),
        borderRadius: 5,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: c => meetings[c[0].dataIndex].title,
          label: c => `${meetings[c.dataIndex].start}–${meetings[c.dataIndex].end} · ${c.parsed.y} min${meetings[c.dataIndex].after_hours ? " · after hours" : ""}`,
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8a918c" } },
        y: { grid: { color: "#f0ece2" }, ticks: { color: "#8a918c" }, title: { display: true, text: "minutes", color: "#8a918c" } },
      },
    },
  });
}

// ---- Full meeting list -----------------------------------------------------
function renderMeetingList(data) {
  const meetings = (data.meetings || []).slice().sort((a, b) => parseHM(a.start) - parseHM(b.start));
  const root = document.getElementById("meetingList");
  const sub = document.getElementById("scheduleSub");
  if (!root) return;
  root.innerHTML = "";
  if (!meetings.length) {
    if (sub) sub.textContent = "";
    const li = document.createElement("li");
    li.className = "meeting-empty";
    li.textContent = "No meetings \u2014 enjoy the focus time \ud83d\udc3c";
    root.appendChild(li);
    return;
  }
  const b2b = meetings.filter(m => m.back_to_back).length;
  const after = meetings.filter(m => m.after_hours).length;
  if (sub) sub.textContent =
    `${meetings.length} meeting${meetings.length > 1 ? "s" : ""}` +
    (b2b ? ` \u00b7 ${b2b} back-to-back` : "") +
    (after ? ` \u00b7 ${after} after-hours` : "");
  meetings.forEach((m, i) => {
    const dur = Math.max(0, parseHM(m.end) - parseHM(m.start));
    const li = document.createElement("li");
    li.className = "meeting-row" + (m.after_hours ? " is-after" : m.back_to_back ? " is-b2b" : "");
    li.style.animationDelay = `${i * 40}ms`;
    const tags = [];
    if (m.back_to_back) tags.push(`<span class="m-tag tag-b2b">back-to-back</span>`);
    if (m.after_hours) tags.push(`<span class="m-tag tag-after">after-hours</span>`);
    li.innerHTML = `
      <span class="m-time"><strong>${escapeHtml(m.start)}</strong><span>${escapeHtml(m.end)}</span></span>
      <span class="m-main">
        <span class="m-title">${escapeHtml(m.title)}</span>
        <span class="m-meta">${fmtDur(dur)}${tags.length ? " " + tags.join(" ") : ""}</span>
      </span>`;
    root.appendChild(li);
  });
}

function fmtDur(min) {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- Pawse Score trend (cloud history + local browsing history) ------------
const HISTORY_KEY = "pawse.history.v1";

function loadLocalHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || {}; }
  catch (_) { return {}; }
}

function recordHistory(date, score, label) {
  if (!date || typeof score !== "number") return;
  const hist = loadLocalHistory();
  hist[date] = { date, score, label };
  const kept = Object.values(hist).sort((a, b) => a.date.localeCompare(b.date)).slice(-60);
  const out = {};
  kept.forEach(e => { out[e.date] = e; });
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(out)); } catch (_) {}
}

function bandColor(s) { return s >= 70 ? "#e8553e" : s >= 40 ? "#f4b740" : "#2ecc71"; }
function shortDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

async function renderTrend(days = 14) {
  // Cloud history is authoritative; local browsing history fills the gaps.
  const merged = loadLocalHistory();
  try {
    const res = await fetch(`/api/history?days=${days}`, { cache: "no-store" });
    if (res.ok) {
      const body = await res.json();
      (body.history || []).forEach(e => {
        if (e.date && typeof e.pawseScore === "number")
          merged[e.date] = { date: e.date, score: e.pawseScore, label: e.label };
      });
    }
  } catch (_) { /* no cloud backend reachable — local history only */ }

  const points = Object.values(merged)
    .filter(e => typeof e.score === "number")
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-days);

  const canvas = document.getElementById("trendChart");
  const empty = document.getElementById("trendEmpty");
  const sub = document.getElementById("trendSub");
  if (!canvas) return;

  if (points.length < 2) {
    destroy("trend");
    canvas.style.display = "none";
    if (empty) empty.hidden = false;
    if (sub) sub.textContent = "";
    return;
  }
  canvas.style.display = "";
  if (empty) empty.hidden = true;

  const scores = points.map(p => p.score);
  const avg = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
  if (sub) sub.textContent = `${points.length} days \u00b7 avg ${avg}`;

  destroy("trend");
  charts.trend = new Chart(canvas, {
    type: "line",
    data: {
      labels: points.map(p => shortDate(p.date)),
      datasets: [{
        data: scores,
        borderColor: "#6c5ce7",
        backgroundColor: "rgba(108,92,231,0.12)",
        fill: true,
        tension: 0.35,
        pointBackgroundColor: scores.map(bandColor),
        pointBorderColor: scores.map(bandColor),
        pointRadius: 4,
        pointHoverRadius: 6,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: c => points[c[0].dataIndex].date,
          label: c => `Score ${c.parsed.y}` + (points[c.dataIndex].label ? ` \u00b7 ${points[c.dataIndex].label}` : ""),
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8a918c", maxTicksLimit: 10 } },
        y: { grid: { color: "#f0ece2" }, ticks: { color: "#8a918c" }, suggestedMin: 0, suggestedMax: 100 },
      },
    },
  });
}

function renderVoice(voice) {
  const v = voice || {};
  const idx = typeof v.avg_stress_index === "number" ? v.avg_stress_index : null;
  document.getElementById("voiceFill").style.width = idx === null ? "0%" : `${Math.round(idx * 100)}%`;
  document.getElementById("voiceVal").textContent = idx === null ? "—" : `${Math.round(idx * 100)}%`;
  document.getElementById("voiceNote").textContent = v.notes ||
    (idx === null ? "No voice analysis for this day." : "");
}

function fillList(id, items) {
  const ul = document.getElementById(id);
  ul.innerHTML = "";
  (items.length ? items : ["—"]).forEach(t => { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); });
}

// ---- Mode badge & date header ---------------------------------------------
// Map a backend `source` string to a friendly device name for the badge.
function deviceLabel(source) {
  const s = String(source || "").toLowerCase();
  if (!s) return "";
  if (s.startsWith("xiaomi") || s.includes("redmi") || s.includes("gadgetbridge")) return "Xiaomi Watch";
  if (s.includes("fitbit")) return "Fitbit";
  if (s.includes("apple")) return "Apple Watch";
  if (s.includes("google")) return "Google Health";
  // Fallback: prettify the raw source (e.g. "garmin-connect" -> "Garmin Connect").
  return s.replace(/[-_]+/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function showMode(mode, source) {
  const el = document.getElementById("mode");
  const device = deviceLabel(source);
  if (mode === "live") {
    el.textContent = device ? `● LIVE · ${device}` : "● LIVE";
    el.className = "mode live";
  } else {
    el.textContent = device ? `○ Demo · ${device}` : "○ Demo data";
    el.className = "mode demo";
  }
}

// Keep the footer disclaimer in sync with the active wearable + live/demo state.
function showSource(mode, source) {
  const el = document.getElementById("sensor-source");
  if (!el) return;
  const device = deviceLabel(source) || "your wearable";
  el.textContent = mode === "live"
    ? `Sensor data is read live from ${device}.`
    : `Showing demo data — no live ${device} connection.`;
}

// Stamp the header with the time of the latest successful data load so you can
// see at a glance how fresh the near-real-time view is.
function showUpdated() {
  const el = document.getElementById("updated");
  if (!el) return;
  const now = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  el.textContent = `updated ${now}`;
  el.hidden = false;
}

function prettyDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}
function relDate(iso) {
  if (iso === state.today) return "Today";
  if (iso === shiftDate(state.today, -1)) return "Yesterday";
  if (iso === shiftDate(state.today, 1)) return "Tomorrow";
  return "";
}
function updateDayHeader() {
  document.getElementById("navDate").textContent = prettyDate(state.date);
  document.getElementById("navRel").textContent = relDate(state.date);
  document.getElementById("nextDay").disabled = state.date >= state.today;
}

// ---- Data loading ----------------------------------------------------------
async function fetchDay(date, { silent = false } = {}) {
  state.date = date;
  updateDayHeader();
  let overlayTimer = null;
  if (!silent) overlayTimer = setTimeout(() => { document.getElementById("loading").hidden = false; }, 220);

  try {
    const res = await fetch(`/api/live-day?date=${encodeURIComponent(date)}`, { cache: "no-store" });
    if (res.ok) {
      const result = await res.json();
      if (!result.error) {
        render(result);
        renderRebalance(date);
        recordHistory(date, result.pawse_score ?? result.score, result.label);
        renderTrend();
        return;
      }
    }
    throw new Error("api");
  } catch (_) {
    // Static fallback (no backend): only the bundled sample day is available.
    try {
      const res = await fetch("../data/alex_workday.json", { cache: "no-store" });
      const sample = await res.json();
      render(scoreDay(sample));
    } catch (e) {
      document.getElementById("summary").textContent =
        "Could not load data — run `py server.py` and open http://localhost:8000.";
      console.error(e);
    }
  } finally {
    if (overlayTimer) clearTimeout(overlayTimer);
    document.getElementById("loading").hidden = true;
  }
}

// ---- Wiring ----------------------------------------------------------------
const REFRESH_MS = 60000;

function main() {
  document.getElementById("prevDay").addEventListener("click", () => fetchDay(shiftDate(state.date, -1)));
  document.getElementById("nextDay").addEventListener("click", () => {
    const next = shiftDate(state.date, 1);
    if (next <= state.today) fetchDay(next);
  });
  document.getElementById("todayBtn").addEventListener("click", () => fetchDay(state.today));

  fetchDay(state.date);

  // Auto-refresh, but only while viewing today (live data keeps changing).
  if (REFRESH_MS > 0) setInterval(() => { if (state.date === state.today) fetchDay(state.today, { silent: true }); }, REFRESH_MS);
}

main();
