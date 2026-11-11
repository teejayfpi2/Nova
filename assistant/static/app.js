/* Nova web/PWA client: chat over WebSocket, hold-to-talk voice, spoken replies. */

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const input = $("input");
const statusEl = $("status");

const store = {
  get url() { return localStorage.getItem("nova.url") || location.origin; },
  set url(v) { localStorage.setItem("nova.url", v); },
  get token() { return localStorage.getItem("nova.token") || ""; },
  set token(v) { localStorage.setItem("nova.token", v); },
  get voice() { return localStorage.getItem("nova.voice") !== "false"; },
  set voice(v) { localStorage.setItem("nova.voice", String(v)); },
};

let ws = null;
let currentAssistant = null;
let session = localStorage.getItem("nova.session") || "default";

function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (store.token) headers["Authorization"] = `Bearer ${store.token}`;
  return fetch(store.url.replace(/\/$/, "") + path, Object.assign({}, opts, { headers }));
}

function bubble(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  chat.appendChild(el);
  scrollDown();
  return el;
}

function toolBubble(name, args) {
  const el = document.createElement("div");
  el.className = "msg tool";
  el.innerHTML = `<b>${name}</b> ${escapeHtml(JSON.stringify(args || {}))}`;
  chat.appendChild(el);
  scrollDown();
  return el;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function scrollDown() { window.scrollTo({ top: document.body.scrollHeight }); }

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status " + (cls || "");
}

// ---------- websocket ----------
function connect() {
  const base = store.url.replace(/^http/, "ws").replace(/\/$/, "");
  const url = `${base}/api/ws` + (store.token ? `?token=${encodeURIComponent(store.token)}` : "");
  ws = new WebSocket(url);
  ws.onopen = () => setStatus("online", "online");
  ws.onclose = () => { setStatus("offline", "offline"); setTimeout(connect, 2500); };
  ws.onerror = () => setStatus("offline", "offline");
  ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
}

function handleEvent(ev) {
  if (ev.type === "thinking") {
    currentAssistant = bubble("assistant", "…");
    return;
  }
  if (ev.type === "tool") {
    if (currentAssistant && currentAssistant.textContent === "…") currentAssistant.remove();
    toolBubble(ev.name, ev.arguments);
    currentAssistant = null;
    return;
  }
  if (ev.type === "tool_result") {
    const last = chat.querySelector(".msg.tool:last-of-type");
    if (last) last.textContent += ` → ${String(ev.result).slice(0, 200)}`;
    return;
  }
  if (ev.type === "reminder") {
    bubble("reminder", `⏰ ${ev.body}`);
    speak(`Reminder: ${ev.body}`);
    return;
  }
  if (ev.type === "final") {
    if (currentAssistant) currentAssistant.remove();
    bubble("assistant", ev.text);
    speak(ev.text);
    currentAssistant = null;
  }
}

function send(text) {
  if (!text.trim()) return;
  bubble("user", text);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ message: text, session }));
  } else {
    api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session }),
    })
      .then((r) => r.json())
      .then((d) => { bubble("assistant", d.reply); speak(d.reply); })
      .catch((e) => bubble("error", "Connection problem: " + e.message));
  }
}

// ---------- speech out ----------
let audioEl = new Audio();
async function speak(text) {
  if (!store.voice) return;
  try {
    const res = await api("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error("server tts unavailable");
    const blob = await res.blob();
    audioEl.src = URL.createObjectURL(blob);
    await audioEl.play();
  } catch {
    if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.02;
      speechSynthesis.speak(u);
    }
  }
}

// ---------- speech in (hold to talk) ----------
let recorder = null;
let chunks = [];

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream, { mimeType: pickMime() });
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: recorder.mimeType });
      await transcribe(blob);
    };
    recorder.start();
    $("mic").classList.add("recording");
  } catch (e) {
    bubble("error", "Microphone unavailable: " + e.message);
  }
}

function stopRecording() {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    $("mic").classList.remove("recording");
  }
}

function pickMime() {
  const options = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  return options.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}

async function transcribe(blob) {
  const form = new FormData();
  form.append("audio", blob, "speech.webm");
  bubble("tool", "transcribing…");
  try {
    const res = await api("/api/transcribe", { method: "POST", body: form });
    const data = await res.json();
    const last = chat.querySelector(".msg.tool:last-of-type");
    if (last) last.remove();
    if (data.text) send(data.text);
    else bubble("error", "I didn't catch that.");
  } catch (e) {
    bubble("error", "Transcription failed: " + e.message);
  }
}

// ---------- wiring ----------
$("send").onclick = () => { send(input.value); input.value = ""; };
input.addEventListener("keydown", (e) => { if (e.key === "Enter") { send(input.value); input.value = ""; } });

const mic = $("mic");
["mousedown", "touchstart"].forEach((ev) => mic.addEventListener(ev, (e) => { e.preventDefault(); startRecording(); }));
["mouseup", "mouseleave", "touchend"].forEach((ev) => mic.addEventListener(ev, stopRecording));

$("speak-toggle").onchange = (e) => { store.voice = e.target.checked; };
$("speak-toggle").checked = store.voice;

$("settings-btn").onclick = async () => {
  $("s-url").value = store.url === location.origin ? "" : store.url;
  $("s-token").value = store.token;
  $("s-voice").checked = store.voice;
  try {
    const res = await api("/api/voice/status");
    const d = await res.json();
    $("voice-info").textContent =
      `STT: ${d.stt.available.join(", ") || "none"} · TTS: ${d.tts.available.join(", ") || "none"}`;
  } catch { $("voice-info").textContent = ""; }
  $("settings").showModal();
};

$("settings").addEventListener("close", () => {
  if ($("settings").returnValue === "save") {
    store.url = $("s-url").value.trim() || location.origin;
    store.token = $("s-token").value.trim();
    store.voice = $("s-voice").checked;
    connect();
  }
});

connect();
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}
