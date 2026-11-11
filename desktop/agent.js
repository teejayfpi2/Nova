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
  return String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
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
      return sh(`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${x},${y}); Add-Type -MemberDefinition '[DllImport(\"user32.dll\")]public static extern void mouse_event(int f,int x,int y,int d,int e);' -Name W -Namespace S; [S.W]::mouse_event(2,0,0,0,0); [S.W]::mouse_event(4,0,0,0,0)"`);
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
    const fixed = /^https?:\/\//.test(url) ? url : `https://${url}`;
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
    this.serverUrl = String(serverUrl || '').replace(/\/+$/, '');
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
