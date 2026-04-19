/**
 * ultraexchange — renderer.js
 * Handles all UI interactions and communication with the Python Flask backend.
 */

const BASE = (window.APP_CONFIG && window.APP_CONFIG.backendUrl) || 'http://127.0.0.1:5678';

// ── DOM REFS ──
const els = {
  overlay:      document.getElementById('boot-overlay'),
  priceVal:     document.getElementById('price-val'),
  smaVal:       document.getElementById('sma-val'),
  upperVal:     document.getElementById('upper-val'),
  lowerVal:     document.getElementById('lower-val'),
  usdVal:       document.getElementById('usd-val'),
  cryptoVal:    document.getElementById('crypto-val'),
  cryptoSym:    document.getElementById('crypto-sym'),
  statusBadge:  document.getElementById('status-badge'),
  statusText:   document.getElementById('status-text'),
  statSymbol:   document.getElementById('stat-symbol'),
  statInterval: document.getElementById('stat-interval'),
  statTrade:    document.getElementById('stat-trade'),
  logOutput:    document.getElementById('log-output'),
  logCount:     document.getElementById('log-count'),
  btnStart:     document.getElementById('btn-start'),
  btnStop:      document.getElementById('btn-stop'),
  inApiKey:     document.getElementById('in-api-key'),
  inSymbol:     document.getElementById('in-symbol'),
  inInterval:   document.getElementById('in-interval'),
  inTrade:      document.getElementById('in-trade'),
  inWallet:     document.getElementById('in-wallet'),
};

// ── STATE ──
let logEventSource = null;
let statusPoller   = null;
let logLineCount   = 0;
let lastPrice      = 0;

// ── BOOT ──
async function boot() {
  // Wait for backend, then hide overlay
  await waitForBackend();
  await loadConfig();
  syncStatus();
  startLogStream();
  startStatusPoller();
  els.overlay.classList.add('hidden');
}

async function waitForBackend(retries = 40, delay = 500) {
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(`${BASE}/api/config`, { signal: AbortSignal.timeout(1000) });
      if (r.ok) return;
    } catch (_) {}
    await sleep(delay);
  }
}

async function loadConfig() {
  try {
    const res = await fetch(`${BASE}/api/config`);
    const data = await res.json();
    if (data.api_key) els.inApiKey.value = data.api_key;
  } catch (_) {}
}

// ── STATUS POLLING (every 2s) ──
function startStatusPoller() {
  statusPoller = setInterval(syncStatus, 2000);
}

async function syncStatus() {
  try {
    const res = await fetch(`${BASE}/api/status`);
    const d = await res.json();
    updateUI(d);
  } catch (_) {}
}

function updateUI(d) {
  // Price
  const price = d.price;
  if (price) {
    els.priceVal.textContent = fmt$(price);
    if (price > lastPrice && lastPrice > 0) {
      flash(els.priceVal, 'up');
    } else if (price < lastPrice && lastPrice > 0) {
      flash(els.priceVal, 'down');
    }
    lastPrice = price;
  }

  // Bands
  els.smaVal.textContent   = d.sma   ? fmt$(d.sma)   : '—';
  els.upperVal.textContent = d.upper ? fmt$(d.upper) : '—';
  els.lowerVal.textContent = d.lower ? fmt$(d.lower) : '—';

  // Portfolio
  els.usdVal.textContent    = fmt$(d.usd);
  els.cryptoVal.textContent = (d.holdings || 0).toFixed(6);
  els.cryptoSym.textContent = d.symbol || 'UNITS';

  // Status stats
  els.statSymbol.textContent   = d.symbol || '—';
  els.statInterval.textContent = d.interval ? `${d.interval}s` : '—';
  els.statTrade.textContent    = d.trade_amt ? fmt$(d.trade_amt) : '—';

  // Status badge
  if (d.is_running) {
    els.statusBadge.className = 'status-badge running';
    els.statusText.textContent = 'Synchronizing';
    els.btnStart.disabled = true;
    els.btnStop.disabled  = false;
    setInputsDisabled(true);
  } else {
    els.statusBadge.className = 'status-badge idle';
    els.statusText.textContent = 'Suspended';
    els.btnStart.disabled = false;
    els.btnStop.disabled  = true;
    setInputsDisabled(false);
  }
}

// ── LOG STREAM (SSE) ──
function startLogStream() {
  if (logEventSource) logEventSource.close();
  logEventSource = new EventSource(`${BASE}/api/logs`);

  logEventSource.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    appendLog(msg);
  };

  logEventSource.onerror = () => {
    // Silently retry — EventSource auto-reconnects
  };
}

function appendLog(line) {
  logLineCount++;
  els.logCount.textContent = `${logLineCount} event${logLineCount !== 1 ? 's' : ''}`;

  // Parse timestamp and body
  const match = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+(.*)$/);
  const time = match ? match[1] : '';
  const msg  = match ? match[2] : line;

  // Classify for coloring
  let cls = '';
  if (/Filled BUY/i.test(msg))   cls = 'buy';
  else if (/Filled SELL/i.test(msg)) cls = 'sell';
  else if (/Error/i.test(msg))   cls = 'err';
  else if (/System:/i.test(msg)) cls = 'sys';

  const row = document.createElement('div');
  row.className = `log-line ${cls}`;
  row.innerHTML = `<span class="log-time">${time}</span><span class="log-msg">${escapeHtml(msg)}</span>`;
  els.logOutput.appendChild(row);
  els.logOutput.scrollTop = els.logOutput.scrollHeight;

  // Keep DOM lean — max 500 lines
  while (els.logOutput.children.length > 500) {
    els.logOutput.removeChild(els.logOutput.firstChild);
  }
}

// ── CONTROLS ──
els.btnStart.addEventListener('click', async () => {
  const key = els.inApiKey.value.trim();
  if (!key) {
    els.inApiKey.focus();
    els.inApiKey.style.borderColor = 'var(--red)';
    setTimeout(() => els.inApiKey.style.borderColor = '', 1500);
    return;
  }

  els.btnStart.disabled = true;
  els.btnStart.textContent = 'Starting…';

  try {
    const res = await fetch(`${BASE}/api/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key:   key,
        symbol:    els.inSymbol.value.trim().toUpperCase() || 'BTC',
        interval:  parseInt(els.inInterval.value) || 300,
        trade_amt: parseFloat(els.inTrade.value)  || 500,
        wallet:    parseFloat(els.inWallet.value) || 10000,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Start failed');
    syncStatus();
  } catch (e) {
    appendLog(`[--:--:--]  Error: ${e.message}`);
    els.btnStart.disabled = false;
  }

  els.btnStart.textContent = 'Initialize Sync';
  // Re-add icon
  els.btnStart.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Initialize Sync`;
});

els.btnStop.addEventListener('click', async () => {
  await fetch(`${BASE}/api/stop`, { method: 'POST' });
  syncStatus();
});

// ── HELPERS ──
function fmt$(n) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(n);
}

function flash(el, cls) {
  el.classList.remove('up', 'down');
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), 1200);
}

function setInputsDisabled(disabled) {
  [els.inApiKey, els.inSymbol, els.inInterval, els.inTrade, els.inWallet].forEach(el => {
    el.disabled = disabled;
    el.style.opacity = disabled ? '0.5' : '1';
  });
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── INIT ──
boot();