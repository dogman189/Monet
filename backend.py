"""
ultraexchange - Python Trading Engine
Flask REST + SSE backend. Electron spawns this process on startup.
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

# --- STATE ---
state = {
    "is_running": False,
    "symbol": "BTC",
    "interval": 300,
    "trade_amt": 500.0,
    "api_key": "",
    "price": 0.0,
    "sma": None,
    "upper": None,
    "lower": None,
    "portfolio": {"USD": 10000.0, "holdings": {}},
    "window_size": 20,
}

price_history = deque(maxlen=20)
log_queue = queue.Queue()
bot_thread = None
CONFIG_FILE = "config.json"


# --- HELPERS ---
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


# --- TRADING MATH ENGINE ---
def fetch_price(symbol, api_key):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = urllib.parse.urlencode({"symbol": symbol, "convert": "USD"})
    req = urllib.request.Request(
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


def execute_trade(side, price):
    symbol = state["symbol"]
    trade_amt = state["trade_amt"]
    portfolio = state["portfolio"]

    if side == "BUY" and portfolio["USD"] >= trade_amt:
        bought = trade_amt / price
        portfolio["USD"] -= trade_amt
        portfolio["holdings"][symbol] = portfolio["holdings"].get(symbol, 0) + bought
        log(f"Execution: Filled BUY  {bought:.6f} {symbol}  @  ${price:,.2f}")

    elif side == "SELL":
        owned = portfolio["holdings"].get(symbol, 0)
        if owned > 0:
            proceeds = owned * price
            portfolio["USD"] += proceeds
            portfolio["holdings"][symbol] = 0
            log(f"Execution: Filled SELL {symbol}  |  Proceeds: ${proceeds:,.2f}")


def bot_loop():
    global price_history
    price_history.clear()
    log(f"System: Data stream initialized for {state['symbol']}")

    while state["is_running"]:
        price = fetch_price(state["symbol"], state["api_key"])

        if price is not None:
            state["price"] = price
            price_history.append(price)

            if len(price_history) >= state["window_size"]:
                sma = statistics.mean(price_history)
                std = statistics.stdev(price_history)
                upper = sma + (std * 2)
                lower = sma - (std * 2)

                state["sma"] = sma
                state["upper"] = upper
                state["lower"] = lower

                log(f"Signal: Price=${price:,.2f}  SMA=${sma:,.2f}  BB=[{lower:,.2f}, {upper:,.2f}]")

                if price <= lower:
                    execute_trade("BUY", price)
                elif price >= upper:
                    execute_trade("SELL", price)
            else:
                samples_needed = state["window_size"] - len(price_history)
                log(f"Calibrating: ${price:,.2f}  —  {samples_needed} more sample(s) needed")
        else:
            state["is_running"] = False
            break

        # Interruptible sleep
        for _ in range(state["interval"]):
            if not state["is_running"]:
                break
            time.sleep(1)

    log("System: Data stream terminated.")


# --- API ROUTES ---
@app.route("/api/status", methods=["GET"])
def get_status():
    symbol = state["symbol"]
    return jsonify({
        "is_running": state["is_running"],
        "symbol": symbol,
        "price": state["price"],
        "sma": state["sma"],
        "upper": state["upper"],
        "lower": state["lower"],
        "usd": state["portfolio"]["USD"],
        "holdings": state["portfolio"]["holdings"].get(symbol, 0),
        "api_key": state["api_key"],
        "interval": state["interval"],
        "trade_amt": state["trade_amt"],
        "wallet": state["portfolio"]["USD"],
    })


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_thread, price_history

    if state["is_running"]:
        return jsonify({"error": "Already running"}), 400

    body = request.get_json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "API key required"}), 400

    save_config(api_key)
    state["api_key"] = api_key
    state["symbol"] = body.get("symbol", "BTC").upper()
    state["interval"] = int(body.get("interval", 300))
    state["trade_amt"] = float(body.get("trade_amt", 500))
    state["portfolio"]["USD"] = float(body.get("wallet", 10000))
    state["portfolio"]["holdings"] = {}
    state["window_size"] = 20
    state["price"] = 0.0
    state["sma"] = None
    state["upper"] = None
    state["lower"] = None
    price_history = deque(maxlen=state["window_size"])

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

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({"api_key": state.get("api_key", "")})


if __name__ == "__main__":
    load_config()
    log("System: ultraexchange engine online  |  port 5678")
    app.run(host="127.0.0.1", port=5678, debug=False, threaded=True)