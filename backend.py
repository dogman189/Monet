"""
ultraexchange - Python Trading Engine
Flask REST + SSE backend. 

Math Engine v2:
  - RSI confirmation filter (14-period)
  - Band re-entry signals (not just touches)
  - Percentage-based position sizing (20% per buy, 50% partial sells)
  - Bandwidth filter (skips BB squeeze periods)a
  - 7% trailing stop-loss
  - Trade cooldown (min 3 intervals between trades)
"""

import json
import ssl
import urllib.parse
import urllib.request
import certifi
import time
import statistics
import os
import queue
import threading
from collections import deque
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── CONFIG CONSTANTS ──────────────────────────────────────────────────────────

RSI_PERIOD        = 14       
RSI_OVERSOLD      = 35       
RSI_OVERBOUGHT    = 65       
BB_WINDOW         = 20       
BB_STDDEV         = 2        
MIN_BANDWIDTH     = 0.02     
BUY_RISK_PCT      = 0.20     
SELL_PCT          = 0.50     
STOP_LOSS_PCT     = 0.07     
TRADE_COOLDOWN    = 3        
CONFIG_FILE       = "config.json"


# ── TRADING ENGINE CLASS ──────────────────────────────────────────────────────

class TradingEngine:
    def __init__(self):
        self.running_event = threading.Event()
        self.log_queue = queue.Queue()
        self.bot_thread = None
        
        # State variables
        self.symbol = "BTC"
        self.interval = 300
        self.trade_amt = 500.0
        self.api_key = ""
        self.price = 0.0
        self.sma = None
        self.upper = None
        self.lower = None
        self.rsi = None
        self.bandwidth = None
        self.portfolio = {"USD": 10000.0, "holdings": {}}
        
        # v2 signal state
        self.avg_buy_price = None
        self.was_below_lower = False
        self.was_above_upper = False
        self.last_trade_interval = 0
        self.interval_count = 0
        self.total_trades = 0
        self.total_buys = 0
        self.total_sells = 0
        self.stop_losses_hit = 0
        
        self.price_history = deque(maxlen=BB_WINDOW + RSI_PERIOD + 5)

    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        entry = f"[{timestamp}]  {message}"
        self.log_queue.put(entry)
        print(entry)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    if "api_key" in config:
                        self.api_key = config["api_key"]
            except Exception:
                self.log("System: Failed to load config.")

    def save_config(self, key):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"api_key": key}, f)
        except Exception:
            self.log("System: Config save failed.")

    def fetch_price(self):
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = urllib.parse.urlencode({"symbol": self.symbol, "convert": "USD"})
        req = urllib.request.Request(
            f"{url}?{params}",
            headers={"X-CMC_PRO_API_KEY": self.api_key}
        )
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            # Added a 10-second timeout to prevent infinite hanging
            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                data = json.load(response)
                return data["data"][self.symbol]["quote"]["USD"]["price"]
        except Exception as e:
            self.log(f"Error: API fetch failed. ({e})")
            return None

    def compute_bollinger(self, prices):
        if len(prices) < BB_WINDOW:
            return None, None, None
        window = list(prices)[-BB_WINDOW:]
        sma = statistics.mean(window)
        std = statistics.stdev(window)
        return sma, sma + (std * BB_STDDEV), sma - (std * BB_STDDEV)

    def compute_rsi(self, prices, period=RSI_PERIOD):
        prices = list(prices)
        if len(prices) < period + 1:
            return None

        recent = prices[-(period + 1):]
        deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]

        gains  = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]

        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 1e-9

        rs  = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    def compute_bandwidth(self, sma, upper, lower):
        if sma and sma != 0:
            return (upper - lower) / sma
        return None

    def execute_trade(self, side, price, reason="signal"):
        symbol = self.symbol
        if side == "BUY":
            trade_amt = self.portfolio["USD"] * BUY_RISK_PCT
            if trade_amt < 1.0:
                self.log(f"Risk: Skipped BUY — insufficient USD balance (${self.portfolio['USD']:.2f})")
                return False

            bought = trade_amt / price
            self.portfolio["USD"] -= trade_amt

            prev_holdings = self.portfolio["holdings"].get(symbol, 0)
            prev_avg = self.avg_buy_price or price
            self.portfolio["holdings"][symbol] = prev_holdings + bought

            if prev_holdings > 0:
                self.avg_buy_price = ((prev_avg * prev_holdings + price * bought) / (prev_holdings + bought))
            else:
                self.avg_buy_price = price

            self.total_trades += 1
            self.total_buys += 1
            self.log(f"Execution: Filled BUY  {bought:.6f} {symbol}  @  ${price:,.2f}  |  Risked: ${trade_amt:,.2f}  |  Reason: {reason}")
            return True

        elif side == "SELL":
            owned = self.portfolio["holdings"].get(symbol, 0)
            if owned <= 0:
                self.log(f"Risk: Skipped SELL — no {symbol} holdings")
                return False

            sell_qty = owned * SELL_PCT
            proceeds = sell_qty * price
            self.portfolio["USD"] += proceeds
            self.portfolio["holdings"][symbol] = owned - sell_qty

            pnl_str = ""
            if self.avg_buy_price:
                pnl = (price - self.avg_buy_price) / self.avg_buy_price * 100
                pnl_str = f"  |  PnL: {pnl:+.2f}%"

            if self.portfolio["holdings"][symbol] < 1e-8:
                self.portfolio["holdings"][symbol] = 0
                self.avg_buy_price = None

            self.total_trades += 1
            self.total_sells += 1
            self.log(f"Execution: Filled SELL {sell_qty:.6f} {symbol}  @  ${price:,.2f}  |  Proceeds: ${proceeds:,.2f}{pnl_str}  |  Reason: {reason}")
            return True

        return False

    def loop(self):
        self.price_history.clear()
        self.was_below_lower = False
        self.was_above_upper = False
        self.last_trade_interval = 0
        self.interval_count = 0
        self.avg_buy_price = None
        self.total_trades = 0
        self.total_buys = 0
        self.total_sells = 0
        self.stop_losses_hit = 0

        self.log(f"System: Data stream initialized for {self.symbol}")
        self.log(f"System: Engine v2 — RSI({RSI_PERIOD}) + BB({BB_WINDOW}) | Stop-loss: {STOP_LOSS_PCT*100:.0f}%")

        while self.running_event.is_set():
            price = self.fetch_price()

            if price is None:
                self.log("System: Failed to fetch price, retrying next interval...")
            else:
                self.price = price
                self.price_history.append(price)
                self.interval_count += 1

                prices = list(self.price_history)
                sma, upper, lower = self.compute_bollinger(prices)
                rsi = self.compute_rsi(prices)
                bandwidth = self.compute_bandwidth(sma, upper, lower) if sma else None

                self.sma = sma
                self.upper = upper
                self.lower = lower
                self.rsi = rsi
                self.bandwidth = bandwidth

                if sma is None or rsi is None:
                    needed = max(BB_WINDOW, RSI_PERIOD + 1) - len(prices)
                    self.log(f"Calibrating: ${price:,.2f}  —  {needed} more sample(s) needed")
                else:
                    rsi_str = f"{rsi:.1f}"
                    bw_str  = f"{bandwidth:.4f}" if bandwidth is not None else "?"
                    self.log(f"Signal: Price=${price:,.2f}  SMA=${sma:,.2f}  BB=[{lower:,.2f}, {upper:,.2f}]  RSI={rsi_str}  BW={bw_str}")

                    intervals_since_trade = self.interval_count - self.last_trade_interval
                    on_cooldown = intervals_since_trade < TRADE_COOLDOWN

                    if on_cooldown:
                        self.log(f"Risk: Cooldown active — {TRADE_COOLDOWN - intervals_since_trade} interval(s) remaining")

                    avg_entry = self.avg_buy_price
                    holdings = self.portfolio["holdings"].get(self.symbol, 0)

                    # Stop Loss
                    if avg_entry and holdings > 0 and price < avg_entry * (1 - STOP_LOSS_PCT):
                        loss_pct = (price - avg_entry) / avg_entry * 100
                        self.log(f"Risk: Stop-loss triggered! Entry=${avg_entry:,.2f} Current=${price:,.2f} Drawdown={loss_pct:+.2f}%")
                        if self.execute_trade("SELL", price, reason="stop-loss"):
                            self.stop_losses_hit += 1
                            self.last_trade_interval = self.interval_count
                            self.was_above_upper = False
                            self.was_below_lower = False
                    
                    # Core Logic
                    elif bandwidth is not None and bandwidth < MIN_BANDWIDTH:
                        self.log(f"Signal: BB squeeze (BW={bw_str} < {MIN_BANDWIDTH}) — no trade")
                    else:
                        if price < lower:
                            if not self.was_below_lower:
                                self.log(f"Signal: Broke below lower band (${lower:,.2f}) | RSI={rsi_str} — watching for re-entry")
                            self.was_below_lower = True

                        elif price > upper:
                            if not self.was_above_upper:
                                self.log(f"Signal: Broke above upper band (${upper:,.2f}) | RSI={rsi_str} — watching for re-entry")
                            self.was_above_upper = True

                        elif self.was_below_lower and price >= lower:
                            self.was_below_lower = False
                            self.log(f"Signal: Re-entered lower band | RSI={rsi_str}")
                            if not on_cooldown and rsi <= RSI_OVERSOLD:
                                if self.execute_trade("BUY", price, reason="BB re-entry + RSI oversold"):
                                    self.last_trade_interval = self.interval_count

                        elif self.was_above_upper and price <= upper:
                            self.was_above_upper = False
                            self.log(f"Signal: Re-entered upper band | RSI={rsi_str}")
                            if not on_cooldown and rsi >= RSI_OVERBOUGHT:
                                if self.execute_trade("SELL", price, reason="BB re-entry + RSI overbought"):
                                    self.last_trade_interval = self.interval_count

            # Replaces interruptible_sleep. Waits for 'interval' seconds or until cleared.
            self.running_event.wait(self.interval)

        self.log(f"System: Data stream terminated. Trades: {self.total_trades}")

    def start(self, config):
        if self.running_event.is_set():
            return False
        
        self.api_key = config.get("api_key", "").strip()
        self.symbol = config.get("symbol", "BTC").upper()
        self.interval = int(config.get("interval", 300))
        self.trade_amt = float(config.get("trade_amt", 500))
        self.portfolio["USD"] = float(config.get("wallet", 10000))
        self.portfolio["holdings"] = {}
        
        self.save_config(self.api_key)
        self.running_event.set()
        self.bot_thread = threading.Thread(target=self.loop, daemon=True)
        self.bot_thread.start()
        return True

    def stop(self):
        self.running_event.clear()

    def get_status(self):
        return {
            "is_running": self.running_event.is_set(),
            "symbol": self.symbol,
            "price": self.price,
            "sma": self.sma,
            "upper": self.upper,
            "lower": self.lower,
            "rsi": self.rsi,
            "bandwidth": self.bandwidth,
            "usd": self.portfolio["USD"],
            "holdings": self.portfolio["holdings"].get(self.symbol, 0),
            "api_key": self.api_key,
            "interval": self.interval,
            "trade_amt": self.trade_amt,
            "wallet": self.portfolio["USD"],
            "avg_buy_price": self.avg_buy_price,
            "total_trades": self.total_trades,
            "total_buys": self.total_buys,
            "total_sells": self.total_sells,
            "stop_losses_hit": self.stop_losses_hit,
        }

# Global Engine Instance
engine = TradingEngine()


# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(engine.get_status())

@app.route("/api/start", methods=["POST"])
def start_bot():
    body = request.get_json()
    if not body.get("api_key", "").strip():
        return jsonify({"error": "API key required"}), 400
        
    if engine.start(body):
        return jsonify({"status": "started"})
    return jsonify({"error": "Already running"}), 400

@app.route("/api/stop", methods=["POST"])
def stop_bot():
    engine.stop()
    return jsonify({"status": "stopped"})

@app.route("/api/logs", methods=["GET"])
def stream_logs():
    def generate():
        yield "retry: 1000\n\n"
        while True:
            try:
                msg = engine.log_queue.get(timeout=15)
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({"api_key": engine.api_key})


if __name__ == "__main__":
    engine.load_config()
    engine.log("System: ultraexchange engine online  |  port 5678  |  math engine v2")
    app.run(host="127.0.0.1", port=5678, debug=False, threaded=True)