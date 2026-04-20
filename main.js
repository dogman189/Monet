const { app, BrowserWindow, dialog } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');

let mainWindow = null;
let pythonProcess = null;
const BACKEND_PORT = 5678;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

// --- PYTHON PROCESS MANAGEMENT ---
function findBackendExecutable() {
  // PRODUCTION: use the bundled backend binary
  if (app.isPackaged) {
    const ext = process.platform === 'win32' ? '.exe' : '';
    return { exe: path.join(process.resourcesPath, `backend${ext}`), args: [] };
  }

  // DEV: find system Python and run backend.py
  const script = path.join(__dirname, 'backend.py');
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      return { exe: cmd, args: [script] };
    } catch (_) {}
  }

  // Windows fallback: check common install paths
  if (process.platform === 'win32') {
    const bases = [
      `${process.env.LOCALAPPDATA}\\Programs\\Python`,
      'C:\\',
    ];
    const versions = ['Python313', 'Python312', 'Python311', 'Python310'];
    for (const base of bases) {
      for (const ver of versions) {
        const p = path.join(base, ver, 'python.exe');
        if (fs.existsSync(p)) return { exe: p, args: [script] };
      }
    }
  }

  return null;
}

function startPythonBackend() {
  const found = findBackendExecutable();

  if (!found) {
    dialog.showErrorBox(
      'Python Not Found',
      'Could not find Python on this system.\n\nPlease install Python from python.org and check "Add Python to PATH" during installation.'
    );
    app.quit();
    return;
  }

  const { exe, args } = found;

  pythonProcess = spawn(exe, args, {
    cwd: app.isPackaged ? process.resourcesPath : __dirname,
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

  console.log(`[Electron] Spawned backend: ${exe} (PID ${pythonProcess.pid})`);
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
    titleBarStyle: 'hiddenInset',
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