import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import ssl
import urllib.parse
import urllib.request
import certifi
import os
import time
import statistics
from collections import deque
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("CMC_API_KEY")

class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Quantitative Trading Bot (Dynamic Mode)")
        self.root.geometry("850x650")
        self.root.configure(bg="#1e1e2e")
        
        # --- DYNAMIC UI VARIABLES ---
        self.var_symbol = tk.StringVar(value="BTC")
        self.var_interval = tk.IntVar(value=300)
        self.var_trade_amt = tk.DoubleVar(value=500.00)
        self.var_start_usd = tk.DoubleVar(value=10000.00)
        
        # Bot State Variables
        self.is_running = False
        self.symbol = "BTC"
        self.window_size = 20
        self.trade_amount_usd = 500.00
        self.interval_seconds = 300 
        
        self.price_history = deque(maxlen=self.window_size)
        self.portfolio = {
            "USD": 10000.00,
            "holdings": {}
        }

        self.setup_ui()
        self.log_message("System initialized. Configure settings and press Start.")
        if not API_KEY:
            self.log_message("CRITICAL WARNING: CMC_API_KEY not found in .env!", "error")

    def setup_ui(self):
        """Builds the dynamic Tkinter interface."""
        style = ttk.Style()
        style.theme_use('clam')
        
        bg_color = "#1e1e2e"
        fg_color = "#cdd6f4"
        panel_bg = "#313244"
        entry_bg = "#11111b"
        
        self.root.configure(bg=bg_color)
        
        # --- HEADER ---
        header = tk.Label(self.root, text="Dynamic Algorithmic Trader", font=("Helvetica", 20, "bold"), bg=bg_color, fg=fg_color)
        header.pack(pady=15)

        # --- MAIN CONTAINER ---
        main_frame = tk.Frame(self.root, bg=bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # --- LEFT PANEL: SETTINGS & CONTROLS ---
        left_panel = tk.Frame(main_frame, bg=panel_bg, padx=15, pady=15)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        # Settings Form
        tk.Label(left_panel, text="Strategy Settings", font=("Helvetica", 14, "bold"), bg=panel_bg, fg=fg_color).pack(anchor="w", pady=(0, 10))
        
        form_frame = tk.Frame(left_panel, bg=panel_bg)
        form_frame.pack(fill=tk.X, pady=5)
        
        # Symbol
        tk.Label(form_frame, text="Coin Symbol:", bg=panel_bg, fg=fg_color).grid(row=0, column=0, sticky="w", pady=5)
        self.ent_symbol = tk.Entry(form_frame, textvariable=self.var_symbol, bg=entry_bg, fg=fg_color, width=12)
        self.ent_symbol.grid(row=0, column=1, sticky="e", pady=5)
        
        # Interval
        tk.Label(form_frame, text="Interval (sec):", bg=panel_bg, fg=fg_color).grid(row=1, column=0, sticky="w", pady=5)
        self.ent_interval = tk.Entry(form_frame, textvariable=self.var_interval, bg=entry_bg, fg=fg_color, width=12)
        self.ent_interval.grid(row=1, column=1, sticky="e", pady=5)
        
        # Trade Amount
        tk.Label(form_frame, text="Trade Amt ($):", bg=panel_bg, fg=fg_color).grid(row=2, column=0, sticky="w", pady=5)
        self.ent_trade = tk.Entry(form_frame, textvariable=self.var_trade_amt, bg=entry_bg, fg=fg_color, width=12)
        self.ent_trade.grid(row=2, column=1, sticky="e", pady=5)
        
        # Starting USD
        tk.Label(form_frame, text="Wallet USD ($):", bg=panel_bg, fg=fg_color).grid(row=3, column=0, sticky="w", pady=5)
        self.ent_usd = tk.Entry(form_frame, textvariable=self.var_start_usd, bg=entry_bg, fg=fg_color, width=12)
        self.ent_usd.grid(row=3, column=1, sticky="e", pady=5)

        tk.Label(left_panel, text="-"*30, bg=panel_bg, fg="#6c7086").pack(pady=15)

        # Controls
        self.btn_start = tk.Button(left_panel, text="START ALGORITHM", bg="#a6e3a1", fg="#11111b", font=("Helvetica", 12, "bold"), command=self.start_bot)
        self.btn_start.pack(fill=tk.X, pady=5)
        
        self.btn_stop = tk.Button(left_panel, text="STOP ALGORITHM", bg="#f38ba8", fg="#11111b", font=("Helvetica", 12, "bold"), command=self.stop_bot, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, pady=5)

        # --- CENTER PANEL: STATS ---
        center_panel = tk.Frame(main_frame, bg=panel_bg, padx=15, pady=15)
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(center_panel, text="Market Analysis", font=("Helvetica", 14, "bold"), bg=panel_bg, fg=fg_color).pack(anchor="w", pady=(0, 10))
        
        self.lbl_price = tk.Label(center_panel, text="Current Price: $0.00", font=("Helvetica", 12), bg=panel_bg, fg="#a6e3a1")
        self.lbl_price.pack(anchor="w", pady=5)
        
        self.lbl_upper = tk.Label(center_panel, text="Upper Band: $0.00", font=("Helvetica", 11), bg=panel_bg, fg="#f38ba8")
        self.lbl_upper.pack(anchor="w", pady=2)
        
        self.lbl_sma = tk.Label(center_panel, text="SMA (Mean): $0.00", font=("Helvetica", 11), bg=panel_bg, fg="#89b4fa")
        self.lbl_sma.pack(anchor="w", pady=2)
        
        self.lbl_lower = tk.Label(center_panel, text="Lower Band: $0.00", font=("Helvetica", 11), bg=panel_bg, fg="#a6e3a1")
        self.lbl_lower.pack(anchor="w", pady=2)

        # --- RIGHT PANEL: PORTFOLIO ---
        right_panel = tk.Frame(main_frame, bg=panel_bg, padx=15, pady=15)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)

        tk.Label(right_panel, text="Paper Portfolio", font=("Helvetica", 14, "bold"), bg=panel_bg, fg=fg_color).pack(anchor="w", pady=(0, 10))
        
        self.lbl_usd = tk.Label(right_panel, text=f"USD Balance: ${self.portfolio['USD']:,.2f}", font=("Helvetica", 12), bg=panel_bg, fg="#a6e3a1")
        self.lbl_usd.pack(anchor="w", pady=5)
        
        self.lbl_crypto = tk.Label(right_panel, text=f"Holdings: 0.000000", font=("Helvetica", 12), bg=panel_bg, fg="#f9e2af")
        self.lbl_crypto.pack(anchor="w", pady=2)
        
        self.lbl_status = tk.Label(right_panel, text="Status: IDLE", font=("Helvetica", 11, "italic"), bg=panel_bg, fg="#6c7086")
        self.lbl_status.pack(anchor="sw", side=tk.BOTTOM, pady=10)

        # --- BOTTOM PANEL: LOGS ---
        log_frame = tk.Frame(self.root, bg=bg_color, padx=20, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_box = scrolledtext.ScrolledText(log_frame, bg="#11111b", fg="#cdd6f4", font=("Consolas", 10), height=8)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.config(state=tk.DISABLED)

    def log_message(self, message, msg_type="info"):
        self.root.after(0, self._append_log, message, msg_type)

    def _append_log(self, message, msg_type):
        self.log_box.config(state=tk.NORMAL)
        timestamp = time.strftime('%H:%M:%S')
        self.log_box.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    def update_dashboard(self, price, sma=None, upper=None, lower=None):
        def update():
            self.lbl_price.config(text=f"Current Price: ${price:,.2f}")
            if sma and upper and lower:
                self.lbl_upper.config(text=f"Upper Band: ${upper:,.2f}")
                self.lbl_sma.config(text=f"SMA (Mean): ${sma:,.2f}")
                self.lbl_lower.config(text=f"Lower Band: ${lower:,.2f}")
            
            self.lbl_usd.config(text=f"USD Balance: ${self.portfolio['USD']:,.2f}")
            self.lbl_crypto.config(text=f"{self.symbol}: {self.portfolio['holdings'].get(self.symbol, 0):.6f}")
        
        self.root.after(0, update)

    def toggle_inputs(self, state):
        """Locks or unlocks the setting fields."""
        self.ent_symbol.config(state=state)
        self.ent_interval.config(state=state)
        self.ent_trade.config(state=state)
        self.ent_usd.config(state=state)

    def start_bot(self):
        if not API_KEY:
            self.log_message("Cannot start. API key missing.", "error")
            return
            
        try:
            # 1. Read Dynamics from UI
            new_symbol = self.var_symbol.get().strip().upper()
            self.interval_seconds = self.var_interval.get()
            self.trade_amount_usd = self.var_trade_amt.get()
            
            if self.interval_seconds < 10:
                messagebox.showwarning("Warning", "Intervals under 10 seconds may crash the API.")
                return

            # 2. Handle Symbol Change (Clear history if changed)
            if new_symbol != self.symbol:
                self.price_history.clear()
                self.log_message(f"Target changed to {new_symbol}. Mathematical baseline reset.")
            self.symbol = new_symbol
            
            # 3. Update Portfolio
            self.portfolio["USD"] = self.var_start_usd.get()
            if self.symbol not in self.portfolio["holdings"]:
                self.portfolio["holdings"][self.symbol] = 0.0

        except Exception as e:
            messagebox.showerror("Input Error", "Please ensure numbers are formatted correctly.")
            return

        # 4. Lock UI and Start
        self.is_running = True
        self.toggle_inputs(tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.lbl_status.config(text=f"Status: RUNNING ({self.symbol} @ {self.interval_seconds}s)", fg="#a6e3a1")
        self.log_message(f"Algorithm Started: Trading {self.symbol} in ${self.trade_amount_usd} chunks.")
        
        threading.Thread(target=self.bot_loop, daemon=True).start()

    def stop_bot(self):
        self.is_running = False
        self.toggle_inputs(tk.NORMAL)
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.lbl_status.config(text="Status: STOPPED", fg="#f38ba8")
        
        # Update the UI wallet amount so it reflects reality after stopping
        self.var_start_usd.set(self.portfolio['USD'])
        self.log_message("Algorithm Stopped by user. Settings unlocked.")

    def fetch_cmc_price(self):
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = urllib.parse.urlencode({"symbol": self.symbol, "convert": "USD"})
        request = urllib.request.Request(
            f"{url}?{params}",
            headers={"Accept": "application/json", "X-CMC_PRO_API_KEY": API_KEY},
        )
        context = ssl.create_default_context(cafile=certifi.where())

        try:
            with urllib.request.urlopen(request, context=context) as response:
                data = json.load(response)
                return data["data"][self.symbol]["quote"]["USD"]["price"]
        except Exception as e:
            self.log_message(f"API Error fetching {self.symbol}. Check symbol name.", "error")
            return None

    def execute_trade(self, action, price):
        if action == "BUY":
            if self.portfolio["USD"] >= self.trade_amount_usd:
                coins = self.trade_amount_usd / price
                self.portfolio["USD"] -= self.trade_amount_usd
                self.portfolio["holdings"][self.symbol] += coins
                self.log_message(f"🟢 BUY EXECUTED: {coins:.6f} {self.symbol} at ${price:,.2f}")
            else:
                self.log_message("❌ Buy Ignored: Insufficient USD.")

        elif action == "SELL":
            coins = self.portfolio["holdings"].get(self.symbol, 0)
            if coins > 0:
                usd_gained = coins * price
                self.portfolio["USD"] += usd_gained
                self.portfolio["holdings"][self.symbol] = 0
                self.log_message(f"🔴 SELL EXECUTED: Liquidated {coins:.6f} {self.symbol} for ${usd_gained:,.2f}")
            else:
                self.log_message("❌ Sell Ignored: No crypto to sell.")

    def bot_loop(self):
        while self.is_running:
            try:
                price = self.fetch_cmc_price()
                if not price:
                    time.sleep(10)
                    continue

                self.price_history.append(price)
                
                if len(self.price_history) < self.window_size:
                    self.log_message(f"Building baseline... ({len(self.price_history)}/{self.window_size} points)")
                    self.update_dashboard(price)
                else:
                    sma = statistics.mean(self.price_history)
                    stdev = statistics.stdev(self.price_history)
                    upper_band = sma + (stdev * 2)
                    lower_band = sma - (stdev * 2)
                    
                    self.update_dashboard(price, sma, upper_band, lower_band)
                    
                    if price <= lower_band:
                        self.log_message(f"Signal: OVERSOLD. Price broke lower band.", "buy")
                        self.execute_trade("BUY", price)
                    elif price >= upper_band:
                        self.log_message(f"Signal: OVERBOUGHT. Price broke upper band.", "sell")
                        self.execute_trade("SELL", price)
                    else:
                        self.log_message(f"Holding. Price is within normal range.")

                for _ in range(self.interval_seconds):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                self.log_message(f"System Error: {e}", "error")
                time.sleep(10)

if __name__ == "__main__":
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.mainloop()