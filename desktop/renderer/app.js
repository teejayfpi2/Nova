'use strict';
const $ = (id) => document.getElementById(id);
const messages = $('messages');
let cfg = { serverUrl: '', token: '', speakReplies: true, agentEnabled: true };
let history = [];

function bubble(text, cls) {
  const div = document.createElement('div');
  div.className = `bubble ${cls}`;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

function setStatus(text, state) {
  $('statusText').textContent = text;
  const dot = $('dot');
  dot.className = 'dot' + (state ? ' ' + state : '');
}

async function refreshHealth() {
  try {
    const h = await window.nova.health();
    setStatus('online', 'on');
  } catch {
    setStatus('offline', 'off');
  }
}

function speak(text) {
  if (!cfg.speakReplies || !window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

async function send() {
  const input = $('input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  bubble(text, 'user');
  history.push({ role: 'user', content: text });
  const pending = bubble('…', 'nova');
  try {
    const res = await window.nova.chat(text, 'desktop');
    pending.textContent = res.reply;
    history.push({ role: 'assistant', content: res.reply });
    speak(res.reply);
  } catch (err) {
    pending.textContent = `I could not reach my server: ${err.message}`;
  }
}

async function listen() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { bubble('Speech recognition is not available in this build.', 'tool'); return; }
  const rec = new SR();
  rec.lang = navigator.language || 'en-US';
  rec.interimResults = false;
  rec.onresult = (e) => {
    const said = e.results[0][0].transcript;
    $('input').value = said;
    send();
  };
  rec.onerror = () => bubble('I could not hear that — check microphone permissions.', 'tool');
  rec.start();
  setStatus('listening…', 'on');
}

function openSettings() {
  $('serverUrl').value = cfg.serverUrl || '';
  $('token').value = cfg.token || '';
  $('deviceName').value = cfg.deviceName || '';
  $('agentEnabled').checked = !!cfg.agentEnabled;
  $('speakReplies').checked = !!cfg.speakReplies;
  $('settings').classList.remove('hidden');
}

function closeSettings() { $('settings').classList.add('hidden'); }

window.addEventListener('DOMContentLoaded', async () => {
  cfg = await window.nova.getConfig();
  await refreshHealth();
  setInterval(refreshHealth, 15000);

  $('sendBtn').onclick = send;
  $('micBtn').onclick = listen;
  $('settingsBtn').onclick = openSettings;
  $('input').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });

  $('testBtn').onclick = async () => {
    $('settingsMsg').textContent = 'testing…';
    try {
      const h = await window.nova.health();
      $('settingsMsg').textContent = `Connected — model: ${h.model || 'unknown'}`;
    } catch (err) {
      $('settingsMsg').textContent = `Failed: ${err.message}`;
    }
  };

  $('saveBtn').onclick = async () => {
    cfg = await window.nova.setConfig({
      serverUrl: $('serverUrl').value.trim(),
      token: $('token').value,
      deviceName: $('deviceName').value.trim(),
      agentEnabled: $('agentEnabled').checked,
      speakReplies: $('speakReplies').checked,
    });
    closeSettings();
    refreshHealth();
  };

  window.nova.onAgentEvent((e) => {
    if (e.type === 'command') bubble(`⚙ ran ${e.action}: ${String(e.result).slice(0, 120)}`, 'tool');
  });

  bubble('Hi, I am Nova. Ask me anything, or tap the microphone and talk.', 'nova');
});
