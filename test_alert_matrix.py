import os
import json
import datetime
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# 1. Pfade & Umgebungsvariablen bestimmen
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
USERS_DIR = os.path.join(BASE_DIR, "users")

# .env laden (sucht in 'RSI Bot' und lokal in 'Trading Dashboard')
env_bot = os.path.join(PARENT_DIR, "RSI Bot", ".env")
env_local = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_bot):
    load_dotenv(env_bot, override=True)
elif os.path.exists(env_local):
    load_dotenv(env_local, override=True)


def get_target_user_dir():
    """Ermittelt dynamisch den Ziel-Mandanten (Standard: 'admin' oder erster Ordner in 'users/')."""
    if not os.path.exists(USERS_DIR):
        os.makedirs(os.path.join(USERS_DIR, "admin"), exist_ok=True)
        return os.path.join(USERS_DIR, "admin"), "admin"

    admin_path = os.path.join(USERS_DIR, "admin")
    if os.path.isdir(admin_path):
        return admin_path, "admin"

    subdirs = [
        d for d in os.listdir(USERS_DIR)
        if os.path.isdir(os.path.join(USERS_DIR, d))
    ]
    if subdirs:
        first_user = sorted(subdirs)[0]
        return os.path.join(USERS_DIR, first_user), first_user

    os.makedirs(admin_path, exist_ok=True)
    return admin_path, "admin"


def fetch_live_price(symbol, fallback):
    """Holt den aktuellen Live-Kurs via yfinance analog zu rsi_alerts.py mit robustem Fallback."""
    try:
        price = float(yf.Ticker(symbol).fast_info.get("lastPrice", 0.0))
        if price > 0:
            return price
    except Exception:
        pass
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if not hist.empty and "Close" in hist.columns:
            return float(hist["Close"].dropna().iloc[-1])
    except Exception:
        pass
    print(f"⚠️ Fallback-Preis für {symbol} genutzt: {fallback}")
    return fallback


def calc_entry_and_sl(curr_price, target_r, risk_dist):
    """Berechnet Entry und SL (Long) exakt so, dass (curr_price - entry) / (entry - sl) == target_r."""
    entry_price = curr_price - (target_r * risk_dist)
    sl_price = entry_price - risk_dist
    return round(entry_price, 4), round(sl_price, 4)


def main():
    user_dir, username = get_target_user_dir()
    print(f"🎯 Ziel-Mandant ermittelt: '{username}' ({user_dir})")

    # 2. alert_state.json auf '{}' zurücksetzen
    alert_state_file = os.path.join(user_dir, "alert_state.json")
    with open(alert_state_file, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=4)
    print("🧹 'alert_state.json' erfolgreich auf '{}' geleert.")

    # Sicherstellen, dass telegram_chat_id in user_profile.json gesetzt ist
    profile_file = os.path.join(user_dir, "user_profile.json")
    env_chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""
    if os.path.exists(profile_file):
        with open(profile_file, "r", encoding="utf-8") as pf:
            p_data = json.load(pf)
        if not p_data.get("telegram_chat_id") and env_chat_id:
            p_data["telegram_chat_id"] = env_chat_id
            with open(profile_file, "w", encoding="utf-8") as pf:
                json.dump(p_data, pf, indent=4)
            print(f"🔗 Telegram Chat-ID ({env_chat_id}) aus .env in user_profile.json synchronisiert.")
    elif env_chat_id:
        with open(profile_file, "w", encoding="utf-8") as pf:
            json.dump({"role": "admin", "telegram_chat_id": env_chat_id}, pf, indent=4)

    # 3. Live-Kurse abrufen
    print("📡 Rufe aktuelle Referenzkurse über yfinance ab...")
    p_aapl = fetch_live_price("AAPL", 225.00)
    p_nq = fetch_live_price("NQ=F", 20500.00)
    p_eurusd = fetch_live_price("EURUSD=X", 1.1100)

    print(f"   • AAPL:     {p_aapl:.4f} USD")
    print(f"   • NQ=F:     {p_nq:.4f} USD")
    print(f"   • EURUSD=X: {p_eurusd:.4f} USD")

    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    old_date_str = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%d/%m/%Y %H:%M")

    # Großzügiger Risikopuffer (5% vom Kurs), damit minimale Live-Ticks das R-Multiple nicht verfälschen
    r_aapl = round(p_aapl * 0.05, 2)
    r_nq = round(p_nq * 0.01, 2)
    r_fx = 0.0050

    cols = [
        'id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction',
        'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size',
        'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price',
        'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type',
        'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur',
        'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type'
    ]

    def build_row(t_id, acc_name, entry_dt, sym, name, ep, sl, tp, curr, pt_val, c_type, atr_d, exit_mode, notes):
        return {
            'id': t_id,
            'account_name': acc_name,
            'entry_date': entry_dt,
            'exit_date': "",
            'symbol': sym,
            'name': name,
            'direction': 'Long',
            'signal_price': ep,
            'entry_price': ep,
            'currency': curr,
            'fx_rate': 0.92,
            'position_size': 10.0 if sym == "AAPL" else (1.0 if sym == "NQ=F" else 0.10),
            'contract_type': c_type,
            'point_value': pt_val,
            'base_currency': 'EUR' if sym == "AAPL" else 'USD',
            'invest_eur': round(ep * 10.0 * 0.92, 2) if sym == "AAPL" else 0.0,
            'sl_price': sl,
            'tp_price': tp,
            'planned_risk_eur': 100.0,
            'est_fees_eur': 2.0,
            'master_score': 70,
            'setup_type': '🟢 ⚡ Long (Trend)',
            'mc_robustness': '🟢 Robust (90%)',
            'atr_days': atr_d,
            'exit_mode': exit_mode,
            'status': 'OPEN',
            'exit_price': None,
            'pnl_eur': None,
            'pnl_pct': None,
            'r_multiple': None,
            'exit_reason': "",
            'notes': notes,
            'strategy_version': 'v1.0.0',
            'execution_type': 'COPILOT_MANUAL'
        }

    trades = []

    # --- A. AAPL (Profil defensive_swing / PROP_DEFENSIVE) ---
    # TP weit nach oben legen (p_aapl * 1.5), damit bei Trade 1-7 kein TP-Hit ausgelöst wird
    high_tp_aapl = round(p_aapl * 1.50, 2)

    # Trade 1 (+1.0 R -> 1.05 R): Triggert Scale-Out 50% & Net-BE
    ep1, sl1 = calc_entry_and_sl(p_aapl, 1.05, r_aapl)
    trades.append(build_row("TEST_T01", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep1, sl1, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 1 (+1.05 R)"))

    # Trade 2 (+1.5 R -> 1.60 R): Triggert Trailing-Stop Start
    ep2, sl2 = calc_entry_and_sl(p_aapl, 1.60, r_aapl)
    trades.append(build_row("TEST_T02", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep2, sl2, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 2 (+1.60 R)"))

    # Trade 3 (+2.5 R -> 2.60 R): Triggert Chandelier +2.5R
    ep3, sl3 = calc_entry_and_sl(p_aapl, 2.60, r_aapl)
    trades.append(build_row("TEST_T03", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep3, sl3, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 3 (+2.60 R)"))

    # Trade 4 (+3.0 R -> 3.10 R): Triggert Parabolik-/Climax-Schutz
    ep4, sl4 = calc_entry_and_sl(p_aapl, 3.10, r_aapl)
    trades.append(build_row("TEST_T04", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep4, sl4, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 4 (+3.10 R)"))

    # Trade 5 (+4.0 R -> 4.10 R): Triggert Traum-Profit (+4.0R)
    ep5, sl5 = calc_entry_and_sl(p_aapl, 4.10, r_aapl)
    trades.append(build_row("TEST_T05", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep5, sl5, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 5 (+4.10 R)"))

    # Trade 6 (+6.0 R -> 6.20 R): Triggert Maximal-Profit (+6.0R Peak Protection)
    ep6, sl6 = calc_entry_and_sl(p_aapl, 6.20, r_aapl)
    trades.append(build_row("TEST_T06", "Privatkonto (10k)", now_str, "AAPL", "Apple Inc.", ep6, sl6, high_tp_aapl, "$", 1.0, "", 10, "PROP_DEFENSIVE", "Test Trade 6 (+6.20 R)"))

    # Trade 7 (Time-Stop): Vor 30 Tagen, atr_days=5 (0.20 R -> löst nur Time-Stop aus)
    ep7, sl7 = calc_entry_and_sl(p_aapl, 0.20, r_aapl)
    trades.append(build_row("TEST_T07", "Privatkonto (10k)", old_date_str, "AAPL", "Apple Inc.", ep7, sl7, high_tp_aapl, "$", 1.0, "", 5, "PROP_DEFENSIVE", "Test Trade 7 (Time-Stop 30d)"))

    # --- B. NQ=F (Profil apex_lock / TARGET_LOCKED) ---
    # Trade 8 (+1.0 R Tightening -> 1.20 R): Triggert Apex 80% Peak Protection
    ep8, sl8 = calc_entry_and_sl(p_nq, 1.20, r_nq)
    high_tp_nq = round(p_nq * 1.20, 2)
    trades.append(build_row("TEST_T08", "Apex 50k Demo", now_str, "NQ=F", "Nasdaq 100", ep8, sl8, high_tp_nq, "$", 2.0, "MNQ", 1, "TARGET_LOCKED", "Test Trade 8 (Apex Tightening +1.20 R)"))

    # --- C. EURUSD=X (Profil ftmo_swing / FTMO_SWING) ---
    # Trade 9 (SL Hit): curr_price <= sl_price (Entry und SL liegen über dem aktuellen Kurs)
    ep9 = round(p_eurusd + (2.0 * r_fx), 4)
    sl9 = round(p_eurusd + (1.0 * r_fx), 4)
    tp9 = round(p_eurusd + (5.0 * r_fx), 4)
    trades.append(build_row("TEST_T09", "FTMO 50k Demo", now_str, "EURUSD=X", "EUR/USD", ep9, sl9, tp9, "USD", 100000.0, "Lot", 5, "FTMO_SWING", "Test Trade 9 (SL Hit)"))

    # Trade 10 (TP Hit): curr_price >= tp_price (bei +0.5 R, damit nur TP-Hit feuert)
    ep10, sl10 = calc_entry_and_sl(p_eurusd, 0.50, r_fx)
    tp10 = round(p_eurusd - (0.10 * r_fx), 4)
    trades.append(build_row("TEST_T10", "FTMO 50k Demo", now_str, "EURUSD=X", "EUR/USD", ep10, sl10, tp10, "USD", 100000.0, "Lot", 5, "FTMO_SWING", "Test Trade 10 (TP Hit)"))

    # 4. In trade_journal.csv schreiben
    journal_file = os.path.join(user_dir, "trade_journal.csv")
    df_out = pd.DataFrame(trades)[cols]
    df_out.to_csv(journal_file, index=False)
    print(f"✅ 10 synthetische Test-Trades erfolgreich in '{journal_file}' geschrieben!")


if __name__ == "__main__":
    main()