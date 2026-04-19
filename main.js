const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
const BACKEND_PORT = 5678;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

// --- PYTHON PROCESS MANAGEMENT ---
function findPythonExecutable() {
  const candidates = ['python3', 'python'];
  // On macOS/Linux prefer python3; on Windows python
  if (process.platform === 'win32') candidates.reverse();
  return candidates[0];
}

function startPythonBackend() {
  const scriptPath = path.join(__dirname, 'backend.py');
  const python = findPythonExecutable();

  pythonProcess = spawn(python, [scriptPath], {
    cwd: __dirname,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  pythonProcess.stdout.on('data', (data) => {
    console.log(`[Python] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`[Python ERR] ${data.toString().trim()}`);
  });

  pythonProcess.on('exit', (code) => {
    console.log(`[Python] Process exited with code ${code}`);
  });

  console.log(`[Electron] Spawned Python backend (PID ${pythonProcess.pid})`);
}

function killPythonBackend() {
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
    console.log('[Electron] Python backend terminated.');
  }
}

// Poll until Flask is ready, then open the window
function waitForBackend(retries = 30, delay = 500) {
  return new Promise((resolve, reject) => {
    function attempt(n) {
      http.get(`${BACKEND_URL}/api/config`, (res) => {
        resolve();
      }).on('error', () => {
        if (n <= 0) {
          reject(new Error('Backend did not start in time.'));
        } else {
          setTimeout(() => attempt(n - 1), delay);
        }
      });
    }
    attempt(retries);
  });
}

// --- WINDOW CREATION ---
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 780,
    minWidth: 960,
    minHeight: 640,
    titleBarStyle: 'hiddenInset',   // macOS traffic lights inset
    backgroundColor: '#0B0F19',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  mainWindow.loadFile('index.html');

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// --- APP LIFECYCLE ---
app.whenReady().then(async () => {
  startPythonBackend();

  try {
    await waitForBackend();
    console.log('[Electron] Backend ready.');
  } catch (e) {
    console.error('[Electron] Backend failed to start:', e.message);
  }

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  killPythonBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  killPythonBackend();
});