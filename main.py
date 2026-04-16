import json
import ssl
import urllib.parse
import urllib.request
import certifi
import os
import os
from dotenv import load_dotenv

# This looks for a .env file and loads the variables
load_dotenv() 

# Now you can access it like a normal environment variable
API_KEY = os.getenv("CMC_API_KEY")

def fetch_crypto_data(api_key, limit=10):
    """Fetches the latest cryptocurrency listings from CoinMarketCap."""
    params = urllib.parse.urlencode({
        "start": "1",
        "limit": str(limit),
        "convert": "USD",
    })

    url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?{params}"
    
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": api_key,
        },
    )

    context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(request, context=context) as response:
            return json.load(response)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def analyze_and_display(data):
    """Parses the data, displays a formatted table, and prints a quick analysis."""
    if not data or "data" not in data:
        print("No valid data received.")
        return

    coins = data["data"]
    
    # --- 1. Display the Data Table ---
    print("\n" + "="*80)
    print(f"{'Crypto Market Analyzer (Top ' + str(len(coins)) + ')':^80}")
    print("="*80)
    
    # Table Header
    header = f"{'Name':<18} | {'Symbol':<8} | {'Price (USD)':<15} | {'24h Change':<12} | {'Market Cap'}"
    print(header)
    print("-" * 80)

    # Track metrics for the summary
    top_gainer = {"name": None, "change": -float('inf')}
    worst_performer = {"name": None, "change": float('inf')}
    total_market_cap = 0

    # Parse and print each coin
    for coin in coins:
        name = coin["name"][:17] # Truncate long names
        symbol = coin["symbol"]
        quote = coin["quote"]["USD"]
        
        price = quote["price"]
        change_24h = quote["percent_change_24h"]
        market_cap = quote["market_cap"]
        
        # Update analysis tracking
        total_market_cap += market_cap
        if change_24h > top_gainer["change"]:
            top_gainer = {"name": name, "change": change_24h}
        if change_24h < worst_performer["change"]:
            worst_performer = {"name": name, "change": change_24h}

        # Determine color/formatting for 24h change (optional terminal colors)
        change_str = f"{change_24h:+.2f}%"
        
        # Print row
        print(f"{name:<18} | {symbol:<8} | ${price:<14.4f} | {change_str:<12} | ${market_cap:,.0f}")

    # --- 2. Display the Quick Analysis ---
    print("-" * 80)
    print("QUICK ANALYSIS:")
    print(f"• Total Market Cap (Top {len(coins)}): ${total_market_cap:,.0f}")
    
    if top_gainer['name']:
        print(f"• 24h Top Gainer:        {top_gainer['name']} ({top_gainer['change']:+.2f}%)")
    if worst_performer['name']:
        print(f"• 24h Worst Performer:   {worst_performer['name']} ({worst_performer['change']:+.2f}%)")
    print("="*80 + "\n")

if __name__ == "__main__":
    # Best Practice: Set your API key in your terminal before running via:
    # export CMC_API_KEY="your_api_key_here"
    # Using your provided key as a fallback for testing purposes.
    API_KEY = os.environ.get("CMC_API_KEY", "33f4dcbb47004b329f7b4655e387edb2")
    
    print("Fetching latest market data...")
    market_data = fetch_crypto_data(API_KEY, limit=10)
    analyze_and_display(market_data)