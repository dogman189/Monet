"""
ultraexchange - Python Trading Engine
Flask REST + SSE backend. Electron spawns this process on startup.

Math Engine v2:
  - RSI confirmation filter (14-period)
  - Band re-entry signals (not just touches)
  - Percentage-based position sizing (20% per buy, 50% partial sells)
  - Bandwidth filter (skips BB squeeze periods)
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

RSI_PERIOD        = 14       # RSI lookback period
RSI_OVERSOLD      = 35       # RSI below this → valid buy zone
RSI_OVERBOUGHT    = 65       # RSI above this → valid sell zone
BB_WINDOW         = 20       # Bollinger Band SMA period
BB_STDDEV         = 2        # Standard deviations for bands
MIN_BANDWIDTH     = 0.02     # Min band width as fraction of SMA (filters squeezes)
BUY_RISK_PCT      = 0.20     # Fraction of USD balance to risk per buy
SELL_PCT          = 0.50     # Fraction of holdings to sell per signal
STOP_LOSS_PCT     = 0.07     # Stop-loss: sell if price drops this % below avg entry
TRADE_COOLDOWN    = 3        # Min intervals between any two trades

# ── STATE ─────────────────────────────────────────────────────────────────────

state = {
    "is_running":        False,
    "symbol":            "BTC",
    "interval":          300,
    "trade_amt":         500.0,   # kept for UI display, sizing is now % based
    "api_key":           "",
    "price":             0.0,
    "sma":               None,
    "upper":             None,
    "lower":             None,
    "rsi":               None,
    "bandwidth":         None,
    "portfolio":         {"USD": 10000.0, "holdings": {}},
    "window_size":       BB_WINDOW,
    # v2 signal state
    "avg_buy_price":     None,
    "was_below_lower":   False,
    "was_above_upper":   False,
    "last_trade_interval": 0,
    "interval_count":    0,
    "total_trades":      0,
    "total_buys":        0,
    "total_sells":       0,
    "stop_losses_hit":   0,
}

price_history = deque(maxlen=BB_WINDOW + RSI_PERIOD + 5)
log_queue     = queue.Queue()
bot_thread    = None
CONFIG_FILE   = "config.json"


# ── HELPERS ───────────────────────────────────────────────────────────────────

def log(message):
    timestamp = time.strftime('%H:%M:%S')
    entry = f"[{timestamp}]  {message}"
    log_queue.put(entry)
    print(entry)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if "api_key" in config:
                    state["api_key"] = config["api_key"]
        except Exception:
            log("System: Failed to load config.")


def save_config(key):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"api_key": key}, f)
    except Exception:
        log("System: Config save failed.")


# ── INDICATORS ────────────────────────────────────────────────────────────────

def compute_bollinger(prices):
    """Returns (sma, upper, lower) or (None, None, None) if insufficient data."""
    if len(prices) < BB_WINDOW:
        return None, None, None
    window = list(prices)[-BB_WINDOW:]
    sma    = statistics.mean(window)
    std    = statistics.stdev(window)
    return sma, sma + (std * BB_STDDEV), sma - (std * BB_STDDEV)


def compute_rsi(prices, period=RSI_PERIOD):
    """
    Classic Wilder RSI using simple average for seed calculation.
    Returns float 0-100, or None if insufficient data.
    """
    prices = list(prices)
    if len(prices) < period + 1:
        return None

    recent = prices[-(period + 1):]
    deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]

    gains  = [d for d in deltas if d > 0]
    losses = [abs(d) for d in deltas if d < 0]

    avg_gain = sum(gains)  / period if gains  else 0.0
    avg_loss = sum(losses) / period if losses else 1e-9

    rs  = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def compute_bandwidth(sma, upper, lower):
    """Band width as a fraction of SMA. Low value = squeeze."""
    if sma and sma != 0:
        return (upper - lower) / sma
    return None


# ── PRICE FEED ────────────────────────────────────────────────────────────────

def fetch_price(symbol, api_key):
    url    = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = urllib.parse.urlencode({"symbol": symbol, "convert": "USD"})
    req    = urllib.request.Request(
        f"{url}?{params}",
        headers={"X-CMC_PRO_API_KEY": api_key}
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, context=context) as response:
            data = json.load(response)
            return data["data"][symbol]["quote"]["USD"]["price"]
    except Exception as e:
        log(f"Error: Invalid API token or connection refused. ({e})")
        return None


# ── TRADE EXECUTION ───────────────────────────────────────────────────────────

def execute_trade(side, price, reason="signal"):
    symbol    = state["symbol"]
    portfolio = state["portfolio"]

    if side == "BUY":
        trade_amt = portfolio["USD"] * BUY_RISK_PCT
        if trade_amt < 1.0:
            log(f"Risk: Skipped BUY — insufficient USD balance (${portfolio['USD']:.2f})")
            return False

        bought = trade_amt / price
        portfolio["USD"] -= trade_amt

        prev_holdings = portfolio["holdings"].get(symbol, 0)
        prev_avg      = state["avg_buy_price"] or price
        portfolio["holdings"][symbol] = prev_holdings + bought

        # Weighted average entry price
        if prev_holdings > 0:
            state["avg_buy_price"] = (
                (prev_avg * prev_holdings + price * bought)
                / (prev_holdings + bought)
            )
        else:
            state["avg_buy_price"] = price

        state["total_trades"] += 1
        state["total_buys"]   += 1
        log(
            f"Execution: Filled BUY  {bought:.6f} {symbol}  @  ${price:,.2f}"
            f"  |  Risked: ${trade_amt:,.2f}  |  Reason: {reason}"
        )
        return True

    elif side == "SELL":
        owned = portfolio["holdings"].get(symbol, 0)
        if owned <= 0:
            log(f"Risk: Skipped SELL — no {symbol} holdings")
            return False

        sell_qty = owned * SELL_PCT
        proceeds = sell_qty * price
        portfolio["USD"] += proceeds
        portfolio["holdings"][symbol] = owned - sell_qty

        pnl_str = ""
        if state["avg_buy_price"]:
            pnl = (price - state["avg_buy_price"]) / state["avg_buy_price"] * 100
            pnl_str = f"  |  PnL: {pnl:+.2f}%"

        # Clear entry tracking if position is now negligible
        if portfolio["holdings"][symbol] < 1e-8:
            portfolio["holdings"][symbol] = 0
            state["avg_buy_price"] = None

        state["total_trades"] += 1
        state["total_sells"]  += 1
        log(
            f"Execution: Filled SELL {sell_qty:.6f} {symbol}  @  ${price:,.2f}"
            f"  |  Proceeds: ${proceeds:,.2f}{pnl_str}  |  Reason: {reason}"
        )
        return True

    return False


# ── BOT LOOP ──────────────────────────────────────────────────────────────────

def bot_loop():
    global price_history
    price_history.clear()

    # Reset all v2 signal state
    state["was_below_lower"]      = False
    state["was_above_upper"]      = False
    state["last_trade_interval"]  = 0
    state["interval_count"]       = 0
    state["avg_buy_price"]        = None
    state["total_trades"]         = 0
    state["total_buys"]           = 0
    state["total_sells"]          = 0
    state["stop_losses_hit"]      = 0

    log(f"System: Data stream initialized for {state['symbol']}")
    log(
        f"System: Engine v2 — RSI({RSI_PERIOD}) + BB({BB_WINDOW})  |  "
        f"Stop-loss: {STOP_LOSS_PCT*100:.0f}%  |  "
        f"Buy size: {BUY_RISK_PCT*100:.0f}% of USD  |  "
        f"Sell size: {SELL_PCT*100:.0f}% of holdings  |  "
        f"Cooldown: {TRADE_COOLDOWN} intervals"
    )

    while state["is_running"]:
        price = fetch_price(state["symbol"], state["api_key"])

        if price is None:
            state["is_running"] = False
            break

        state["price"] = price
        price_history.append(price)
        state["interval_count"] += 1

        prices    = list(price_history)
        sma, upper, lower = compute_bollinger(prices)
        rsi       = compute_rsi(prices)
        bandwidth = compute_bandwidth(sma, upper, lower) if sma else None

        state["sma"]       = sma
        state["upper"]     = upper
        state["lower"]     = lower
        state["rsi"]       = rsi
        state["bandwidth"] = bandwidth

        # ── Calibrating: not enough data yet ────────────────────────────────
        if sma is None or rsi is None:
            needed = max(BB_WINDOW, RSI_PERIOD + 1) - len(prices)
            log(f"Calibrating: ${price:,.2f}  —  {needed} more sample(s) needed")
            _interruptible_sleep()
            continue

        rsi_str = f"{rsi:.1f}"
        bw_str  = f"{bandwidth:.4f}" if bandwidth is not None else "?"
        log(
            f"Signal: Price=${price:,.2f}  SMA=${sma:,.2f}  "
            f"BB=[{lower:,.2f}, {upper:,.2f}]  RSI={rsi_str}  BW={bw_str}"
        )

        # ── Cooldown check ───────────────────────────────────────────────────
        intervals_since_trade = state["interval_count"] - state["last_trade_interval"]
        on_cooldown           = intervals_since_trade < TRADE_COOLDOWN

        if on_cooldown:
            log(
                f"Risk: Cooldown active — "
                f"{TRADE_COOLDOWN - intervals_since_trade} interval(s) remaining"
            )

        # ── Stop-loss (bypasses cooldown) ────────────────────────────────────
        avg_entry = state["avg_buy_price"]
        holdings  = state["portfolio"]["holdings"].get(state["symbol"], 0)

        if avg_entry and holdings > 0 and price < avg_entry * (1 - STOP_LOSS_PCT):
            loss_pct = (price - avg_entry) / avg_entry * 100
            log(
                f"Risk: Stop-loss triggered!  "
                f"Entry=${avg_entry:,.2f}  Current=${price:,.2f}  "
                f"Drawdown={loss_pct:+.2f}%"
            )
            if execute_trade("SELL", price, reason="stop-loss"):
                state["stop_losses_hit"]       += 1
                state["last_trade_interval"]    = state["interval_count"]
                state["was_above_upper"]        = False
                state["was_below_lower"]        = False
            _interruptible_sleep()
            continue

        # ── Bandwidth filter: skip squeeze periods ────────────────────────────
        if bandwidth is not None and bandwidth < MIN_BANDWIDTH:
            log(f"Signal: BB squeeze (BW={bw_str} < {MIN_BANDWIDTH}) — no trade")
            _interruptible_sleep()
            continue

        # ── Band re-entry tracking ────────────────────────────────────────────
        if price < lower:
            if not state["was_below_lower"]:
                log(
                    f"Signal: Broke below lower band (${lower:,.2f})  "
                    f"|  RSI={rsi_str} — watching for re-entry"
                )
            state["was_below_lower"] = True

        elif price > upper:
            if not state["was_above_upper"]:
                log(
                    f"Signal: Broke above upper band (${upper:,.2f})  "
                    f"|  RSI={rsi_str} — watching for re-entry"
                )
            state["was_above_upper"] = True

        # ── BUY: crossed back inside from below + RSI oversold ───────────────
        elif state["was_below_lower"] and price >= lower:
            state["was_below_lower"] = False
            log(f"Signal: Re-entered lower band  |  RSI={rsi_str}")

            if on_cooldown:
                log("Risk: BUY signal skipped — still on cooldown")
            elif rsi > RSI_OVERSOLD:
                log(
                    f"Filter: BUY skipped — RSI {rsi_str} not oversold "
                    f"(threshold < {RSI_OVERSOLD})"
                )
            else:
                if execute_trade("BUY", price, reason="BB re-entry + RSI oversold"):
                    state["last_trade_interval"] = state["interval_count"]

        # ── SELL: crossed back inside from above + RSI overbought ────────────
        elif state["was_above_upper"] and price <= upper:
            state["was_above_upper"] = False
            log(f"Signal: Re-entered upper band  |  RSI={rsi_str}")

            if on_cooldown:
                log("Risk: SELL signal skipped — still on cooldown")
            elif rsi < RSI_OVERBOUGHT:
                log(
                    f"Filter: SELL skipped — RSI {rsi_str} not overbought "
                    f"(threshold > {RSI_OVERBOUGHT})"
                )
            else:
                if execute_trade("SELL", price, reason="BB re-entry + RSI overbought"):
                    state["last_trade_interval"] = state["interval_count"]

        _interruptible_sleep()

    log(
        f"System: Data stream terminated.  "
        f"Trades: {state['total_trades']}  "
        f"(Buys: {state['total_buys']}  "
        f"Sells: {state['total_sells']}  "
        f"Stop-losses: {state['stop_losses_hit']})"
    )


def _interruptible_sleep():
    """Sleep for `interval` seconds but exit immediately if bot is stopped."""
    for _ in range(state["interval"]):
        if not state["is_running"]:
            break
        time.sleep(1)


# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    symbol = state["symbol"]
    return jsonify({
        "is_running":      state["is_running"],
        "symbol":          symbol,
        "price":           state["price"],
        "sma":             state["sma"],
        "upper":           state["upper"],
        "lower":           state["lower"],
        "rsi":             state["rsi"],
        "bandwidth":       state["bandwidth"],
        "usd":             state["portfolio"]["USD"],
        "holdings":        state["portfolio"]["holdings"].get(symbol, 0),
        "api_key":         state["api_key"],
        "interval":        state["interval"],
        "trade_amt":       state["trade_amt"],
        "wallet":          state["portfolio"]["USD"],
        "avg_buy_price":   state["avg_buy_price"],
        "total_trades":    state["total_trades"],
        "total_buys":      state["total_buys"],
        "total_sells":     state["total_sells"],
        "stop_losses_hit": state["stop_losses_hit"],
    })


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, price_history

    if state["is_running"]:
        return jsonify({"error": "Already running"}), 400

    body    = request.get_json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "API key required"}), 400

    save_config(api_key)
    state["api_key"]               = api_key
    state["symbol"]                = body.get("symbol", "BTC").upper()
    state["interval"]              = int(body.get("interval", 300))
    state["trade_amt"]             = float(body.get("trade_amt", 500))
    state["portfolio"]["USD"]      = float(body.get("wallet", 10000))
    state["portfolio"]["holdings"] = {}
    state["window_size"]           = BB_WINDOW
    state["price"]                 = 0.0
    state["sma"]                   = None
    state["upper"]                 = None
    state["lower"]                 = None
    state["rsi"]                   = None
    state["bandwidth"]             = None
    state["avg_buy_price"]         = None

    price_history = deque(maxlen=BB_WINDOW + RSI_PERIOD + 5)

    state["is_running"] = True
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    state["is_running"] = False
    return jsonify({"status": "stopped"})


@app.route("/api/logs", methods=["GET"])
def stream_logs():
    """Server-Sent Events endpoint for real-time log streaming."""
    def generate():
        yield "retry: 1000\n\n"
        while True:
            try:
                msg = log_queue.get(timeout=15)
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
    return jsonify({"api_key": state.get("api_key", "")})


if __name__ == "__main__":
    load_config()
    log("System: ultraexchange engine online  |  port 5678  |  math engine v2")
    app.run(host="127.0.0.1", port=5678, debug=False, threaded=True)