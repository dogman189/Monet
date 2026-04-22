# Monét — Electron App

Algorithmic crypto trading bot. Electron frontend + Python Flask math engine.

## Architecture

```
Electron (main.js)
  └── spawns → Python (backend.py) on port 5678
                  └── Flask REST + SSE API
Renderer (index.html + renderer.js)
  └── fetch() + EventSource → Python backend
```

The Python engine handles all trading math:
- Price fetching via CoinMarketCap Pro API
- Bollinger Band calculation (SMA ± 2σ)
- Buy/Sell execution with portfolio tracking
- Real-time log streaming via Server-Sent Events

## Setup

### 1. Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Node dependencies
```bash
npm install
```

### 3. Run in development
```bash
npm start
```

### 4. Build a distributable (optional)
```bash
npm run build
```
Output goes to `dist/`.

## Configuration

- API key is saved to `config.json` in the app directory and auto-loaded on next launch.
- All trading parameters (symbol, interval, trade amount, wallet) are set in the sidebar before starting.

## Notes

- Requires a [CoinMarketCap Pro API](https://coinmarketcap.com/api/) key (free tier works).
- The bot waits for 20 price samples before trading (configurable via `window_size` in `backend.py`).
- On macOS, `titleBarStyle: 'hiddenInset'` gives native traffic light buttons over the sidebar.
