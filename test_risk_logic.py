import unittest
import pandas as pd
import sys
import io

# --- TRICK: Konsolen-Ausgabe (Warnungen) stummschalten während des Imports ---
# Wir fangen die Streamlit-Panik ab, damit die Konsole sauber bleibt.
original_stderr = sys.stderr
sys.stderr = io.StringIO()

try:
    from app import (
        calculate_master_score, 
        calculate_sl_tp_crv, 
        calculate_position_size, 
        calculate_smart_proposal
    )
finally:
    # Ton wieder an!
    sys.stderr = original_stderr

# --- HIER STARTEN DIE EIGENTLICHEN TESTS ---
class TestRiskAndScoreLogic(unittest.TestCase):

    def setUp(self):
        self.standard_config = {
            "global_settings": {
                "risk_mode": "Festes Euro-Risiko (€)",
                "account_size": 10000.0,
                "risk_eur": 100.0,
                "prop_guard": True
            }
        }
        
    def test_master_score_hard_cap_zu_teuer(self):
        """Testet das Hard-Cap (Max 45 Pkt), wenn das Signal 'Zu teuer' ist."""
        details = {"score": 5, "score_max": 6, "ampel": "🔴 Zu teuer", "plateau": "⛰️ Robust", "is_dynamic": False}
        score_val, score_str, _ = calculate_master_score(details, "🟢 Top CRV (1:3.0)", 1.10, 85.0, 30.0)
        self.assertLessEqual(score_val, 45, "Master-Score darf bei 'Zu teuer' nicht über 45 liegen!")

    def test_master_score_setup_b_pullback(self):
        """Testet, ob das Setup B (Trend-Kauf Pullback) korrekt den Signal-Bonus von 15 erhält."""
        details = {"score": 4, "score_max": 6, "ampel": "🔵 Trend-Kauf (Pullback)", "plateau": "⚪ N/A", "is_dynamic": False}
        score_val, _, _ = calculate_master_score(details, "🟡 Passabel", 1.0, 45.0, 30.0)
        # 4/6 von 40 = 26 Pkt, + 15 Pkt CRV, + 0 Pkt RS, + 15 Pkt Bonus = 56
        self.assertGreaterEqual(score_val, 55, "Trend-Pullbacks müssen den vollen 15 Pkt Signal-Bonus bekommen.")

    def test_division_by_zero_atr_and_crv(self):
        """Testet die Absicherung gegen Division durch 0 (z.B. ATR = 0 oder gleicher Entry/SL)."""
        df_mock = pd.DataFrame({"High": [10, 10], "Low": [10, 10], "Close": [10, 10], "EMA_200": [9, 9], "EMA_20": [9, 9]})
        sl, tp, crv_rating = calculate_sl_tp_crv(df_mock, current_price=10.0, p_sell=11.0, tab_mode="tab1")
        # System sollte den SL durch die Zwangs-Regel korrigieren (current_price * 0.95)
        self.assertNotEqual(sl, 10.0, "SL muss korrigiert werden, um Division durch 0 zu vermeiden.")
        self.assertNotIn("N/A", crv_rating)

    def test_prop_firm_limit_and_smart_proposal(self):
        """Testet den Prop-Firm Guard (Modifier darf nicht > 1.0 sein)."""
        proposal = calculate_smart_proposal(
            entry_price=10.0, sl_price=9.0, tp_price=13.0, 
            max_r_eur=100.0, config=self.standard_config, expected_days=5
        )
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["risk"], 100.0, "Risk darf bei Prop-Guard = True nicht über das Basisrisiko steigen.")
        self.assertIn("strikt auf Limit gedeckelt", proposal["reason"])

if __name__ == '__main__':
    # verbosity=2 gibt eine schöne, detaillierte Ausgabe in der Konsole
    unittest.main(verbosity=2)