from typing import Dict, Any

def evaluate_account_risk(account_dict: Dict[str, Any], signal_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kernevaluierung des Account-Risikos (RESONO-Modul).
    Prüft Puffer, Kollisionen und setzt Phasen-Resonanz (Dreizonen-Modell) um.
    """
    account_id = account_dict.get('account_id', 'Unknown')
    account_type = account_dict.get('account_type', 'evaluation')
    current_balance = float(account_dict.get('current_balance', 0.0))
    high_watermark = float(account_dict.get('high_watermark', 0.0))
    has_open_position = bool(account_dict.get('has_open_position', False))

    symbol = signal_dict.get('symbol', 'MNQ')
    stop_distance_points = float(signal_dict.get('stop_distance_points', 0.0))
    point_value = float(signal_dict.get('point_value', 2.0))
    
    # 1. Monetäres Trade-Risiko für 1 Kontrakt berechnen
    trade_risk_usd = stop_distance_points * point_value

    # 2. Veto-Check: Offene Positionen
    if has_open_position:
        return {
            'allowed': False,
            'status_code': 'VETO_OCCUPIED',
            'max_contracts': 0,
            'risk_buffer_usd': 0.0,
            'ko_threshold_usd': 0.0,
            'trade_risk_usd': trade_risk_usd,
            'ui_badge': '🔴 Gesperrt',
            'ui_reason': 'Konto belegt: Maximal 1 offener Trade erlaubt'
        }

    # 3. K.O.-Schwelle und effektiven Restpuffer berechnen (Apex 50k Standard)
    raw_ko_threshold = high_watermark - 2500.0
    
    # Freeze-Regel (High-Watermark Lock)
    if raw_ko_threshold >= 50100.0:
        ko_threshold_usd = 50100.0
    else:
        ko_threshold_usd = raw_ko_threshold

    risk_buffer_usd = current_balance - ko_threshold_usd
    
    # Kollabiertes Konto abfangen
    if risk_buffer_usd < 0:
        risk_buffer_usd = 0.0

    # Initialisierung der Rückgabewerte
    allowed = False
    status_code = ''
    max_contracts = 0
    ui_badge = ''
    ui_reason = ''

    # 4. Dreizonen-Modell & Phasen-Resonanz auswerten
    if risk_buffer_usd >= 1500.0:
        # --- GRÜNE ZONE ---
        if account_type == 'evaluation':
            allowed = True
            status_code = 'GREEN_FULL'
            max_contracts = 3 if symbol == 'MNQ' else (2 if symbol == 'MCL' else 1)
            ui_badge = f'🟢 Freigegeben ({max_contracts} {symbol})'
            ui_reason = f'Grüne Zone (Puffer: {risk_buffer_usd:.2f} USD). Volle Skalierung für Evaluation freigegeben.'
            
        elif account_type == 'funded_pa':
            allowed = True
            status_code = 'GREEN_FULL'
            # Check auf Freeze-Schwelle für PA-Skalierung
            if ko_threshold_usd == 50100.0 and current_balance > 53100.0:
                max_contracts = 2
                ui_badge = f'🟢 Freigegeben ({max_contracts} {symbol})'
                ui_reason = f'Grüne Zone (Puffer: {risk_buffer_usd:.2f} USD). Reifes PA-Konto: Skalierung auf 2 Kontrakte freigegeben.'
            else:
                max_contracts = 1
                ui_badge = f'🟢 Freigegeben ({max_contracts} {symbol})'
                ui_reason = f'Grüne Zone (Puffer: {risk_buffer_usd:.2f} USD). PA-Konto im Festungsmodus (max. 1 Kontrakt).'

    elif 800.0 <= risk_buffer_usd < 1500.0:
        # --- GELBE ZONE ---
        allowed = True
        status_code = 'YELLOW_THROTTLED'
        max_contracts = 1
        ui_badge = f'🟡 Schonmodus (1 {symbol})'
        ui_reason = f'Gelbe Zone (Puffer: {risk_buffer_usd:.2f} USD). Strikt auf 1 Kontrakt gedrosselt.'

    else:
        # --- ROTE ZONE (< 800 USD) ---
        if symbol == 'MCL':
            allowed = False
            status_code = 'VETO_ASSET_LOCKED'
            max_contracts = 0
            ui_badge = '🔴 Gesperrt (MCL)'
            ui_reason = f'Rote Zone (Puffer: {risk_buffer_usd:.2f} USD). MCL bei akuter K.O.-Gefahr ausnahmslos gesperrt.'
        else:
            # Sniper-Rehabilitations-Modus für MNQ
            if trade_risk_usd <= (0.20 * risk_buffer_usd) and risk_buffer_usd > 0:
                allowed = True
                status_code = 'RED_SNIPER'
                max_contracts = 1
                ui_badge = f'🔴 Sniper-Modus (1 {symbol})'
                ui_reason = f'Rote Zone (Puffer: {risk_buffer_usd:.2f} USD). Risiko ({trade_risk_usd:.2f} USD) <= 20% des Puffers. Sniper-Modus aktiv.'
            else:
                allowed = False
                status_code = 'RED_MUTED'
                max_contracts = 0
                ui_badge = '🔴 Stummgeschaltet'
                ui_reason = f'Rote Zone (Puffer: {risk_buffer_usd:.2f} USD). Risiko ({trade_risk_usd:.2f} USD) übersteigt 20% des Puffers. Stummgeschaltet.'

    return {
        'allowed': allowed,
        'status_code': status_code,
        'max_contracts': max_contracts,
        'risk_buffer_usd': round(risk_buffer_usd, 2),
        'ko_threshold_usd': round(ko_threshold_usd, 2),
        'trade_risk_usd': round(trade_risk_usd, 2),
        'ui_badge': ui_badge,
        'ui_reason': ui_reason
    }
def calculate_plateau_distance(symbol: str, master_score: float) -> float:
    """
    Berechnet die statistische Setup-Güte basierend auf den validierten Optimum-Korridoren.
    """
    if symbol == 'MNQ':
        opt_min, opt_max = 55.0, 60.0
    elif symbol == 'MCL':
        opt_min, opt_max = 65.0, 70.0
    else:
        opt_min, opt_max = 0.0, 0.0

    if master_score < opt_min:
        return opt_min - master_score
    elif master_score > opt_max:
        return master_score - opt_max
    else:
        return 0.0


def evaluate_fleet(accounts_list: list, incoming_signals: list) -> dict:
    """
    Bewertet eine Flotte von Konten und löst Kollisionen bei zeitgleichen Signalen algorithmisch auf.
    """
    # Signale sortieren: Geringste Distanz zuerst, bei Gleichstand höchster Score
    sorted_signals = sorted(
        incoming_signals, 
        key=lambda sig: (
            calculate_plateau_distance(sig.get('symbol', ''), float(sig.get('master_score', 0.0))),
            -float(sig.get('master_score', 0.0))
        )
    )

    fleet_summary = {
        'total_accounts': len(accounts_list),
        'approved_accounts': 0,
        'throttled_accounts': 0,
        'muted_accounts': 0,
        'total_risk_usd': 0.0
    }
    
    allocations = []

    for acc in accounts_list:
        acc_id = acc.get('account_id', 'Unknown')
        
        # Veto-Check vorab für belegte Konten
        if acc.get('has_open_position', False):
            dummy_sig = sorted_signals[0] if sorted_signals else {'symbol': 'NONE', 'stop_distance_points': 0, 'point_value': 0}
            res = evaluate_account_risk(acc, dummy_sig)
            allocations.append({
                'account_id': acc_id,
                'allocated_symbol': None,
                'max_contracts': 0,
                'status_code': res['status_code'],
                'ui_badge': res['ui_badge'],
                'ui_reason': res['ui_reason']
            })
            fleet_summary['muted_accounts'] += 1
            continue

        allocated = False
        best_res = None

        for sig in sorted_signals:
            res = evaluate_account_risk(acc, sig)
            if best_res is None:
                best_res = res  # Fallback merken, falls kein Signal erlaubt ist
            
            if res['allowed']:
                allocations.append({
                    'account_id': acc_id,
                    'allocated_symbol': sig.get('symbol'),
                    'max_contracts': res['max_contracts'],
                    'status_code': res['status_code'],
                    'ui_badge': res['ui_badge'],
                    'ui_reason': res['ui_reason']
                })
                fleet_summary['total_risk_usd'] += res['trade_risk_usd'] * res['max_contracts']
                
                if res['status_code'] == 'GREEN_FULL':
                    fleet_summary['approved_accounts'] += 1
                else:
                    fleet_summary['throttled_accounts'] += 1
                
                allocated = True
                break
        
        # Fallback: Wenn kein Signal zugewiesen werden konnte (oder keins existiert)
        if not allocated:
            if best_res is not None:
                allocations.append({
                    'account_id': acc_id,
                    'allocated_symbol': None,
                    'max_contracts': 0,
                    'status_code': best_res['status_code'],
                    'ui_badge': best_res['ui_badge'],
                    'ui_reason': best_res['ui_reason']
                })
                fleet_summary['muted_accounts'] += 1
            else:
                # Edge Case: incoming_signals Liste war komplett leer
                allocations.append({
                    'account_id': acc_id,
                    'allocated_symbol': None,
                    'max_contracts': 0,
                    'status_code': 'NO_SIGNAL',
                    'ui_badge': '⚪ Kein Signal',
                    'ui_reason': 'Keine Signale zur Zuweisung übergeben.'
                })

    return {
        'fleet_summary': fleet_summary,
        'allocations': allocations
    }
def evaluate_ftmo_risk(account_dict: Dict[str, Any], signal_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bewertet das Risiko und berechnet die Positionsgröße (Lots) für FTMO Forex-Swings
    basierend auf dem Flaschenhals-Prinzip (Minimum aus Tagespuffer und Max-DD-Puffer)
    inklusive Sniper-Rehabilitationsmodus in der Roten Zone.
    """
    account_size = float(account_dict.get("account_size", account_dict.get("initial_balance", 50000.0)))
    current_balance = float(account_dict.get("current_balance", account_size))
    daily_limit = float(account_dict.get("daily_loss_limit", account_size * 0.05))
    
    if "daily_buffer" in account_dict and account_dict.get("daily_buffer") is not None:
        daily_buffer = float(account_dict.get("daily_buffer", daily_limit))
    elif "day_start_balance" in account_dict:
        day_start = float(account_dict.get("day_start_balance", account_size))
        daily_buffer = max(0.0, current_balance - (day_start - daily_limit))
    else:
        daily_buffer = daily_limit

    has_open_position = bool(account_dict.get("has_open_position", False))

    max_loss_threshold = account_size * 0.90
    max_dd_buffer = max(0.0, current_balance - max_loss_threshold)

    # 1. FLASCHENHALS-PUFFER
    effective_buffer = max(0.0, min(daily_buffer, max_dd_buffer))
    effective_threshold_usd = current_balance - effective_buffer

    pt_val = float(signal_dict.get("point_value", 100000.0))
    sl_dist = float(signal_dict.get("stop_loss_distance", 0.0))
    if sl_dist <= 0.0 and "sl_pips" in signal_dict:
        sl_dist = float(signal_dict.get("sl_pips", 0.0)) / 10000.0
    score = float(signal_dict.get("score", 0.0))

    # 2. Veto-Check: Offene Positionen
    if has_open_position:
        return {
            'allowed': False,
            'zone': 'RED',
            'status_code': 'VETO_OCCUPIED',
            'max_lots': 0.0,
            'daily_buffer_usd': round(effective_buffer, 2),
            'effective_buffer': round(effective_buffer, 2),
            'effective_threshold_usd': round(effective_threshold_usd, 2),
            'allocated_risk_usd': 0.0,
            'ui_badge': '🔴 Gesperrt',
            'ui_reason': 'Konto belegt: Maximal 1 offener Trade erlaubt.'
        }

    allowed = False
    zone = 'GREEN'
    status_code = ''
    max_lots = 0.0
    allocated_risk_usd = 0.0
    ui_badge = ''
    ui_reason = ''

    # 3. DYNAMISCHE ZONEN & SNIPER-REHA (FOREX)
    if effective_buffer >= (daily_limit * 0.60):
        zone = 'GREEN'
        allowed = True
        status_code = 'GREEN_FULL'
        risk_percentage = 5.0
        allocated_risk_usd = effective_buffer * (risk_percentage / 100.0)
        risk_per_lot_usd = sl_dist * pt_val
        if risk_per_lot_usd > 0:
            raw_lots = allocated_risk_usd / risk_per_lot_usd
            max_lots = round(max(0.01, min(raw_lots, 10.0)), 2)
        else:
            max_lots = 0.01
        ui_badge = f'🟢 Freigegeben ({max_lots:.2f} Lots)'
        ui_reason = f'Grüne Zone (Puffer: {effective_buffer:.2f} USD). {risk_percentage}% Risiko = {allocated_risk_usd:.2f} USD Budget.'

    elif (daily_limit * 0.30) <= effective_buffer < (daily_limit * 0.60):
        zone = 'YELLOW'
        allowed = True
        status_code = 'YELLOW_THROTTLED'
        risk_percentage = 2.5
        allocated_risk_usd = effective_buffer * (risk_percentage / 100.0)
        risk_per_lot_usd = sl_dist * pt_val
        if risk_per_lot_usd > 0:
            raw_lots = allocated_risk_usd / risk_per_lot_usd
            max_lots = round(max(0.01, min(raw_lots, 10.0)), 2)
        else:
            max_lots = 0.01
        ui_badge = f'🟡 Schonmodus ({max_lots:.2f} Lots)'
        ui_reason = f'Gelbe Zone (Puffer: {effective_buffer:.2f} USD). {risk_percentage}% Risiko = {allocated_risk_usd:.2f} USD Budget.'

    else:
        # ROTE ZONE (< 30% von daily_limit): Sniper-Reha-Prüfung
        zone = 'RED'
        if effective_buffer >= 50.0 and score >= 60.0:
            status_code = 'SNIPER_REHAB'
            sniper_risk_usd = effective_buffer * 0.10
            allocated_risk_usd = sniper_risk_usd
            raw_lots = sniper_risk_usd / (sl_dist * pt_val) if (sl_dist * pt_val) > 0 else 0.01
            max_lots = round(max(0.01, min(raw_lots, 1.0)), 2)
            allowed = True
            ui_badge = f'🎯 Sniper-Reha ({max_lots:.2f} Lots)'
            ui_reason = f'🎯 Sniper-Reha aktiv: Starkes Setup ({int(score)} Pkt.) mit Mini-Risiko (${sniper_risk_usd:.2f}) freigegeben.'
        else:
            allowed = False
            max_lots = 0.0
            status_code = 'RED_MUTED'
            allocated_risk_usd = 0.0
            ui_badge = '🔴 Tages-Stopp'
            ui_reason = '🚨 Notbremse aktiv: Puffer erschöpft oder Setup zu schwach für Reha.'

    return {
        'allowed': allowed,
        'zone': zone,
        'status_code': status_code,
        'max_lots': max_lots,
        'daily_buffer_usd': round(effective_buffer, 2),
        'effective_buffer': round(effective_buffer, 2),
        'effective_threshold_usd': round(effective_threshold_usd, 2),
        'allocated_risk_usd': round(allocated_risk_usd, 2),
        'ui_badge': ui_badge,
        'ui_reason': ui_reason
    }

if __name__ == "__main__":
    import json
    
    print("=== RESONO TERMINAL-PRÜFSTAND ===\n")

    # Szenario 1: Frische Evaluation
    print("Szenario 1: Frische Evaluation (Erwartung: GRÜN, 3 Kontrakte)")
    acc1 = {'account_id': 'EVAL_1', 'account_type': 'evaluation', 'current_balance': 50000.0, 'high_watermark': 50000.0, 'has_open_position': False}
    sig1 = {'symbol': 'MNQ', 'stop_distance_points': 30, 'point_value': 2.0}
    print(json.dumps(evaluate_account_risk(acc1, sig1), indent=2, ensure_ascii=False), "\n")

    # Szenario 2: Angeschlagene Evaluation
    print("Szenario 2: Angeschlagene Evaluation (Erwartung: GRÜN, 2 MCL Kontrakte - exakt auf 1500 Grenze)")
    acc2 = {'account_id': 'EVAL_2', 'account_type': 'evaluation', 'current_balance': 49000.0, 'high_watermark': 50000.0, 'has_open_position': False}
    sig2 = {'symbol': 'MCL', 'stop_distance_points': 0.40, 'point_value': 100.0}
    print(json.dumps(evaluate_account_risk(acc2, sig2), indent=2, ensure_ascii=False), "\n")

    # Szenario 3: Schonmodus Evaluation
    print("Szenario 3: Schonmodus Evaluation (Erwartung: GELB, 1 Kontrakt)")
    acc3 = {'account_id': 'EVAL_3', 'account_type': 'evaluation', 'current_balance': 48600.0, 'high_watermark': 50000.0, 'has_open_position': False}
    sig3 = {'symbol': 'MNQ', 'stop_distance_points': 30, 'point_value': 2.0}
    print(json.dumps(evaluate_account_risk(acc3, sig3), indent=2, ensure_ascii=False), "\n")

    # Szenario 4a: Kritische Evaluation - Signal MCL
    print("Szenario 4a: Kritisch - MCL (Erwartung: ROT, Gesperrt)")
    acc4 = {'account_id': 'EVAL_4', 'account_type': 'evaluation', 'current_balance': 48000.0, 'high_watermark': 50000.0, 'has_open_position': False}
    sig4a = {'symbol': 'MCL', 'stop_distance_points': 0.40, 'point_value': 100.0}
    print(json.dumps(evaluate_account_risk(acc4, sig4a), indent=2, ensure_ascii=False), "\n")

    # Szenario 4b: Kritische Evaluation - Signal MNQ mit weitem Stop (55 Punkte = 110 USD)
    print("Szenario 4b: Kritisch - MNQ weiter Stop > 20% (Erwartung: ROT, Stummgeschaltet)")
    sig4b = {'symbol': 'MNQ', 'stop_distance_points': 55, 'point_value': 2.0}
    print(json.dumps(evaluate_account_risk(acc4, sig4b), indent=2, ensure_ascii=False), "\n")

    # Szenario 4c: Kritische Evaluation - Signal MNQ mit engem Sniper-Stop (15 Punkte = 30 USD)
    print("Szenario 4c: Kritisch - MNQ enger Stop <= 20% (Erwartung: ROT_SNIPER, 1 Kontrakt)")
    sig4c = {'symbol': 'MNQ', 'stop_distance_points': 15, 'point_value': 2.0}
    print(json.dumps(evaluate_account_risk(acc4, sig4c), indent=2, ensure_ascii=False), "\n")

    # Szenario 5: Reifes PA-Konto über Freeze-Schwelle
    print("Szenario 5: Reifes PA-Konto über Freeze (Erwartung: GRÜN, 2 Kontrakte)")
    acc5 = {'account_id': 'PA_1', 'account_type': 'funded_pa', 'current_balance': 54000.0, 'high_watermark': 54000.0, 'has_open_position': False}
    sig5 = {'symbol': 'MNQ', 'stop_distance_points': 30, 'point_value': 2.0}
    print(json.dumps(evaluate_account_risk(acc5, sig5), indent=2, ensure_ascii=False), "\n")
    print("=== FLOTTEN-STEUERUNG & KOLLISIONS-TEST ===\n")
    
    fleet_accounts = [
        {'account_id': 'Eval-A', 'account_type': 'evaluation', 'current_balance': 50000.0, 'high_watermark': 50000.0, 'has_open_position': False},
        {'account_id': 'Eval-B', 'account_type': 'evaluation', 'current_balance': 48800.0, 'high_watermark': 50000.0, 'has_open_position': False},
        {'account_id': 'Eval-C', 'account_type': 'evaluation', 'current_balance': 48000.0, 'high_watermark': 50000.0, 'has_open_position': False},
        {'account_id': 'PA-01', 'account_type': 'funded_pa', 'current_balance': 50500.0, 'high_watermark': 50500.0, 'has_open_position': True}
    ]
    
    fleet_signals = [
        {'symbol': 'MCL', 'master_score': 68.0, 'stop_distance_points': 0.40, 'point_value': 100.0},
        {'symbol': 'MNQ', 'master_score': 50.0, 'stop_distance_points': 15.0, 'point_value': 2.0}
    ]
    
    print("Flotten-Ergebnis (Erwartung: Eval-A -> 2 MCL, Eval-B -> 1 MCL, Eval-C -> 1 MNQ Sniper, PA-01 -> VETO)")
    print(json.dumps(evaluate_fleet(fleet_accounts, fleet_signals), indent=2, ensure_ascii=False), "\n")
    print("=== FTMO FOREX-RISIKOPRÜFUNG ===\n")
    
    # Szenario F1: Frisches FTMO 100k Konto
    print("Szenario F1: Frisches Konto (Erwartung: GRÜN, 0.71 Lots)")
    ftmo_acc1 = {'initial_balance': 100000.0, 'day_start_balance': 100000.0, 'current_balance': 100000.0, 'has_open_position': False}
    ftmo_sig1 = {'symbol': 'GBPUSD=X', 'sl_pips': 35.0, 'pip_value_per_standard_lot': 10.0}
    print(json.dumps(evaluate_ftmo_risk(ftmo_acc1, ftmo_sig1), indent=2, ensure_ascii=False), "\n")

    # Szenario F2: Angeschlagener Tag / Schonmodus
    print("Szenario F2: Angeschlagen (Erwartung: GELB, 0.14 Lots)")
    ftmo_acc2 = {'initial_balance': 100000.0, 'day_start_balance': 100000.0, 'current_balance': 97200.0, 'has_open_position': False}
    ftmo_sig2 = {'symbol': 'USDJPY=X', 'sl_pips': 40.0, 'pip_value_per_standard_lot': 10.0}
    print(json.dumps(evaluate_ftmo_risk(ftmo_acc2, ftmo_sig2), indent=2, ensure_ascii=False), "\n")

    # Szenario F3: Kritischer Tag / Rote Zone
    print("Szenario F3: Kritischer Tag (Erwartung: ROT_MUTED, 0.0 Lots)")
    ftmo_acc3 = {'initial_balance': 100000.0, 'day_start_balance': 100000.0, 'current_balance': 96100.0, 'has_open_position': False}
    ftmo_sig3 = {'symbol': 'EURUSD=X', 'sl_pips': 25.0, 'pip_value_per_standard_lot': 10.0}
    print(json.dumps(evaluate_ftmo_risk(ftmo_acc3, ftmo_sig3), indent=2, ensure_ascii=False), "\n")