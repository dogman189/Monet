import customtkinter as ctk
import threading
import json
import ssl
import urllib.parse
import urllib.request
import certifi
import time
import statistics
from collections import deque

# --- CYBER-MINIMALIST THEME (Aanetra/HF Style) ---
COLORS = {
    "bg": "#09090B",           # Deep Onyx
    "sidebar": "#111113",      # Slightly lighter sidebar
    "card": "#18181B",         # Card background
    "border": "#27272A",       # Subtle zinc border
    "text_main": "#FAFAFA",    # Bright white
    "text_dim": "#A1A1AA",     # Muted gray
    "accent": "#6366F1",       # Indigo neon
    "success": "#10B981",      # Emerald Green
    "danger": "#EF4444",       # Rose Red
}

UI_FONT_BOLD = ("SF Pro Display", 16, "bold")
UI_FONT_REGULAR = ("SF Pro Text", 13)
UI_FONT_LARGE = ("SF Pro Display", 42, "bold")
LOG_FONT = ("SF Mono", 11)

ctk.set_appearance_mode("Dark")

class TradingBotGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ultraexchange")
        self.geometry("1150x750")
        self.configure(fg_color=COLORS["bg"])

        self.is_running = False
        self.active_api_key = ""
        self.symbol = "BTC"
        self.window_size = 20
        self.price_history = deque(maxlen=self.window_size)
        self.portfolio = {"USD": 10000.00, "holdings": {}}
        
        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLORS["sidebar"], border_width=1, border_color=COLORS["border"])
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="ultraexchange", font=("SF Pro Display", 28, "bold"), text_color=COLORS["accent"])
        self.logo_label.pack(pady=(40, 30), padx=20)

        # Input Grouping
        self.create_sidebar_input("API KEY", "entry_api_key", "", is_password=True)
        ctk.CTkLabel(self.sidebar, text="", height=10).pack() # Spacer
        self.create_sidebar_input("SYMBOL", "entry_symbol", "BTC")
        self.create_sidebar_input("INTERVAL (S)", "entry_interval", "300")
        self.create_sidebar_input("TRADE AMT ($)", "entry_trade", "500")
        self.create_sidebar_input("WALLET ($)", "entry_usd", "10000")

        # Buttons
        self.btn_start = ctk.CTkButton(self.sidebar, text="INITIALIZE", fg_color=COLORS["accent"], hover_color="#4f46e5", 
                                       font=UI_FONT_BOLD, height=45, corner_radius=8, command=self.start_bot)
        self.btn_start.pack(pady=(40, 10), padx=25, fill="x")
        
        self.btn_stop = ctk.CTkButton(self.sidebar, text="TERMINATE", fg_color="transparent", border_width=1, border_color=COLORS["danger"],
                                      text_color=COLORS["danger"], hover_color="#450a0a", font=UI_FONT_BOLD, height=45, 
                                      corner_radius=8, command=self.stop_bot, state="disabled")
        self.btn_stop.pack(pady=10, padx=25, fill="x")

        # --- MAIN PANEL ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        self.main_container.grid_columnconfigure((0, 1), weight=1)

        # Market Analysis Card
        self.market_card = ctk.CTkFrame(self.main_container, fg_color=COLORS["card"], border_width=1, border_color=COLORS["border"], corner_radius=12)
        self.market_card.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.market_card, text="MARKET INDEX", font=UI_FONT_BOLD, text_color=COLORS["text_dim"]).pack(pady=(15, 5))
        
        self.price_val = ctk.CTkLabel(self.market_card, text="$0.00", font=UI_FONT_LARGE, text_color=COLORS["success"])
        self.price_val.pack(pady=10)
        
        stats_frame = ctk.CTkFrame(self.market_card, fg_color="transparent")
        stats_frame.pack(pady=(0, 20))
        self.sma_val = ctk.CTkLabel(stats_frame, text="SMA: --", font=UI_FONT_REGULAR, text_color=COLORS["text_dim"])
        self.sma_val.pack()
        self.upper_val = ctk.CTkLabel(stats_frame, text="UPPER: --", font=UI_FONT_REGULAR, text_color=COLORS["danger"])
        self.upper_val.pack()
        self.lower_val = ctk.CTkLabel(stats_frame, text="LOWER: --", font=UI_FONT_REGULAR, text_color=COLORS["success"])
        self.lower_val.pack()

        # Portfolio Card
        self.port_card = ctk.CTkFrame(self.main_container, fg_color=COLORS["card"], border_width=1, border_color=COLORS["border"], corner_radius=12)
        self.port_card.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.port_card, text="LIQUIDITY", font=UI_FONT_BOLD, text_color=COLORS["text_dim"]).pack(pady=(15, 5))
        
        self.usd_val = ctk.CTkLabel(self.port_card, text="$0.00", font=("SF Pro Display", 26, "bold"), text_color=COLORS["text_main"])
        self.usd_val.pack(pady=10)
        
        self.crypto_val = ctk.CTkLabel(self.port_card, text="0.000000 UNITS", font=("SF Pro Display", 18), text_color=COLORS["accent"])
        self.crypto_val.pack(pady=5)
        
        self.status_val = ctk.CTkLabel(self.port_card, text="● IDLE", font=("SF Pro Text", 11, "bold"), text_color="#3F3F46")
        self.status_val.pack(side="bottom", pady=20)

        # Log Terminal
        self.textbox = ctk.CTkTextbox(self.main_container, fg_color="#050505", text_color=COLORS["text_dim"], 
                                      font=LOG_FONT, corner_radius=12, border_width=1, border_color=COLORS["border"])
        self.textbox.grid(row=1, column=0, columnspan=2, padx=10, pady=20, sticky="nsew")
        self.main_container.grid_rowconfigure(1, weight=1)

    def create_sidebar_input(self, label, attr, default, is_password=False):
        lbl = ctk.CTkLabel(self.sidebar, text=label, font=("SF Pro Text", 11, "bold"), text_color=COLORS["text_dim"])
        lbl.pack(pady=(15, 0), padx=25, anchor="w")
        entry = ctk.CTkEntry(self.sidebar, placeholder_text=default, show="*" if is_password else "",
                             fg_color="#050505", border_color=COLORS["border"], font=UI_FONT_REGULAR, height=35)
        entry.insert(0, default)
        entry.pack(pady=5, padx=25, fill="x")
        setattr(self, attr, entry)

    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        self.textbox.insert("end", f" {timestamp}  {message}\n")
        self.textbox.see("end")

    def fetch_price(self, symbol):
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = urllib.parse.urlencode({"symbol": symbol, "convert": "USD"})
        request = urllib.request.Request(f"{url}?{params}", headers={"X-CMC_PRO_API_KEY": self.active_api_key})
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            with urllib.request.urlopen(request, context=context) as response:
                data = json.load(response)
                return data["data"][symbol]["quote"]["USD"]["price"]
        except:
            self.log("⚠️ API AUTHENTICATION FAILED")
            self.stop_bot()
            return None

    def start_bot(self):
        key = self.entry_api_key.get().strip()
        if not key: return
        self.active_api_key = key
        self.is_running = True
        self.symbol = self.entry_symbol.get().upper()
        self.interval = int(self.entry_interval.get())
        self.trade_amt = float(self.entry_trade.get())
        self.portfolio["USD"] = float(self.entry_usd.get())
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_val.configure(text="● ACTIVE", text_color=COLORS["success"])
        self.log(f"CORE INITIALIZED: TRADING {self.symbol}")
        threading.Thread(target=self.bot_loop, daemon=True).start()

    def stop_bot(self):
        self.is_running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_val.configure(text="● TERMINATED", text_color=COLORS["danger"])

    def bot_loop(self):
        while self.is_running:
            price = self.fetch_price(self.symbol)
            if price:
                self.price_history.append(price)
                self.price_val.configure(text=f"${price:,.2f}")
                if len(self.price_history) >= self.window_size:
                    sma = statistics.mean(self.price_history)
                    std = statistics.stdev(self.price_history)
                    upper, lower = sma + (std * 2), sma - (std * 2)
                    self.sma_val.configure(text=f"SMA: ${sma:,.2f}")
                    self.upper_val.configure(text=f"UPPER: ${upper:,.2f}")
                    self.lower_val.configure(text=f"LOWER: ${lower:,.2f}")
                    if price <= lower: self.execute_trade("BUY", price)
                    elif price >= upper: self.execute_trade("SELL", price)
            self.usd_val.configure(text=f"${self.portfolio['USD']:,.2f}")
            self.crypto_val.configure(text=f"{self.portfolio['holdings'].get(self.symbol, 0):.6f} {self.symbol}")
            for _ in range(self.interval):
                if not self.is_running: break
                time.sleep(1)

    def execute_trade(self, side, price):
        if side == "BUY" and self.portfolio["USD"] >= self.trade_amt:
            bought = self.trade_amt / price
            self.portfolio["USD"] -= self.trade_amt
            self.portfolio["holdings"][self.symbol] = self.portfolio["holdings"].get(self.symbol, 0) + bought
            self.log(f"EXEC: BUY {bought:.4f} {self.symbol}")
        elif side == "SELL":
            owned = self.portfolio["holdings"].get(self.symbol, 0)
            if owned > 0:
                self.portfolio["USD"] += (owned * price)
                self.portfolio["holdings"][self.symbol] = 0
                self.log(f"EXEC: LIQUIDATE {self.symbol}")

if __name__ == "__main__":
    app = TradingBotGUI()
    app.mainloop()