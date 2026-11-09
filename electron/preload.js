'use strict';
// Expõe só o seletor nativo de arquivos/pastas à página (ela usa quando existe; no navegador cai no seletor do servidor).
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('idemuNative', {
  desktop: true,
  pick: (kind, prompt, start) => ipcRenderer.invoke('idemu:pick', { kind, prompt, start }),
});
