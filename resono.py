from typing import Dict, Any

def evaluate_account_risk(account_dict: Dict[str, Any], signal_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kernevaluierung des Account-Risikos (RESONO-Modul).
    Prüft Puffer, Kollisionen und setzt Phasen-Resonanz (Dreizonen-Modell) um.
    """
    import math
    account_id = account_dict.get('account_id', 'Unknown')
    account_type = str(account_dict.get('account_type', 'evaluation')).strip().lower()
    eod_keywords = ("eod_futures", "eod futures", "eod-futures", "mffu", "tradeify")
    eod_check_fields = (
        account_type,
        str(account_dict.get('broker_profile') or '').strip().lower(),
        str(account_dict.get('exit_profile') or '').strip().lower(),
        str(account_dict.get('name') or '').strip().lower(),
        str(account_id or '').strip().lower(),
    )
    is_eod_futures = any(kw in field for field in eod_check_fields for kw in eod_keywords)

    raw_account_size = None
    for size_key in ('account_size', 'initial_balance', 'start_cap'):
        if account_dict.get(size_key) is not None:
            raw_account_size = account_dict.get(size_key)
            break
    account_size = float(raw_account_size) if raw_account_size is not None else (100000.0 if is_eod_futures else 50000.0)
    current_balance = float(account_dict.get('current_balance', 0.0))
    high_watermark = float(account_dict.get('high_watermark', 0.0))
    
    raw_symbol = str(signal_dict.get('ticker', signal_dict.get('symbol', 'MNQ'))).strip().upper()
    cme_mapping = {
        "NQ=F": "MNQ", "NQ": "MNQ", "MNQ": "MNQ", "MNQ=F": "MNQ",
        "ES=F": "MES", "ES": "MES", "MES": "MES",
        "YM=F": "MYM", "YM": "MYM", "MYM": "MYM",
        "RTY=F": "M2K", "RTY": "M2K", "M2K": "M2K",
        "CL=F": "MCL", "CL": "MCL", "MCL": "MCL", "MCL=F": "MCL",
        "GC=F": "MGC", "GC": "MGC", "MGC": "MGC", "MGC=F": "MGC",
        "6E=F": "M6E", "6E": "M6E", "M6E": "M6E", "M6E=F": "M6E",
        "SI=F": "SIL", "SI": "SIL", "SIL": "SIL",
        "NG=F": "QG", "NG": "QG", "QG": "QG",
        "HG=F": "MHG", "HG": "MHG", "MHG": "MHG"
    }
    ticker = cme_mapping.get(raw_symbol, raw_symbol)
    symbol = ticker

    stop_distance = float(signal_dict.get('stop_distance_points', signal_dict.get('stop_loss_distance', 0.0)))
    point_value_defaults = {"MNQ": 2.0, "MGC": 10.0, "MCL": 100.0, "M6E": 12500.0}
    raw_point_value = signal_dict.get('point_value')
    point_value = float(raw_point_value) if raw_point_value is not None else point_value_defaults.get(ticker, 1.0)
    score = float(signal_dict.get('score', signal_dict.get('master_score', 0.0)))

    # VETO STUFE 1: Whitelist-Prüfung
    if is_eod_futures:
        allowed_futures = ["MNQ", "MGC", "MCL", "M6E", "NQ=F", "GC=F", "CL=F", "6E=F", "MNQ=F", "MGC=F", "MCL=F", "M6E=F"]
        if ticker not in allowed_futures and raw_symbol not in allowed_futures:
            return {
                "allowed": False, "max_contracts": 0, "zone": "RED",
                "status_code": "UNAUTHORIZED_PROP_ASSET",
                "ui_reason": f"Asset '{ticker}' ist nicht im EOD-Futures Master-Kader validiert.",
                'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
                'ui_badge': '🔴 Gesperrt (Asset)'
            }
    else:
        allowed_futures = ["MNQ", "MCL", "NQ=F", "CL=F"]
        if ticker not in allowed_futures and raw_symbol not in allowed_futures:
            return {
                "allowed": False, "max_contracts": 0, "zone": "RED",
                "status_code": "UNAUTHORIZED_PROP_ASSET",
                "ui_reason": f"Asset '{ticker}' ist nicht im Apex Master-Kader validiert.",
                'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
                'ui_badge': '🔴 Gesperrt (Asset)'
            }
        
    # VETO STUFE 2: Belegungs-Prüfung
    has_open_position = bool(account_dict.get('has_open_position', False))
    if is_eod_futures:
        raw_open_count = account_dict.get('open_positions_count')
        open_positions_count = int(raw_open_count) if raw_open_count is not None else (1 if has_open_position else 0)
        if open_positions_count >= 2:
            return {
                'allowed': False, 'max_contracts': 0, 'zone': 'RED',
                'status_code': 'VETO_OCCUPIED',
                'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
                'ui_badge': '🔴 Gesperrt', 'ui_reason': 'Konto belegt: Maximal 2 offene Futures-Positionen gleichzeitig erlaubt.'
            }
        raw_open_symbols = account_dict.get('open_symbols')
        if raw_open_symbols:
            norm_open_symbols = set()
            for osym in raw_open_symbols:
                osym_u = str(osym).strip().upper()
                if osym_u:
                    norm_open_symbols.add(osym_u)
                    norm_open_symbols.add(cme_mapping.get(osym_u, osym_u))
            if ticker in norm_open_symbols or raw_symbol in norm_open_symbols:
                return {
                    'allowed': False, 'max_contracts': 0, 'zone': 'RED',
                    'status_code': 'VETO_OCCUPIED',
                    'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
                    'ui_badge': '🔴 Gesperrt', 'ui_reason': f"Asset '{ticker}' bereits offen: Maximal 1 Position pro Asset erlaubt."
                }
    elif has_open_position:
        return {
            'allowed': False, 'max_contracts': 0, 'zone': 'RED',
            'status_code': 'VETO_OCCUPIED',
            'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
            'ui_badge': '🔴 Gesperrt', 'ui_reason': 'Konto belegt: Maximal 1 offener Trade erlaubt'
        }
        
    # VETO STUFE 3: Parameter-Validierung
    if stop_distance <= 0.0 or point_value <= 0.0:
        return {
            'allowed': False, 'max_contracts': 0, 'zone': 'RED',
            'status_code': 'INVALID_SL_DISTANCE',
            'risk_buffer_usd': 0.0, 'ko_threshold_usd': 0.0, 'trade_risk_usd': 0.0,
            'ui_badge': '🔴 Fehler (SL/PV)', 'ui_reason': 'Stop-Distance oder Point-Value ungültig (<= 0).'
        }

    # VETO STUFE 4: Risikobudget & Zonen-Evaluation
    loss_per_contract = stop_distance * point_value
    
    raw_daily_limit = None
    for d_key in ('daily_loss_limit', 'daily_loss'):
        if account_dict.get(d_key) is not None:
            raw_daily_limit = account_dict.get(d_key)
            break
    daily_loss_limit = float(raw_daily_limit) if raw_daily_limit is not None else (0.0 if is_eod_futures else account_size * 0.025)

    max_dd_limit = None
    for dd_key in ('max_trailing_dd', 'trail_dd', 'max_dd_limit'):
        dd_val = account_dict.get(dd_key)
        if dd_val is not None and float(dd_val) > 0.0:
            max_dd_limit = float(dd_val)
            break
    if max_dd_limit is None:
        max_dd_limit = account_size * 0.03 if is_eod_futures else account_size * 0.05
    
    raw_ko_threshold = high_watermark - max_dd_limit
    if is_eod_futures:
        ko_freeze_floor = account_size + (account_size * 0.001)
        ko_threshold_usd = ko_freeze_floor if raw_ko_threshold >= ko_freeze_floor else raw_ko_threshold
    else:
        ko_threshold_usd = 50100.0 if raw_ko_threshold >= 50100.0 else raw_ko_threshold
    calculated_max_dd_buffer = max(0.0, current_balance - ko_threshold_usd)
    
    raw_max_dd_buffer = None
    for buf_key in ('max_dd_buffer', 'risk_buffer_usd', 'buffer_to_ko'):
        if account_dict.get(buf_key) is not None:
            raw_max_dd_buffer = account_dict.get(buf_key)
            break
    max_dd_buffer = float(raw_max_dd_buffer) if raw_max_dd_buffer is not None else calculated_max_dd_buffer

    raw_daily_buffer = account_dict.get('daily_buffer')
    daily_buffer = float(raw_daily_buffer) if raw_daily_buffer is not None else daily_loss_limit

    if is_eod_futures:
        if daily_loss_limit <= 0.0:
            effective_ratio = (max_dd_buffer / max_dd_limit) if max_dd_limit > 0 else 0.0
        else:
            effective_ratio = min(daily_buffer / daily_loss_limit, max_dd_buffer / max_dd_limit) if max_dd_limit > 0 else 0.0
    else:
        effective_ratio = min(daily_buffer / daily_loss_limit, max_dd_buffer / max_dd_limit) if daily_loss_limit > 0 and max_dd_limit > 0 else 0.0
    
    allowed = False
    status_code = ""
    zone_cap = 0
    ui_badge = ""
    ui_reason = ""

    if is_eod_futures:
        # Proportionale Gangschaltung: EVAL_TURBO vs. FUNDED_SHIELD
        explicit_gear = None
        for g_key in ('risk_gear', 'eod_gear', 'gear'):
            g_val = account_dict.get(g_key)
            if g_val is not None:
                g_norm = str(g_val).strip().upper()
                if g_norm in ('EVAL_TURBO', 'FUNDED_SHIELD'):
                    explicit_gear = g_norm
                    break

        if explicit_gear is not None:
            active_gear = explicit_gear
        else:
            acc_name_low = str(account_dict.get('name') or '').strip().lower()
            is_funded_flag = bool(account_dict.get('is_funded', False))
            has_funded_kw = any(kw in field for field in (account_type, acc_name_low) for kw in ('funded', 'pa', 'live'))
            if has_funded_kw or is_funded_flag or ko_threshold_usd >= ko_freeze_floor:
                active_gear = 'FUNDED_SHIELD'
            else:
                active_gear = 'EVAL_TURBO'

        raw_max_trade_risk = account_dict.get('max_trade_risk_usd')
        if raw_max_trade_risk is not None and float(raw_max_trade_risk) > 0.0:
            base_max_risk = float(raw_max_trade_risk)
        else:
            base_max_risk = account_size * 0.0035 if active_gear == 'EVAL_TURBO' else account_size * 0.0025

        if effective_ratio >= 0.60:
            allowed = True
            status_code = 'GREEN_FULL'
            zone_cap = 3 if ticker == 'MNQ' else 2
            max_trade_risk = base_max_risk
            ui_badge = f'🟢 Freigegeben ({zone_cap} {ticker})'
            ui_reason = f'Grüne Zone (Quote: {effective_ratio:.2f} | Gang: {active_gear}, Limit: {max_trade_risk:.2f} USD).'
        elif 0.32 <= effective_ratio < 0.60:
            allowed = True
            status_code = 'YELLOW_THROTTLED'
            zone_cap = 1
            max_trade_risk = base_max_risk * 0.5
            ui_badge = f'🟡 Schonmodus (1 {ticker})'
            ui_reason = f'Gelbe Zone (Quote: {effective_ratio:.2f} | Gang: {active_gear}, Limit: {max_trade_risk:.2f} USD). Defensiver Schonmodus.'
        else:
            allowed = False
            status_code = 'MUTED_RED_ZONE'
            zone_cap = 0
            max_trade_risk = base_max_risk * 0.5
            ui_badge = '🔴 Stummgeschaltet'
            ui_reason = f'Rote Zone (Quote: {effective_ratio:.2f} | Gang: {active_gear}).'

            # Ausnahme Sniper-Reha (EOD-Futures)
            if score >= 75.0:
                erlaubtes_risiko = min(0.20 * max_dd_buffer, base_max_risk * 0.5)
                if max_dd_buffer > 0 and round(loss_per_contract, 6) <= round(erlaubtes_risiko, 6):
                    allowed = True
                    status_code = 'SNIPER_REHAB'
                    zone_cap = 1
                    max_trade_risk = erlaubtes_risiko
                    ui_badge = f'🎯 Sniper-Reha (1 {ticker})'
                    ui_reason = f'Rote Zone Sniper (Gang: {active_gear}): Risiko {loss_per_contract:.2f} <= {erlaubtes_risiko:.2f}.'

        if allowed and round(loss_per_contract, 6) > round(max_trade_risk, 6):
            allowed = False
            zone_cap = 0
            status_code = 'SL_TOO_WIDE'
            ui_badge = '🔴 Gesperrt (SL)'
            ui_reason = f'Stop-Loss zu weit (Risiko {loss_per_contract:.2f} > Deckel {max_trade_risk:.2f} | Gang: {active_gear}).'

        risk_capped_qty = math.floor((max_trade_risk + 1e-9) / loss_per_contract) if loss_per_contract > 0 else 0
        max_contracts = min(zone_cap, risk_capped_qty) if allowed else 0
    else:
        if effective_ratio >= 0.60:
            allowed = True
            status_code = 'GREEN_FULL'
            zone_cap = 2 if ticker == 'MCL' else 3
            ui_badge = f'🟢 Freigegeben ({zone_cap} {ticker})'
            ui_reason = f'Grüne Zone (Quote: {effective_ratio:.2f}).'
        elif 0.32 <= effective_ratio < 0.60:
            allowed = True
            status_code = 'YELLOW_THROTTLED'
            zone_cap = 1
            ui_badge = f'🟡 Schonmodus (1 {ticker})'
            ui_reason = f'Gelbe Zone (Quote: {effective_ratio:.2f}). Defensiver Schonmodus.'
        else:
            allowed = False
            status_code = 'MUTED_RED_ZONE'
            zone_cap = 0
            ui_badge = '🔴 Stummgeschaltet'
            ui_reason = f'Rote Zone (Quote: {effective_ratio:.2f}).'
            
            # Ausnahme Sniper-Reha
            if score >= 75.0:
                effective_buffer = max(0.0, min(daily_buffer, max_dd_buffer))
                erlaubtes_risiko = 0.20 * effective_buffer
                max_trade_risk_reha = daily_loss_limit * 0.10
                if loss_per_contract <= erlaubtes_risiko and loss_per_contract <= max_trade_risk_reha and effective_buffer > 0:
                    allowed = True
                    status_code = 'SNIPER_REHAB'
                    zone_cap = 1
                    ui_badge = f'🎯 Sniper-Reha (1 {ticker})'
                    ui_reason = f'Rote Zone Sniper: Risiko {loss_per_contract:.2f} <= {erlaubtes_risiko:.2f}.'

        # Mathematischer 10%-Risikodeckel
        max_trade_risk = daily_loss_limit * 0.10
        if loss_per_contract > max_trade_risk:
            allowed = False
            zone_cap = 0
            status_code = 'SL_TOO_WIDE'
            ui_badge = '🔴 Gesperrt (SL)'
            ui_reason = f'Stop-Loss zu weit (Risiko {loss_per_contract:.2f} > Deckel {max_trade_risk:.2f}).'
            
        risk_capped_qty = math.floor(max_trade_risk / loss_per_contract) if loss_per_contract > 0 else 0
        max_contracts = min(zone_cap, risk_capped_qty) if allowed else 0
    
    if max_contracts == 0 and allowed:
        allowed = False
        status_code = 'SL_TOO_WIDE'
        ui_badge = '🔴 Gesperrt (SL)'
        ui_reason = f'Risiko für 1 Kontrakt ({loss_per_contract:.2f}) übersteigt Limit ({max_trade_risk:.2f}).'
    elif allowed:
        # Dynamisches Poka-Yoke UI-Badge mit der freigegebenen Kontraktzahl
        if 'GREEN' in status_code:
            ui_badge = f'🟢 Freigegeben ({max_contracts} {symbol})'
        elif 'YELLOW' in status_code:
            ui_badge = f'🟡 Schonmodus ({max_contracts} {symbol})'
        elif status_code == 'SNIPER_REHAB':
            ui_badge = f'🎯 Sniper-Reha ({max_contracts} {symbol})'
            
        if max_contracts < zone_cap:
            ui_reason += f' [Gedrosselt durch Risikodeckel: {max_contracts} max]'

    return {
        'allowed': allowed,
        'status_code': status_code,
        'max_contracts': max_contracts,
        'risk_buffer_usd': round(max_dd_buffer, 2),
        'ko_threshold_usd': round(ko_threshold_usd, 2),
        'trade_risk_usd': round(loss_per_contract, 2),
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
    elif symbol in ('MGC', 'M6E', 'GC=F', '6E=F'):
        opt_min, opt_max = 65.0, 75.0
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
    import math
    account_size = float(account_dict.get("account_size", account_dict.get("initial_balance", account_dict.get("current_balance", 100000.0))))
    current_balance = float(account_dict.get("current_balance", account_size))
    
    raw_symbol = str(signal_dict.get("ticker", signal_dict.get("symbol", "EURUSD"))).strip().upper()
    if not raw_symbol.endswith("=X") and raw_symbol != "NONE":
        ticker = raw_symbol + "=X"
    else:
        ticker = raw_symbol
    symbol = ticker
        
    stop_distance = float(signal_dict.get('stop_distance_points', signal_dict.get('stop_loss_distance', signal_dict.get('sl_pips', 0.0))))
    if stop_distance > 10.0:
        stop_distance = stop_distance / 10000.0
        
    point_value = float(signal_dict.get('point_value', 100000.0))
    score = float(signal_dict.get("score", signal_dict.get("master_score", 0.0)))
    
    # Stufe 1: Whitelist-Prüfung
    allowed_forex = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "EURJPY=X", "NONE=X"]
    if ticker not in allowed_forex and symbol != "NONE":
        return {
            'allowed': False, 'zone': 'RED', 'status_code': 'UNAUTHORIZED_PROP_ASSET',
            'max_lots': 0.0, 'daily_buffer_usd': 0.0, 'effective_buffer': 0.0,
            'effective_threshold_usd': 0.0, 'allocated_risk_usd': 0.0,
            'ui_badge': '🔴 Gesperrt (Asset)', 'ui_reason': f"Asset '{ticker}' nicht freigegeben."
        }

    has_open_position = bool(account_dict.get("has_open_position", False))
    # Stufe 2: Belegungs-Prüfung
    if has_open_position:
        return {
            'allowed': False, 'zone': 'RED', 'status_code': 'VETO_OCCUPIED',
            'max_lots': 0.0, 'daily_buffer_usd': 0.0, 'effective_buffer': 0.0,
            'effective_threshold_usd': 0.0, 'allocated_risk_usd': 0.0,
            'ui_badge': '🔴 Gesperrt', 'ui_reason': 'Konto belegt: Maximal 1 offener Trade erlaubt.'
        }

    # Stufe 3: Parameter-Validierung
    if stop_distance <= 0.0 or point_value <= 0.0:
        return {
            'allowed': False, 'zone': 'RED', 'status_code': 'INVALID_SL_DISTANCE',
            'max_lots': 0.0, 'daily_buffer_usd': 0.0, 'effective_buffer': 0.0,
            'effective_threshold_usd': 0.0, 'allocated_risk_usd': 0.0,
            'ui_badge': '🔴 Fehler (SL/PV)', 'ui_reason': 'Stop-Distance oder Point-Value ungültig.'
        }

    daily_limit = float(account_dict.get("daily_loss_limit", account_size * 0.05))
    if "daily_buffer" in account_dict and account_dict.get("daily_buffer") is not None:
        daily_buffer = float(account_dict.get("daily_buffer", daily_limit))
    elif "day_start_balance" in account_dict:
        day_start = float(account_dict.get("day_start_balance", account_size))
        daily_buffer = max(0.0, current_balance - (day_start - daily_limit))
    else:
        daily_buffer = account_size * 0.05

    if "max_dd_buffer" in account_dict and account_dict.get("max_dd_buffer") is not None:
        max_dd_buffer = float(account_dict.get("max_dd_buffer"))
    else:
        max_loss_threshold = account_size * 0.90
        max_dd_buffer = max(0.0, current_balance - max_loss_threshold)

    # 1. FLASCHENHALS-PUFFER
    effective_buffer = max(0.0, min(daily_buffer, max_dd_buffer))
    effective_threshold_usd = current_balance - effective_buffer

    allowed = False
    zone = 'GREEN'
    status_code = ''
    allocated_risk_usd = 0.0
    ui_badge = ''
    ui_reason = ''

    # 3. DYNAMISCHE ZONEN & SNIPER-REHA (FOREX)
    if effective_buffer >= (daily_limit * 0.60):
        zone = 'GREEN'
        allowed = True
        status_code = 'GREEN_FULL'
        allocated_risk_usd = effective_buffer * 0.05
        ui_reason = f'Grüne Zone (Puffer: {effective_buffer:.2f} USD). 5.0% Risiko = {allocated_risk_usd:.2f} USD Budget.'
    elif (daily_limit * 0.30) <= effective_buffer < (daily_limit * 0.60):
        zone = 'YELLOW'
        allowed = True
        status_code = 'YELLOW_THROTTLED'
        allocated_risk_usd = effective_buffer * 0.025
        ui_reason = f'Gelbe Zone (Puffer: {effective_buffer:.2f} USD). 2.5% Risiko = {allocated_risk_usd:.2f} USD Budget.'
    else:
        zone = 'RED'
        if score >= 70.0 and effective_buffer >= 50.0:
            allowed = True
            status_code = 'SNIPER_REHAB'
            allocated_risk_usd = effective_buffer * 0.01  # Strikt 1.0%
            ui_reason = f'🎯 Sniper-Reha aktiv: Score {score} freigegeben. Budget: {allocated_risk_usd:.2f} USD.'
        else:
            allowed = False
            status_code = 'MUTED_RED_ZONE'
            allocated_risk_usd = 0.0
            ui_reason = '🚨 Notbremse aktiv: Puffer erschöpft oder Setup zu schwach für Reha.'

    # Universelle Obergrenze über alle Zonen
    allocated_risk_usd = min(allocated_risk_usd, daily_limit * 0.05)

    # Mikrolot-Sizing & math.floor
    risk_per_lot_usd = stop_distance * point_value
    raw_lots = math.floor((allocated_risk_usd / risk_per_lot_usd) * 100.0) / 100.0 if risk_per_lot_usd > 0 else 0.0
    
    # Poka-Yoke Schutz gegen Lot-Aufrundung (nur aktiv wenn Trade grundsätzlich erlaubt)
    if allowed:
        if raw_lots < 0.01:
            allowed = False
            max_lots = 0.0
            status_code = 'SL_TOO_WIDE'
            ui_reason = 'Stop-Loss zu weit für Mikrolot-Minimum.'
        else:
            max_lots = raw_lots
    else:
        max_lots = 0.0

    if allowed:
        if status_code == 'GREEN_FULL':
            ui_badge = f'🟢 Freigegeben ({max_lots:.2f} Lots)'
        elif status_code == 'YELLOW_THROTTLED':
            ui_badge = f'🟡 Schonmodus ({max_lots:.2f} Lots)'
        elif status_code == 'SNIPER_REHAB':
            ui_badge = f'🎯 Sniper-Reha ({max_lots:.2f} Lots)'
    else:
        ui_badge = '🔴 Gesperrt (SL)' if status_code == 'SL_TOO_WIDE' else '🔴 Tages-Stopp'

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
    print("=== MFFU EOD-FUTURES PRÜFUNG (DYNAMISCH) ===\n")

    # EOD-1: Frisches 100k EOD Konto mit daily_loss_limit = 0.0 -> EVAL_TURBO ($350), GREEN_FULL
    eod_acc_100k = {
        'account_id': 'MFFU_100K_EVAL', 'account_type': 'eod_futures',
        'account_size': 100000.0, 'current_balance': 100000.0, 'high_watermark': 100000.0,
        'daily_loss_limit': 0.0, 'has_open_position': False
    }
    res_eod_1 = evaluate_account_risk(eod_acc_100k, {'symbol': 'MNQ', 'stop_distance_points': 50.0})
    assert res_eod_1['allowed'] is True and res_eod_1['status_code'] == 'GREEN_FULL'
    assert res_eod_1['max_contracts'] == 3 and res_eod_1['risk_buffer_usd'] == 3000.0
    assert 'EVAL_TURBO' in res_eod_1['ui_reason'] and '350.00' in res_eod_1['ui_reason']
    print("[PASS] EOD-1: 100k EVAL_TURBO (daily_loss=0.0, $350 Budget, 3 MNQ):", json.dumps(res_eod_1, ensure_ascii=False))

    # EOD-2: Dynamische Skalierung auf 50k EOD Konto (3% = $1.500 DD, EVAL_TURBO $175, FUNDED_SHIELD $125)
    eod_acc_50k_eval = {
        'account_id': 'MFFU_50K_EVAL', 'account_type': 'eod_futures',
        'account_size': 50000.0, 'current_balance': 50000.0, 'high_watermark': 50000.0,
        'has_open_position': False
    }
    res_50k_turbo = evaluate_account_risk(eod_acc_50k_eval, {'symbol': 'MGC', 'stop_distance_points': 17.5})
    assert res_50k_turbo['allowed'] is True and res_50k_turbo['risk_buffer_usd'] == 1500.0
    assert 'EVAL_TURBO' in res_50k_turbo['ui_reason'] and '175.00' in res_50k_turbo['ui_reason']

    eod_acc_50k_funded = dict(eod_acc_50k_eval, account_id='MFFU_50K_FUNDED', name='MFFU 50k Funded')
    res_50k_shield_ok = evaluate_account_risk(eod_acc_50k_funded, {'symbol': 'MNQ', 'stop_distance_points': 62.5})
    res_50k_shield_too_wide = evaluate_account_risk(eod_acc_50k_funded, {'symbol': 'MGC', 'stop_distance_points': 13.0})
    assert res_50k_shield_ok['allowed'] is True and 'FUNDED_SHIELD' in res_50k_shield_ok['ui_reason'] and '125.00' in res_50k_shield_ok['ui_reason']
    assert res_50k_shield_too_wide['allowed'] is False and res_50k_shield_too_wide['status_code'] == 'SL_TOO_WIDE'
    print("[PASS] EOD-2: 50k Skalierung ($1.500 DD | EVAL_TURBO $175 | FUNDED_SHIELD $125)")

    # EOD-3: Alle 4 Kader-Assets am exakten Stop-Deckel im FUNDED_SHIELD ($250) -> 0% SL_TOO_WIDE; MGC 26.0 -> SL_TOO_WIDE
    eod_acc_100k_funded = dict(eod_acc_100k, account_id='MFFU_100K_PA', name='MFFU 100k Funded')
    kader_cap_tests = [
        ('6E=F', 0.0160, 200.0),
        ('GC=F', 25.0, 250.0),
        ('CL=F', 2.50, 250.0),
        ('NQ=F', 62.5, 125.0),
    ]
    for k_sym, k_sl, exp_risk in kader_cap_tests:
        r_cap = evaluate_account_risk(eod_acc_100k_funded, {'symbol': k_sym, 'stop_distance_points': k_sl})
        assert r_cap['allowed'] is True and r_cap['status_code'] == 'GREEN_FULL', f"Failed at cap for {k_sym}: {r_cap}"
        assert r_cap['trade_risk_usd'] == exp_risk and r_cap['max_contracts'] >= 1
    r_mgc_over = evaluate_account_risk(eod_acc_100k_funded, {'symbol': 'MGC', 'stop_distance_points': 26.0})
    assert r_mgc_over['allowed'] is False and r_mgc_over['status_code'] == 'SL_TOO_WIDE'
    print("[PASS] EOD-3: 4er-Kader am exakten Stop-Deckel (M6E/MGC/MCL/MNQ) im FUNDED_SHIELD freigegeben, MGC 26.0 -> SL_TOO_WIDE")

    # EOD-4: Automatischer Gangwechsel auf FUNDED_SHIELD ($250) ab HWM 103.100,00 (KO-Floor 100.100,00)
    eod_acc_freeze = {
        'account_id': 'MFFU_100K_EVAL', 'account_type': 'eod_futures',
        'account_size': 100000.0, 'current_balance': 103100.0, 'high_watermark': 103100.0,
        'has_open_position': False
    }
    res_freeze = evaluate_account_risk(eod_acc_freeze, {'symbol': 'MGC', 'stop_distance_points': 25.0})
    assert res_freeze['allowed'] is True and res_freeze['ko_threshold_usd'] == 100100.0
    assert 'FUNDED_SHIELD' in res_freeze['ui_reason'] and '250.00' in res_freeze['ui_reason']
    res_freeze_over = evaluate_account_risk(eod_acc_freeze, {'symbol': 'MGC', 'stop_distance_points': 26.0})
    assert res_freeze_over['allowed'] is False and res_freeze_over['status_code'] == 'SL_TOO_WIDE'
    print("[PASS] EOD-4: Auto-Gangwechsel ab HWM 103.100 (KO-Floor 100.100) -> FUNDED_SHIELD ($250)")

    # EOD-5: Belegungs-Deckel (1 offen erlaubt, 2 offen -> VETO_OCCUPIED, gleiches Asset -> VETO_OCCUPIED, MES -> UNAUTHORIZED_PROP_ASSET)
    eod_1_open = dict(eod_acc_100k, has_open_position=True, open_positions_count=1, open_symbols=['MNQ'])
    res_1_open_ok = evaluate_account_risk(eod_1_open, {'symbol': 'M6E', 'stop_distance_points': 0.0120})
    res_1_open_same = evaluate_account_risk(eod_1_open, {'symbol': 'NQ=F', 'stop_distance_points': 40.0})
    eod_2_open = dict(eod_acc_100k, has_open_position=True, open_positions_count=2, open_symbols=['MNQ', 'MGC'])
    res_2_open = evaluate_account_risk(eod_2_open, {'symbol': 'MCL', 'stop_distance_points': 1.50})
    res_mes = evaluate_account_risk(eod_acc_100k, {'symbol': 'MES', 'stop_distance_points': 10.0, 'point_value': 5.0})
    assert res_1_open_ok['allowed'] is True
    assert res_1_open_same['allowed'] is False and res_1_open_same['status_code'] == 'VETO_OCCUPIED'
    assert res_2_open['allowed'] is False and res_2_open['status_code'] == 'VETO_OCCUPIED'
    assert res_mes['allowed'] is False and res_mes['status_code'] == 'UNAUTHORIZED_PROP_ASSET'
    print("[PASS] EOD-5: Belegungs-Deckel (max. 2 Futures, max. 1 pro Asset) & Whitelist (MES -> UNAUTHORIZED_PROP_ASSET)\n")