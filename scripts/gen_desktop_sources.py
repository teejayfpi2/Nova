#!/usr/bin/env python3
"""Generate the Nova desktop app (Electron) source files."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "desktop"

FILES: dict[str, str] = {}


def _png(width: int, height: int, pixels: bytes) -> bytes:
    """Encode RGBA pixel data as a PNG (no third-party libraries needed)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_icon(path: Path, size: int = 512) -> None:
    """Draw the Nova app icon: a dark rounded tile with an accent sparkle.

    Matches the in-app brand (dark navy background, blue ``✦``), so the window,
    tray and installer all agree. Drawn with 3x supersampling for smooth edges.
    """
    bg_top, bg_bot = (16, 21, 42), (11, 15, 26)  # #10152a -> #0b0f1a
    accent, core = (108, 140, 255), (232, 238, 255)  # #6c8cff, near-white
    radius = size * 0.22
    arm = size * 0.30  # sparkle arm length
    ss = 3  # supersampling factor

    def coverage(fx: float, fy: float) -> tuple[float, float]:
        """Return (tile_alpha, sparkle_alpha) at a sample point."""
        # Rounded-rect tile test.
        cx = min(max(fx, radius), size - radius)
        cy = min(max(fy, radius), size - radius)
        in_tile = (fx - cx) ** 2 + (fy - cy) ** 2 <= radius**2 or (
            radius <= fx <= size - radius or radius <= fy <= size - radius
        )
        # Astroid sparkle: |x|^(2/3) + |y|^(2/3) <= a^(2/3).
        dx, dy = abs(fx - size / 2), abs(fy - size / 2)
        in_spark = dx ** (2 / 3) + dy ** (2 / 3) <= arm ** (2 / 3)
        return (1.0 if in_tile else 0.0), (1.0 if in_spark else 0.0)

    px = bytearray()
    for y in range(size):
        for x in range(size):
            tile_hits = spark_hits = 0
            for sy in range(ss):
                for sx in range(ss):
                    t, s = coverage(x + (sx + 0.5) / ss, y + (sy + 0.5) / ss)
                    tile_hits += t
                    spark_hits += s
            n = ss * ss
            tile = tile_hits / n
            spark = spark_hits / n
            if tile == 0:
                px += b"\x00\x00\x00\x00"
                continue
            blend = y / size
            r = int(bg_top[0] + (bg_bot[0] - bg_top[0]) * blend)
            g = int(bg_top[1] + (bg_bot[1] - bg_top[1]) * blend)
            b = int(bg_top[2] + (bg_bot[2] - bg_top[2]) * blend)
            # Sparkle: accent edges with a brighter core for a glow.
            sr = int(accent[0] + (core[0] - accent[0]) * spark)
            sg = int(accent[1] + (core[1] - accent[1]) * spark)
            sb = int(accent[2] + (core[2] - accent[2]) * spark)
            r = int(r * (1 - spark) + sr * spark)
            g = int(g * (1 - spark) + sg * spark)
            b = int(b * (1 - spark) + sb * spark)
            px += bytes((r, g, b, int(255 * tile)))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png(size, size, bytes(px)))

FILES["package.json"] = """\
{
  "name": "nova-desktop",
  "version": "1.0.0",
  "description": "Nova personal assistant for your laptop",
  "main": "main.js",
  "scripts": {
    "start": "electron .",
    "dist": "electron-builder --publish never"
  },
  "author": "Ayanlowo Olatunji Ayobami <ayanlowo89@gmail.com> (https://www.linkedin.com/in/olatunjiayanlowo)",
  "homepage": "https://github.com/teejayfpi2/Nova",
  "license": "MIT",
  "devDependencies": {
    "electron": "^31.0.0",
    "electron-builder": "^24.13.3"
  },
  "build": {
    "appId": "ai.nova.desktop",
    "productName": "Nova",
    "files": ["main.js", "preload.js", "agent.js", "renderer/**", "package.json"],
    "directories": { "output": "dist", "buildResources": "build" },
    "icon": "build/icons",
    "mac": { "target": ["dmg", "zip"], "category": "public.app-category.productivity" },
    "win": { "target": ["nsis", "portable"] },
    "linux": { "target": ["AppImage", "deb"], "category": "Utility" }
  },
  "allowScripts": {
    "electron@31.7.7": true
  }
}
"""

FILES["preload.js"] = """\
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nova', {
  getConfig: () => ipcRenderer.invoke('config:get'),
  setConfig: (cfg) => ipcRenderer.invoke('config:set', cfg),
  health: () => ipcRenderer.invoke('server:health'),
  chat: (message, session) => ipcRenderer.invoke('server:chat', { message, session }),
  devices: () => ipcRenderer.invoke('server:devices'),
  speak: (text) => ipcRenderer.invoke('tts:speak', text),
  openExternal: (url) => ipcRenderer.invoke('open:external', url),
  onAgentEvent: (cb) => ipcRenderer.on('agent:event', (_e, data) => cb(data)),
});
"""

FILES["agent.js"] = """\
'use strict';
/**
 * Nova desktop device agent.
 *
 * Polls the Nova server for commands and runs them on this computer: typing,
 * key presses, clicks, screenshots, opening apps and URLs, clipboard and
 * sending messages. Uses the platform's own automation tools so there is
 * nothing to compile.
 */
const { exec, execFile } = require('child_process');
const os = require('os');
const fs = require('fs');
const path = require('path');

const PLATFORM = process.platform; // darwin | win32 | linux

function run(cmd, args, timeout = 20000) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout }, (err, stdout, stderr) => {
      if (err) resolve(`error: ${err.message}`);
      else resolve((stdout || stderr || 'ok').toString().trim());
    });
  });
}

function sh(cmd, timeout = 20000) {
  return new Promise((resolve) => {
    exec(cmd, { timeout }, (err, stdout, stderr) => {
      if (err) resolve(`error: ${err.message}`);
      else resolve((stdout || stderr || 'ok').toString().trim());
    });
  });
}

/** Escape a string for embedding in an AppleScript / PowerShell literal. */
function esc(s) {
  return String(s).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
}

const actions = {
  async type_text({ text }) {
    if (PLATFORM === 'darwin') {
      return run('osascript', ['-e', `tell application "System Events" to keystroke "${esc(text)}"`]);
    }
    if (PLATFORM === 'win32') {
      return sh(`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('${String(text).replace(/'/g, "''")}')"`);
    }
    return run('xdotool', ['type', '--', text]);
  },

  async press_key({ keys }) {
    if (PLATFORM === 'darwin') {
      const parts = String(keys).split('+').map((k) => k.trim());
      const key = parts.pop();
      const mods = parts.map((m) => ({
        cmd: 'command down', command: 'command down', ctrl: 'control down',
        control: 'control down', alt: 'option down', option: 'option down',
        shift: 'shift down',
      }[m.toLowerCase()] || `${m} down`));
      const using = mods.length ? ` using {${mods.join(', ')}}` : '';
      return run('osascript', ['-e', `tell application "System Events" to keystroke "${esc(key)}"${using}`]);
    }
    if (PLATFORM === 'win32') {
      const map = { ctrl: '^', control: '^', alt: '%', shift: '+', cmd: '^', super: '^', enter: '{ENTER}', tab: '{TAB}' };
      const seq = String(keys).split('+').map((k) => map[k.toLowerCase()] || k).join('');
      return sh(`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('${seq.replace(/'/g, "''")}')"`);
    }
    const combo = String(keys).split('+').map((k) => k.trim().replace('cmd', 'ctrl').replace('super', 'win')).join('+');
    return run('xdotool', ['key', combo]);
  },

  async click({ x, y }) {
    if (PLATFORM === 'darwin') {
      return run('osascript', ['-e', `tell application "System Events" to click at {${x}, ${y}}`]);
    }
    if (PLATFORM === 'win32') {
      return sh(`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x},${y}); Add-Type -MemberDefinition '[DllImport(\\"user32.dll\\")]public static extern void mouse_event(int f,int x,int y,int d,int e);' -Name W -Namespace S; [S.W]::mouse_event(2,0,0,0,0); [S.W]::mouse_event(4,0,0,0,0)"`);
    }
    return run('xdotool', ['mousemove', String(x), String(y), 'click', '1']);
  },

  async screenshot({ savePath }) {
    const out = savePath || path.join(os.tmpdir(), `nova-shot-${Date.now()}.png`);
    if (PLATFORM === 'darwin') {
      await run('screencapture', ['-x', out]);
    } else if (PLATFORM === 'win32') {
      await sh(`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $bmp.Save('${out}')"`);
    } else {
      await sh(`import -window root "${out}" || gnome-screenshot -f "${out}" || scrot "${out}"`);
    }
    return fs.existsSync(out) ? `screenshot saved to ${out}` : 'screenshot failed (install ImageMagick, gnome-screenshot or scrot)';
  },

  async open_app({ name }) {
    if (PLATFORM === 'darwin') return run('open', ['-a', name]);
    if (PLATFORM === 'win32') return sh(`start "" "${name}"`);
    return sh(`gtk-launch "${name}" 2>/dev/null || xdg-open "${name}" 2>/dev/null || ${name} &`);
  },

  async open_url({ url }) {
    const fixed = /^https?:\\/\\//.test(url) ? url : `https://${url}`;
    if (PLATFORM === 'darwin') return run('open', [fixed]);
    if (PLATFORM === 'win32') return sh(`start "" "${fixed}"`);
    return run('xdg-open', [fixed]);
  },

  async clipboard({ action, text }) {
    if (action === 'set') {
      if (PLATFORM === 'darwin') return run('pbcopy', [], 5000).then(() => sh(`printf %s ${JSON.stringify(text)} | pbcopy`));
      if (PLATFORM === 'win32') return sh(`powershell -NoProfile -Command "Set-Clipboard -Value '${String(text).replace(/'/g, "''")}'"`);
      return sh(`printf %s ${JSON.stringify(text)} | xclip -selection clipboard || printf %s ${JSON.stringify(text)} | xsel -b`);
    }
    if (PLATFORM === 'darwin') return run('pbpaste', []);
    if (PLATFORM === 'win32') return sh('powershell -NoProfile -Command "Get-Clipboard"');
    return sh('xclip -selection clipboard -o || xsel -b');
  },

  async send_message({ contact, text, app }) {
    if (app === 'whatsapp') return actions.open_url({ url: `https://wa.me/${encodeURIComponent(contact)}?text=${encodeURIComponent(text)}` });
    if (app === 'imessage' && PLATFORM === 'darwin') {
      return sh(`osascript -e 'tell application "Messages" to send "${esc(text)}" to buddy "${esc(contact)}"'`);
    }
    if (app === 'telegram') return actions.open_url({ url: `https://t.me/${encodeURIComponent(contact)}` });
    return actions.open_url({ url: `sms:${encodeURIComponent(contact)}?body=${encodeURIComponent(text)}` });
  },
};

class DeviceAgent {
  constructor({ serverUrl, token, deviceName = os.hostname(), pollMs = 1500, onEvent = () => {} }) {
    this.serverUrl = String(serverUrl || '').replace(/\\/+$/, '');
    this.token = token || '';
    this.deviceName = deviceName;
    this.pollMs = pollMs;
    this.onEvent = onEvent;
    this.running = false;
    this.capabilities = Object.keys(actions);
  }

  headers() {
    const h = { 'Content-Type': 'application/json' };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    return h;
  }

  async api(path, body, method) {
    const res = await fetch(this.serverUrl + path, {
      method: method || (body ? 'POST' : 'GET'),
      headers: this.headers(),
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
    return text ? JSON.parse(text) : {};
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.loop();
  }

  stop() {
    this.running = false;
  }

  async loop() {
    while (this.running) {
      try {
        const { job } = await this.api('/api/bridge/poll', {
          name: this.deviceName,
          capabilities: this.capabilities,
        });
        if (job) {
          const result = await this.execute(job.action, job.args || {});
          this.onEvent({ type: 'command', action: job.action, result });
          await this.api('/api/bridge/result', { name: this.deviceName, id: job.id, result: String(result) });
        }
      } catch (err) {
        this.onEvent({ type: 'error', message: err.message });
        await new Promise((r) => setTimeout(r, 3000));
      }
      await new Promise((r) => setTimeout(r, this.pollMs));
    }
  }

  async execute(action, args) {
    const fn = actions[action];
    if (!fn) return `unsupported action on this device: ${action}`;
    try {
      return await fn(args);
    } catch (err) {
      return `error: ${err.message}`;
    }
  }
}

module.exports = { DeviceAgent, actions, PLATFORM };
"""

FILES["main.js"] = """\
'use strict';
const { app, BrowserWindow, ipcMain, shell, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { DeviceAgent } = require('./agent');

const CONFIG_PATH = path.join(app.getPath('userData'), 'nova-config.json');

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch {
    return { serverUrl: 'http://127.0.0.1:8000', token: '', deviceName: require('os').hostname(), agentEnabled: true };
  }
}

function saveConfig(cfg) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
}

let win = null;
let tray = null;
let agent = null;
let config = loadConfig();

function startAgent() {
  if (agent) agent.stop();
  agent = new DeviceAgent({
    serverUrl: config.serverUrl,
    token: config.token,
    deviceName: config.deviceName,
    onEvent: (e) => {
      if (win && !win.isDestroyed()) win.webContents.send('agent:event', e);
    },
  });
  agent.start();
}

function createWindow() {
  win = new BrowserWindow({
    width: 460,
    height: 760,
    minWidth: 380,
    minHeight: 560,
    title: 'Nova',
    backgroundColor: '#0B0F1A',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.on('closed', () => { win = null; });
}

function createTray() {
  try {
    const icon = nativeImage.createFromPath(path.join(__dirname, 'renderer', 'icon.png'));
    tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
    tray.setToolTip('Nova');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Open Nova', click: () => (win ? win.show() : createWindow()) },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]));
    tray.on('click', () => (win ? win.show() : createWindow()));
  } catch {
    /* tray is best-effort */
  }
}

app.whenReady().then(() => {
  createWindow();
  createTray();
  if (config.agentEnabled) startAgent();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (agent) agent.stop(); });

// ---- IPC ----------------------------------------------------------------
ipcMain.handle('config:get', () => config);

ipcMain.handle('config:set', (_e, cfg) => {
  config = { ...config, ...cfg };
  saveConfig(config);
  if (config.agentEnabled) startAgent();
  else if (agent) agent.stop();
  return config;
});

ipcMain.handle('server:health', async () => {
  const res = await fetch(config.serverUrl.replace(/\\/+$/, '') + '/api/health');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
});

ipcMain.handle('server:chat', async (_e, { message, session }) => {
  const res = await fetch(config.serverUrl.replace(/\\/+$/, '') + '/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(config.token ? { Authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify({ message, session: session || 'desktop' }),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  return JSON.parse(text);
});

ipcMain.handle('server:devices', async () => {
  const res = await fetch(config.serverUrl.replace(/\\/+$/, '') + '/api/devices', {
    headers: config.token ? { Authorization: `Bearer ${config.token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
});

ipcMain.handle('tts:speak', (_e, text) => {
  // The renderer uses the Web Speech API for TTS; nothing to do in main.
  return true;
});

ipcMain.handle('open:external', (_e, url) => shell.openExternal(url));
"""

FILES["renderer/index.html"] = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Nova</title>
<link rel="stylesheet" href="style.css" />
</head>
<body>
  <header>
    <div class="brand"><span class="spark">✦</span> Nova</div>
    <div class="status"><span id="dot" class="dot"></span><span id="statusText">connecting…</span></div>
  </header>

  <main id="messages"></main>

  <footer>
    <button id="micBtn" title="Talk to Nova">🎙</button>
    <input id="input" placeholder="Ask Nova anything…" autocomplete="off" />
    <button id="sendBtn">Send</button>
  </footer>

  <div id="settings" class="sheet hidden">
    <h2>Settings</h2>
    <label>Server URL<input id="serverUrl" /></label>
    <label>Access token<input id="token" type="password" /></label>
    <label>Device name<input id="deviceName" /></label>
    <label class="check"><input id="agentEnabled" type="checkbox" /> Let Nova control this computer</label>
    <label class="check"><input id="speakReplies" type="checkbox" /> Speak replies aloud</label>
    <div class="row">
      <button id="testBtn">Test connection</button>
      <button id="saveBtn" class="primary">Save</button>
    </div>
    <p id="settingsMsg" class="muted"></p>
    <p class="muted about">Nova — built by Ayanlowo Olatunji Ayobami<br />
      ayanlowo89@gmail.com · +2347038193753 ·<br />
      <a href="https://www.linkedin.com/in/olatunjiayanlowo" target="_blank" rel="noopener">LinkedIn</a>
    </p>
  </div>

  <button id="settingsBtn" class="gear" title="Settings">⚙</button>
  <script src="app.js"></script>
</body>
</html>
"""

FILES["renderer/style.css"] = """\
:root {
  --bg: #0b0f1a;
  --surface: #141b2d;
  --accent: #6c8cff;
  --text: #e8ecf7;
  --dim: #8a94ad;
  --user: #2b3a63;
  --nova: #1a2236;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid #1d2740;
}
.brand { font-weight: 600; font-size: 17px; letter-spacing: .2px; }
.spark { color: var(--accent); }
.status { display: flex; align-items: center; gap: 7px; color: var(--dim); font-size: 12px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7280; }
.dot.on { background: #4ade80; }
.dot.off { background: #f87171; }
main { flex: 1; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }
.bubble {
  max-width: 84%; padding: 10px 14px; border-radius: 14px; white-space: pre-wrap;
  word-wrap: break-word; font-size: 14.5px;
}
.bubble.user { align-self: flex-end; background: var(--user); border-bottom-right-radius: 4px; }
.bubble.nova { align-self: flex-start; background: var(--nova); border-bottom-left-radius: 4px; }
.bubble.tool { align-self: flex-start; color: var(--dim); font-size: 12.5px; font-family: ui-monospace, monospace; }
footer { display: flex; gap: 8px; padding: 12px 14px; border-top: 1px solid #1d2740; }
input {
  flex: 1; background: var(--surface); border: 1px solid #24304d; color: var(--text);
  border-radius: 10px; padding: 10px 12px; font-size: 14.5px; outline: none;
}
input:focus { border-color: var(--accent); }
button {
  background: var(--surface); color: var(--text); border: 1px solid #24304d;
  border-radius: 10px; padding: 10px 14px; cursor: pointer; font-size: 14px;
}
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: #0b0f1a; border-color: var(--accent); font-weight: 600; }
#micBtn { padding: 10px 12px; }
.gear {
  position: fixed; right: 12px; top: 12px; background: transparent; border: none;
  font-size: 18px; color: var(--dim); padding: 4px 8px;
}
.sheet {
  position: fixed; inset: 0; background: rgba(11, 15, 26, .97); padding: 26px;
  display: flex; flex-direction: column; gap: 14px; overflow-y: auto;
}
.sheet h2 { margin: 4px 0 6px; font-size: 19px; }
.sheet label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--dim); }
.sheet label.check { flex-direction: row; align-items: center; gap: 10px; color: var(--text); }
.sheet label.check input { flex: none; width: 17px; height: 17px; }
.row { display: flex; gap: 10px; margin-top: 8px; }
.row button { flex: 1; }
.hidden { display: none; }
.muted { color: var(--dim); font-size: 12.5px; }
.about { margin-top: 14px; line-height: 1.6; }
.about a { color: var(--accent); text-decoration: none; }
.about a:hover { text-decoration: underline; }
"""

FILES["renderer/app.js"] = """\
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

  document.querySelectorAll('#settings a[href]').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      if (window.nova.openExternal) window.nova.openExternal(a.href);
    });
  });

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
"""


def main() -> None:
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print("wrote", path)
    write_icon(ROOT / "renderer" / "icon.png")
    print("wrote", ROOT / "renderer" / "icon.png")
    # electron-builder derives icon sizes from filenames, so ship a directory of
    # named sizes; a lone PNG is left unsized (hicolor/0x0) by some builds.
    for s in (16, 32, 48, 64, 128, 256, 512):
        write_icon(ROOT / "build" / "icons" / f"{s}x{s}.png", size=s)
    print("wrote", ROOT / "build" / "icons" / "{16..512}.png")


if __name__ == "__main__":
    main()
