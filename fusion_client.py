import os
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

class BitpandaFusionClient:
    """REST Client für die Bitpanda Fusion / Pro API inkl. Fallback auf yfinance."""
    
    def __init__(self):
        self.api_key = os.getenv("BITPANDA_API_KEY")
        # Öffentliche Endpunkte benötigen oft keinen Key für einfache Ticker-Daten
        self.base_url = "https://api.exchange.bitpanda.com/public/v1" 

    def get_ticker_price(self, symbol):
        """Holt Preisdaten von Fusion, fällt bei Fehler oder Krypto-Mismatch auf yfinance zurück."""
        # Anpassung des Symbols für Bitpanda (z.B. BTC_EUR)
        bp_symbol = symbol.replace("-USD", "_USD").replace("-EUR", "_EUR")
        
        try:
            headers = {"Accept": "application/json"}
            url = f"{self.base_url}/market-ticker/{bp_symbol}"
            response = requests.get(url, headers=headers, timeout=3)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "symbol": symbol,
                    "last_price": float(data.get("last_price", 0.0)),
                    "best_bid": float(data.get("best_bid", 0.0)),
                    "best_ask": float(data.get("best_ask", 0.0)),
                    "source": "Bitpanda Fusion"
                }
        except Exception as e:
            pass # Silent Fail, Fallback greift

        # Fallback auf yfinance
        try:
            df = yf.download(symbol, period="1d", interval="1m", progress=False)
            if not df.empty and "Close" in df.columns:
                c_p = float(df["Close"].iloc[-1])
                return {
                    "symbol": symbol,
                    "last_price": c_p,
                    "best_bid": c_p, # Mock-Werte für yfinance
                    "best_ask": c_p,
                    "source": "yfinance (Fallback)"
                }
        except:
            pass
            
        return None