// Pawse — Teams-style meeting clone.
// Flow: pre-join (pick meeting + camera) -> in-call (mute/camera/leave, biomarkers
// captured every ~1.5s) -> on leave ask to save -> POST to /api/teams-sessions -> dashboard.
//
// NOTE: the biomarker capture here is a lightweight on-device *simulation* so the demo
// runs anywhere. The accumulation/averaging + save pipeline is real — swap `sampleBiomarkers`
// for the actual Pawse vision/voice engine to use live measurements.

const WEIGHTS = { fatigue: 0.35, emotion: 0.25, tension: 0.20, voice: 0.20 };
const PARTICIPANTS = [
  { name: "Henrik R.", color: "#5b5fc7" },
  { name: "Mara K.", color: "#c4314b" },
  { name: "Devon L.", color: "#3fa34d" },
];

const els = {};
["prejoin", "incall", "preview", "noCam", "preMic", "preCam", "meetingSelect", "joinBtn",
 "stage", "callTitle", "callTimer", "micBtn", "camBtn", "leaveBtn",
 "leaveDialog", "dlgTitle", "dlgStats", "discardBtn", "saveBtn"].forEach(id => els[id] = document.getElementById(id));

const state = {
  stream: null, micOn: true, camOn: true,
  meetings: [], selected: null,
  joinedAt: null, timer: null, sampler: null,
  bm: { fatigue: 38, emotion: 34, tension: 36, voice: 32 },
  acc: { fatigue: 0, emotion: 0, tension: 0, voice: 0 }, n: 0,
};

function todayISO() { return new Date().toLocaleDateString("en-CA"); }
function nowHM() { return new Date().toTimeString().slice(0, 5); }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function parseHM(s) { const [h, m] = String(s || "").split(":").map(Number); return (h || 0) * 60 + (m || 0); }
function fmtTimer(sec) { const m = Math.floor(sec / 60), s = sec % 60; return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; }
function distressColor(s) { return s >= 70 ? "#c4314b" : s >= 40 ? "#e8a13a" : "#3fa34d"; }
function weightedDistress(b) {
  let tot = 0, w = 0;
  for (const k in WEIGHTS) { tot += (b[k] || 0) * WEIGHTS[k]; w += WEIGHTS[k]; }
  return clamp(tot / (w || 1), 0, 100);
}

// ---------- Camera ----------
async function initCamera() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    els.preview.srcObject = state.stream;
    els.noCam.hidden = true;
  } catch (e) {
    els.noCam.hidden = false;
    console.warn("No camera/mic:", e);
  }
}
function setMic(on) {
  state.micOn = on;
  (state.stream?.getAudioTracks() || []).forEach(t => t.enabled = on);
  els.preMic.classList.toggle("off", !on);
  if (els.micBtn) {
    els.micBtn.classList.toggle("active", on);
    els.micBtn.classList.toggle("off", !on);
    els.micBtn.querySelector("small").textContent = on ? "Mute" : "Unmute";
  }
}
function setCam(on) {
  state.camOn = on;
  (state.stream?.getVideoTracks() || []).forEach(t => t.enabled = on);
  els.preCam.classList.toggle("off", !on);
  els.preview.style.visibility = on ? "visible" : "hidden";
  els.noCam.hidden = on;
  if (els.camBtn) {
    els.camBtn.classList.toggle("active", on);
    els.camBtn.classList.toggle("off", !on);
    const selfV = document.getElementById("selfVideo");
    if (selfV) selfV.style.visibility = on ? "visible" : "hidden";
    const selfA = document.getElementById("selfAvatar");
    if (selfA) selfA.style.display = on ? "none" : "grid";
  }
}

// ---------- Meetings list ----------
async function loadMeetings() {
  const opts = [{ title: "Ad-hoc meeting", start: nowHM(), end: "" }];
  try {
    const res = await fetch(`/api/live-day?date=${todayISO()}`, { cache: "no-store" });
    const data = await res.json();
    (data?.data?.meetings || []).forEach(m => opts.push({ title: m.title, start: m.start, end: m.end }));
  } catch (_) { /* offline: only ad-hoc */ }
  state.meetings = opts;
  els.meetingSelect.innerHTML = opts.map((m, i) =>
    `<option value="${i}">${m.start}${m.end ? "–" + m.end : ""} · ${m.title}</option>`).join("");
  // default to the first scheduled meeting if present
  els.meetingSelect.value = opts.length > 1 ? "1" : "0";
}

// ---------- In-call ----------
function buildStage() {
  els.stage.innerHTML = "";
  // self tile
  const self = document.createElement("div");
  self.className = "tile-v";
  self.innerHTML = `
    <video id="selfVideo" autoplay muted playsinline></video>
    <div class="avatar" id="selfAvatar" style="background:#6264a7;display:none">You</div>
    <span class="pawse-pill"><span class="pawse-dot" id="pawseDot"></span><span id="pawseLive">–</span></span>
    <span class="tile-name">You</span>`;
  els.stage.appendChild(self);
  const sv = self.querySelector("#selfVideo");
  if (state.stream) sv.srcObject = state.stream;
  // participant tiles
  PARTICIPANTS.forEach(p => {
    const t = document.createElement("div");
    t.className = "tile-v";
    const initials = p.name.split(" ").map(w => w[0]).join("").slice(0, 2);
    t.innerHTML = `<div class="avatar" style="background:${p.color}">${initials}</div>
      <span class="tile-name">${p.name}</span>`;
    els.stage.appendChild(t);
  });
}

function sampleBiomarkers() {
  // Slow random walk with a slight upward (fatigue-building) bias; muted = a touch calmer.
  const bias = state.micOn ? 0.40 : 0.46;
  for (const k of Object.keys(state.bm)) {
    const drift = (Math.random() - bias) * 6;
    state.bm[k] = clamp(state.bm[k] + drift, 12, 95);
    state.acc[k] += state.bm[k];
  }
  state.n++;
  const live = Math.round(weightedDistress(state.bm));
  const dot = document.getElementById("pawseDot");
  const lbl = document.getElementById("pawseLive");
  if (dot) dot.style.background = distressColor(live);
  if (lbl) lbl.textContent = "distress " + live;
}

function join() {
  state.selected = state.meetings[Number(els.meetingSelect.value) || 0];
  els.prejoin.hidden = true;
  els.incall.hidden = false;
  els.callTitle.textContent = state.selected.title;
  buildStage();
  setMic(state.micOn); setCam(state.camOn);

  state.joinedAt = Date.now();
  els.callTimer.textContent = "00:00";
  state.timer = setInterval(() => {
    els.callTimer.textContent = fmtTimer(Math.floor((Date.now() - state.joinedAt) / 1000));
  }, 1000);
  // reset capture + sample immediately, then every 1.5s
  state.acc = { fatigue: 0, emotion: 0, tension: 0, voice: 0 }; state.n = 0;
  sampleBiomarkers();
  state.sampler = setInterval(sampleBiomarkers, 1500);
}

function leave() {
  clearInterval(state.timer); clearInterval(state.sampler);
  const avg = {};
  for (const k of Object.keys(state.bm)) avg[k] = state.n ? Math.round(state.acc[k] / state.n) : Math.round(state.bm[k]);
  const distress = Math.round(weightedDistress(avg));
  const m = state.selected || { title: "Ad-hoc meeting", start: nowHM(), end: nowHM() };
  const start = m.start || nowHM();
  const end = m.end || nowHM();
  const elapsedMin = Math.max(1, Math.round((Date.now() - state.joinedAt) / 60000));
  const dur = (parseHM(end) - parseHM(start)) > 0 ? parseHM(end) - parseHM(start) : elapsedMin;

  state.pending = {
    date: todayISO(), title: m.title, start, end, duration_min: dur,
    distress_score: distress, biomarkers: avg, source: "pawse-app",
  };

  els.dlgTitle.textContent = m.title;
  els.dlgStats.innerHTML =
    `<div class="dlg-stat"><span>Distress</span><b style="color:${distressColor(distress)}">${distress}</b></div>` +
    Object.entries(avg).map(([k, v]) =>
      `<div class="dlg-stat"><span>${k[0].toUpperCase() + k.slice(1)}</span><b>${v}</b></div>`).join("");
  els.leaveDialog.hidden = false;
}

async function saveAndExit() {
  els.saveBtn.disabled = true;
  els.saveBtn.textContent = "Saving…";
  try {
    await fetch("/api/teams-sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.pending),
    });
  } catch (e) {
    alert("Could not reach the server to save. Is `python server.py` running?");
    console.error(e);
  }
  stopStream();
  location.href = "/";
}
function discardAndExit() { stopStream(); location.href = "/"; }
function stopStream() { (state.stream?.getTracks() || []).forEach(t => t.stop()); }

// ---------- Wiring ----------
function main() {
  initCamera();
  loadMeetings();
  els.preMic.addEventListener("click", () => setMic(!state.micOn));
  els.preCam.addEventListener("click", () => setCam(!state.camOn));
  els.joinBtn.addEventListener("click", join);
  els.micBtn.addEventListener("click", () => setMic(!state.micOn));
  els.camBtn.addEventListener("click", () => setCam(!state.camOn));
  els.leaveBtn.addEventListener("click", leave);
  els.saveBtn.addEventListener("click", saveAndExit);
  els.discardBtn.addEventListener("click", discardAndExit);
}

main();
