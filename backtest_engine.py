#region IMPORTS
import os
import argparse
import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import csv
#endregion

POINT_VALUES = {
    "MNQ": 2.0, "NQ=F": 2.0,
    "MES": 5.0, "ES=F": 5.0,
    "MYM": 0.5, "YM=F": 0.5,
    "M2K": 5.0, "RTY=F": 5.0,
    "MGC": 10.0, "GC=F": 10.0,
    "SIL": 10.0, "SI=F": 10.0,
    "MCL": 10.0, "CL=F": 10.0,
    "QG": 2500.0, "NG=F": 2500.0,
    "MHG": 250.0, "HG=F": 250.0,
    "EURUSD=X": 100000.0, "GBPUSD=X": 100000.0, "USDJPY=X": 100000.0,
    "AUDUSD=X": 100000.0, "USDCAD=X": 100000.0, "USDCHF=X": 100000.0,
    "EURJPY=X": 100000.0, "DX-Y.NYB": 1000.0
}

def get_asset_specs(ticker: str):
    pt_val = POINT_VALUES.get(ticker, 1.0)
    sym_u = str(ticker).upper()
    if "=F" in sym_u:
        a_type = "future"
    elif "=X" in sym_u or sym_u == "DX-Y.NYB":
        a_type = "forex"
    else:
        a_type = "stock_crypto"
    return pt_val, a_type

#region DATA & INDICATORS
def get_bars_per_day(interval: str, asset_type: str) -> int:
    """Berechnet die Kerzenanzahl pro Tag abhängig von Intervall und Anlageklasse."""
    if interval == "15m":
        return 28 if asset_type == "future" else (96 if asset_type in ["forex", "stock_crypto"] else 26)
    elif interval == "1h":
        return 7 if asset_type in ["future", "stock_crypto"] else 24
    elif interval == "4h":
        return 6
    return 1  # 1d Standard

def is_rth_bar(timestamp, ticker: str) -> bool:
    """Prüft robust über verschiedene Zeitzonen-Darstellungen, ob sich die Kerze in der Haupt-Session (RTH) befindet."""
    sym_u = str(ticker).upper()
    if "=F" not in sym_u:
        return True
    try:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = ts.tz_convert("Europe/Berlin")
        
        hour = ts.hour
        minute = ts.minute
        t_min = hour * 60 + minute

        metals = ["GC=F", "MGC", "SI=F", "SIL", "HG=F", "MHG"]
        energy = ["CL=F", "MCL", "NG=F", "QG"]
        us_indices = ["NQ=F", "ES=F", "YM=F", "RTY=F", "MNQ", "MES", "MYM", "M2K"]

        if any(m in sym_u for m in metals):
            return 540 <= t_min <= 1080
        elif any(e in sym_u for e in energy):
            return 870 <= t_min <= 1230
        elif any(u in sym_u for u in us_indices):
            return 930 <= t_min <= 1230
        else:
            return True
    except Exception as e:
        return False

def get_benchmark_data(ticker, start_date, end_date, interval="1d"):
    # 1. Sofortiger Abbruch für Forex (Ressourcenschonung & Crash-Prävention)
    if str(ticker).upper().endswith("=X") or str(ticker).upper() == "DX-Y.NYB":
        return pd.DataFrame()
        
    tech_tickers = ["NFLX", "NVDA", "PLTR", "XPEV", "PANW", "CRWD", "AAPL", "MSFT", "GOOGL", "META", "TSLA", "AMZN"]
    crypto_tickers = ["BTC-USD", "ETH-USD", "SOL-USD", "KAS-USD"]
    
    if ticker.upper() in tech_tickers:
        bench_symbol = "^NDX"
    elif ticker.upper() in crypto_tickers:
        bench_symbol = "BTC-USD"
    else:
        bench_symbol = "^GSPC"
        
    try:
        fetch_interval = "1h" if interval == "4h" else interval
        bench_df = yf.download(bench_symbol, start=start_date, end=end_date, interval=fetch_interval, progress=False)
        
        # 2. Absicherung gegen fehlerhafte oder leere Downloads
        if bench_df is None or bench_df.empty:
            return pd.DataFrame()
            
        if isinstance(bench_df.columns, pd.MultiIndex):
            bench_df.columns = bench_df.columns.get_level_values(0)
            
        if interval == "4h":
            agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
            if 'Volume' in bench_df.columns: agg_dict['Volume'] = 'sum'
            bench_df = bench_df.resample('4h').agg(agg_dict).dropna(subset=['Close'])
            
        bench_df = bench_df.dropna(subset=["Close"]).copy()
        
        if bench_df.empty:
            return pd.DataFrame()
            
        bench_df["EMA_200"] = bench_df["Close"].ewm(span=200, adjust=False).mean()
        return bench_df
        
    except Exception as e:
        print(f"⚠️ Benchmark-Download fehlgeschlagen für {ticker} ({e}). Setze Makro-Filter aus.")
        return pd.DataFrame()

def calculate_indicators(df, bench_df, vol_proxy="atr_ratio", vol_proxy_mult=1.0):
    if len(df) < 200: return df
    df = df.copy()
    
    close = df["Close"]
    
    # --- Wilder's RSI ---
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # --- Gleitende Durchschnitte ---
    df["EMA_20"] = close.ewm(span=20, adjust=False).mean()
    df["EMA_200"] = close.ewm(span=200, adjust=False).mean()

    # --- MACD ---
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # --- Volumen & Volatility Activity Proxy ---
    has_valid_volume = False
    if "Volume" in df.columns:
        df["Vol_SMA_20"] = df["Volume"].rolling(window=20).mean()
        if df["Vol_SMA_20"].max() > 0:
            has_valid_volume = True
            
    if not has_valid_volume:
        df["Vol_SMA_20"] = 0
        df["Volume"] = 0
        
    # Synthetischer Activity Proxy (saubere Trennung von echtem Volumen)
    tr = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
    df['True_Range'] = tr
    
    if vol_proxy == "raw_tr":
        df['Activity_Proxy'] = tr * vol_proxy_mult
    elif vol_proxy == "median_ratio":
        tr_median = tr.rolling(window=20).median().replace(0, np.nan)
        df['Activity_Proxy'] = (tr / tr_median) * vol_proxy_mult
    else: # atr_ratio (Standard)
        atr_14 = tr.rolling(window=14).mean().replace(0, np.nan)
        df['Activity_Proxy'] = (tr / atr_14) * vol_proxy_mult

    df['Activity_Proxy_SMA_20'] = df['Activity_Proxy'].rolling(window=20).mean()
    df['Has_Valid_Volume'] = has_valid_volume

    # --- Bollinger Bänder ---
    sma_20 = close.rolling(window=20).mean()
    std_20 = close.rolling(window=20).std()
    df["BB_lower"] = sma_20 - (std_20 * 2)
    df["BB_upper"] = sma_20 + (std_20 * 2)
    df["Z_Score"] = (close - sma_20) / std_20

    # --- ATR & Keltner Kanal ---
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - close.shift()).abs()
    low_close = (df["Low"] - close.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()
    df["KC_lower"] = df["EMA_20"] - (2 * df["ATR"])
    df["KC_upper"] = df["EMA_20"] + (2 * df["ATR"])
    
    # --- Relative Stärke & Makro Filter ---
    if not bench_df.empty:
        df["Bench_Close"] = bench_df["Close"].reindex(df.index).ffill().bfill()
        df["Bench_EMA_200"] = bench_df["EMA_200"].reindex(df.index).ffill().bfill()
        df["RS_20d"] = (df["Close"] / df["Close"].shift(20)) / (df["Bench_Close"] / df["Bench_Close"].shift(20))
    else:
        df["Bench_Close"] = 0
        df["Bench_EMA_200"] = 0
        df["RS_20d"] = 1.0
        
    return df
#endregion

#region TRADE LOGIC
def run_simulation(df, ticker, fee_rate, slippage, min_score, start_idx, train_end_idx, test_end_idx, account_size, risk_pct, trailing_stop_mode="active", window_name="", exit_profile="prop_guard", allowed_direction="both", daily_loss=None):
    trades = []
    in_trade = False
    cooldown = 0
    entry_price = initial_sl = current_sl = tp = initial_risk = days_in_trade = max_days = highest_high = lowest_low = 0
    trade_type = ""
    direction = "Long"
    pos_size = 0.0
    planned_risk = 0.0
    scaled_out = False
    account_balance = account_size
    pt_val, a_type = get_asset_specs(ticker)
    if fee_rate >= 0.001:
        if a_type == "forex":
            fee_rate, slippage = 0.00003, 0.00002
        elif a_type == "future":
            fee_rate, slippage = 0.00005, 0.0001
    interval = "1d"
    if len(df) > 1:
        min_td = min([df.index[i] - df.index[i-1] for i in range(1, min(10, len(df)))])
        if min_td.total_seconds() <= 900: interval = "15m"
        elif min_td.total_seconds() <= 3600: interval = "1h"
        elif min_td.total_seconds() <= 14400: interval = "4h"
    b_per_day = get_bars_per_day(interval, a_type)
    t_exit_mode = "PROP_DEFENSIVE"
    
    for i in range(start_idx + 1, test_end_idx):
        prev_bar = df.iloc[i-1] 
        curr_bar = df.iloc[i]   
        is_oos = i >= train_end_idx
        bar_date = curr_bar.name.date() if hasattr(curr_bar.name, 'date') else curr_bar.name
        if 'current_trade_date' not in locals() or current_trade_date != bar_date:
            current_trade_date = bar_date
            daily_loss_tracker = 0.0
            
        loss_threshold = (daily_loss * 0.20) if daily_loss and daily_loss > 0 else (account_balance * (risk_pct / 100.0) * 2.0)
        
        # --- A. VERWALTUNG OFFENER TRADES ---
        if in_trade:
            is_setup_b_trade = "Trend" in trade_type
            dir_m = 1 if direction == "Long" else -1
            force_eod_close = False
            if interval in ["15m", "1h"] and "=F" in str(ticker).upper() and exit_profile == "apex_lock":
                bar_time = curr_bar.name.tz_convert('Europe/Berlin') if hasattr(curr_bar.name, 'tzinfo') and curr_bar.name.tzinfo else curr_bar.name
                if hasattr(bar_time, 'time'):
                    h, m = bar_time.hour, bar_time.minute
                    if h > 22 or (h == 22 and m >= 45):
                        force_eod_close = True
            
            if t_exit_mode == "HOME_RUN_TREND" or (t_exit_mode == "FTMO_SWING" and is_setup_b_trade):
                if dir_m == 1 and curr_bar["High"] > highest_high:
                    highest_high = curr_bar["High"]
                    days_in_trade = 0
                elif dir_m == -1 and curr_bar["Low"] < lowest_low:
                    lowest_low = curr_bar["Low"]
                    days_in_trade = 0

            days_in_trade += 1
            exit_price = 0
            exit_reason = ""
            
            if force_eod_close:
                exit_price = curr_bar["Close"]
                exit_reason = "EOD_Close"
            elif dir_m == 1:
                if curr_bar["Low"] <= current_sl:
                    exit_price = current_sl
                    exit_reason = "Trailing_SL" if current_sl > initial_sl else "Initial_SL"
                elif t_exit_mode != "HOME_RUN_TREND" and not (t_exit_mode == "FTMO_SWING" and is_setup_b_trade) and curr_bar["High"] >= tp:
                    exit_price = tp
                    exit_reason = "Take_Profit"
            else:
                if curr_bar["High"] >= current_sl:
                    exit_price = current_sl
                    exit_reason = "Trailing_SL" if current_sl < initial_sl else "Initial_SL"
                elif t_exit_mode != "HOME_RUN_TREND" and not (t_exit_mode == "FTMO_SWING" and is_setup_b_trade) and curr_bar["Low"] <= tp:
                    exit_price = tp
                    exit_reason = "Take_Profit"
                    
            if days_in_trade >= max_days and exit_price == 0:
                exit_price = curr_bar["Close"]
                exit_reason = "Time-Stop"
                    
            if exit_price > 0:
                actual_exit = exit_price * (1 - slippage*dir_m) if "SL" in exit_reason or "Time-Stop" in exit_reason else exit_price
                
                pnl = (actual_exit - entry_price) * pos_size * pt_val * dir_m
                fees = (entry_price * pos_size * pt_val + actual_exit * pos_size * pt_val) * fee_rate
                if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                    pnl /= actual_exit
                    fees /= actual_exit
                    
                net_pnl = pnl - fees
                
                account_balance += net_pnl
                if net_pnl < 0:
                    daily_loss_tracker += abs(net_pnl)
                
                trades.append({
                    "ticker": ticker, "entry_date": entry_date, "exit_date": curr_bar.name.strftime("%d/%m/%Y"),
                    "type": trade_type, "entry_price": entry_price, "exit_price": actual_exit,
                    "reason": exit_reason, "net_pnl": net_pnl, 
                    "r_multiple": net_pnl / planned_risk if planned_risk > 0 else 0,
                    "is_oos": is_oos, "window": window_name, "exit_mode": t_exit_mode
                })
                in_trade = False
                cooldown = 2
                continue
                
            # --- Dynamisches Trade-Management ---
            if trailing_stop_mode == "active":
                current_high = curr_bar["High"]
                current_low = curr_bar["Low"]
                atr_val = prev_bar["ATR"]
                ema20_val = prev_bar["EMA_20"]
                
                fees_rest = (entry_price * pos_size * pt_val) * fee_rate
                exit_fees_est = (entry_price * pos_size * pt_val) * fee_rate
                fees_per_unit = (fees_rest + exit_fees_est) / (pos_size * pt_val) if pos_size > 0 else 0
                net_be = entry_price + fees_per_unit if dir_m == 1 else entry_price - fees_per_unit
                
                sym_str = str(ticker).upper()
                is_crypto = any(sym_str.endswith(ext) for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL"])
                
                open_profit = (current_high - entry_price) if dir_m == 1 else (entry_price - current_low)
                current_r = open_profit / initial_risk if initial_risk > 0 else 0

                if is_crypto:
                    if current_r >= 1.5:
                        if not scaled_out and t_exit_mode != "HOME_RUN_TREND":
                            exit_price_scale = entry_price + (1.5 * initial_risk * dir_m)
                            actual_exit = exit_price_scale * (1 - slippage*dir_m)
                            scale_size = pos_size * 0.5
                            pnl_scale = (actual_exit - entry_price) * scale_size * pt_val * dir_m
                            fees_scale = (entry_price * scale_size * pt_val + actual_exit * scale_size * pt_val) * fee_rate
                            net_pnl_scale = pnl_scale - fees_scale
                            account_balance += net_pnl_scale
                            trades.append({
                                "ticker": ticker, "entry_date": entry_date, "exit_date": curr_bar.name.strftime("%d/%m/%Y"),
                                "type": trade_type + " (Krypto-Scale 50%)", "entry_price": entry_price, "exit_price": actual_exit,
                                "reason": "Scale-Out +1.5R", "net_pnl": net_pnl_scale, 
                                "r_multiple": net_pnl_scale / (planned_risk * 0.5) if planned_risk > 0 else 0,
                                "is_oos": is_oos, "window": window_name, "exit_mode": t_exit_mode
                            })
                            pos_size -= scale_size
                            scaled_out = True
                            current_sl = max(current_sl, net_be) if dir_m == 1 else min(current_sl, net_be)
                        
                        trend_trail = current_high - (3.5 * atr_val) if dir_m == 1 else current_low + (3.5 * atr_val)
                        if ema20_val > 0:
                            if dir_m == 1: trend_trail = max(trend_trail, ema20_val * 0.98)
                            else: trend_trail = min(trend_trail, ema20_val * 1.02)
                        current_sl = max(current_sl, trend_trail) if dir_m == 1 else min(current_sl, trend_trail)
                        
                elif t_exit_mode == "TARGET_LOCKED":
                    if current_r >= 1.0:
                        peak_protection = entry_price + (open_profit * 0.80) * dir_m
                        current_sl = max(current_sl, net_be, peak_protection) if dir_m == 1 else min(current_sl, net_be, peak_protection)            
                
                elif t_exit_mode == "PROP_DEFENSIVE":
                    if current_r >= 1.0 and not scaled_out:
                        exit_price_scale = entry_price + (1.0 * initial_risk * dir_m)
                        actual_exit = exit_price_scale * (1 - slippage*dir_m)
                        scale_size = pos_size * 0.5
                        pnl_scale = (actual_exit - entry_price) * scale_size * pt_val * dir_m
                        fees_scale = (entry_price * scale_size * pt_val + actual_exit * scale_size * pt_val) * fee_rate
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": entry_date, "exit_date": curr_bar.name.strftime("%d/%m/%Y"),
                            "type": trade_type + " (Scale-Out 50%)", "entry_price": entry_price, "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (planned_risk * 0.5) if planned_risk > 0 else 0,
                            "is_oos": is_oos, "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos_size -= scale_size
                        scaled_out = True
                        current_sl = max(current_sl, net_be) if dir_m == 1 else min(current_sl, net_be)
                    if current_r >= 1.5:
                        new_trail = current_high - (2.0 * atr_val) if dir_m == 1 else current_low + (2.0 * atr_val)
                        current_sl = max(current_sl, new_trail) if dir_m == 1 else min(current_sl, new_trail)
                        
                elif t_exit_mode == "ALPHA_CASHFLOW":
                    tp_distance = abs(tp - entry_price)
                    tight_trigger_profit = 0.9 * tp_distance
                    
                    if current_r >= 1.0 and not scaled_out:
                        exit_price_scale = entry_price + (1.0 * initial_risk * dir_m)
                        actual_exit = exit_price_scale * (1 - slippage*dir_m)
                        scale_size = pos_size * 0.3
                        pnl_scale = (actual_exit - entry_price) * scale_size * pt_val * dir_m
                        fees_scale = (entry_price * scale_size * pt_val + actual_exit * scale_size * pt_val) * fee_rate
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": entry_date, "exit_date": curr_bar.name.strftime("%d/%m/%Y"),
                            "type": trade_type + " (Scale-Out 30%)", "entry_price": entry_price, "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (planned_risk * 0.3) if planned_risk > 0 else 0,
                            "is_oos": is_oos, "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos_size -= scale_size
                        scaled_out = True
                        current_sl = max(current_sl, net_be) if dir_m == 1 else min(current_sl, net_be)
                        
                    if current_r >= 1.5:
                        new_target_sl = net_be
                        if open_profit >= tight_trigger_profit:
                            trail_base = current_high - (0.5 * atr_val) if dir_m == 1 else current_low + (0.5 * atr_val)
                        else:
                            trail_base = current_high - (2.5 * atr_val) if dir_m == 1 else current_low + (2.5 * atr_val)
                        
                        new_target_sl = max(new_target_sl, trail_base) if dir_m == 1 else min(new_target_sl, trail_base)
                        
                        if current_r >= 6.0:
                            peak_floor = entry_price + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = entry_price + (2.5 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = entry_price + (1.0 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                            
                        current_sl = max(current_sl, new_target_sl) if dir_m == 1 else min(current_sl, new_target_sl)
                        
                elif t_exit_mode == "FTMO_SWING":
                    if current_r >= 1.0 and not scaled_out:
                        exit_price_scale = entry_price + (1.0 * initial_risk * dir_m)
                        actual_exit = exit_price_scale * (1 - slippage*dir_m)
                        scale_size = pos_size * 0.3
                        pnl_scale = (actual_exit - entry_price) * scale_size * pt_val * dir_m
                        fees_scale = (entry_price * scale_size * pt_val + actual_exit * scale_size * pt_val) * fee_rate
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": entry_date, "exit_date": curr_bar.name.strftime("%d/%m/%Y"),
                            "type": trade_type + " (Scale-Out 30%)", "entry_price": entry_price, "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (planned_risk * 0.3) if planned_risk > 0 else 0,
                            "is_oos": is_oos, "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos_size -= scale_size
                        scaled_out = True
                        current_sl = max(current_sl, net_be) if dir_m == 1 else min(current_sl, net_be)
                        
                    if current_r >= 1.5:
                        trail_mult = 2.5 if is_setup_b_trade else 2.0
                        trail_base = current_high - (trail_mult * atr_val) if dir_m == 1 else current_low + (trail_mult * atr_val)
                        if is_setup_b_trade and ema20_val > 0:
                            trail_base = max(trail_base, ema20_val * 0.98) if dir_m == 1 else min(trail_base, ema20_val * 1.02)
                        
                        new_target_sl = max(net_be, trail_base) if dir_m == 1 else min(net_be, trail_base)
                        
                        if current_r >= 6.0:
                            peak_floor = entry_price + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = entry_price + (2.5 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = entry_price + (1.0 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                            
                        current_sl = max(current_sl, new_target_sl) if dir_m == 1 else min(current_sl, new_target_sl)

                elif t_exit_mode == "HOME_RUN_TREND":
                    if current_r >= 1.5:
                        trend_trail = current_high - (3.0 * atr_val) if dir_m == 1 else current_low + (3.0 * atr_val)
                        if ema20_val > 0:
                            trend_trail = max(trend_trail, ema20_val * 0.98) if dir_m == 1 else min(trend_trail, ema20_val * 1.02)
                            
                        new_target_sl = max(net_be, trend_trail) if dir_m == 1 else min(net_be, trend_trail)
                        if current_r >= 6.0:
                            peak_floor = entry_price + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = entry_price + (2.5 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = entry_price + (1.0 * initial_risk * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                        current_sl = max(current_sl, new_target_sl) if dir_m == 1 else min(current_sl, new_target_sl)
            continue
            
        # --- B. SIGNALGENERIERUNG AN BAR t-1 ---
        if cooldown > 0:
                cooldown -= 1
                continue
        if daily_loss_tracker >= loss_threshold:
            continue  # Daily Circuit Breaker aktiv: Keine neuen Trades für den Rest des Tages
        if ticker.endswith("=F") and interval in ["15m", "1h", "4h"]:
            if not is_rth_bar(curr_bar.name, ticker):
                continue  # Keine neuen Trades außerhalb der asset-spezifischen Hauptsession!
                
        # Forex Session-Filter
        if (ticker.endswith("=X") or ticker == "DX-Y.NYB") and interval in ["15m", "1h", "4h"]:
            bar_time = curr_bar.name.tz_convert('Europe/Berlin') if hasattr(curr_bar.name, 'tzinfo') and curr_bar.name.tzinfo else curr_bar.name
            hour = bar_time.hour
            minute = bar_time.minute
            
            if ticker == "EURUSD=X":
                # London/NY Overlap für EURUSD (13:00 - 18:00 MEZ, keine neuen Trades ab 18:00)
                if hour < 13 or hour >= 18:
                    continue
            else:
                # Standard Forex Session (08:00 - 20:30 Uhr MEZ)
                if hour < 8 or hour > 20 or (hour == 20 and minute > 30):
                    continue
            
        setup = evaluate_setup_and_score(df.iloc[max(0, i-24):i], min_score, allowed_direction, ticker)
        if setup:
            m_score, initial_sl_calc, tp_calc, t_type, dir_calc = setup
            dir_m = 1 if dir_calc == "Long" else -1
            entry_date = curr_bar.name.strftime("%d/%m/%Y")
            entry_price = curr_bar["Open"] * (1 + slippage*dir_m)
            
            initial_sl = initial_sl_calc
            if dir_m == 1 and initial_sl >= entry_price: initial_sl = entry_price * 0.95
            if dir_m == -1 and initial_sl <= entry_price: initial_sl = entry_price * 1.05
            
            if exit_profile == "commodity_alpha":
                target_risk = account_balance * (risk_pct / 100.0)
            elif exit_profile == "apex_commodity" and daily_loss is not None and daily_loss > 0:
                target_risk = daily_loss * 0.05
            elif daily_loss is not None and daily_loss > 0:
                target_risk = daily_loss * 0.10
            else:
                target_risk = account_balance * (risk_pct / 100.0)
                
            worst_case_exit = initial_sl * (1 - slippage*dir_m)
            loss_per_unit = (abs(entry_price - worst_case_exit) * pt_val) + (entry_price * pt_val + worst_case_exit * pt_val) * fee_rate
            
            # Währungs-Normalisierung für JPY, CHF, CAD (Risiko fällt in Fremdwährung an)
            if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                loss_per_unit = loss_per_unit / entry_price

            if loss_per_unit > 0:
                raw_qty = target_risk / loss_per_unit
                if a_type == "future":
                    pos_size = float(int(raw_qty))
                elif a_type == "forex":
                    pos_size = round(raw_qty, 2)
                    if pos_size <= 0.0:
                        pos_size = 0.01  # Mindest-Lotgröße
                else:
                    pos_size = raw_qty
            else:
                pos_size = 0.0
                
            # Einstiegs-Schranke: Futures brauchen >= 1 Kontrakt, Forex/Aktien brauchen > 0.0
            is_valid_size = (pos_size >= 1.0) if a_type == "future" else (pos_size > 0.0)
            
            if is_valid_size:
                in_trade = True
                direction = dir_calc
                planned_risk = pos_size * loss_per_unit
                current_sl = initial_sl
                initial_risk = abs(entry_price - initial_sl)
                trade_type = t_type
                is_setup_b_trade = "Trend" in trade_type
                
                if exit_profile in ["apex_lock", "commodity_alpha", "apex_commodity"]:
                    t_exit_mode = "TARGET_LOCKED"
                    tp = entry_price + (2.0 * initial_risk * dir_m) if not is_setup_b_trade else entry_price + (2.5 * initial_risk * dir_m)
                    max_days = b_per_day
                    highest_high = entry_price
                    lowest_low = entry_price
                elif exit_profile in ["prop_guard", "apex_commodity_scale"]:
                    t_exit_mode = "PROP_DEFENSIVE"
                    tp = tp_calc if not is_setup_b_trade else entry_price + (2.5 * initial_risk * dir_m)
                    if is_setup_b_trade:
                        max_days = 10 * b_per_day
                    else:
                        exp_d = (abs(tp - entry_price) / prev_bar["ATR"]) if prev_bar["ATR"] > 0 else 10
                        max_days = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))
                    highest_high = entry_price
                    lowest_low = entry_price
                elif exit_profile == "ftmo_swing":
                    t_exit_mode = "FTMO_SWING"
                    if is_setup_b_trade:
                        tp = 999999.0 if dir_m == 1 else 0.0001
                        max_days = 10 * b_per_day
                    else:
                        tp = tp_calc
                        exp_d = (abs(tp - entry_price) / prev_bar["ATR"]) if prev_bar["ATR"] > 0 else 10
                        max_days = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))
                    highest_high = entry_price
                    lowest_low = entry_price
                
                else: # private_alpha
                    if is_setup_b_trade:
                        t_exit_mode = "HOME_RUN_TREND"
                        tp = 999999.0 if dir_m == 1 else 0.0001
                        max_days = 15 * b_per_day
                        highest_high = entry_price
                        lowest_low = entry_price
                    else:
                        t_exit_mode = "ALPHA_CASHFLOW"
                        tp = tp_calc
                        exp_d = (abs(tp - entry_price) / prev_bar["ATR"]) if prev_bar["ATR"] > 0 else 10
                        max_days = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))
                        highest_high = entry_price
                        lowest_low = entry_price
                        
                days_in_trade = 0
                scaled_out = False

    return trades

#endregion

#region PORTFOLIO LOGIC
def evaluate_setup_and_score(recent_bars, min_score, allowed_direction="both", ticker=""):
    prev_bar = recent_bars.iloc[-1]
    c_p = prev_bar["Close"]
    ema200 = prev_bar["EMA_200"]
    ema20 = prev_bar["EMA_20"]
    rsi = prev_bar["RSI"]
    atr = prev_bar["ATR"]
    z_score = prev_bar.get("Z_Score", 0)

    sym_u = str(ticker).upper()
    if any(ext in sym_u for ext in ["=X", "DX-Y"]): asset_class = "FOREX"
    elif "=F" in sym_u: asset_class = "FUTURES"
    elif any(ext in sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]): asset_class = "CRYPTO"
    else: asset_class = "EQUITY"

    macro_ok = prev_bar["Bench_Close"] > prev_bar["Bench_EMA_200"]
    if asset_class in ["FOREX", "FUTURES"]: macro_ok = True

    if asset_class == "CRYPTO":
        pb_low, pb_high = 42.0, 58.0
        eff_t_buy = 25.0
        eff_z_buy = -2.2
    else:
        pb_low, pb_high = 38.0, 52.0
        eff_t_buy = 30.0
        eff_z_buy = -2.0

    trend_ok_long = (c_p > ema200) if asset_class != "FOREX" else True
    trend_ok_short = (c_p < ema200) if asset_class != "FOREX" else True

    is_setup_b_long = (pb_low <= rsi <= pb_high) and trend_ok_long and (abs(c_p - ema20) / ema20 <= 0.015) if asset_class != "FOREX" else False
    is_setup_b_short = ((100-pb_high) <= rsi <= (100-pb_low)) and trend_ok_short and (abs(c_p - ema20) / ema20 <= 0.015) if asset_class != "FOREX" else False

    is_setup_a_long = (rsi <= eff_t_buy) or (c_p <= prev_bar.get("KC_lower", 0)) or (z_score <= eff_z_buy)
    is_setup_a_short = (rsi >= (100-eff_t_buy)) or (c_p >= prev_bar.get("KC_upper", 999999)) or (z_score >= abs(eff_z_buy))

    direction = None
    if allowed_direction in ["both", "long"] and macro_ok:
        if asset_class in ["EQUITY", "CRYPTO"]:
            if is_setup_b_long:
                direction = "Long"
                is_setup_b = True
        else:
            if is_setup_a_long or is_setup_b_long:
                direction = "Long"
                is_setup_b = is_setup_b_long

    if direction is None and allowed_direction in ["both", "short"] and (is_setup_a_short or is_setup_b_short):
        # Futures und Forex ignorieren den Makro-Filter auf der Short-Seite
        if asset_class in ["FUTURES", "FOREX"] or not macro_ok:
            direction = "Short"
            is_setup_b = is_setup_b_short

    if not direction: return None

    # SL & TP Ermittlung
    if "=F" in str(ticker).upper():
        is_energy_fut = any(e in str(ticker).upper() for e in ["CL=F", "MCL", "NG=F", "QG"])
        atr_mult = 1.2 if is_energy_fut else 1.8
        vol_buffer = (atr * atr_mult) if atr > 0 else (c_p * 0.008)
        if direction == "Long":
            sl = c_p - vol_buffer
            temp_tp = c_p + (2.0 * vol_buffer)
            risk, reward = c_p - sl, temp_tp - c_p
        else:
            sl = c_p + vol_buffer
            temp_tp = c_p - (2.0 * vol_buffer)
            risk, reward = sl - c_p, c_p - temp_tp
    elif "=X" in str(ticker).upper() or str(ticker).upper() == "DX-Y.NYB" or allowed_direction in ["both", "short"]:
        if direction == "Long":
            sl = recent_bars["Low"].min()
            if sl >= c_p: sl = c_p * 0.95
            temp_tp = recent_bars["High"].max()
            risk, reward = c_p - sl, temp_tp - c_p
        else:
            sl = recent_bars["High"].max()
            if sl <= c_p: sl = c_p * 1.05
            temp_tp = recent_bars["Low"].min()
            risk, reward = sl - c_p, c_p - temp_tp
    else:
        if direction == "Long":
            sl = max(c_p * 0.95, ema20 * 0.98)
            if sl >= c_p: sl = c_p * 0.95
            temp_tp = ema200 if (c_p < ema200 and ema200 < c_p * 1.15) else (c_p + (2.0 * atr) if atr > 0 else c_p * 1.08)
            risk, reward = c_p - sl, temp_tp - c_p
        else:
            sl = min(c_p * 1.05, ema20 * 1.02)
            if sl <= c_p: sl = c_p * 1.05
            temp_tp = ema200 if (c_p > ema200 and ema200 > c_p * 0.85) else (c_p - (2.0 * atr) if atr > 0 else c_p * 0.92)
            risk, reward = sl - c_p, c_p - temp_tp

    crv = reward / risk if risk > 0 else 0
    rs_val = prev_bar.get("RS_20d", 1.0)
    has_real_vol = prev_bar.get("Has_Valid_Volume", False)
    if has_real_vol:
        vol = prev_bar.get("Volume", 0)
        vol_sma = prev_bar.get("Vol_SMA_20", 0)
    else:
        vol = prev_bar.get("Activity_Proxy", 0)
        vol_sma = prev_bar.get("Activity_Proxy_SMA_20", 0)
        
    vol_missing = True if (pd.isna(vol) or pd.isna(vol_sma) or vol_sma <= 0) else False

    max_crv = 20 if is_setup_b else 30
    max_signal = 15 if is_setup_b else 25

    if is_setup_b:
        p1 = 15 if (c_p > ema200 if direction=="Long" else c_p < ema200) or asset_class == "FOREX" else 0
        p2 = 10 if (prev_bar.get("MACD_Hist", 0) > 0 if direction=="Long" else prev_bar.get("MACD_Hist", 0) < 0) else 0
        p3 = 10 if (not vol_missing and vol > vol_sma) else 0
        pts_saeulen = p1 + p2 + p3
        max_saeulen = 25 if (vol_missing or asset_class == "FOREX") else 35

        pts_rs = 0
        max_rs = 0
        if asset_class == "EQUITY" and pd.notna(rs_val):
            max_rs = 30
            if direction == "Long": pts_rs = 30 if rs_val >= 1.05 else (15 if rs_val >= 0.95 else 0)
            else: pts_rs = 30 if rs_val <= 0.95 else (15 if rs_val <= 1.05 else 0)

        pts_crv = 20 if crv >= 2.0 else (10 if crv >= 1.5 else 0)
        pts_signal = 15
        t_type = "Trend-Kauf" if direction=="Long" else "Trend-Short"
    else:
        p1 = 15 if (rsi <= eff_t_buy if direction=="Long" else rsi >= (100-eff_t_buy)) else 0
        p2 = 10 if (c_p <= prev_bar.get("BB_lower", 0) if direction=="Long" else c_p >= prev_bar.get("BB_upper", 999999)) else 0
        p3 = 10 if (c_p <= prev_bar.get("KC_lower", 0) if direction=="Long" else c_p >= prev_bar.get("KC_upper", 999999)) else 0
        p4 = 10 if (not vol_missing and vol > vol_sma) else 0
        pts_saeulen = p1 + p2 + p3 + p4
        max_saeulen = 35 if (vol_missing or asset_class == "FOREX") else 45

        pts_rs = 0
        max_rs = 0
        pts_crv = 30 if crv >= 2.0 else (15 if crv >= 1.5 else 0)
        sig_trend = 15 if ((c_p > ema200 if direction=="Long" else c_p < ema200) or asset_class == "FOREX") else (10 if (c_p > ema20 if direction=="Long" else c_p < ema20) else 0)
        sig_ext = 10 if ((rsi <= eff_t_buy or z_score <= eff_z_buy) if direction=="Long" else (rsi >= (100-eff_t_buy) or z_score >= abs(eff_z_buy))) else 0
        pts_signal = sig_trend + sig_ext

        if direction == "Long": t_type = "Kauf" if c_p > ema200 else ("Rebound" if c_p > ema20 else "Risk-Rebound")
        else: t_type = "Short" if c_p < ema200 else ("Rebound-Short" if c_p < ema20 else "Risk-Short")

    achieved = pts_saeulen + pts_crv + pts_rs + pts_signal
    achievable = max_saeulen + max_crv + max_rs + max_signal
    master_score = int((achieved / achievable) * 100) if achievable > 0 else 0
    if (rsi >= 70 and direction == "Long") or (rsi <= 30 and direction == "Short"): master_score = min(master_score, 45)

    if asset_class == "FUTURES":
        if crv < 1.5:
            return None
        if is_setup_b:
            if not (p1 > 0 and p2 > 0):
                return None
        else:
            active_pillars = sum([1 for p in [p1, p2, p3, p4] if p > 0])
            if active_pillars < 2:
                return None

    if master_score >= min_score:
        return (master_score, sl, temp_tp, t_type, direction)
    return None

def run_portfolio_simulation(dfs, sector_map, all_dates, fee_rate, slippage, min_score, start_idx, train_end_idx, test_end_idx, account_size, risk_pct, compounding, trailing_stop_mode, window_name, exit_profile="prop_guard", allowed_direction="both", daily_loss=None):
    trades = []
    open_positions = {}
    account_balance = account_size
    cooldowns = {}
    
    interval = "1d"
    if len(all_dates) > 1:
        min_td = min([all_dates[i] - all_dates[i-1] for i in range(1, min(10, len(all_dates)))])
        if min_td.total_seconds() <= 900: interval = "15m"
        elif min_td.total_seconds() <= 3600: interval = "1h"
        elif min_td.total_seconds() <= 14400: interval = "4h"
    is_intraday = interval in ["15m", "1h", "4h"]
    
    for i in range(start_idx + 1, test_end_idx):
        curr_date = all_dates[i]
        prev_date = all_dates[i-1]
        is_oos = i >= train_end_idx
        bar_date = curr_date.date() if hasattr(curr_date, 'date') else curr_date
        if 'current_trade_date' not in locals() or current_trade_date != bar_date:
            current_trade_date = bar_date
            daily_loss_tracker = 0.0
            
        loss_threshold = (daily_loss * 0.20) if daily_loss and daily_loss > 0 else (account_balance * (risk_pct / 100.0) * 2.0)
        
        # --- A. VERWALTUNG OFFENER TRADES ---
        for ticker, pos in list(open_positions.items()):
            df = dfs[ticker]
            if curr_date not in df.index: continue
            curr_bar = df.loc[curr_date]
            prev_bar = df.loc[prev_date] if prev_date in df.index else df.iloc[df.index.get_loc(curr_date)-1]
            
            is_setup_b_trade = "Trend" in pos["type"]
            dir_m = 1 if pos.get("direction", "Long") == "Long" else -1
            
            t_exit_mode = pos.get("exit_mode", "PROP_DEFENSIVE")
            force_eod_close = False
            if interval in ["15m", "1h"] and "=F" in str(ticker).upper() and exit_profile == "apex_lock":
                bar_time = curr_date.tz_convert('Europe/Berlin') if hasattr(curr_date, 'tzinfo') and curr_date.tzinfo else curr_date
                if hasattr(bar_time, 'time'):
                    h, m = bar_time.hour, bar_time.minute
                    if h > 22 or (h == 22 and m >= 45):
                        force_eod_close = True
            
            if t_exit_mode == "HOME_RUN_TREND" or (t_exit_mode == "FTMO_SWING" and is_setup_b_trade):
                if dir_m == 1 and curr_bar["High"] > pos.get("highest_high", 0):
                    pos["highest_high"] = curr_bar["High"]
                    pos["days"] = 0
                elif dir_m == -1 and curr_bar["Low"] < pos.get("lowest_low", 999999):
                    pos["lowest_low"] = curr_bar["Low"]
                    pos["days"] = 0
                
            pos["days"] += 1
            exit_price, exit_reason = 0, ""
            if force_eod_close:
                exit_price = curr_bar["Close"]
                exit_reason = "EOD_Close"
            elif dir_m == 1:
                if curr_bar["Low"] <= pos["current_sl"]:
                    exit_price = pos["current_sl"]
                    exit_reason = "Trailing_SL" if pos["current_sl"] > pos["initial_sl"] else "Initial_SL"
                elif t_exit_mode != "HOME_RUN_TREND" and not (t_exit_mode == "FTMO_SWING" and is_setup_b_trade) and curr_bar["High"] >= pos["tp"]:
                    exit_price = pos["tp"]
                    exit_reason = "Take_Profit"
            else:
                if curr_bar["High"] >= pos["current_sl"]:
                    exit_price = pos["current_sl"]
                    exit_reason = "Trailing_SL" if pos["current_sl"] < pos["initial_sl"] else "Initial_SL"
                elif t_exit_mode != "HOME_RUN_TREND" and not (t_exit_mode == "FTMO_SWING" and is_setup_b_trade) and curr_bar["Low"] <= pos["tp"]:
                    exit_price = pos["tp"]
                    exit_reason = "Take_Profit"
                    
            if pos["days"] >= pos["max_days"] and exit_price == 0:
                exit_price = curr_bar["Close"]
                exit_reason = "Time-Stop"
                
            if exit_price > 0:
                pt_val, a_type = get_asset_specs(ticker)
                t_fee, t_slip = fee_rate, slippage
                if fee_rate >= 0.001:
                    if a_type == "forex": t_fee, t_slip = 0.00003, 0.00002
                    elif a_type == "future": t_fee, t_slip = 0.00005, 0.0001
                    
                actual_exit = exit_price * (1 - t_slip*dir_m) if "SL" in exit_reason or "Time-Stop" in exit_reason else exit_price
                pnl = (actual_exit - pos["entry"]) * pos["size"] * pt_val * dir_m
                fees = (pos["entry"] * pos["size"] * pt_val + actual_exit * pos["size"] * pt_val) * t_fee
                if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                    pnl /= actual_exit
                    fees /= actual_exit
                    
                net_pnl = pnl - fees
                
                if compounding == "active": 
                    account_balance += net_pnl
                if net_pnl < 0:
                    daily_loss_tracker += abs(net_pnl)
                    
                trades.append({
                    "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": curr_date.strftime("%d/%m/%Y"),
                    "type": pos["type"], "entry_price": pos["entry"], "exit_price": actual_exit,
                    "reason": exit_reason, "net_pnl": net_pnl, 
                    "r_multiple": net_pnl / pos["planned_risk"] if pos["planned_risk"] > 0 else 0,
                    "is_oos": pos.get("is_oos", False), "window": window_name, "exit_mode": t_exit_mode
                })
                del open_positions[ticker]
                cooldowns[ticker] = 2
                continue
                
            # Trailing Stop Logik
            if trailing_stop_mode == "active":
                current_high = curr_bar["High"]
                current_low = curr_bar["Low"]
                atr_val = prev_bar["ATR"]
                ema20_val = prev_bar["EMA_20"]
                pt_val, a_type = get_asset_specs(ticker)
                
                t_fee, t_slip = fee_rate, slippage
                if fee_rate >= 0.001:
                    if a_type == "forex": t_fee, t_slip = 0.00003, 0.00002
                    elif a_type == "future": t_fee, t_slip = 0.00005, 0.0001
                
                fees_rest = (pos["entry"] * pos["size"] * pt_val) * t_fee
                exit_fees_est = (pos["entry"] * pos["size"] * pt_val) * t_fee
                fees_per_unit = (fees_rest + exit_fees_est) / (pos["size"] * pt_val) if pos["size"] > 0 else 0
                net_be = pos["entry"] + fees_per_unit if dir_m == 1 else pos["entry"] - fees_per_unit
                
                sym_str = str(ticker).upper()
                is_crypto = any(sym_str.endswith(ext) for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL"])
                
                open_profit = (current_high - pos["entry"]) if dir_m == 1 else (pos["entry"] - current_low)
                current_r = open_profit / pos["initial_risk"] if pos["initial_risk"] > 0 else 0

                if is_crypto:
                    if current_r >= 1.5:
                        if not pos.get("scaled_out", False) and t_exit_mode != "HOME_RUN_TREND":
                            exit_price_scale = pos["entry"] + (1.5 * pos["initial_risk"] * dir_m)
                            actual_exit = exit_price_scale * (1 - t_slip*dir_m)
                            scale_size = pos["size"] * 0.5
                            pnl_scale = (actual_exit - pos["entry"]) * scale_size * pt_val * dir_m
                            fees_scale = (pos["entry"] * scale_size * pt_val + actual_exit * scale_size * pt_val) * t_fee
                            net_pnl_scale = pnl_scale - fees_scale
                            if compounding == "active":
                                account_balance += net_pnl_scale
                            trades.append({
                                "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": curr_date.strftime("%d/%m/%Y"),
                                "type": pos["type"] + " (Krypto-Scale 50%)", "entry_price": pos["entry"], "exit_price": actual_exit,
                                "reason": "Scale-Out +1.5R", "net_pnl": net_pnl_scale, 
                                "r_multiple": net_pnl_scale / (pos["planned_risk"] * 0.5) if pos["planned_risk"] > 0 else 0,
                                "is_oos": pos.get("is_oos", False), "window": window_name, "exit_mode": t_exit_mode
                            })
                            pos["size"] -= scale_size
                            pos["scaled_out"] = True
                            pos["current_sl"] = max(pos["current_sl"], net_be) if dir_m == 1 else min(pos["current_sl"], net_be)
                            
                        trend_trail = current_high - (3.5 * atr_val) if dir_m == 1 else current_low + (3.5 * atr_val)
                        if ema20_val > 0:
                            if dir_m == 1: trend_trail = max(trend_trail, ema20_val * 0.98)
                            else: trend_trail = min(trend_trail, ema20_val * 1.02)
                        pos["current_sl"] = max(pos["current_sl"], trend_trail) if dir_m == 1 else min(pos["current_sl"], trend_trail)
                        
                elif t_exit_mode == "TARGET_LOCKED":
                    if current_r >= 1.0:
                        profit_peak = current_high if dir_m == 1 else current_low
                        open_profit_peak = (profit_peak - pos["entry"]) * dir_m
                        peak_protection = pos["entry"] + (open_profit_peak * 0.80) * dir_m
                        pos["current_sl"] = max(pos["current_sl"], net_be, peak_protection) if dir_m == 1 else min(pos["current_sl"], net_be, peak_protection)
                
                elif t_exit_mode == "PROP_DEFENSIVE":
                    if current_r >= 1.0 and not pos.get("scaled_out", False):
                        exit_price_scale = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                        actual_exit = exit_price_scale * (1 - t_slip*dir_m)
                        scale_size = pos["size"] * 0.5
                        pnl_scale = (actual_exit - pos["entry"]) * scale_size * pt_val * dir_m
                        fees_scale = (pos["entry"] * scale_size * pt_val + actual_exit * scale_size * pt_val) * t_fee
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        if compounding == "active":
                            account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": curr_date.strftime("%d/%m/%Y"),
                            "type": pos["type"] + " (Scale-Out 50%)", "entry_price": pos["entry"], "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (pos["planned_risk"] * 0.5) if pos["planned_risk"] > 0 else 0,
                            "is_oos": pos.get("is_oos", False), "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos["size"] -= scale_size
                        pos["scaled_out"] = True
                        pos["current_sl"] = max(pos["current_sl"], net_be) if dir_m == 1 else min(pos["current_sl"], net_be)
                    if current_r >= 1.5:
                        new_trail = current_high - (2.0 * atr_val) if dir_m == 1 else current_low + (2.0 * atr_val)
                        pos["current_sl"] = max(pos["current_sl"], new_trail) if dir_m == 1 else min(pos["current_sl"], new_trail)
                        
                elif t_exit_mode == "ALPHA_CASHFLOW":
                    tp_distance = abs(pos["tp"] - pos["entry"])
                    tight_trigger_profit = 0.9 * tp_distance
                    
                    if current_r >= 1.0 and not pos.get("scaled_out", False):
                        exit_price_scale = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                        actual_exit = exit_price_scale * (1 - t_slip*dir_m)
                        scale_size = pos["size"] * 0.3
                        pnl_scale = (actual_exit - pos["entry"]) * scale_size * pt_val * dir_m
                        fees_scale = (pos["entry"] * scale_size * pt_val + actual_exit * scale_size * pt_val) * t_fee
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        if compounding == "active":
                            account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": curr_date.strftime("%d/%m/%Y"),
                            "type": pos["type"] + " (Scale-Out 30%)", "entry_price": pos["entry"], "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (pos["planned_risk"] * 0.3) if pos["planned_risk"] > 0 else 0,
                            "is_oos": pos.get("is_oos", False), "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos["size"] -= scale_size
                        pos["scaled_out"] = True
                        pos["current_sl"] = max(pos["current_sl"], net_be) if dir_m == 1 else min(pos["current_sl"], net_be)
                        
                    if current_r >= 1.5:
                        new_target_sl = net_be
                        if open_profit >= tight_trigger_profit:
                            trail_base = current_high - (0.5 * atr_val) if dir_m == 1 else current_low + (0.5 * atr_val)
                        else:
                            trail_base = current_high - (2.5 * atr_val) if dir_m == 1 else current_low + (2.5 * atr_val)
                        
                        new_target_sl = max(new_target_sl, trail_base) if dir_m == 1 else min(new_target_sl, trail_base)
                        
                        if current_r >= 6.0:
                            peak_floor = pos["entry"] + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = pos["entry"] + (2.5 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                            
                        pos["current_sl"] = max(pos["current_sl"], new_target_sl) if dir_m == 1 else min(pos["current_sl"], new_target_sl)

                elif t_exit_mode == "FTMO_SWING":
                    if current_r >= 1.0 and not pos.get("scaled_out", False):
                        exit_price_scale = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                        actual_exit = exit_price_scale * (1 - t_slip*dir_m)
                        scale_size = pos["size"] * 0.3
                        pnl_scale = (actual_exit - pos["entry"]) * scale_size * pt_val * dir_m
                        fees_scale = (pos["entry"] * scale_size * pt_val + actual_exit * scale_size * pt_val) * t_fee
                        if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                            pnl_scale /= actual_exit
                            fees_scale /= actual_exit
                            
                        net_pnl_scale = pnl_scale - fees_scale
                        if compounding == "active":
                            account_balance += net_pnl_scale
                        trades.append({
                            "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": curr_date.strftime("%d/%m/%Y"),
                            "type": pos["type"] + " (Scale-Out 30%)", "entry_price": pos["entry"], "exit_price": actual_exit,
                            "reason": "Scale-Out +1.0R", "net_pnl": net_pnl_scale, 
                            "r_multiple": net_pnl_scale / (pos["planned_risk"] * 0.3) if pos["planned_risk"] > 0 else 0,
                            "is_oos": pos.get("is_oos", False), "window": window_name, "exit_mode": t_exit_mode
                        })
                        pos["size"] -= scale_size
                        pos["scaled_out"] = True
                        pos["current_sl"] = max(pos["current_sl"], net_be) if dir_m == 1 else min(pos["current_sl"], net_be)
                        
                    if current_r >= 1.5:
                        trail_mult = 2.5 if is_setup_b_trade else 2.0
                        trail_base = current_high - (trail_mult * atr_val) if dir_m == 1 else current_low + (trail_mult * atr_val)
                        if is_setup_b_trade and ema20_val > 0:
                            trail_base = max(trail_base, ema20_val * 0.98) if dir_m == 1 else min(trail_base, ema20_val * 1.02)
                        
                        new_target_sl = max(net_be, trail_base) if dir_m == 1 else min(net_be, trail_base)
                        
                        if current_r >= 6.0:
                            peak_floor = pos["entry"] + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = pos["entry"] + (2.5 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                            
                        pos["current_sl"] = max(pos["current_sl"], new_target_sl) if dir_m == 1 else min(pos["current_sl"], new_target_sl)
                
                        
                elif t_exit_mode == "HOME_RUN_TREND":
                    if current_r >= 1.5:
                        trend_trail = current_high - (3.0 * atr_val) if dir_m == 1 else current_low + (3.0 * atr_val)
                        if ema20_val > 0:
                            trend_trail = max(trend_trail, ema20_val * 0.98) if dir_m == 1 else min(trend_trail, ema20_val * 1.02)
                            
                        new_target_sl = max(net_be, trend_trail) if dir_m == 1 else min(net_be, trend_trail)
                        if current_r >= 6.0:
                            peak_floor = pos["entry"] + (open_profit * 0.50 * dir_m)
                            new_target_sl = max(new_target_sl, peak_floor) if dir_m == 1 else min(new_target_sl, peak_floor)
                        elif current_r >= 4.0:
                            r4_floor = pos["entry"] + (2.5 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r4_floor) if dir_m == 1 else min(new_target_sl, r4_floor)
                        elif current_r >= 2.5:
                            r25_floor = pos["entry"] + (1.0 * pos["initial_risk"] * dir_m)
                            new_target_sl = max(new_target_sl, r25_floor) if dir_m == 1 else min(new_target_sl, r25_floor)
                        pos["current_sl"] = max(pos["current_sl"], new_target_sl) if dir_m == 1 else min(pos["current_sl"], new_target_sl)
                    
        # --- B. SIGNALGENERIERUNG ---
        if len(open_positions) >= 3: continue
        if daily_loss_tracker >= loss_threshold:
            continue  # Daily Circuit Breaker aktiv: Keine neuen Trades für den Rest des Tages
        
        candidates = []
        for ticker, df in dfs.items():
            if ticker in open_positions or prev_date not in df.index or curr_date not in df.index: continue
            # Cooldown-Sperre prüfen (mind. 2 Bars nach Exit)
            if cooldowns.get(ticker, 0) > 0:
                cooldowns[ticker] -= 1
                continue
            # Zeit- und Session-Filter für CME-Futures
            if ticker.endswith("=F") and is_intraday:
                curr_bar = df.loc[curr_date]
                if not is_rth_bar(curr_bar.name, ticker):
                    continue  # Keine neuen Trades außerhalb der asset-spezifischen Hauptsession!
                    
            # Zeit- und Session-Filter für Forex Majors
            if (ticker.endswith("=X") or ticker == "DX-Y.NYB") and is_intraday:
                bar_time = curr_date.tz_convert('Europe/Berlin') if hasattr(curr_date, 'tzinfo') and curr_date.tzinfo else curr_date
                hour = bar_time.hour
                minute = bar_time.minute
                
                if ticker == "EURUSD=X":
                    # London/NY Overlap für EURUSD (13:00 - 18:00 MEZ)
                    if hour < 13 or hour >= 18:
                        continue
                else:
                    # Standard Forex Session (08:00 - 20:30 Uhr MEZ)
                    if hour < 8 or hour > 20 or (hour == 20 and minute > 30):
                        continue  # Keine neuen Trades in der Asien-Nacht!
            
            prev_bar, curr_bar = df.loc[prev_date], df.loc[curr_date]
            recent_bars = df.loc[:prev_date].tail(24)
            setup_res = evaluate_setup_and_score(recent_bars, min_score, allowed_direction, ticker)
            if setup_res:
                m_score, initial_sl_calc, tp_calc, t_type, dir_calc = setup_res
                candidates.append((m_score, ticker, curr_bar, prev_bar, initial_sl_calc, tp_calc, t_type, dir_calc))
                    
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # --- C. EINSTIEG ---
        us_indices = ["NQ=F", "ES=F", "YM=F", "RTY=F"]
        
        for cand in candidates:
            if len(open_positions) >= 3: break
            m_score, ticker, curr_bar, prev_bar, initial_sl_calc, tp_calc, t_type, dir_calc = cand
            sec = sector_map.get(ticker, "Standard")
            
            if sum(1 for p in open_positions.values() if p["sector"] == sec) >= 2: continue
            
            if ticker in us_indices and any(t in us_indices for t in open_positions.keys()):
                continue
            if "USD" in ticker and ticker.endswith("=X") and any("USD" in t and t.endswith("=X") for t in open_positions.keys()):
                continue
            
            dir_m = 1 if dir_calc == "Long" else -1
            
            pt_val, a_type = get_asset_specs(ticker)
            t_fee, t_slip = fee_rate, slippage
            if fee_rate >= 0.001:
                if a_type == "forex": t_fee, t_slip = 0.00003, 0.00002
                elif a_type == "future": t_fee, t_slip = 0.00005, 0.0001
            b_per_day = get_bars_per_day(interval, a_type)
            
            entry_price = curr_bar["Open"] * (1 + t_slip*dir_m)
            
            initial_sl = initial_sl_calc
            if dir_m == 1 and initial_sl >= entry_price: initial_sl = entry_price * 0.95
            if dir_m == -1 and initial_sl <= entry_price: initial_sl = entry_price * 1.05
            
            if exit_profile == "commodity_alpha":
                target_risk = account_balance * (risk_pct / 100.0)
            elif exit_profile == "apex_commodity" and daily_loss is not None and daily_loss > 0:
                target_risk = daily_loss * 0.05
            elif daily_loss is not None and daily_loss > 0:
                target_risk = daily_loss * 0.10
            else:
                target_risk = account_balance * (risk_pct / 100.0)
                
            worst_case_exit = initial_sl * (1 - t_slip*dir_m)
            loss_per_unit = (abs(entry_price - worst_case_exit) * pt_val) + (entry_price * pt_val + worst_case_exit * pt_val) * t_fee
            
            # Währungs-Normalisierung für JPY, CHF, CAD (Risiko fällt in Fremdwährung an)
            if a_type == "forex" and any(ext in str(ticker).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]):
                loss_per_unit = loss_per_unit / entry_price

            if loss_per_unit > 0:
                raw_qty = target_risk / loss_per_unit
                if a_type == "future":
                    pos_size = float(int(raw_qty))
                elif a_type == "forex":
                    pos_size = round(raw_qty, 2)
                    if pos_size <= 0.0:
                        pos_size = 0.01  # Mindest-Lotgröße
                else:
                    pos_size = raw_qty
            else:
                pos_size = 0.0
                
            is_valid_size = (pos_size >= 1.0) if a_type == "future" else (pos_size > 0.0)
            
            if is_valid_size:
                    is_setup_b_trade = "Trend" in t_type
                    if exit_profile in ["apex_lock", "commodity_alpha", "apex_commodity"]:
                        t_exit_mode = "TARGET_LOCKED"
                        tp_final = entry_price + (2.0 * abs(entry_price - initial_sl) * dir_m) if not is_setup_b_trade else entry_price + (2.5 * abs(entry_price - initial_sl) * dir_m)
                        max_d = b_per_day
                    elif exit_profile in ["prop_guard", "apex_commodity_scale"]:
                        t_exit_mode = "PROP_DEFENSIVE"
                        if is_setup_b_trade: tp_final = entry_price + (2.5 * abs(entry_price - initial_sl) * dir_m)
                        else: tp_final = tp_calc
                        if is_setup_b_trade:
                            max_d = 10 * b_per_day
                        else:
                            exp_d = abs(tp_final - entry_price) / prev_bar["ATR"] if prev_bar["ATR"] > 0 else 10
                            max_d = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))
                    elif exit_profile == "ftmo_swing":
                        t_exit_mode = "FTMO_SWING"
                        if is_setup_b_trade:                            
                            tp_final = 999999.0 if dir_m == 1 else 0.0001
                            max_d = 10 * b_per_day
                        else:
                            tp_final = tp_calc
                            exp_d = abs(tp_final - entry_price) / prev_bar["ATR"] if prev_bar["ATR"] > 0 else 10
                            max_d = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))
                    
                    else: # private_alpha
                        if is_setup_b_trade:                            
                            t_exit_mode = "HOME_RUN_TREND"
                            tp_final = 999999.0 if dir_m == 1 else 0.0001
                            max_d = 15 * b_per_day
                        else:
                            t_exit_mode = "ALPHA_CASHFLOW"
                            tp_final = tp_calc
                            exp_d = abs(tp_final - entry_price) / prev_bar["ATR"] if prev_bar["ATR"] > 0 else 10
                            max_d = max(3 * b_per_day, round(exp_d * 1.5 * b_per_day))

                    open_positions[ticker] = {
                        "entry": entry_price, "initial_sl": initial_sl, "current_sl": initial_sl, "tp": tp_final, 
                        "size": pos_size, "planned_risk": pos_size * loss_per_unit, "initial_risk": abs(entry_price - initial_sl),
                        "days": 0, "max_days": max_d, "highest_high": entry_price, "lowest_low": entry_price,
                        "entry_date": curr_date.strftime("%d/%m/%Y"), "type": t_type, "direction": dir_calc, "sector": sec,
                        "is_oos": is_oos, "scaled_out": False, "exit_mode": t_exit_mode
                    }
    return trades

def run_portfolio_backtest(tickers, sector_map, years, fee_rate, slippage, min_score, account_size, risk_pct, compounding="inactive", trailing_stop_mode="active", mode="walk_forward", exit_profile="prop_guard", allowed_direction="both", interval="1d", daily_loss=None, vol_proxy="atr_ratio", vol_proxy_mult=1.0):
    end_date = datetime.date.today()
    days_to_sub = int(years*365) 
    if interval in ["1h", "4h"] and days_to_sub > 720: days_to_sub = 720
    if interval == "15m" and days_to_sub > 59: days_to_sub = 59
    start_date = end_date - datetime.timedelta(days=days_to_sub)
    
    dfs = {}
    for ticker in tickers:
        fetch_interval = "1h" if interval == "4h" else interval
        df = yf.download(ticker, start=start_date, end=end_date, interval=fetch_interval, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        if interval == "4h" and not df.empty:
            agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
            if 'Volume' in df.columns: agg_dict['Volume'] = 'sum'
            df = df.resample('4h').agg(agg_dict).dropna(subset=['Close'])
            
        bench_df = get_benchmark_data(ticker, start_date, end_date, interval)
        df = df.dropna(subset=["Close"])
        df = calculate_indicators(df, bench_df, vol_proxy=vol_proxy, vol_proxy_mult=vol_proxy_mult)
        dfs[ticker] = df.dropna(subset=["Close", "EMA_200", "RSI", "ATR"])
        
    all_dates = sorted(list(set(date for df in dfs.values() for date in df.index)))
    all_trades = []
    
    if mode == "holdout":
        split_idx = int(len(all_dates) * 0.7)
        all_trades = run_portfolio_simulation(dfs, sector_map, all_dates, fee_rate, slippage, min_score, 0, split_idx, len(all_dates), account_size, risk_pct, compounding, trailing_stop_mode, "Portfolio Holdout", exit_profile, allowed_direction, daily_loss)
    elif mode == "walk_forward":
        if interval in ["1h", "15m", "4h"]:
            if interval == "15m": bars_per_day = 28
            elif interval == "1h": bars_per_day = 7
            else: bars_per_day = 6
            train_size = 120 * bars_per_day
            test_size = 40 * bars_per_day
        else:
            bars_per_year = 252
            train_size = 3 * bars_per_year
            test_size = 1 * bars_per_year
        
        start_idx = 0
        window_num = 1
        while start_idx + train_size < len(all_dates):
            train_end = start_idx + train_size
            test_end = min(train_end + test_size, len(all_dates))
            window_name = f"WF-Fenster {window_num}"
            
            w_trades = run_portfolio_simulation(dfs, sector_map, all_dates, fee_rate, slippage, min_score, start_idx, train_end, test_end, account_size, risk_pct, compounding, trailing_stop_mode, window_name, exit_profile, allowed_direction, daily_loss)
            all_trades.extend(w_trades)
            
            if test_end == len(all_dates): break
            start_idx += test_size
            window_num += 1

    return all_trades

def optimize_basket_pool(candidate_tickers, sector_map, target_size, years, fee_rate, slippage, min_score, account_size, risk_pct, compounding="inactive", trailing_stop_mode="active", mode="walk_forward", exit_profile="prop_guard", allowed_direction="both", progress_callback=None, interval="1d", daily_loss=None, vol_proxy="atr_ratio", vol_proxy_mult=1.0):
    skipped_tickers = {}
    end_date = datetime.date.today()
    days_to_sub = int(years*365)
    if interval in ["1h", "4h"] and days_to_sub > 720: days_to_sub = 720
    if interval == "15m" and days_to_sub > 59: days_to_sub = 59
    start_date = end_date - datetime.timedelta(days=days_to_sub)
    
    dfs = {}
    total_cands = len(candidate_tickers)
    batch_size = 15
    
    for i in range(0, total_cands, batch_size):
        batch = candidate_tickers[i:i + batch_size]
        if progress_callback: progress_callback(i, total_cands, f"Lade Batch {i//batch_size + 1} ({len(batch)} Ticker)...")
            
        fetch_interval = "1h" if interval == "4h" else interval
        b_df = yf.download(batch, start=start_date, end=end_date, interval=fetch_interval, progress=False)
        if isinstance(b_df.columns, pd.MultiIndex) and len(batch) == 1:
            b_df.columns = b_df.columns.get_level_values(0)
            
        for ticker in batch:
            try: df_t = b_df[ticker].copy() if (isinstance(b_df.columns, pd.MultiIndex) and ticker in b_df.columns.get_level_values(0)) else (b_df.xs(ticker, level=1, axis=1).copy() if isinstance(b_df.columns, pd.MultiIndex) else b_df.copy())
            except: continue
            
            if interval == "4h" and not df_t.empty:
                agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
                if 'Volume' in df_t.columns: agg_dict['Volume'] = 'sum'
                df_t = df_t.resample('4h').agg(agg_dict).dropna(subset=['Close'])
                
            df_t = df_t.dropna(subset=["Close"])
            if df_t.empty:
                skipped_tickers[ticker] = "Keine Kursdaten bei Yahoo gefunden (evtl. delisted oder umbenannt)"
                continue
            if len(df_t) < 200:
                skipped_tickers[ticker] = f"Historie zu kurz ({len(df_t)} von mind. 200 Kerzen für EMA 200)"
                continue
            
            bench_df = get_benchmark_data(ticker, start_date, end_date, interval)
            df_t = calculate_indicators(df_t, bench_df, vol_proxy=vol_proxy, vol_proxy_mult=vol_proxy_mult)
            dfs[ticker] = df_t.dropna(subset=["Close", "EMA_200", "RSI", "ATR"])
            
    single_metrics = {}
    for i, (ticker, df) in enumerate(dfs.items()):
        if progress_callback: progress_callback(i, len(dfs), f"Pre-Scoring Einzel-Simulation: {ticker}")
        if mode == "holdout":
            split_idx = int(len(df) * 0.7)
            t_trades = run_simulation(df, ticker, fee_rate, slippage, min_score, 0, split_idx, len(df), account_size, risk_pct, trailing_stop_mode, "Holdout", exit_profile, allowed_direction, daily_loss)
        else:
            if interval == "1h": bars_per_year = 1764
            elif interval == "15m": bars_per_year = 7056
            elif interval == "4h": bars_per_year = 1512
            else: bars_per_year = 252
            train_size = 3 * bars_per_year
            test_size = 1 * bars_per_year
            start_idx = 0
            t_trades = []
            while start_idx + train_size < len(df):
                train_end = start_idx + train_size
                test_end = min(train_end + test_size, len(df))
                w_trades = run_simulation(df, ticker, fee_rate, slippage, min_score, start_idx, train_end, test_end, account_size, risk_pct, trailing_stop_mode, "WF", exit_profile, allowed_direction, daily_loss)
                t_trades.extend(w_trades)
                if test_end == len(df): break
                start_idx += test_size
        single_metrics[ticker] = calculate_metrics(t_trades)

    qualified = []
    for t, m in single_metrics.items():
        wr = m.get("Winrate (%)", 0)
        pf = m.get("Profit Factor", 0)
        tr = m.get("Total Trades", 0)
        if exit_profile in ["prop_guard", "defensive_swing", "apex_commodity_scale", "commodity_scale"]:
            if wr < 45 or pd.isna(pf) or pf < 1.3 or tr < 5: continue
        else:
            if tr < 5: continue
        qualified.append((t, m))
        
    qualified.sort(key=lambda x: x[1].get("Profit Factor", 0) if pd.notna(x[1].get("Profit Factor", 0)) else 0, reverse=True)
    
    if len(qualified) < 2: return {"error": f"Abbruch: Nur {len(qualified)} qualifizierte Ticker gefunden. (Minimum: 2)"}
        
    warning_msg = None
    effective_target = target_size
    if len(qualified) < target_size:
        effective_target = len(qualified)
        warning_msg = f"Zielgröße automatisch auf {effective_target} angepasst, da nur {effective_target} Ticker die Qualitätskriterien erfüllten."
        
    basket = [qualified[0][0]]
    remaining = [x[0] for x in qualified[1:]]
    all_dates = sorted(list(set(date for d in dfs.values() for date in d.index)))
    
    final_metrics = single_metrics[basket[0]]
    final_trades = []
    
    while len(basket) < effective_target and remaining:
        if progress_callback: progress_callback(len(basket), effective_target, f"Optimiere Korb (Größe {len(basket)+1}/{effective_target})...")
        best_cand = None
        best_score = -999999
        best_trades = []
        best_mets = {}
        
        for cand in remaining:
            test_basket = basket + [cand]
            # Korrelations-Ausschluss (Max 1 pro Cluster)
            us_indices = ["NQ=F", "ES=F", "YM=F", "RTY=F"]
            if sum(1 for t in test_basket if t in us_indices) > 1:
                continue
                
            usd_forex_count = sum(1 for t in test_basket if ("USD" in t and t.endswith("=X")))
            if usd_forex_count > 1:
                continue
                
            test_dfs = {k: dfs[k] for k in test_basket}
            
            test_trades = []
            if mode == "holdout":
                split_idx = int(len(all_dates) * 0.7)
                test_trades = run_portfolio_simulation(test_dfs, sector_map, all_dates, fee_rate, slippage, min_score, 0, split_idx, len(all_dates), account_size, risk_pct, compounding, trailing_stop_mode, "Holdout", exit_profile, allowed_direction, daily_loss)
            else:
                if interval == "1h": bars_per_year = 1764
                elif interval == "15m": bars_per_year = 7056
                elif interval == "4h": bars_per_year = 1512
                else: bars_per_year = 252
                train_size = 3 * bars_per_year
                test_size = 1 * bars_per_year
                start_idx = 0
                while start_idx + train_size < len(all_dates):
                    train_end = start_idx + train_size
                    test_end = min(train_end + test_size, len(all_dates))
                    w_trades = run_portfolio_simulation(test_dfs, sector_map, all_dates, fee_rate, slippage, min_score, start_idx, train_end, test_end, account_size, risk_pct, compounding, trailing_stop_mode, "WF", exit_profile, allowed_direction, daily_loss)
                    test_trades.extend(w_trades)
                    if test_end == len(all_dates): break
                    start_idx += test_size
            
            mets = calculate_metrics(test_trades)
            net_pnl = mets.get("Total Net PnL", 0)
            mdd = mets.get("Max Drawdown (€)", 0)
            wr = mets.get("Winrate (%)", 0)
            
            score = (net_pnl / max(1.0, mdd)) * np.sqrt(wr)
            cand_sec = sector_map.get(cand, "Standard")
            basket_secs = [sector_map.get(t, "Standard") for t in basket]
            if basket_secs.count(cand_sec) >= 2: continue
            if score > best_score:
                best_score = score
                best_cand = cand
                best_trades = test_trades
                best_mets = mets
                
        if best_cand:
            basket.append(best_cand)
            remaining.remove(best_cand)
            final_metrics = best_mets
            final_trades = best_trades
        else:
            warning_msg = f"Optimierung bei Korbgröße {len(basket)} beendet, da keine weiteren unkorrelierten Kandidaten den Korb verbessern konnten."
            break
            
    return {
        "best_basket": basket,
        "metrics": final_metrics,
        "trades": final_trades,
        "warning_msg": warning_msg,
        "skipped_tickers": skipped_tickers
    }

def backtest(ticker, years, fee_rate, slippage, min_score, mode, account_size, risk_pct, trailing_stop_mode="active", exit_profile="prop_guard", allowed_direction="both", interval="1d", daily_loss=None, vol_proxy="atr_ratio", vol_proxy_mult=1.0):
    end_date = datetime.date.today()
    days_to_sub = int(years*365)
    if interval in ["1h", "4h"] and days_to_sub > 720: days_to_sub = 720
    if interval == "15m" and days_to_sub > 59: days_to_sub = 59
    start_date = end_date - datetime.timedelta(days=days_to_sub)
    
    fetch_interval = "1h" if interval == "4h" else interval
    df = pd.DataFrame()
    for attempt in range(3):
        try:
            df = yf.download(ticker, start=start_date, end=end_date, interval=fetch_interval, progress=False)
            if not df.empty: break
        except Exception:
            pass
        import time
        time.sleep(2.0)
        
    if df.empty:
        return [], pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    
    if interval == "4h" and not df.empty:
        agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
        if 'Volume' in df.columns: agg_dict['Volume'] = 'sum'
        df = df.resample('4h').agg(agg_dict).dropna(subset=['Close'])
        
    bench_df = get_benchmark_data(ticker, start_date, end_date, interval)
    df = df.dropna(subset=["Close"])
    df = calculate_indicators(df, bench_df, vol_proxy=vol_proxy, vol_proxy_mult=vol_proxy_mult)
    df = df.dropna(subset=["Close", "EMA_200", "RSI", "ATR"])
    
    all_trades = []
    
    if mode == "holdout":
        split_idx = int(len(df) * 0.7)
        all_trades = run_simulation(df, ticker, fee_rate, slippage, min_score, 0, split_idx, len(df), account_size, risk_pct, trailing_stop_mode, "Holdout", exit_profile, allowed_direction, daily_loss)
    elif mode == "walk_forward":
        if interval in ["1h", "15m", "4h"]:
            if interval == "15m": bars_per_day = 28
            elif interval == "1h": bars_per_day = 7
            else: bars_per_day = 6
            train_size = 120 * bars_per_day
            test_size = 40 * bars_per_day
        else:
            bars_per_year = 252
            train_size = 3 * bars_per_year
            test_size = 1 * bars_per_year
        
        start_idx = 0
        window_num = 1
        while start_idx + train_size < len(df):
            train_end = start_idx + train_size
            test_end = min(train_end + test_size, len(df))
            window_name = f"WF-Fenster {window_num}"
            
            w_trades = run_simulation(df, ticker, fee_rate, slippage, min_score, start_idx, train_end, test_end, account_size, risk_pct, trailing_stop_mode, window_name, exit_profile, allowed_direction, daily_loss)
            all_trades.extend(w_trades)
            
            if test_end == len(df): break
            start_idx += test_size
            window_num += 1

    return all_trades, df
#endregion

#region METRICS
def calculate_metrics(trades):
    if not trades: return {}
    df_trades = pd.DataFrame(trades)
    
    wins = df_trades[df_trades["net_pnl"] > 0]
    losses = df_trades[df_trades["net_pnl"] <= 0]
    
    winrate = len(wins) / len(df_trades) * 100
    gross_profit = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else np.nan
    
    cum_pnl = df_trades["net_pnl"].cumsum()
    running_max = cum_pnl.cummax()
    drawdown = running_max - cum_pnl
    mdd_eur = drawdown.max()
    
    avg_r = df_trades["r_multiple"].mean()
    total_net = df_trades["net_pnl"].sum()
    
    return {
        "Total Trades": len(df_trades),
        "Winrate (%)": winrate,
        "Profit Factor": pf,
        "Max Drawdown (€)": mdd_eur,
        "Ø R-Multiple": avg_r,
        "Total Net PnL": total_net
    }
#endregion

#region CLI & LOGGING
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Backtest Engine - RSI Strategie")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Ticker Symbol für den Backtest")
    parser.add_argument("--tickers", type=str, default=None, help="Kommagetrennte Ticker-Liste (überschreibt --ticker, z.B. NQ=F,ES=F,YM=F)")
    parser.add_argument("--compounding", type=str, default="inactive", choices=["active", "inactive"], help="Dynamischer Zinseszins für das Risk-Management")
    parser.add_argument("--years", type=int, default=5, help="Anzahl der historischen Jahre")
    parser.add_argument("--min_score", type=int, default=70, help="Mindest-Master-Score für Einstiege (Standard: 70)")
    parser.add_argument("--mode", type=str, default="holdout", choices=["holdout", "walk_forward"], help="Test-Modus (holdout oder walk_forward)")
    parser.add_argument("--broker_profile", type=str, default="custom", help="Broker-Profil für Gebühren & Slippage")
    parser.add_argument("--fee_rate", type=float, default=None, help="Manuelle Gebühr (z.B. 0.0025 für 0.25%%) - überschreibt Profil")
    parser.add_argument("--slippage", type=float, default=None, help="Manuelle Slippage (z.B. 0.001 für 0.1%%) - überschreibt Profil")
    parser.add_argument("--account_size", type=float, default=10000.0, help="Startkapital des Kontos (Standard: 10000.0)")
    parser.add_argument("--risk_pct", type=float, default=1.0, help="Risiko pro Trade in Prozent (Standard: 1.0%%)")
    parser.add_argument("--trailing_stop", type=str, default="active", choices=["active", "inactive"], help="Dynamischer Trailing-Stop (active/inactive)")
    parser.add_argument("--exit_profile", type=str, default="prop_guard", choices=["prop_guard", "private_alpha", "apex_lock", "commodity_alpha", "apex_commodity", "apex_commodity_scale", "ftmo_swing"], help="Dual-Exit-Profil")
    parser.add_argument("--direction", type=str, default="both", choices=["long", "short", "both"], help="Simulierte Richtung (long/short/both)")
    parser.add_argument("--interval", type=str, default="1d", choices=["1d", "1h", "15m", "4h"], help="Daten-Intervall (Standard: 1d)")
    parser.add_argument("--daily_loss", type=float, default=None, help="Tagesverlust-Limit für Sizing (Überschreibt risk_pct)")
    parser.add_argument("--vol_proxy", type=str, default="atr_ratio", choices=["atr_ratio", "raw_tr", "median_ratio"], help="Berechnungsmethode für den Volume-Proxy bei fehlenden Volumendaten")
    parser.add_argument("--vol_proxy_mult", type=float, default=1.0, help="Sensitivitäts-Multiplikator für den Volume-Proxy (z. B. 0.8 bis 1.4)")
    args = parser.parse_args()
    
    fee_rate = 0.0025
    slippage = 0.001
    
    prof = args.broker_profile.lower()
    if prof == "ftmo" or "forex" in prof or "raw" in prof:
        fee_rate = 0.00003
        slippage = 0.00002
    elif prof == "apex" or "cme" in prof or "insti" in prof:
        fee_rate = 0.00005
        slippage = 0.0001
    elif "fusion" in prof:
        fee_rate = 0.001
        slippage = 0.0005
    elif "retail" in prof or "bitpanda" in prof:
        fee_rate = 0.0199
        slippage = 0.0015
    elif "aktien broker" in prof or "flat" in prof:
        fee_rate = 0.0005
        slippage = 0.0005
    elif prof == "standard_crypto":
        fee_rate, slippage = 0.0025, 0.001
        
    if args.fee_rate is not None: fee_rate = args.fee_rate
    if args.slippage is not None: slippage = args.slippage
    target_display = args.tickers if args.tickers else args.ticker
    print(f"\n🚀 Starte Backtest für {target_display} über {args.years} Jahre...")
    print(f"⚙️  Profil: {args.broker_profile.upper()} | Modus: {args.mode.upper()} | Score >= {args.min_score}")
    print(f"💸 Fee: {fee_rate*100:.2f}% | Slippage: {slippage*100:.2f}%")
    print(f"🌍 Makro-Filter: Aktiv (Benchmark EMA 200)")
    if args.daily_loss:
        print(f"💰 Startkonto: {args.account_size:,.2f} € | Risiko: 10% vom Daily Loss ({args.daily_loss * 0.10:,.2f} € pro Trade)")
    else:
        print(f"💰 Startkonto: {args.account_size:,.2f} € | Risiko: {args.risk_pct}% ({args.account_size * (args.risk_pct/100):,.2f} € pro Trade)")
    print(f"🛡️ Trailing-Stop: {'Aktiv (Break-Even & ATR-Trail)' if args.trailing_stop == 'active' else 'Inaktiv (Nur TP/SL)'}")
    print(f"🎯 Exit-Profil: {args.exit_profile.upper()}")
    print(f"🧭 Trade-Richtung: {args.direction.upper()}")
    print(f"⏱️ Intervall: {args.interval} | 🛡️ Daily Loss Puffer: {args.daily_loss if args.daily_loss else 'Inaktiv (Nutze %-Risiko)'}")
    print(f"📊 Volume-Proxy Modus: {args.vol_proxy} | Multiplikator: {args.vol_proxy_mult}")
    
    ticker_label = args.ticker
    if args.tickers:
        ticker_list = [t.strip() for t in args.tickers.split(",") if t.strip()]
        if len(ticker_list) > 1:
            print(f"📦 Portfolio-Modus Aktiviert! ({len(ticker_list)} Ticker)")
            sec_map = {t: "Standard" for t in ticker_list} 
            trades = run_portfolio_backtest(
                tickers=ticker_list, 
                sector_map=sec_map, 
                years=args.years, 
                fee_rate=fee_rate, 
                slippage=slippage, 
                min_score=args.min_score, 
                account_size=args.account_size, 
                risk_pct=args.risk_pct, 
                compounding=args.compounding, 
                trailing_stop_mode=args.trailing_stop, 
                mode=args.mode, 
                exit_profile=args.exit_profile, 
                allowed_direction=args.direction, 
                interval=args.interval, 
                daily_loss=args.daily_loss,
                vol_proxy=args.vol_proxy,
                vol_proxy_mult=args.vol_proxy_mult
                )
            df_hist = pd.DataFrame() 
            ticker_label = f"PORTFOLIO:[{','.join(ticker_list)}]"
        else:
            trades, df_hist = backtest(args.ticker, args.years, fee_rate, slippage, args.min_score, args.mode, args.account_size, args.risk_pct, args.trailing_stop, args.exit_profile, args.direction, args.interval, args.daily_loss, args.vol_proxy, args.vol_proxy_mult)
    else:
        trades, df_hist = backtest(args.ticker, args.years, fee_rate, slippage, args.min_score, args.mode, args.account_size, args.risk_pct, args.trailing_stop, args.exit_profile, args.direction, args.interval, args.daily_loss, args.vol_proxy, args.vol_proxy_mult)
    metrics_all = calculate_metrics(trades)
    df_trades = pd.DataFrame(trades)
    
    if not df_trades.empty:
        is_trades = df_trades[~df_trades["is_oos"]].to_dict('records')
        oos_trades = df_trades[df_trades["is_oos"]].to_dict('records')
        
        metrics_is = calculate_metrics(is_trades)
        metrics_oos = calculate_metrics(oos_trades)
        
        print("\n📊 --- GESAMTERGEBNISSE ---")
        print(f"Total Trades:   {metrics_all.get('Total Trades', 0)}")
        print(f"Winrate:        {metrics_all.get('Winrate (%)', 0):.2f} %")
        print(f"Profit Factor:  {metrics_all.get('Profit Factor', 0):.2f}")
        print(f"Max Drawdown:   {metrics_all.get('Max Drawdown (€)', 0):.2f} €")
        print(f"Ø R-Multiple:   {metrics_all.get('Ø R-Multiple', 0):.2f} R")
        print(f"Net PnL gesamt: {metrics_all.get('Total Net PnL', 0):.2f} €")
        
        print(f"\n🔬 --- IN-SAMPLE (Train) vs. OUT-OF-SAMPLE (Test) ---")
        print(f"IS Trades:      {metrics_is.get('Total Trades', 0):<8} |  OOS Trades:      {metrics_oos.get('Total Trades', 0)}")
        print(f"IS Winrate:     {metrics_is.get('Winrate (%)', 0):.2f} %  |  OOS Winrate:    {metrics_oos.get('Winrate (%)', 0):.2f} %")
        print(f"IS Profit Fact: {metrics_is.get('Profit Factor', 0):.2f}     |  OOS Profit Fact: {metrics_oos.get('Profit Factor', 0):.2f}")
        print(f"IS Net PnL:     {metrics_is.get('Total Net PnL', 0):.2f} € |  OOS Net PnL:    {metrics_oos.get('Total Net PnL', 0):.2f} €")

        if args.mode == "walk_forward":
            print("\n🚶 --- WALK-FORWARD FENSTER (OOS) ---")
            for window in df_trades["window"].unique():
                w_oos = df_trades[(df_trades["window"] == window) & (df_trades["is_oos"])]
                if not w_oos.empty:
                    w_met = calculate_metrics(w_oos.to_dict('records'))
                    print(f"[{window}] Trades: {w_met.get('Total Trades', 0):>2} | Winrate: {w_met.get('Winrate (%)', 0):.1f}% | Net PnL: {w_met.get('Total Net PnL', 0):.2f} €")
        
        out_file = "backtest_runs.csv"
        file_exists = os.path.isfile(out_file)
        with open(out_file, 'a', newline='', encoding='utf-8') as csvfile:
           fieldnames = ['Timestamp', 'Ticker', 'Years', 'Interval', 'Min Score', 'Mode', 'Trailing Stop', 'Exit Profile', 'Broker Profile', 'Fee Rate', 'Slippage', 'Account Size', 'Daily Loss', 'Risk Pct', 'Total Trades', 'Winrate (%)', 'Profit Factor', 'Max Drawdown (€)', 'Avg R-Multiple', 'OOS Winrate (%)', 'OOS Profit Factor', 'Vol_Proxy', 'Vol_Proxy_Mult']
           writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
           if not file_exists:
                writer.writeheader()
           writer.writerow({
                'Timestamp': datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                'Ticker': ticker_label,
                'Years': args.years,
                'Interval': args.interval,
                'Min Score': args.min_score,
                'Mode': args.mode,
                'Trailing Stop': args.trailing_stop,
                'Exit Profile': args.exit_profile,
                'Broker Profile': args.broker_profile,
                'Fee Rate': fee_rate,
                'Slippage': slippage,
                'Account Size': args.account_size,
                'Daily Loss': args.daily_loss if args.daily_loss else 0.0,
                'Risk Pct': args.risk_pct,
                'Total Trades': metrics_all.get('Total Trades', 0),
                'Winrate (%)': round(metrics_all.get('Winrate (%)', 0), 2),
                'Profit Factor': round(metrics_all.get('Profit Factor', 0), 2) if pd.notna(metrics_all.get('Profit Factor')) else 0,
                'Max Drawdown (€)': round(metrics_all.get('Max Drawdown (€)', 0), 2),
                'Avg R-Multiple': round(metrics_all.get('Ø R-Multiple', 0), 2),
                'OOS Winrate (%)': round(metrics_oos.get('Winrate (%)', 0), 2) if oos_trades else 0.0,
                'OOS Profit Factor': round(metrics_oos.get('Profit Factor', 0), 2) if pd.notna(metrics_oos.get('Profit Factor')) and oos_trades else 0.0,
                'Vol_Proxy': args.vol_proxy,
                'Vol_Proxy_Mult': args.vol_proxy_mult
            })
        print(f"\n✅ Ergebnisse erfolgreich an '{out_file}' angehängt.")
    else:
        print("\n⚠️ Keine Trades im gewählten Zeitraum ausgeführt.")
#endregion