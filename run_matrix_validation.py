import os
import sys
import datetime
import csv
import pandas as pd
import traceback
import gc

try:
    import backtest_engine as bte
except ImportError:
    print("❌ Fehler: backtest_engine.py nicht gefunden. Bitte aus dem Ordner 'Trading Dashboard' ausführen.")
    sys.exit(1)

RESULTS_FILE = "matrix_validation_resono_candidates.csv"

def get_broker_fees(broker_profile):
    profile = broker_profile.lower()
    if "ftmo" in profile:
        return 0.00003, 0.00002
    elif "apex" in profile:
        return 0.00005, 0.0001
    elif "crypto" in profile:
        return 0.0025, 0.001
    elif "aktien" in profile:
        return 0.0005, 0.0005
    return 0.001, 0.0005

SCORE_CORRIDOR = [55, 60, 65, 70, 75]

# 🎯 MICRO-CAP STRESSTEST (CL=F)
TEST_MATRIX = [
    # Block A (Harter 1-Micro-Schutz)
    {"ticker": "CL=F", "interval": "1h", "years": 2, "direction": "both", "broker": "apex", "daily_loss": 1250.0, "exit_profile": "apex_lock", "scores": [60, 65, 70], "risk_pct": 1.0, "account_size": 50000.0, "max_contracts_cap": 1},
    
    # Block B (Kontrollierte 2-Micro-Skalierung)
    {"ticker": "CL=F", "interval": "1h", "years": 2, "direction": "both", "broker": "apex", "daily_loss": 1250.0, "exit_profile": "apex_lock", "scores": [60, 65, 70], "risk_pct": 1.0, "account_size": 50000.0, "max_contracts_cap": 2},
    
    # Block C (Aggressiver 3-Micro-Start für frische Konten)
    {"ticker": "CL=F", "interval": "1h", "years": 2, "direction": "both", "broker": "apex", "daily_loss": 1250.0, "exit_profile": "apex_lock", "scores": [60, 65, 70], "risk_pct": 1.0, "account_size": 50000.0, "max_contracts_cap": 3}
]
def run_matrix():
    print(f"🚀 Starte Matrix-Validierung Engine (Out-of-Sample Walk-Forward)")
    print("=" * 115)
    
    results = []

    fieldnames = [
        "Timestamp", "Ticker", "Interval", "Score", "Exit_Profile", "Broker_Profile",
        "Total_Trades", "Winrate_Pct", "Profit_Factor", "Max_Drawdown_EUR",
        "Avg_R_Multiple", "Net_PnL_EUR", "OOS_Trades", "OOS_Winrate_Pct",
        "OOS_Profit_Factor", "OOS_Net_PnL_EUR"
    ]
    
    file_exists = os.path.isfile(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for config in TEST_MATRIX:
            ticker = config["ticker"]
            interval = config["interval"]
            years = config["years"]
            direction = config["direction"]
            broker = config["broker"]
            daily_loss = config.get("daily_loss", None)
            exit_profile = config["exit_profile"]
            risk_pct = config["risk_pct"]
            account_size = config.get("account_size", 10000.0)
            
            max_contracts_cap = config.get("max_contracts_cap", None)
            fee_rate, slippage = get_broker_fees(broker)

            mode_label = "PROP" if daily_loss is not None else "PRIVAT"

            for score in config["scores"]:
                print(f"⏳ Prüfe [{mode_label:6}] {ticker:8} | {interval:3} | Score: {score:2} | Profil: {exit_profile:20} | Account: {account_size:.0f} €...")
                if max_contracts_cap is not None:
                    print(f"   -> Führe Backtest aus mit max_contracts_cap = {max_contracts_cap}")
                
                try:
                    all_trades, df_hist = bte.backtest(
                        ticker=ticker, years=years, fee_rate=fee_rate, slippage=slippage,
                        min_score=score, mode="walk_forward", account_size=account_size,
                        risk_pct=risk_pct, trailing_stop_mode="active", exit_profile=exit_profile,
                        allowed_direction=direction, interval=interval, daily_loss=daily_loss,
                        max_contracts_cap=max_contracts_cap
                    )
                    metrics_all = bte.calculate_metrics(all_trades)
                    
                    oos_trades = [t for t in all_trades if t.get("is_oos", False)]
                    metrics_oos = bte.calculate_metrics(oos_trades)

                    row_data = {
                        "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Ticker": ticker,
                        "Interval": interval,
                        "Score": score,
                        "Exit_Profile": exit_profile,
                        "Broker_Profile": broker,
                        "Total_Trades": metrics_all.get("Total Trades", 0),
                        "Winrate_Pct": round(metrics_all.get("Winrate (%)", 0.0), 2),
                        "Profit_Factor": round(metrics_all.get("Profit Factor", 0.0), 2) if pd.notna(metrics_all.get("Profit Factor")) else 0.0,
                        "Max_Drawdown_EUR": round(metrics_all.get("Max Drawdown (€)", 0.0), 2),
                        "Avg_R_Multiple": round(metrics_all.get("Ø R-Multiple", 0.0), 2),
                        "Net_PnL_EUR": round(metrics_all.get("Total Net PnL", 0.0), 2),
                        "OOS_Trades": metrics_oos.get("Total Trades", 0) if metrics_oos else 0,
                        "OOS_Winrate_Pct": round(metrics_oos.get("Winrate (%)", 0.0), 2) if metrics_oos else 0.0,
                        "OOS_Profit_Factor": round(metrics_oos.get("Profit Factor", 0.0), 2) if metrics_oos and pd.notna(metrics_oos.get("Profit Factor")) else 0.0,
                        "OOS_Net_PnL_EUR": round(metrics_oos.get("Total Net PnL", 0.0), 2) if metrics_oos else 0.0,
                    }

                    writer.writerow(row_data)
                    results.append(row_data)

                    del all_trades
                    del df_hist
                    gc.collect()

                except Exception as e:
                    print(f"❌ Fehler bei {ticker} (Score {score}): {e}")
                    traceback.print_exc()
                finally:
                    import time
                    time.sleep(1.0)

    print("\n" + "=" * 115)
    print(f"✅ MATRIX-VALIDIERUNG ABGESCHLOSSEN")
    print("=" * 115)
    
    if results:
        df_res = pd.DataFrame(results)
        df_res["Modus"] = df_res["Exit_Profile"].apply(
            lambda p: "Prop" if p in ["apex_lock", "ftmo_swing"] else "Privat"
        )
        display_df = df_res[["Ticker", "Interval", "Modus", "Exit_Profile", "Score", "Total_Trades", "OOS_Trades", "Winrate_Pct", "Profit_Factor", "OOS_Profit_Factor", "Max_Drawdown_EUR", "Net_PnL_EUR"]].copy()
        display_df.rename(columns={
            "Exit_Profile": "Profil", 
            "Total_Trades": "Total (IS+OOS)", 
            "OOS_Trades": "OOS Trades",
            "Winrate_Pct": "Winrate", 
            "Profit_Factor": "PF",
            "OOS_Profit_Factor": "OOS-PF",
            "Max_Drawdown_EUR": "Max DD",
            "Net_PnL_EUR": "Net PnL"
        }, inplace=True)
        
        print(display_df.to_string(index=False))
        print("-" * 115)
        print(f"💾 Alle Ergebnisse wurden in '{RESULTS_FILE}' gesichert.")
    else:
        print("⚠️ Keine Ergebnisse generiert. Bitte Fehler-Logs prüfen.")

if __name__ == "__main__":
    run_matrix()