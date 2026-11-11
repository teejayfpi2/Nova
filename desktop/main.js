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
  const res = await fetch(config.serverUrl.replace(/\/+$/, '') + '/api/health');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
});

ipcMain.handle('server:chat', async (_e, { message, session }) => {
  const res = await fetch(config.serverUrl.replace(/\/+$/, '') + '/api/chat', {
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
  const res = await fetch(config.serverUrl.replace(/\/+$/, '') + '/api/devices', {
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
