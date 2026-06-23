// Pawse — Teams app: REAL on-device biomarkers in the browser.
// Vision  : MediaPipe Web FaceLandmarker (fatigue via EAR/PERCLOS, tension via blendshapes,
//           emotion proxy via blendshapes).
// Voice   : Web Audio (RMS energy + pitch -> vocal arousal).
// Saves the averaged session to the Pawse dashboard (/api/teams-sessions).

import {
  FaceLandmarker, FilesetResolver, DrawingUtils,
} from "./vendor/tasks-vision/vision_bundle.js";

const MODEL = "./vendor/tasks-vision/face_landmarker.task";
const WASM = "./vendor/tasks-vision/wasm";

const WEIGHTS = { fatigue: 0.35, emotion: 0.25, tension: 0.20, voice: 0.20 };
const RIGHT_EYE = [33, 160, 158, 133, 153, 144];
const LEFT_EYE = [362, 385, 387, 263, 373, 380];
const BARS = [["fatigue", "Fatigue", "#6c5ce7"], ["emotion", "Emotion", "#ef5777"],
              ["tension", "Tension", "#e8553e"], ["voice", "Voice", "#4a90d9"]];

const $ = id => document.getElementById(id);
const setNote = t => { const n = $("note"); if (n) n.textContent = t; };
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

const S = {
  landmarker: null, video: $("video"), canvas: $("overlay"), ctx: null, draw: null,
  running: false, lastVideoTime: -1,
  // fatigue
  earOpen: 0.3, earSamples: [], calibFrames: 0, closedFrames: 0, blinks: 0,
  frameLog: [], yawnOpenSince: null, yawns: 0,
  // smoothing + accumulation
  smooth: { distress: 0 }, live: { fatigue: 0, emotion: 0, tension: 0, voice: 0 },
  acc: { fatigue: 0, emotion: 0, tension: 0, voice: 0 }, n: 0,
  startedAt: null, meeting: null,
  // audio
  audioCtx: null, analyser: null, audioBuf: null, rmsBase: 0.02, pitchBase: 150,
  audioCalib: [], audioCalibrated: false, voiceScore: 0, pitchHist: [],
};

function distressColor(s) { return s >= 60 ? "#c4314b" : s >= 35 ? "#e8a13a" : "#3fa34d"; }

// ---------------- Teams SDK + meeting context ----------------
async function initTeams() {
  try {
    await microsoftTeams.app.initialize();
    const ctx = await microsoftTeams.app.getContext();
    $("ctx").textContent = "in Teams · " + (ctx.app?.host?.name || "Teams");
  } catch (_) {
    $("ctx").textContent = "standalone (browser)";
  }
}

async function loadMeeting() {
  // Auto-link to the calendar meeting happening now (from the dashboard's Outlook data).
  try {
    const today = new Date().toLocaleDateString("en-CA");
    const r = await fetch(`/api/live-day?date=${today}`, { cache: "no-store" });
    const data = await r.json();
    const now = new Date();
    const hm = now.getHours() * 60 + now.getMinutes();
    const parse = s => { const [h, m] = String(s).split(":").map(Number); return h * 60 + m; };
    const meetings = data?.data?.meetings || [];
    let pick = meetings.find(m => hm >= parse(m.start) && hm <= parse(m.end));
    if (!pick) pick = meetings.find(m => parse(m.start) >= hm) || null;
    if (pick) {
      S.meeting = { title: pick.title, start: pick.start, end: pick.end };
      $("meetingTitle").textContent = pick.title;
      $("meetingTime").textContent = `${pick.start}–${pick.end} · measured on-device`;
      return;
    }
  } catch (_) { /* offline */ }
  const hm = new Date().toTimeString().slice(0, 5);
  S.meeting = { title: "Ad-hoc meeting", start: hm, end: "" };
}

// ---------------- Vision ----------------
async function initVision() {
  const resolver = await FilesetResolver.forVisionTasks(WASM);
  const opts = (delegate) => ({
    baseOptions: { modelAssetPath: MODEL, delegate },
    outputFaceBlendshapes: true, runningMode: "VIDEO", numFaces: 1,
  });
  try {
    S.landmarker = await FaceLandmarker.createFromOptions(resolver, opts("GPU"));
  } catch (e) {
    console.warn("GPU delegate failed, falling back to CPU", e);
    S.landmarker = await FaceLandmarker.createFromOptions(resolver, opts("CPU"));
  }
}

function blendMap(categories) {
  const m = {};
  (categories || []).forEach(c => { m[c.categoryName] = c.score; });
  return m;
}

function earFor(pts, idx, w, h) {
  const P = idx.map(i => ({ x: pts[i].x * w, y: pts[i].y * h }));
  const horiz = dist(P[0], P[3]);
  if (horiz < 1e-6) return 0;
  return (dist(P[1], P[5]) + dist(P[2], P[4])) / (2 * horiz);
}

function analyzeFace(res, w, h, t) {
  if (!res.faceLandmarks || !res.faceLandmarks.length) return null;
  const pts = res.faceLandmarks[0];
  const bs = blendMap(res.faceBlendshapes && res.faceBlendshapes[0]?.categories);

  // --- Fatigue: EAR -> PERCLOS + blinks + yawns ---
  const ear = (earFor(pts, LEFT_EYE, w, h) + earFor(pts, RIGHT_EYE, w, h)) / 2;
  if (S.calibFrames < 45) { // ~1.5s warmup
    S.earSamples.push(ear); S.calibFrames++;
    if (S.calibFrames === 45) {
      const sorted = [...S.earSamples].sort((a, b) => a - b);
      S.earOpen = sorted[Math.floor(sorted.length * 0.5)] || 0.3;
    }
  }
  const thr = Math.max(0.10, S.earOpen * 0.62);
  const closed = ear < thr;
  if (closed) S.closedFrames++;
  else { if (S.closedFrames >= 2) S.blinks++; S.closedFrames = 0; }
  S.frameLog.push([t, closed]);
  while (S.frameLog.length && t - S.frameLog[0][0] > 20000) S.frameLog.shift();
  const perclos = S.frameLog.length ? S.frameLog.filter(f => f[1]).length / S.frameLog.length : 0;

  // yawn via jawOpen sustained
  const jawOpen = bs.jawOpen || 0;
  if (jawOpen > 0.55) {
    if (S.yawnOpenSince == null) S.yawnOpenSince = t;
    else if (t - S.yawnOpenSince > 1200 && !S._yawnLogged) { S.yawns++; S._yawnLogged = true; }
  } else { S.yawnOpenSince = null; S._yawnLogged = false; }
  const fatigue = clamp(0.75 * Math.min(perclos / 0.3, 1) + 0.25 * Math.min(S.yawns / 3, 1), 0, 1) * 100;

  // --- Tension (blendshapes) ---
  const tension = clamp((
    (bs.browDownLeft || 0) + (bs.browDownRight || 0)
    + 0.5 * (bs.browInnerUp || 0)
    + 0.4 * ((bs.eyeSquintLeft || 0) + (bs.eyeSquintRight || 0))
    + 0.3 * ((bs.mouthPressLeft || 0) + (bs.mouthPressRight || 0))
  ) / 1.8, 0, 1) * 100;

  // --- Emotion proxy (blendshapes) ---
  const neg = 0.5 * ((bs.mouthFrownLeft || 0) + (bs.mouthFrownRight || 0))
            + 0.25 * ((bs.browDownLeft || 0) + (bs.browDownRight || 0));
  const pos = 0.5 * ((bs.mouthSmileLeft || 0) + (bs.mouthSmileRight || 0));
  const emotion = clamp(neg - 0.5 * pos, 0, 1) * 100;

  return { pts, fatigue, emotion, tension, calibrating: S.calibFrames < 45 };
}

// ---------------- Voice (Web Audio) ----------------
function initAudio(stream) {
  try {
    S.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = S.audioCtx.createMediaStreamSource(stream);
    S.analyser = S.audioCtx.createAnalyser();
    S.analyser.fftSize = 2048;
    src.connect(S.analyser);
    S.audioBuf = new Float32Array(S.analyser.fftSize);
    setInterval(analyzeAudio, 200);
  } catch (e) { console.warn("audio off", e); }
}

function autocorrPitch(buf, sr) {
  let mean = 0; for (const v of buf) mean += v; mean /= buf.length;
  let rms = 0; for (const v of buf) rms += (v - mean) ** 2; rms = Math.sqrt(rms / buf.length);
  if (rms < 0.005) return 0;
  const minLag = Math.floor(sr / 350), maxLag = Math.floor(sr / 80);
  let best = -1, bestVal = 0, c0 = 0;
  for (let i = 0; i < buf.length; i++) c0 += (buf[i] - mean) ** 2;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let s = 0;
    for (let i = 0; i + lag < buf.length; i++) s += (buf[i] - mean) * (buf[i + lag] - mean);
    if (s > bestVal) { bestVal = s; best = lag; }
  }
  if (best < 0 || bestVal < 0.3 * c0) return 0;
  return sr / best;
}

function analyzeAudio() {
  if (!S.analyser) return;
  S.analyser.getFloatTimeDomainData(S.audioBuf);
  let rms = 0; for (const v of S.audioBuf) rms += v * v; rms = Math.sqrt(rms / S.audioBuf.length);
  const pitch = autocorrPitch(S.audioBuf, S.audioCtx.sampleRate);

  if (!S.audioCalibrated) {
    S.audioCalib.push(rms);
    if (S.audioCalib.length >= 15) {
      S.rmsBase = Math.max(0.005, median(S.audioCalib));
      S.audioCalibrated = true;
    }
    return;
  }
  const speaking = rms > S.rmsBase * 2;
  if (!speaking) { S.voiceScore *= 0.85; return; }
  if (pitch > 0) { S.pitchHist.push(pitch); if (S.pitchHist.length > 12) S.pitchHist.shift(); }
  const jitter = S.pitchHist.length >= 3 ? std(S.pitchHist) : 0;
  const energyExcess = clamp((rms / S.rmsBase - 1) / 3, 0, 1);
  const pitchExcess = pitch > 0 ? clamp((pitch / S.pitchBase - 1) / 0.5, 0, 1) : 0;
  S.voiceScore = clamp(0.45 * energyExcess + 0.35 * pitchExcess + 0.20 * clamp(jitter / 30, 0, 1), 0, 1) * 100;
}
const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
const std = a => { const m = a.reduce((x, y) => x + y, 0) / a.length; return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / a.length); };

// ---------------- Fusion + render ----------------
function fuse(face) {
  const c = {
    fatigue: face && !face.calibrating ? face.fatigue : 0,
    emotion: face ? face.emotion : 0,
    tension: face ? face.tension : 0,
    voice: S.audioCalibrated ? S.voiceScore : 0,
  };
  S.live = c;
  let tot = 0, w = 0;
  for (const k in WEIGHTS) { tot += c[k] * WEIGHTS[k]; w += WEIGHTS[k]; }
  const raw = clamp(tot / w, 0, 100);
  // EMA smoothing (~ a few seconds)
  S.smooth.distress = S.smooth.distress * 0.92 + raw * 0.08;
  if (S.running && face && !face.calibrating) {
    for (const k in S.acc) S.acc[k] += c[k];
    S.n++;
  }
  return S.smooth.distress;
}

function renderBars() {
  $("bars").innerHTML = BARS.map(([k, lab, col]) => {
    const v = Math.round(S.live[k] || 0);
    return `<div class="row"><span class="lbl">${lab}</span>
      <span class="bar"><i style="width:${v}%;background:${col}"></i></span>
      <span class="val">${v}</span></div>`;
  }).join("");
}

function drawMesh(face, distress) {
  const ctx = S.ctx;
  ctx.clearRect(0, 0, S.canvas.width, S.canvas.height);
  if (!face) return;
  const col = distressColor(distress);
  S.draw.drawConnectors(face.pts, FaceLandmarker.FACE_LANDMARKS_TESSELATION,
    { color: col + "66", lineWidth: 1 });
}

function loop() {
  if (!S.running && !S._previewing) return;
  if (!S.landmarker) { requestAnimationFrame(loop); return; }
  const v = S.video;
  if (v.readyState >= 2 && v.currentTime !== S.lastVideoTime) {
    S.lastVideoTime = v.currentTime;
    if (S.canvas.width !== v.videoWidth) { S.canvas.width = v.videoWidth; S.canvas.height = v.videoHeight; }
    const res = S.landmarker.detectForVideo(v, performance.now());
    const face = analyzeFace(res, v.videoWidth, v.videoHeight, performance.now());
    const distress = fuse(face);
    drawMesh(face, distress);
    renderBars();
    const d = Math.round(distress);
    $("distress").textContent = face && face.calibrating ? "…" : d;
    $("dot").style.background = distressColor(d);
    $("live").textContent = face ? (face.calibrating ? "calibrating…" : "distress " + d) : "no face";
  }
  requestAnimationFrame(loop);
}

// ---------------- Camera + lifecycle ----------------
async function startCamera() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: true });
  } catch (e) {
    // audio may be blocked -> retry video-only so the vision part still works
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
  }
  S.video.srcObject = stream;
  await new Promise(r => { S.video.onloadedmetadata = () => { S.video.play().catch(() => {}); r(); }; });
  if (stream.getAudioTracks().length) initAudio(stream);
  S._previewing = true;
  loop();
}

async function ensureStarted() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
    throw new Error("Camera API not available in this context");
  if (!S.landmarker) { setNote("Loading Pawse vision model\u2026"); await initVision(); }
  if (!S._previewing) { setNote("Requesting camera & microphone\u2026"); await startCamera(); }
  setNote("Ready.");
}

async function beginCapture() {
  $("startBtn").disabled = true; $("startBtn").textContent = "Starting\u2026";
  try {
    await ensureStarted();
  } catch (e) {
    setNote("Could not start: " + (e && e.message ? e.message : e) + " \u2014 allow camera/mic for this app, then click Start again.");
    $("startBtn").disabled = false; $("startBtn").textContent = "Start capture";
    return;
  }
  S.acc = { fatigue: 0, emotion: 0, tension: 0, voice: 0 }; S.n = 0;
  S.startedAt = Date.now();
  S.running = true;
  $("startBtn").textContent = "Capturing\u2026";
  $("saveBtn").disabled = false;
  setNote("Pawse is measuring. Click \u2018End & save\u2019 when the meeting ends.");
}

function buildSession() {
  const avg = {};
  for (const k in S.acc) avg[k] = S.n ? Math.round(S.acc[k] / S.n) : Math.round(S.live[k] || 0);
  let tot = 0, w = 0; for (const k in WEIGHTS) { tot += avg[k] * WEIGHTS[k]; w += WEIGHTS[k]; }
  const m = S.meeting || { title: "Ad-hoc meeting", start: new Date().toTimeString().slice(0, 5), end: "" };
  const end = m.end || new Date().toTimeString().slice(0, 5);
  const parse = s => { const [h, mm] = String(s).split(":").map(Number); return (h || 0) * 60 + (mm || 0); };
  const dur = Math.max(1, (parse(end) - parse(m.start)) || Math.round((Date.now() - (S.startedAt || Date.now())) / 60000));
  return {
    date: new Date().toLocaleDateString("en-CA"),
    title: m.title, start: m.start, end, duration_min: dur,
    distress_score: Math.round(clamp(tot / w, 0, 100)),
    biomarkers: avg, source: "pawse-teams-app",
  };
}

async function saveAndShow() {
  const session = buildSession();
  $("saveBtn").disabled = true; $("saveBtn").textContent = "Saving…";
  try {
    await fetch("/api/teams-sessions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(session),
    });
  } catch (e) { alert("Could not save: " + e.message); }
  S.running = false;
  $("startBtn").disabled = false; $("startBtn").textContent = "Start capture";
  $("saveBtn").textContent = "Saved ✓";
  switchView("dashboard");
}

// Best-effort auto-save if the tab/meeting is closed mid-capture.
function autoSaveOnExit() {
  if (S.running && S.n > 0) {
    try { navigator.sendBeacon("/api/teams-sessions", new Blob([JSON.stringify(buildSession())], { type: "application/json" })); } catch (_) {}
  }
}

// ---------------- Views ----------------
function switchView(view) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $("view-capture").hidden = view !== "capture";
  $("view-dashboard").hidden = view !== "dashboard";
  if (view === "dashboard") {
    const f = $("dash");
    f.src = "/?t=" + Date.now(); // reload so the new session shows
  }
}

// ---------------- Boot ----------------
async function main() {
  S.ctx = S.canvas.getContext("2d");
  S.draw = new DrawingUtils(S.ctx);
  document.querySelectorAll(".tab-btn").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
  $("startBtn").addEventListener("click", beginCapture);
  $("saveBtn").addEventListener("click", saveAndShow);
  window.addEventListener("beforeunload", autoSaveOnExit);
  document.addEventListener("visibilitychange", () => { if (document.hidden) autoSaveOnExit(); });

  initTeams();
  await loadMeeting();
  try {
    await ensureStarted();
    setNote("Ready. Click \u2018Start capture\u2019 to begin measuring.");
  } catch (e) {
    console.error(e);
    setNote("Tap \u2018Start capture\u2019 and allow camera/microphone. (" + (e && e.message ? e.message : e) + ")");
  }
}
main();
