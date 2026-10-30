'use strict';
/*
 * The MrSOLIS 3 window is frameless: its minimize / maximize / close buttons are
 * part of the design image. This exposes just those three actions to the page.
 */
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('mrsolisWindow', {
  minimize: () => ipcRenderer.send('win:minimize'),
  toggleMaximize: () => ipcRenderer.send('win:toggle-maximize'),
  close: () => ipcRenderer.send('win:close'),
  openSqe: (question) => ipcRenderer.send('sqe:open', String(question || '')),   // the main window only
});

// The SQE window (sqe.html): a question passed in from the main window ("Practise more like this").
contextBridge.exposeInMainWorld('mrsolisSqe', {
  onPrefill: (fn) => { ipcRenderer.on('sqe:prefill', (_e, q) => fn(String(q || ''))); },
});

// Where a dropped or picked file lives on this computer, so a video is read in place by the backend
// instead of being copied (lecture videos run to gigabytes). Empty when it can't be told.
contextBridge.exposeInMainWorld('mrsolisFiles', {
  pathFor: (file) => {
    try { return (webUtils && webUtils.getPathForFile(file)) || ''; } catch (e) { return ''; }
  },
});

// The activation screen (activate.html): type a licence code, buy one with Paystack, or close MrSOLIS. main.js
// only answers these from that window.
contextBridge.exposeInMainWorld('mrsolisLicence', {
  info: () => ipcRenderer.invoke('licence:info'),
  activate: (code) => ipcRenderer.invoke('licence:activate', code),
  quit: () => ipcRenderer.invoke('licence:quit'),
  price: () => ipcRenderer.invoke('licence:price'),
  buy: (email, opts) => ipcRenderer.invoke('licence:buy', email, opts),   // opts { method: 'momo', payer } for MoMo
  copy: (text) => ipcRenderer.invoke('licence:copy', text),
  reopen: () => ipcRenderer.invoke('licence:buy-reopen'),
  cancelBuy: () => ipcRenderer.invoke('licence:buy-cancel'),
  onBuy: (fn) => { ipcRenderer.on('licence:buy-progress', (_e, data) => fn(data)); },
});
