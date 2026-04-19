// preload.js — context bridge between renderer and Node
const { contextBridge } = require('electron');

// Expose the backend URL to the renderer safely
contextBridge.exposeInMainWorld('APP_CONFIG', {
  backendUrl: 'http://127.0.0.1:5678',
});