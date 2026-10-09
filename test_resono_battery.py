# --- HIER STARTET DER NEUE CODE (Gesamte Datei test_resono_battery.py) ---
import json
import sys
import os

# Sicherstellen, dass resono.py aus dem gleichen Verzeichnis geladen werden kann
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resono


def run_test_battery():
    print("============================================================")
    print("🚀 STARTE ISOLIERTE RESONO TEST-BATTERIE (DETERMINISTISCH)")
    print("============================================================\n")

    # =========================================================================
    # 1. TEST-BATTERIE 1: APEX 50K DREIZONEN-MODELL & PHASEN-RESONANZ
    # =========================================================================
    print("--- [BATTERIE 1] APEX 50K DREIZONEN-MODELL & PHASEN-RESONANZ ---")

    # Szenario 1.1: Grün - Evaluation (MNQ)
    acc_1_1 = {
        "account_id": "EVAL_1_1",
        "account_type": "evaluation",
        "current_balance": 50000.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_1 = {"symbol": "MNQ", "stop_distance_points": 30.0, "point_value": 2.0}
    res_1_1 = resono.evaluate_account_risk(acc_1_1, sig_1_1)
    assert res_1_1["allowed"] is True, f"1.1 Fehler: allowed={res_1_1['allowed']}"
    assert res_1_1["status_code"] == "GREEN_FULL", f"1.1 Fehler: status_code={res_1_1['status_code']}"
    assert res_1_1["max_contracts"] == 3, f"1.1 Fehler: max_contracts={res_1_1['max_contracts']}"
    assert res_1_1["risk_buffer_usd"] == 2500.0, f"1.1 Fehler: risk_buffer_usd={res_1_1['risk_buffer_usd']}"
    print(f"  [OK] 1.1 Grün (Evaluation MNQ): Puffer=${res_1_1['risk_buffer_usd']} -> {res_1_1['max_contracts']} Kontrakte ({res_1_1['status_code']})")

    # Szenario 1.2: Grün - Evaluation MCL (Exakt Schwellenwert $1.500)
    acc_1_2 = {
        "account_id": "EVAL_1_2",
        "account_type": "evaluation",
        "current_balance": 49000.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_2 = {"symbol": "MCL", "stop_distance_points": 0.40, "point_value": 100.0}
    res_1_2 = resono.evaluate_account_risk(acc_1_2, sig_1_2)
    assert res_1_2["allowed"] is True, f"1.2 Fehler: allowed={res_1_2['allowed']}"
    assert res_1_2["status_code"] == "GREEN_FULL", f"1.2 Fehler: status_code={res_1_2['status_code']}"
    assert res_1_2["max_contracts"] == 2, f"1.2 Fehler: max_contracts={res_1_2['max_contracts']}"
    assert res_1_2["risk_buffer_usd"] == 1500.0, f"1.2 Fehler: risk_buffer_usd={res_1_2['risk_buffer_usd']}"
    print(f"  [OK] 1.2 Grün (Evaluation MCL @ $1.500 Grenze): Puffer=${res_1_2['risk_buffer_usd']} -> {res_1_2['max_contracts']} Kontrakte ({res_1_2['status_code']})")

    # Szenario 1.3: Gelb - Schonmodus
    acc_1_3 = {
        "account_id": "EVAL_1_3",
        "account_type": "evaluation",
        "current_balance": 48600.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_3 = {"symbol": "MNQ", "stop_distance_points": 30.0, "point_value": 2.0}
    res_1_3 = resono.evaluate_account_risk(acc_1_3, sig_1_3)
    assert res_1_3["allowed"] is True, f"1.3 Fehler: allowed={res_1_3['allowed']}"
    assert res_1_3["status_code"] == "YELLOW_THROTTLED", f"1.3 Fehler: status_code={res_1_3['status_code']}"
    assert res_1_3["max_contracts"] == 1, f"1.3 Fehler: max_contracts={res_1_3['max_contracts']}"
    assert res_1_3["risk_buffer_usd"] == 1100.0, f"1.3 Fehler: risk_buffer_usd={res_1_3['risk_buffer_usd']}"
    print(f"  [OK] 1.3 Gelb (Schonmodus): Puffer=${res_1_3['risk_buffer_usd']} -> {res_1_3['max_contracts']} Kontrakt ({res_1_3['status_code']})")

    # Szenario 1.4: Rot - MCL Asset-Sperre
    acc_1_4 = {
        "account_id": "EVAL_1_4",
        "account_type": "evaluation",
        "current_balance": 48000.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_4 = {"symbol": "MCL", "stop_distance_points": 0.40, "point_value": 100.0}
    res_1_4 = resono.evaluate_account_risk(acc_1_4, sig_1_4)
    assert res_1_4["allowed"] is False, f"1.4 Fehler: allowed={res_1_4['allowed']}"
    assert res_1_4["status_code"] == "VETO_ASSET_LOCKED", f"1.4 Fehler: status_code={res_1_4['status_code']}"
    assert res_1_4["max_contracts"] == 0, f"1.4 Fehler: max_contracts={res_1_4['max_contracts']}"
    assert res_1_4["risk_buffer_usd"] == 500.0, f"1.4 Fehler: risk_buffer_usd={res_1_4['risk_buffer_usd']}"
    print(f"  [OK] 1.4 Rot (MCL Asset-Sperre): Puffer=${res_1_4['risk_buffer_usd']} -> {res_1_4['max_contracts']} Kontrakte ({res_1_4['status_code']})")

    # Szenario 1.5: Rot - MNQ Sniper-Reha erfolgreich ($30 Risiko <= 20% von $500 = $100)
    acc_1_5 = {
        "account_id": "EVAL_1_5",
        "account_type": "evaluation",
        "current_balance": 48000.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_5 = {"symbol": "MNQ", "stop_distance_points": 15.0, "point_value": 2.0}
    res_1_5 = resono.evaluate_account_risk(acc_1_5, sig_1_5)
    assert res_1_5["allowed"] is True, f"1.5 Fehler: allowed={res_1_5['allowed']}"
    assert res_1_5["status_code"] == "RED_SNIPER", f"1.5 Fehler: status_code={res_1_5['status_code']}"
    assert res_1_5["max_contracts"] == 1, f"1.5 Fehler: max_contracts={res_1_5['max_contracts']}"
    assert res_1_5["trade_risk_usd"] == 30.0, f"1.5 Fehler: trade_risk_usd={res_1_5['trade_risk_usd']}"
    print(f"  [OK] 1.5 Rot (MNQ Sniper-Reha): Puffer=${res_1_5['risk_buffer_usd']}, Risiko=${res_1_5['trade_risk_usd']} -> {res_1_5['max_contracts']} Kontrakt ({res_1_5['status_code']})")

    # Szenario 1.6: Rot - MNQ Risiko zu hoch ($110 Risiko > 20% von $500 = $100)
    acc_1_6 = {
        "account_id": "EVAL_1_6",
        "account_type": "evaluation",
        "current_balance": 48000.0,
        "high_watermark": 50000.0,
        "has_open_position": False
    }
    sig_1_6 = {"symbol": "MNQ", "stop_distance_points": 55.0, "point_value": 2.0}
    res_1_6 = resono.evaluate_account_risk(acc_1_6, sig_1_6)
    assert res_1_6["allowed"] is False, f"1.6 Fehler: allowed={res_1_6['allowed']}"
    assert res_1_6["status_code"] == "RED_MUTED", f"1.6 Fehler: status_code={res_1_6['status_code']}"
    assert res_1_6["max_contracts"] == 0, f"1.6 Fehler: max_contracts={res_1_6['max_contracts']}"
    assert res_1_6["trade_risk_usd"] == 110.0, f"1.6 Fehler: trade_risk_usd={res_1_6['trade_risk_usd']}"
    print(f"  [OK] 1.6 Rot (MNQ Risiko zu hoch): Puffer=${res_1_6['risk_buffer_usd']}, Risiko=${res_1_6['trade_risk_usd']} -> Stumm ({res_1_6['status_code']})")

    # Szenario 1.7: PA-Festungsmodus (Balance $52.000 <= $53.100)
    acc_1_7 = {
        "account_id": "PA_1_7",
        "account_type": "funded_pa",
        "current_balance": 52000.0,
        "high_watermark": 52000.0,
        "has_open_position": False
    }
    sig_1_7 = {"symbol": "MNQ", "stop_distance_points": 30.0, "point_value": 2.0}
    res_1_7 = resono.evaluate_account_risk(acc_1_7, sig_1_7)
    assert res_1_7["allowed"] is True, f"1.7 Fehler: allowed={res_1_7['allowed']}"
    assert res_1_7["status_code"] == "GREEN_FULL", f"1.7 Fehler: status_code={res_1_7['status_code']}"
    assert res_1_7["max_contracts"] == 1, f"1.7 Fehler: max_contracts={res_1_7['max_contracts']}"
    print(f"  [OK] 1.7 PA-Festungsmodus ($52.000): Puffer=${res_1_7['risk_buffer_usd']} -> {res_1_7['max_contracts']} Kontrakt ({res_1_7['status_code']})")

    # Szenario 1.8: PA-Skalierung freigegeben (Balance $54.000 > $53.100 & KO-Lock bei $50.100)
    acc_1_8 = {
        "account_id": "PA_1_8",
        "account_type": "funded_pa",
        "current_balance": 54000.0,
        "high_watermark": 54000.0,
        "has_open_position": False
    }
    sig_1_8 = {"symbol": "MNQ", "stop_distance_points": 30.0, "point_value": 2.0}
    res_1_8 = resono.evaluate_account_risk(acc_1_8, sig_1_8)
    assert res_1_8["allowed"] is True, f"1.8 Fehler: allowed={res_1_8['allowed']}"
    assert res_1_8["status_code"] == "GREEN_FULL", f"1.8 Fehler: status_code={res_1_8['status_code']}"
    assert res_1_8["max_contracts"] == 2, f"1.8 Fehler: max_contracts={res_1_8['max_contracts']}"
    assert res_1_8["ko_threshold_usd"] == 50100.0, f"1.8 Fehler: ko_threshold_usd={res_1_8['ko_threshold_usd']}"
    print(f"  [OK] 1.8 PA-Skalierung ($54.000, Lock @ $50.100): Puffer=${res_1_8['risk_buffer_usd']} -> {res_1_8['max_contracts']} Kontrakte ({res_1_8['status_code']})")

    # Szenario 1.9: Kollisions-Veto (has_open_position=True)
    acc_1_9 = {
        "account_id": "EVAL_1_9",
        "account_type": "evaluation",
        "current_balance": 50000.0,
        "high_watermark": 50000.0,
        "has_open_position": True
    }
    sig_1_9 = {"symbol": "MNQ", "stop_distance_points": 30.0, "point_value": 2.0}
    res_1_9 = resono.evaluate_account_risk(acc_1_9, sig_1_9)
    assert res_1_9["allowed"] is False, f"1.9 Fehler: allowed={res_1_9['allowed']}"
    assert res_1_9["status_code"] == "VETO_OCCUPIED", f"1.9 Fehler: status_code={res_1_9['status_code']}"
    assert res_1_9["max_contracts"] == 0, f"1.9 Fehler: max_contracts={res_1_9['max_contracts']}"
    print(f"  [OK] 1.9 Kollisions-Veto (Offener Trade): allowed={res_1_9['allowed']} ({res_1_9['status_code']})\n")

    # =========================================================================
    # 2. TEST-BATTERIE 2: FLOTTEN-ALLOKATION & KOLLISIONSAUFLÖSUNG
    # =========================================================================
    print("--- [BATTERIE 2] FLOTTEN-ALLOKATION & KOLLISIONSAUFLÖSUNG (evaluate_fleet) ---")

    fleet_accounts = [
        {"account_id": "Acc_1_Green", "account_type": "evaluation", "current_balance": 50000.0, "high_watermark": 50000.0, "has_open_position": False},
        {"account_id": "Acc_2_Yellow", "account_type": "evaluation", "current_balance": 48800.0, "high_watermark": 50000.0, "has_open_position": False},
        {"account_id": "Acc_3_Red", "account_type": "evaluation", "current_balance": 48000.0, "high_watermark": 50000.0, "has_open_position": False},
        {"account_id": "Acc_4_Occupied", "account_type": "funded_pa", "current_balance": 50500.0, "high_watermark": 50500.0, "has_open_position": True}
    ]

    fleet_signals = [
        {"symbol": "MCL", "master_score": 68.0, "stop_distance_points": 0.40, "point_value": 100.0},
        {"symbol": "MNQ", "master_score": 50.0, "stop_distance_points": 15.0, "point_value": 2.0}
    ]

    # Vorab Plateau-Distanzen verifizieren
    dist_mcl = resono.calculate_plateau_distance("MCL", 68.0)
    dist_mnq = resono.calculate_plateau_distance("MNQ", 50.0)
    assert dist_mcl == 0.0, f"Plateau-Distanz MCL fehlerhaft: {dist_mcl}"
    assert dist_mnq == 5.0, f"Plateau-Distanz MNQ fehlerhaft: {dist_mnq}"
    print(f"  [OK] Plateau-Priorisierung: MCL Distanz={dist_mcl} (Prio 1) vor MNQ Distanz={dist_mnq} (Prio 2)")

    fleet_res = resono.evaluate_fleet(fleet_accounts, fleet_signals)
    summary = fleet_res["fleet_summary"]
    allocs = {a["account_id"]: a for a in fleet_res["allocations"]}

    # Einzelkonten-Prüfung
    assert allocs["Acc_1_Green"]["allocated_symbol"] == "MCL"
    assert allocs["Acc_1_Green"]["max_contracts"] == 2
    assert allocs["Acc_1_Green"]["status_code"] == "GREEN_FULL"

    assert allocs["Acc_2_Yellow"]["allocated_symbol"] == "MCL"
    assert allocs["Acc_2_Yellow"]["max_contracts"] == 1
    assert allocs["Acc_2_Yellow"]["status_code"] == "YELLOW_THROTTLED"

    assert allocs["Acc_3_Red"]["allocated_symbol"] == "MNQ"
    assert allocs["Acc_3_Red"]["max_contracts"] == 1
    assert allocs["Acc_3_Red"]["status_code"] == "RED_SNIPER"

    assert allocs["Acc_4_Occupied"]["allocated_symbol"] is None
    assert allocs["Acc_4_Occupied"]["max_contracts"] == 0
    assert allocs["Acc_4_Occupied"]["status_code"] == "VETO_OCCUPIED"

    # Summenprüfung
    assert summary["total_accounts"] == 4, f"total_accounts={summary['total_accounts']}"
    assert summary["approved_accounts"] == 1, f"approved_accounts={summary['approved_accounts']}"
    assert summary["throttled_accounts"] == 2, f"throttled_accounts={summary['throttled_accounts']}"
    assert summary["muted_accounts"] == 1, f"muted_accounts={summary['muted_accounts']}"

    print(f"  [OK] Acc 1 (Grün):   -> {allocs['Acc_1_Green']['allocated_symbol']} ({allocs['Acc_1_Green']['max_contracts']} Kontrakte, {allocs['Acc_1_Green']['status_code']})")
    print(f"  [OK] Acc 2 (Gelb):   -> {allocs['Acc_2_Yellow']['allocated_symbol']} ({allocs['Acc_2_Yellow']['max_contracts']} Kontrakt, {allocs['Acc_2_Yellow']['status_code']})")
    print(f"  [OK] Acc 3 (Rot):    -> MCL blockiert, Fallback auf {allocs['Acc_3_Red']['allocated_symbol']} ({allocs['Acc_3_Red']['max_contracts']} Kontrakt, {allocs['Acc_3_Red']['status_code']})")
    print(f"  [OK] Acc 4 (Belegt): -> {allocs['Acc_4_Occupied']['allocated_symbol']} ({allocs['Acc_4_Occupied']['status_code']})")
    print(f"  [OK] Fleet Summary:  approved={summary['approved_accounts']}, throttled={summary['throttled_accounts']}, muted={summary['muted_accounts']}, total_risk=${summary['total_risk_usd']:.2f}\n")

    # =========================================================================
    # 3. TEST-BATTERIE 3: FTMO FOREX FLASCHENHALS-PUFFER (evaluate_ftmo_risk)
    # =========================================================================
    print("--- [BATTERIE 3] FTMO FOREX FLASCHENHALS-PUFFER (evaluate_ftmo_risk) ---")

    # Szenario 3.1: Voller Tages- und Gesamtpuffer (100k Konto, Stop 35 Pips GBPUSD)
    ftmo_acc_3_1 = {
        "initial_balance": 100000.0,
        "day_start_balance": 100000.0,
        "current_balance": 100000.0,
        "has_open_position": False
    }
    ftmo_sig_3_1 = {"symbol": "GBPUSD=X", "sl_pips": 35.0, "point_value": 100000.0, "score": 65.0}
    res_3_1 = resono.evaluate_ftmo_risk(ftmo_acc_3_1, ftmo_sig_3_1)
    assert res_3_1["zone"] == "GREEN", f"3.1 Fehler: zone={res_3_1['zone']}"
    assert res_3_1["allowed"] is True, f"3.1 Fehler: allowed={res_3_1['allowed']}"
    assert res_3_1["status_code"] == "GREEN_FULL", f"3.1 Fehler: status_code={res_3_1['status_code']}"
    assert res_3_1["effective_buffer"] == 5000.0, f"3.1 Fehler: effective_buffer={res_3_1['effective_buffer']}"
    assert res_3_1["allocated_risk_usd"] == 250.0, f"3.1 Fehler: allocated_risk_usd={res_3_1['allocated_risk_usd']}"
    assert res_3_1["max_lots"] == 0.71, f"3.1 Fehler: max_lots={res_3_1['max_lots']}"
    print(f"  [OK] 3.1 FTMO Grün (100k voll): Eff. Puffer=${res_3_1['effective_buffer']} -> Budget=${res_3_1['allocated_risk_usd']} (5.0%) -> {res_3_1['max_lots']} Lots")

    # Szenario 3.2: Flaschenhals-Prüfung (Gesamtdrawdown schlägt Tagespuffer)
    # Initial $100k, Day-Start $91.500 (Tagespuffer $5.000), Balance $91.500 (Max-DD-Puffer über $90k ist nur $1.500)
    ftmo_acc_3_2 = {
        "initial_balance": 100000.0,
        "day_start_balance": 91500.0,
        "current_balance": 91500.0,
        "has_open_position": False
    }
    ftmo_sig_3_2 = {"symbol": "GBPUSD=X", "sl_pips": 35.0, "point_value": 100000.0, "score": 50.0}
    res_3_2 = resono.evaluate_ftmo_risk(ftmo_acc_3_2, ftmo_sig_3_2)
    assert res_3_2["effective_buffer"] == 1500.0, f"3.2 Fehler: effective_buffer={res_3_2['effective_buffer']}"
    assert res_3_2["zone"] == "YELLOW" or res_3_2["zone"] == "RED", f"3.2 Fehler: zone={res_3_2['zone']}"
    # Hinweis: Daily Limit bei 100k ist $5.000. 30% von $5.000 = $1.500.
    # Um strikt < 30% ($1.500) für Rote Zone oder exakt die Flaschenhals-Drosselung zu zeigen, prüfen wir zusätzlich $91.400 ($1.400 < $1.500):
    ftmo_acc_3_2_red = {
        "initial_balance": 100000.0,
        "day_start_balance": 91400.0,
        "current_balance": 91400.0,
        "has_open_position": False
    }
    res_3_2_red = resono.evaluate_ftmo_risk(ftmo_acc_3_2_red, ftmo_sig_3_2)
    assert res_3_2_red["effective_buffer"] == 1400.0, f"3.2b Fehler: effective_buffer={res_3_2_red['effective_buffer']}"
    assert res_3_2_red["zone"] == "RED", f"3.2b Fehler: zone={res_3_2_red['zone']}"
    print(f"  [OK] 3.2 Flaschenhals-Schutz: Tagespuffer=$5.000, aber Max-DD-Restpuffer=${res_3_2['effective_buffer']} (bzw. $1.400 -> Zone={res_3_2_red['zone']}) greift!\n")

    # =========================================================================
    # 4. TEST-BATTERIE 4: FTMO FOREX SNIPER-REHABILITATION IN DER ROTEN ZONE
    # =========================================================================
    print("--- [BATTERIE 4] FTMO FOREX SNIPER-REHABILITATION IN DER ROTEN ZONE ---")

    # Szenario 4.1: Rote Zone mit schwachem Setup (Buffer $1.200, Score 45.0 < 60)
    ftmo_acc_4_1 = {
        "account_size": 100000.0,
        "current_balance": 96200.0,
        "daily_loss_limit": 5000.0,
        "daily_buffer": 1200.0,
        "has_open_position": False
    }
    ftmo_sig_4_1 = {"symbol": "EURUSD=X", "sl_pips": 25.0, "point_value": 100000.0, "score": 45.0}
    res_4_1 = resono.evaluate_ftmo_risk(ftmo_acc_4_1, ftmo_sig_4_1)
    assert res_4_1["zone"] == "RED", f"4.1 Fehler: zone={res_4_1['zone']}"
    assert res_4_1["allowed"] is False, f"4.1 Fehler: allowed={res_4_1['allowed']}"
    assert res_4_1["status_code"] == "RED_MUTED", f"4.1 Fehler: status_code={res_4_1['status_code']}"
    assert res_4_1["max_lots"] == 0.0, f"4.1 Fehler: max_lots={res_4_1['max_lots']}"
    print(f"  [OK] 4.1 Rote Zone (Schwaches Setup, Score 45): allowed={res_4_1['allowed']}, status={res_4_1['status_code']}, Lots={res_4_1['max_lots']}")

    # Szenario 4.2: Rote Zone mit A+-Setup & Reha-Freigabe (Buffer $1.200, Score 72.0 >= 60, Stop 25 Pips)
    ftmo_acc_4_2 = {
        "account_size": 100000.0,
        "current_balance": 96200.0,
        "daily_loss_limit": 5000.0,
        "daily_buffer": 1200.0,
        "has_open_position": False
    }
    ftmo_sig_4_2 = {"symbol": "EURUSD=X", "sl_pips": 25.0, "point_value": 100000.0, "score": 72.0}
    res_4_2 = resono.evaluate_ftmo_risk(ftmo_acc_4_2, ftmo_sig_4_2)
    assert res_4_2["zone"] == "RED", f"4.2 Fehler: zone={res_4_2['zone']}"
    assert res_4_2["allowed"] is True, f"4.2 Fehler: allowed={res_4_2['allowed']}"
    assert res_4_2["status_code"] == "SNIPER_REHAB", f"4.2 Fehler: status_code={res_4_2['status_code']}"
    assert res_4_2["allocated_risk_usd"] == 120.0, f"4.2 Fehler: allocated_risk_usd={res_4_2['allocated_risk_usd']}"
    assert res_4_2["max_lots"] == 0.48, f"4.2 Fehler: max_lots={res_4_2['max_lots']}"
    print(f"  [OK] 4.2 Rote Zone (A+ Setup, Score 72): allowed={res_4_2['allowed']}, status={res_4_2['status_code']}, Budget=${res_4_2['allocated_risk_usd']}, Lots={res_4_2['max_lots']}")

    # Szenario 4.3: Rote Zone mit verbranntem Puffer < $50 (Buffer $35.0, Score 75.0)
    ftmo_acc_4_3 = {
        "account_size": 100000.0,
        "current_balance": 95035.0,
        "daily_loss_limit": 5000.0,
        "daily_buffer": 35.0,
        "has_open_position": False
    }
    ftmo_sig_4_3 = {"symbol": "EURUSD=X", "sl_pips": 25.0, "point_value": 100000.0, "score": 75.0}
    res_4_3 = resono.evaluate_ftmo_risk(ftmo_acc_4_3, ftmo_sig_4_3)
    assert res_4_3["zone"] == "RED", f"4.3 Fehler: zone={res_4_3['zone']}"
    assert res_4_3["allowed"] is False, f"4.3 Fehler: allowed={res_4_3['allowed']}"
    assert res_4_3["status_code"] == "RED_MUTED", f"4.3 Fehler: status_code={res_4_3['status_code']}"
    assert res_4_3["max_lots"] == 0.0, f"4.3 Fehler: max_lots={res_4_3['max_lots']}"
    print(f"  [OK] 4.3 Rote Zone (Puffer $35 < $50 Notbremse): allowed={res_4_3['allowed']}, status={res_4_3['status_code']}, Lots={res_4_3['max_lots']}\n")

    print("============================================================")
    print("✅ ALLE 4 RESONO TEST-BATTERIEN ERFOLGREICH BESTANDEN (15/15)")
    print("============================================================")


if __name__ == "__main__":
    run_test_battery()
# --- ENDE DER DATEI ---