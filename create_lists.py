import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
BOT_DIR = os.path.join(PARENT_DIR, "RSI Bot")
MEGA_LISTS_DIR = os.path.join(BOT_DIR, "mega_lists")

os.makedirs(MEGA_LISTS_DIR, exist_ok=True)

listen = {
    "US Tech & KI": [
        {"symbol": "NVDA", "name": "NVIDIA"}, {"symbol": "AAPL", "name": "Apple"},
        {"symbol": "MSFT", "name": "Microsoft"}, {"symbol": "GOOGL", "name": "Alphabet"},
        {"symbol": "AMZN", "name": "Amazon"}, {"symbol": "META", "name": "Meta Platforms"},
        {"symbol": "AMD", "name": "Advanced Micro Devices"}, {"symbol": "TSM", "name": "Taiwan Semiconductor"},
        {"symbol": "ASML", "name": "ASML Holding"}, {"symbol": "AVGO", "name": "Broadcom"},
        {"symbol": "QCOM", "name": "Qualcomm"}, {"symbol": "ADBE", "name": "Adobe"},
        {"symbol": "CRM", "name": "Salesforce"}, {"symbol": "INTC", "name": "Intel"},
        {"symbol": "CSCO", "name": "Cisco Systems"}, {"symbol": "IBM", "name": "IBM"},
        {"symbol": "ORCL", "name": "Oracle"}, {"symbol": "NOW", "name": "ServiceNow"},
        {"symbol": "UBER", "name": "Uber"}, {"symbol": "PLTR", "name": "Palantir"},
        {"symbol": "SNOW", "name": "Snowflake"}, {"symbol": "DDOG", "name": "Datadog"},
        {"symbol": "NET", "name": "Cloudflare"}, {"symbol": "MDB", "name": "MongoDB"}
    ],
    "Halbleiter & Equipment": [
        {"symbol": "TXN", "name": "Texas Instruments"}, {"symbol": "AMAT", "name": "Applied Materials"},
        {"symbol": "LRCX", "name": "Lam Research"}, {"symbol": "KLAC", "name": "KLA Corp"},
        {"symbol": "MU", "name": "Micron Technology"}, {"symbol": "NXPI", "name": "NXP Semiconductors"},
        {"symbol": "MRVL", "name": "Marvell Technology"}, {"symbol": "ON", "name": "ON Semiconductor"},
        {"symbol": "MCHP", "name": "Microchip Technology"}, {"symbol": "MPWR", "name": "Monolithic Power"},
        {"symbol": "ARM", "name": "ARM Holdings"}
    ],
    "S&P 500 Heavyweights": [
        {"symbol": "BRK-B", "name": "Berkshire Hathaway"}, {"symbol": "LLY", "name": "Eli Lilly"},
        {"symbol": "JPM", "name": "JPMorgan Chase"}, {"symbol": "XOM", "name": "Exxon Mobil"},
        {"symbol": "UNH", "name": "UnitedHealth"}, {"symbol": "V", "name": "Visa"},
        {"symbol": "PG", "name": "Procter & Gamble"}, {"symbol": "MA", "name": "Mastercard"},
        {"symbol": "JNJ", "name": "Johnson & Johnson"}, {"symbol": "HD", "name": "Home Depot"},
        {"symbol": "MRK", "name": "Merck & Co"}, {"symbol": "CVX", "name": "Chevron"},
        {"symbol": "KO", "name": "Coca-Cola"}, {"symbol": "PEP", "name": "PepsiCo"},
        {"symbol": "COST", "name": "Costco"}, {"symbol": "WMT", "name": "Walmart"},
        {"symbol": "MCD", "name": "McDonald's"}, {"symbol": "ABBV", "name": "AbbVie"}
    ],
    "DAX 40 & MDAX Picks": [
        {"symbol": "SAP.DE", "name": "SAP SE"}, {"symbol": "SIE.DE", "name": "Siemens"},
        {"symbol": "ALV.DE", "name": "Allianz"}, {"symbol": "AIR.DE", "name": "Airbus"},
        {"symbol": "DTE.DE", "name": "Deutsche Telekom"}, {"symbol": "BMW.DE", "name": "BMW"},
        {"symbol": "MBG.DE", "name": "Mercedes-Benz"}, {"symbol": "VOW3.DE", "name": "Volkswagen"},
        {"symbol": "BAS.DE", "name": "BASF"}, {"symbol": "MUV2.DE", "name": "Munich Re"},
        {"symbol": "DHL.DE", "name": "DHL Group"}, {"symbol": "IFX.DE", "name": "Infineon"},
        {"symbol": "DBK.DE", "name": "Deutsche Bank"}, {"symbol": "RHM.DE", "name": "Rheinmetall"},
        {"symbol": "BAYN.DE", "name": "Bayer"}, {"symbol": "BEI.DE", "name": "Beiersdorf"},
        {"symbol": "MRK.DE", "name": "Merck KGaA"}, {"symbol": "ENR.DE", "name": "Siemens Energy"},
        {"symbol": "CBK.DE", "name": "Commerzbank"}, {"symbol": "SY1.DE", "name": "Symrise"},
        {"symbol": "MTX.DE", "name": "MTU Aero Engines"}, {"symbol": "LHA.DE", "name": "Lufthansa"},
        {"symbol": "FRA.DE", "name": "Fraport"}, {"symbol": "NOEJ.DE", "name": "Norma Group"}
    ],
    "SMI & Swiss Midcaps": [
        {"symbol": "NOVN.SW", "name": "Novartis"}, {"symbol": "ROG.SW", "name": "Roche"},
        {"symbol": "NESN.SW", "name": "Nestle"}, {"symbol": "UBSG.SW", "name": "UBS Group"},
        {"symbol": "ZURN.SW", "name": "Zurich Insurance"}, {"symbol": "SREN.SW", "name": "Swiss Re"},
        {"symbol": "SIK.SW", "name": "Sika AG"}, {"symbol": "LONN.SW", "name": "Lonza Group"},
        {"symbol": "CFR.SW", "name": "Richemont"}, {"symbol": "HOLN.SW", "name": "Holcim"},
        {"symbol": "ABBN.SW", "name": "ABB Ltd"}, {"symbol": "ALC.SW", "name": "Alcon"},
        {"symbol": "KNIN.SW", "name": "Kuehne + Nagel"}, {"symbol": "SGSN.SW", "name": "SGS"},
        {"symbol": "GEBN.SW", "name": "Geberit"}, {"symbol": "GIVN.SW", "name": "Givaudan"},
        {"symbol": "SOON.SW", "name": "Sonova"}, {"symbol": "VATN.SW", "name": "VAT Group"},
        {"symbol": "SCHP.SW", "name": "Schindler"}
    ],
    "Bauwesen & Landschaftsbau": [
        {"symbol": "CAT", "name": "Caterpillar"}, {"symbol": "DE", "name": "Deere & Company"},
        {"symbol": "TTC", "name": "The Toro Company"}, {"symbol": "HUSQ-B.ST", "name": "Husqvarna"},
        {"symbol": "URI", "name": "United Rentals"}, {"symbol": "VMC", "name": "Vulcan Materials"},
        {"symbol": "MLM", "name": "Martin Marietta"}, {"symbol": "BLDR", "name": "Builders FirstSource"},
        {"symbol": "PWR", "name": "Quanta Services"}, {"symbol": "JCI", "name": "Johnson Controls"},
        {"symbol": "FAST", "name": "Fastenal"}
    ],
    "Automobil & Zulieferer": [
        {"symbol": "TM", "name": "Toyota Motor"}, {"symbol": "F", "name": "Ford Motor"},
        {"symbol": "GM", "name": "General Motors"}, {"symbol": "RNO.PA", "name": "Renault"},
        {"symbol": "STLA", "name": "Stellantis"}, {"symbol": "CON.DE", "name": "Continental"},
        {"symbol": "SKF-B.ST", "name": "SKF"}, {"symbol": "BWA", "name": "BorgWarner"},
        {"symbol": "MGA", "name": "Magna International"}, {"symbol": "APTV", "name": "Aptiv"},
        {"symbol": "PII", "name": "Polaris"}, {"symbol": "HOG", "name": "Harley-Davidson"}
    ],
    "Krypto Top & Altcoins": [
        {"symbol": "BTC-USD", "name": "Bitcoin"}, {"symbol": "ETH-USD", "name": "Ethereum"},
        {"symbol": "SOL-USD", "name": "Solana"}, {"symbol": "BNB-USD", "name": "BNB"},
        {"symbol": "XRP-USD", "name": "XRP"}, {"symbol": "ADA-USD", "name": "Cardano"},
        {"symbol": "AVAX-USD", "name": "Avalanche"}, {"symbol": "DOGE-USD", "name": "Dogecoin"},
        {"symbol": "DOT-USD", "name": "Polkadot"}, {"symbol": "LINK-USD", "name": "Chainlink"},
        {"symbol": "MATIC-USD", "name": "Polygon"}, {"symbol": "KAS-USD", "name": "Kaspa"},
        {"symbol": "UNI-USD", "name": "Uniswap"}, {"symbol": "LTC-USD", "name": "Litecoin"},
        {"symbol": "NEAR-USD", "name": "NEAR Protocol"}, {"symbol": "ATOM-USD", "name": "Cosmos"},
        {"symbol": "APT-USD", "name": "Aptos"}, {"symbol": "INJ-USD", "name": "Injective"},
        {"symbol": "RNDR-USD", "name": "Render"}, {"symbol": "HBAR-USD", "name": "Hedera"}
    ],
    "Cybersecurity": [
        {"symbol": "CRWD", "name": "CrowdStrike"}, {"symbol": "OKTA", "name": "Okta"},
        {"symbol": "ZS", "name": "Zscaler"}, {"symbol": "CYBR", "name": "CyberArk"},
        {"symbol": "FTNT", "name": "Fortinet"}, {"symbol": "PANW", "name": "Palo Alto Networks"},
        {"symbol": "CHKP", "name": "Check Point"}, {"symbol": "S", "name": "SentinelOne"},
        {"symbol": "TENB", "name": "Tenable"}, {"symbol": "QLYS", "name": "Qualys"}
    ],
    "Defense & Aerospace": [
        {"symbol": "LMT", "name": "Lockheed Martin"}, {"symbol": "RTX", "name": "RTX Corporation"},
        {"symbol": "NOC", "name": "Northrop Grumman"}, {"symbol": "GD", "name": "General Dynamics"},
        {"symbol": "BA", "name": "Boeing"}, {"symbol": "HEI", "name": "Heico"},
        {"symbol": "TDG", "name": "TransDigm"}, {"symbol": "HII", "name": "Huntington Ingalls"},
        {"symbol": "LHX", "name": "L3Harris Technologies"}, {"symbol": "AXON", "name": "Axon Enterprise"}
    ],
    "Pharma & Biotech": [
        {"symbol": "CRSP", "name": "CRISPR Therapeutics"}, {"symbol": "PACB", "name": "Pacific Biosciences"},
        {"symbol": "VRTX", "name": "Vertex Pharmaceuticals"}, {"symbol": "REGN", "name": "Regeneron"},
        {"symbol": "GILD", "name": "Gilead Sciences"}, {"symbol": "AMGN", "name": "Amgen"},
        {"symbol": "BIIB", "name": "Biogen"}, {"symbol": "ISRG", "name": "Intuitive Surgical"},
        {"symbol": "PFE", "name": "Pfizer"}, {"symbol": "BMY", "name": "Bristol-Myers Squibb"},
        {"symbol": "AZN", "name": "AstraZeneca"}, {"symbol": "NVO", "name": "Novo Nordisk"},
        {"symbol": "ZTS", "name": "Zoetis"}, {"symbol": "IDXX", "name": "IDEXX Laboratories"}
    ],
    "Finanzen & Banken": [
        {"symbol": "GS", "name": "Goldman Sachs"}, {"symbol": "MS", "name": "Morgan Stanley"},
        {"symbol": "BAC", "name": "Bank of America"}, {"symbol": "C", "name": "Citigroup"},
        {"symbol": "WFC", "name": "Wells Fargo"}, {"symbol": "AXP", "name": "American Express"},
        {"symbol": "BLK", "name": "BlackRock"}, {"symbol": "BX", "name": "Blackstone"},
        {"symbol": "CME", "name": "CME Group"}, {"symbol": "SPGI", "name": "S&P Global"},
        {"symbol": "MCO", "name": "Moody's"}, {"symbol": "ICE", "name": "Intercontinental Exchange"}
    ],
    "Erneuerbare Energien & Utilities": [
        {"symbol": "NEE", "name": "NextEra Energy"}, {"symbol": "ENPH", "name": "Enphase Energy"},
        {"symbol": "FSLR", "name": "First Solar"}, {"symbol": "SEDG", "name": "SolarEdge"},
        {"symbol": "VWDRY", "name": "Vestas Wind Systems"}, {"symbol": "DUK", "name": "Duke Energy"},
        {"symbol": "SO", "name": "Southern Company"}, {"symbol": "D", "name": "Dominion Energy"},
        {"symbol": "SRE", "name": "Sempra"}, {"symbol": "EXC", "name": "Exelon"}
    ],
    "Öl, Gas & Rohstoffe": [
        {"symbol": "COP", "name": "ConocoPhillips"}, {"symbol": "SLB", "name": "Schlumberger"},
        {"symbol": "HAL", "name": "Halliburton"}, {"symbol": "BKR", "name": "Baker Hughes"},
        {"symbol": "EOG", "name": "EOG Resources"}, {"symbol": "PXD", "name": "Pioneer Natural Resources"},
        {"symbol": "FCX", "name": "Freeport-McMoRan"}, {"symbol": "NEM", "name": "Newmont"},
        {"symbol": "GOLD", "name": "Barrick Gold"}, {"symbol": "SCCO", "name": "Southern Copper"},
        {"symbol": "ALB", "name": "Albemarle"}, {"symbol": "SQM", "name": "Sociedad Quimica"}
    ],
    "Konsum, Handel & E-Commerce": [
        {"symbol": "TGT", "name": "Target"}, {"symbol": "DG", "name": "Dollar General"},
        {"symbol": "DLTR", "name": "Dollar Tree"}, {"symbol": "NKE", "name": "Nike"},
        {"symbol": "LULU", "name": "Lululemon"}, {"symbol": "SBUX", "name": "Starbucks"},
        {"symbol": "CMG", "name": "Chipotle"}, {"symbol": "MELI", "name": "MercadoLibre"},
        {"symbol": "SE", "name": "Sea Limited"}, {"symbol": "SHOP", "name": "Shopify"},
        {"symbol": "EBAY", "name": "eBay"}, {"symbol": "ETSY", "name": "Etsy"}
    ],
    "Reise, Transport & Freizeit": [
        {"symbol": "BKNG", "name": "Booking Holdings"}, {"symbol": "EXPE", "name": "Expedia"},
        {"symbol": "ABNB", "name": "Airbnb"}, {"symbol": "MAR", "name": "Marriott"},
        {"symbol": "HLT", "name": "Hilton"}, {"symbol": "DAL", "name": "Delta Air Lines"},
        {"symbol": "UAL", "name": "United Airlines"}, {"symbol": "UPS", "name": "United Parcel Service"},
        {"symbol": "FDX", "name": "FedEx"}, {"symbol": "UNP", "name": "Union Pacific"},
        {"symbol": "CSX", "name": "CSX Corp"}, {"symbol": "DIS", "name": "Walt Disney"}
    ],
    "China Tech & EV": [
        {"symbol": "BABA", "name": "Alibaba"}, {"symbol": "TCEHY", "name": "Tencent"},
        {"symbol": "JD", "name": "JD.com"}, {"symbol": "PDD", "name": "Pinduoduo"},
        {"symbol": "BIDU", "name": "Baidu"}, {"symbol": "NTES", "name": "NetEase"},
        {"symbol": "BYDDY", "name": "BYD Co"}, {"symbol": "LI", "name": "Li Auto"},
        {"symbol": "NIO", "name": "NIO Inc."}, {"symbol": "8XP.F", "name": "XPeng Inc."}
    ],
    "High Risk / Exoten": [
        {"symbol": "PLUG", "name": "Plug Power"}, {"symbol": "SPCE", "name": "Virgin Galactic"},
        {"symbol": "RIVN", "name": "Rivian Automotive"}, {"symbol": "LCID", "name": "Lucid Group"},
        {"symbol": "NKLA", "name": "Nikola"}, {"symbol": "MSTR", "name": "MicroStrategy"},
        {"symbol": "COIN", "name": "Coinbase"}, {"symbol": "MARA", "name": "Marathon Digital"},
        {"symbol": "RIOT", "name": "Riot Platforms"}, {"symbol": "CVNA", "name": "Carvana"}
    ]
}
# 1. Wir bauen ein leeres Dictionary für unsere Master-Liste
master_dict = {}

# 2. Wir iterieren durch alle Listen. Der Key (z.B. "DAX 40") wird automatisch zum Tag!
for tag, ticker_liste in listen.items():
    for ticker in ticker_liste:
        sym = ticker["symbol"]
        name = ticker["name"]
        
        # Wenn der Ticker schon existiert, hängen wir nur den neuen Tag an
        if sym in master_dict:
            if tag not in master_dict[sym]["tags"]:
                master_dict[sym]["tags"].append(tag)
        # Wenn er neu ist, legen wir ihn mit dem ersten Tag an
        else:
            master_dict[sym] = {
                "symbol": sym,
                "name": name,
                "tags": [tag]
            }

# 3. Wir wandeln das Dictionary in eine einfache Liste um
master_liste = list(master_dict.values())

# 4. Speichern der zusammengeführten master_universes.json
master_pfad = os.path.join(MEGA_LISTS_DIR, "master_universes.json")
with open(master_pfad, "w", encoding="utf-8") as f:
    json.dump(master_liste, f, indent=4)

print(f"✅ master_universes.json erfolgreich mit {len(master_liste)} eindeutigen Tickern erstellt!")
# Generierung der neuen Prop-Desk und Macro Universen
futures_cme = [
    {"symbol": "NQ=F", "name": "Nasdaq 100", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "ES=F", "name": "S&P 500", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "YM=F", "name": "Dow Jones", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "RTY=F", "name": "Russell 2000", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "GC=F", "name": "Gold", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "SI=F", "name": "Silber", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "CL=F", "name": "Crude Oil", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "NG=F", "name": "Erdgas", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]},
    {"symbol": "HG=F", "name": "Kupfer", "tags": ["Futures", "CME", "US-Indizes", "Rohstoffe"]}
]

forex_majors = [
    {"symbol": "EURUSD=X", "name": "EUR/USD", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "GBPUSD=X", "name": "GBP/USD", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "USDJPY=X", "name": "USD/JPY", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "AUDUSD=X", "name": "AUD/USD", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "USDCAD=X", "name": "USD/CAD", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "USDCHF=X", "name": "USD/CHF", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "EURJPY=X", "name": "EUR/JPY", "tags": ["Forex", "Währungen", "Makro"]},
    {"symbol": "DX-Y.NYB", "name": "Dollar Index", "tags": ["Forex", "Währungen", "Makro"]}
]

crypto_futures = [
    {"symbol": "BTC-USD", "name": "Bitcoin", "tags": ["Krypto", "Futures"]},
    {"symbol": "ETH-USD", "name": "Ethereum", "tags": ["Krypto", "Futures"]},
    {"symbol": "SOL-USD", "name": "Solana", "tags": ["Krypto", "Futures"]}
]

with open(os.path.join(MEGA_LISTS_DIR, "futures_cme.json"), "w", encoding="utf-8") as f:
    json.dump(futures_cme, f, indent=4)
with open(os.path.join(MEGA_LISTS_DIR, "forex_majors.json"), "w", encoding="utf-8") as f:
    json.dump(forex_majors, f, indent=4)
with open(os.path.join(MEGA_LISTS_DIR, "crypto_futures.json"), "w", encoding="utf-8") as f:
    json.dump(crypto_futures, f, indent=4)

print("✅ futures_cme.json, forex_majors.json und crypto_futures.json erfolgreich erstellt!")