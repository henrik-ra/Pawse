// Pawse — in-call meeting side panel.
// Auto-starts measuring YOUR biomarkers when opened in a Teams call, and auto-saves
// to the dashboard when the call/panel closes (plus a manual "Save & finish").

import { FaceLandmarker, FilesetResolver } from "./vendor/tasks-vision/vision_bundle.js";

const MODEL = "./vendor/tasks-vision/face_landmarker.task";
const WASM = "./vendor/tasks-vision/wasm";
const WEIGHTS = { fatigue: 0.35, emotion: 0.25, tension: 0.20, voice: 0.20 };
const RIGHT_EYE = [33, 160, 158, 133, 153, 144];
const LEFT_EYE = [362, 385, 387, 263, 373, 380];
const BARS = [["fatigue", "Fatigue", "#6c5ce7"], ["emotion", "Emotion", "#ef5777"],
              ["tension", "Tension", "#e8553e"], ["voice", "Voice", "#4a90d9"]];

const $ = id => document.getElementById(id);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const note = t => { $("note").textContent = t; };
const setStatus = (t, col) => { const e = $("pstatus"); e.textContent = t; if (col) e.style.background = col; };
const dcolor = s => s >= 60 ? "#c4314b" : s >= 35 ? "#e8a13a" : "#3fa34d";

const S = {
  lm: null, video: $("video"), canvas: $("overlay"), ctx: null,
  previewing: false, capturing: false, lastT: -1,
  earOpen: 0.3, earS: [], calib: 0, closed: 0, blinks: 0, log: [], yawnAt: null, yawns: 0, yawnLogged: false,
  smooth: 0, live: { fatigue: 0, emotion: 0, tension: 0, voice: 0 },
  acc: { fatigue: 0, emotion: 0, tension: 0, voice: 0 }, n: 0, startedAt: Date.now(),
  meeting: null, saved: false,
  // audio
  actx: null, an: null, abuf: null, rmsBase: 0.02, pBase: 150, acal: [], acald: false, voice: 0, ph: [],
};

// ---------- Teams meeting context ----------
async function initTeams() {
  try {
    await microsoftTeams.app.initialize();
    microsoftTeams.meeting?.getMeetingDetails?.((err, d) => {
      const subj = d?.details?.subject;
      const start = d?.details?.scheduledStartTime;
      if (subj) S.meeting = { title: subj, start: hm(start), end: "" };
    });
  } catch (_) { /* standalone */ }
}
function hm(iso) { try { return new Date(iso).toTimeString().slice(0, 5); } catch { return nowHM(); } }
function nowHM() { return new Date().toTimeString().slice(0, 5); }

// ---------- Vision ----------
async function initVision() {
  const res = await FilesetResolver.forVisionTasks(WASM);
  const opt = d => ({ baseOptions: { modelAssetPath: MODEL, delegate: d }, outputFaceBlendshapes: true, runningMode: "VIDEO", numFaces: 1 });
  try { S.lm = await FaceLandmarker.createFromOptions(res, opt("GPU")); }
  catch (e) { console.warn("CPU fallback", e); S.lm = await FaceLandmarker.createFromOptions(res, opt("CPU")); }
}
function bmap(c) { const m = {}; (c || []).forEach(x => m[x.categoryName] = x.score); return m; }
function ear(p, idx, w, h) { const P = idx.map(i => ({ x: p[i].x * w, y: p[i].y * h })); const horiz = dist(P[0], P[3]); return horiz < 1e-6 ? 0 : (dist(P[1], P[5]) + dist(P[2], P[4])) / (2 * horiz); }

function analyze(res, w, h, t) {
  if (!res.faceLandmarks || !res.faceLandmarks.length) return null;
  const pts = res.faceLandmarks[0];
  const bs = bmap(res.faceBlendshapes && res.faceBlendshapes[0]?.categories);
  const e = (ear(pts, LEFT_EYE, w, h) + ear(pts, RIGHT_EYE, w, h)) / 2;
  if (S.calib < 45) { S.earS.push(e); S.calib++; if (S.calib === 45) { const s = [...S.earS].sort((a, b) => a - b); S.earOpen = s[s.length >> 1] || 0.3; } }
  const thr = Math.max(0.10, S.earOpen * 0.62), closed = e < thr;
  if (closed) S.closed++; else { if (S.closed >= 2) S.blinks++; S.closed = 0; }
  S.log.push([t, closed]); while (S.log.length && t - S.log[0][0] > 20000) S.log.shift();
  const perclos = S.log.length ? S.log.filter(f => f[1]).length / S.log.length : 0;
  const jaw = bs.jawOpen || 0;
  if (jaw > 0.55) { if (S.yawnAt == null) S.yawnAt = t; else if (t - S.yawnAt > 1200 && !S.yawnLogged) { S.yawns++; S.yawnLogged = true; } }
  else { S.yawnAt = null; S.yawnLogged = false; }
  const fatigue = clamp(0.75 * Math.min(perclos / 0.3, 1) + 0.25 * Math.min(S.yawns / 3, 1), 0, 1) * 100;
  const tension = clamp(((bs.browDownLeft || 0) + (bs.browDownRight || 0) + 0.5 * (bs.browInnerUp || 0) + 0.4 * ((bs.eyeSquintLeft || 0) + (bs.eyeSquintRight || 0)) + 0.3 * ((bs.mouthPressLeft || 0) + (bs.mouthPressRight || 0))) / 1.8, 0, 1) * 100;
  const neg = 0.5 * ((bs.mouthFrownLeft || 0) + (bs.mouthFrownRight || 0)) + 0.25 * ((bs.browDownLeft || 0) + (bs.browDownRight || 0));
  const pos = 0.5 * ((bs.mouthSmileLeft || 0) + (bs.mouthSmileRight || 0));
  const emotion = clamp(neg - 0.5 * pos, 0, 1) * 100;
  return { pts, fatigue, emotion, tension, calibrating: S.calib < 45 };
}

// ---------- Voice ----------
function initAudio(stream) {
  try {
    S.actx = new (window.AudioContext || window.webkitAudioContext)();
    const src = S.actx.createMediaStreamSource(stream);
    S.an = S.actx.createAnalyser(); S.an.fftSize = 2048; src.connect(S.an);
    S.abuf = new Float32Array(S.an.fftSize);
    setInterval(aLoop, 200);
  } catch (e) { console.warn("audio off", e); }
}
const med = a => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };
const sd = a => { const m = a.reduce((x, y) => x + y, 0) / a.length; return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / a.length); };
function pitch(buf, sr) {
  let mean = 0; for (const v of buf) mean += v; mean /= buf.length;
  let rms = 0; for (const v of buf) rms += (v - mean) ** 2; rms = Math.sqrt(rms / buf.length);
  if (rms < 0.005) return 0;
  const lo = Math.floor(sr / 350), hi = Math.floor(sr / 80); let best = -1, bv = 0, c0 = 0;
  for (let i = 0; i < buf.length; i++) c0 += (buf[i] - mean) ** 2;
  for (let lag = lo; lag <= hi; lag++) { let s = 0; for (let i = 0; i + lag < buf.length; i++) s += (buf[i] - mean) * (buf[i + lag] - mean); if (s > bv) { bv = s; best = lag; } }
  return (best < 0 || bv < 0.3 * c0) ? 0 : sr / best;
}
function aLoop() {
  if (!S.an) return;
  S.an.getFloatTimeDomainData(S.abuf);
  let rms = 0; for (const v of S.abuf) rms += v * v; rms = Math.sqrt(rms / S.abuf.length);
  const p = pitch(S.abuf, S.actx.sampleRate);
  if (!S.acald) { S.acal.push(rms); if (S.acal.length >= 15) { S.rmsBase = Math.max(0.005, med(S.acal)); S.acald = true; } return; }
  if (rms <= S.rmsBase * 2) { S.voice *= 0.85; return; }
  if (p > 0) { S.ph.push(p); if (S.ph.length > 12) S.ph.shift(); }
  const jit = S.ph.length >= 3 ? sd(S.ph) : 0;
  const ee = clamp((rms / S.rmsBase - 1) / 3, 0, 1), pe = p > 0 ? clamp((p / S.pBase - 1) / 0.5, 0, 1) : 0;
  S.voice = clamp(0.45 * ee + 0.35 * pe + 0.20 * clamp(jit / 30, 0, 1), 0, 1) * 100;
}

// ---------- Fusion + render ----------
function fuse(face) {
  const c = { fatigue: face && !face.calibrating ? face.fatigue : 0, emotion: face ? face.emotion : 0, tension: face ? face.tension : 0, voice: S.acald ? S.voice : 0 };
  S.live = c;
  let tot = 0, w = 0; for (const k in WEIGHTS) { tot += c[k] * WEIGHTS[k]; w += WEIGHTS[k]; }
  const raw = clamp(tot / w, 0, 100);
  S.smooth = S.smooth * 0.92 + raw * 0.08;
  if (S.capturing && face && !face.calibrating) { for (const k in S.acc) S.acc[k] += c[k]; S.n++; }
  return S.smooth;
}
function renderBars() {
  $("bars").innerHTML = BARS.map(([k, l, col]) => { const v = Math.round(S.live[k] || 0); return `<div class="row"><span class="lbl">${l}</span><span class="bar"><i style="width:${v}%;background:${col}"></i></span><span class="val">${v}</span></div>`; }).join("");
}
function loop() {
  if (!S.previewing) return;
  if (!S.lm) { requestAnimationFrame(loop); return; }
  const v = S.video;
  if (v.readyState >= 2 && v.currentTime !== S.lastT) {
    S.lastT = v.currentTime;
    if (S.canvas.width !== v.videoWidth) { S.canvas.width = v.videoWidth; S.canvas.height = v.videoHeight; }
    let res; try { res = S.lm.detectForVideo(v, performance.now()); } catch (e) { requestAnimationFrame(loop); return; }
    const face = analyze(res, v.videoWidth, v.videoHeight, performance.now());
    const d = Math.round(fuse(face));
    S.ctx.clearRect(0, 0, S.canvas.width, S.canvas.height);
    if (face) drawMesh(face.pts, dcolor(d));
    renderBars();
    $("distress").textContent = face && face.calibrating ? "…" : d;
    if (S.capturing && (!face || !face.calibrating)) setStatus("recording", dcolor(d));
  }
  requestAnimationFrame(loop);
}

// ---------- Camera + lifecycle ----------
async function startCamera() {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: true }); }
  catch (e) { stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } }); }
  S.video.srcObject = stream;
  await new Promise(r => { S.video.onloadedmetadata = () => { S.video.play().catch(() => {}); r(); }; });
  if (stream.getAudioTracks().length) initAudio(stream);
  S.previewing = true; loop();
}

function buildSession() {
  const avg = {}; for (const k in S.acc) avg[k] = S.n ? Math.round(S.acc[k] / S.n) : Math.round(S.live[k] || 0);
  let tot = 0, w = 0; for (const k in WEIGHTS) { tot += avg[k] * WEIGHTS[k]; w += WEIGHTS[k]; }
  const m = S.meeting || { title: "Teams meeting", start: nowHM(), end: "" };
  const end = m.end || nowHM();
  const parse = s => { const [h, mm] = String(s).split(":").map(Number); return (h || 0) * 60 + (mm || 0); };
  const dur = Math.max(1, (parse(end) - parse(m.start)) || Math.round((Date.now() - S.startedAt) / 60000));
  return { date: new Date().toLocaleDateString("en-CA"), title: m.title, start: m.start, end, duration_min: dur, distress_score: Math.round(clamp(tot / w, 0, 100)), biomarkers: avg, source: "pawse-teams-incall" };
}

function autoSave() {
  if (S.saved || S.n < 1) return;
  S.saved = true;
  try { navigator.sendBeacon("/api/teams-sessions", new Blob([JSON.stringify(buildSession())], { type: "application/json" })); } catch (_) {}
}

// Auto-save when the panel/meeting closes.
window.addEventListener("pagehide", autoSave);
window.addEventListener("beforeunload", autoSave);
document.addEventListener("visibilitychange", () => { if (document.hidden) autoSave(); });

// ---------- Boot ----------
function drawMesh(pts, col) {
  const w = S.canvas.width, h = S.canvas.height;
  S.ctx.fillStyle = col;
  for (let i = 0; i < pts.length; i += 3) S.ctx.fillRect(pts[i].x * w, pts[i].y * h, 1.6, 1.6);
  S.ctx.strokeStyle = col; S.ctx.lineWidth = 4; S.ctx.strokeRect(2, 2, w - 4, h - 4);
}

async function main() {
  S.ctx = S.canvas.getContext("2d");
  initTeams();
  try {
    note("Loading model…"); await initVision();
    note("Requesting camera & microphone…"); await startCamera();
    S.capturing = true; S.startedAt = Date.now();
    note("Measuring your wellbeing live during this call…");
    setStatus("recording", "#3fa34d");
  } catch (e) {
    console.error(e);
    setStatus("blocked", "#c4314b");
    note("Camera blocked: " + (e && e.message ? e.message : e) + ". In a call the camera may be busy — allow camera/mic for this app, or use the local companion mode.");
  }
}
main();
