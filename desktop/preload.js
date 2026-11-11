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
