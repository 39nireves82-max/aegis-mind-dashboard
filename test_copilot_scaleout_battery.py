import os
import csv
import json
import argparse
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_DIR = os.path.join(BASE_DIR, "users", "admin")
JOURNAL_PATH = os.path.join(ADMIN_DIR, "trade_journal.csv")
STATE_PATH = os.path.join(ADMIN_DIR, "alert_state.json")

COLUMNS = [
    "id", "account_name", "entry_date", "exit_date", "symbol", "name", "direction",
    "signal_price", "entry_price", "currency", "fx_rate", "position_size", "contract_type",
    "point_value", "base_currency", "invest_eur", "sl_price", "current_sl", "tp_price",
    "planned_risk_eur", "current_risk_eur", "est_fees_eur", "master_score", "setup_type",
    "mc_robustness", "atr_days", "exit_mode", "status", "exit_price", "pnl_eur", "pnl_pct",
    "r_multiple", "exit_reason", "notes", "strategy_version", "execution_type"
]

SEED_DATA = [
    {
        "id": "TEST_SO_MNQ_LONG", "account_name": "Apex 50k Demo", "entry_date": "01/11/2026 15:30", "exit_date": "",
        "symbol": "MNQ", "name": "Micro E-mini Nasdaq", "direction": "Long",
        "signal_price": 20000.00, "entry_price": 20000.00, "currency": "USD", "fx_rate": 0.92,
        "position_size": 2.0, "contract_type": "", "point_value": 2.0, "base_currency": "EUR",
        "invest_eur": 73600.00, "sl_price": 19950.00, "current_sl": 19950.00, "tp_price": 0.00,
        "planned_risk_eur": 184.00, "current_risk_eur": 184.00, "est_fees_eur": 4.00,
        "master_score": 75, "setup_type": "Setup B Trend-Pullback", "mc_robustness": "N/A", "atr_days": 10,
        "exit_mode": "PROP_DEFENSIVE", "status": "OPEN", "exit_price": "", "pnl_eur": "", "pnl_pct": "",
        "r_multiple": "", "exit_reason": "", "notes": "Co-Pilot Scale-Out Test 1", "strategy_version": "v1.0.0", "execution_type": "HISTORICAL_MANUAL"
    },
    {
        "id": "TEST_SO_MCL_SHORT", "account_name": "Apex 50k Demo", "entry_date": "01/11/2026 15:30", "exit_date": "",
        "symbol": "MCL", "name": "Micro Crude Oil", "direction": "Short",
        "signal_price": 70.00, "entry_price": 70.00, "currency": "USD", "fx_rate": 0.92,
        "position_size": 2.0, "contract_type": "", "point_value": 100.0, "base_currency": "EUR",
        "invest_eur": 12880.00, "sl_price": 71.00, "current_sl": 71.00, "tp_price": 0.00,
        "planned_risk_eur": 184.00, "current_risk_eur": 184.00, "est_fees_eur": 4.00,
        "master_score": 72, "setup_type": "Setup B Trend-Pullback", "mc_robustness": "N/A", "atr_days": 10,
        "exit_mode": "PROP_DEFENSIVE", "status": "OPEN", "exit_price": "", "pnl_eur": "", "pnl_pct": "",
        "r_multiple": "", "exit_reason": "", "notes": "Co-Pilot Scale-Out Test 2", "strategy_version": "v1.0.0", "execution_type": "HISTORICAL_MANUAL"
    },
    {
        "id": "TEST_SO_EURUSD_LONG", "account_name": "FTMO 50k Demo", "entry_date": "01/11/2026 15:30", "exit_date": "",
        "symbol": "EURUSD=X", "name": "Euro / US Dollar", "direction": "Long",
        "signal_price": 1.0800, "entry_price": 1.0800, "currency": "USD", "fx_rate": 0.92,
        "position_size": 0.04, "contract_type": "", "point_value": 100000.0, "base_currency": "EUR",
        "invest_eur": 3974.40, "sl_price": 1.0760, "current_sl": 1.0760, "tp_price": 0.00,
        "planned_risk_eur": 147.20, "current_risk_eur": 147.20, "est_fees_eur": 0.24,
        "master_score": 70, "setup_type": "Setup B Trend-Pullback", "mc_robustness": "N/A", "atr_days": 10,
        "exit_mode": "ftmo_swing", "status": "OPEN", "exit_price": "", "pnl_eur": "", "pnl_pct": "",
        "r_multiple": "", "exit_reason": "", "notes": "Co-Pilot Scale-Out Test 3", "strategy_version": "v1.0.0", "execution_type": "HISTORICAL_MANUAL"
    },
    {
        "id": "TEST_SO_MIN_LOCK", "account_name": "Apex 50k Demo", "entry_date": "01/11/2026 15:30", "exit_date": "",
        "symbol": "MNQ", "name": "Micro E-mini Nasdaq (Min-Lock)", "direction": "Long",
        "signal_price": 20000.00, "entry_price": 20000.00, "currency": "USD", "fx_rate": 0.92,
        "position_size": 1.0, "contract_type": "", "point_value": 2.0, "base_currency": "EUR",
        "invest_eur": 36800.00, "sl_price": 19950.00, "current_sl": 19950.00, "tp_price": 0.00,
        "planned_risk_eur": 92.00, "current_risk_eur": 92.00, "est_fees_eur": 2.00,
        "master_score": 75, "setup_type": "Setup B Trend-Pullback", "mc_robustness": "N/A", "atr_days": 10,
        "exit_mode": "PROP_DEFENSIVE", "status": "OPEN", "exit_price": "", "pnl_eur": "", "pnl_pct": "",
        "r_multiple": "", "exit_reason": "", "notes": "Poka-Yoke Lock Test", "strategy_version": "v1.0.0", "execution_type": "HISTORICAL_MANUAL"
    }
]

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv_atomic(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".csv")
    with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)

def cmd_seed():
    rows = read_csv(JOURNAL_PATH)
    existing_ids = {r['id'] for r in rows}
    
    injected = 0
    for seed_trade in SEED_DATA:
        if seed_trade['id'] not in existing_ids:
            rows.append(seed_trade)
            injected += 1
            
    if injected > 0:
        write_csv_atomic(JOURNAL_PATH, rows)
        
    print("\n✅ Seed erfolgreich! Folgende Trades stehen im UI bereit:")
    print("-" * 90)
    print(f"{'Trade ID':<22} | {'Symbol':<10} | {'Qty':<5} | {'Fokus für Test'}")
    print("-" * 90)
    print(f"{'TEST_SO_MNQ_LONG':<22} | {'MNQ':<10} | {'2.0':<5} | {'Standard 50% Scale-Out (Long)'}")
    print(f"{'TEST_SO_MCL_SHORT':<22} | {'MCL':<10} | {'2.0':<5} | {'Hoher Punktwert (100.0) Scale-Out (Short)'}")
    print(f"{'TEST_SO_EURUSD_LONG':<22} | {'EURUSD=X':<10} | {'0.04':<5} | {'Dezimal-Lots & Forex Net-BE (Long)'}")
    print(f"{'TEST_SO_MIN_LOCK':<22} | {'MNQ':<10} | {'1.0':<5} | {'Poka-Yoke: Scale-Out Button muss gesperrt sein'}")
    print("-" * 90)
    print("▶️ Bitte jetzt im Browser auf '⚖️ Co-Pilot Scale-Out' klicken und testen.")

def cmd_verify():
    rows = read_csv(JOURNAL_PATH)
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f: alert_state = json.load(f)
    except:
        alert_state = {}

    test_ids = ["TEST_SO_MNQ_LONG", "TEST_SO_MCL_SHORT", "TEST_SO_EURUSD_LONG"]
    splits_found = 0
    all_passed = True
    
    for base_id in test_ids:
        t2_runner = next((r for r in rows if r['id'] == base_id), None)
        t1_splits = [r for r in rows if r['id'].startswith(f"{base_id}_SO")]
        
        if not t1_splits or not t2_runner:
            continue
            
        splits_found += 1
        t1 = t1_splits[0]
        orig_seed = next((s for s in SEED_DATA if s['id'] == base_id), None)
        
        print(f"\n🔍 Prüfe forensisch: {base_id} ...")
        
        # 1. Status-Prüfung
        stat_ok = (t1['status'] == "CLOSED" and t2_runner['status'] == "OPEN")
        if not stat_ok: 
            print(f"  ❌ Fehler (Status): T1={t1['status']}, T2={t2_runner['status']}")
            all_passed = False
        else: print("  ✅ Status-Prüfung bestanden")

        # 2. Mengen-Prüfung
        orig_qty = float(orig_seed['position_size'])
        t1_qty = float(t1['position_size'])
        t2_qty = float(t2_runner['position_size'])
        qty_ok = abs((t1_qty + t2_qty) - orig_qty) < 0.0001
        if not qty_ok: 
            print(f"  ❌ Fehler (Menge): {t1_qty} + {t2_qty} != {orig_qty}")
            all_passed = False
        else: print("  ✅ Mengen-Erhaltung bestanden")

        # 3. Cent-Residuen-Prüfung
        inv_ok = abs((float(t1['invest_eur'] or 0) + float(t2_runner['invest_eur'] or 0)) - float(orig_seed['invest_eur'])) <= 0.01
        risk_ok = abs((float(t1['planned_risk_eur'] or 0) + float(t2_runner['planned_risk_eur'] or 0)) - float(orig_seed['planned_risk_eur'])) <= 0.01
        fees_ok = abs((float(t1['est_fees_eur'] or 0) + float(t2_runner['est_fees_eur'] or 0)) - float(orig_seed['est_fees_eur'])) <= 0.01
        if not (inv_ok and risk_ok and fees_ok):
            print("  ❌ Fehler (Cent-Residuen): Splitting von Kapital, Risiko oder Gebühren inkorrekt.")
            all_passed = False
        else: print("  ✅ Cent-Residuen mathematisch perfekt")

        # 4. Net-Break-Even & Risk
        orig_entry = float(orig_seed['entry_price'])
        current_sl = float(t2_runner['current_sl'])
        current_risk = float(t2_runner['current_risk_eur'] or 0)
        is_long = orig_seed['direction'].upper() == 'LONG'
        
        be_ok = (current_sl > orig_entry) if is_long else (current_sl < orig_entry)
        risk_free_ok = (current_risk == 0.0)
        
        if not (be_ok and risk_free_ok):
            print(f"  ❌ Fehler (Net-BE): SL={current_sl}, Risk={current_risk}. Runner nicht auf Risk-Free!")
            all_passed = False
        else: print("  ✅ Net-Break-Even Setzung & Risk-Free verifiziert")

        # 5. Alert-State Prüfung
        alert_ok = (alert_state.get(f"{base_id}_be") is True) and (alert_state.get(f"{base_id}_trail") is True)
        if not alert_ok:
            print("  ❌ Fehler (Alert-State): Flags für _be und _trail fehlen in JSON.")
            all_passed = False
        else: print("  ✅ Alert-State JSON-Signatur verifiziert")

    if splits_found == 0:
        print("\n⏳ Noch keine ausgeführten Splits gefunden. Bitte im Browser auf '⚖️ Co-Pilot Scale-Out' klicken.")
    elif all_passed:
        print("\n\033[92m✅ ALLE FORENSISCHEN PRÜFUNGEN BESTANDEN\033[0m")
    else:
        print("\n\033[91m⚠️ PRÜFUNG FEHLGESCHLAGEN. Bitte obige Deltas prüfen.\033[0m")

def cmd_clean():
    # 1. Clean CSV
    rows = read_csv(JOURNAL_PATH)
    filtered_rows = [r for r in rows if not r['id'].startswith("TEST_SO_")]
    write_csv_atomic(JOURNAL_PATH, filtered_rows)
    
    # 2. Clean JSON
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f: state = json.load(f)
            filtered_state = {k: v for k, v in state.items() if "TEST_SO_" not in k}
            
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATE_PATH), suffix=".json")
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(filtered_state, f, indent=4)
            os.replace(tmp_path, STATE_PATH)
        except Exception as e:
            print(f"Warnung beim JSON Clean: {e}")
            
    print("🧹 Alle Test-Trades und State-Flags restlos aus dem Admin-Profil entfernt.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="INVARIX - Co-Pilot Scale-Out Test Battery")
    parser.add_argument("--seed", action="store_true", help="Injiziert deterministisch 4 synthetische Test-Trades.")
    parser.add_argument("--verify", action="store_true", help="Forensischer Soll-Ist-Abgleich der Teilverkäufe.")
    parser.add_argument("--clean", action="store_true", help="Löscht alle Test-Trades restlos.")
    args = parser.parse_args()

    if args.seed:
        cmd_seed()
    elif args.verify:
        cmd_verify()
    elif args.clean:
        cmd_clean()
    else:
        parser.print_help()