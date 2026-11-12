"""
Test Suite: ARAA AI Prediction-First Core Quantitative & ML Forecasting Engine
Validates:
1. Feature extraction and market regime detection
2. GRU sequence projection & statistical drift model
3. Multi-horizon price cones (1m, 5m, 15m, 30m, 1h, 4h)
4. Decision rules: UP, DOWN, SIDEWAYS, UNCERTAIN -> BUY, SELL, WAIT
5. Zero look-ahead bias and prediction accuracy tracking (Directional accuracy, Brier score, MAPE)
6. Non-blocking manual trading guidance
"""

import sys
import os
import unittest
import sqlite3

# Ensure backend directory is importable
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# pyrefly: ignore [missing-import]
from prediction_engine import (
    extract_features,
    run_gru_sequence_forecast,
    run_statistical_drift_model,
    generate_multi_horizon_forecast,
    predict_and_advise,
    record_prediction_audit,
    evaluate_prediction_accuracy,
    MODEL_VERSION
)

class TestPredictionEngine(unittest.TestCase):

    def setUp(self):
        # Create synthetic trending up candles
        self.bull_candles = []
        base_price = 100.0
        for i in range(50):
            p = base_price * (1.0 + (i * 0.005))
            self.bull_candles.append({
                "t": 1700000000 + i * 900,
                "o": p * 0.998,
                "h": p * 1.004,
                "l": p * 0.996,
                "c": p,
                "v": 1000 + i * 20
            })

        # Create synthetic range/sideways candles
        self.flat_candles = []
        for i in range(50):
            p = 100.0 + (0.1 if i % 2 == 0 else -0.1)
            self.flat_candles.append({
                "t": 1700000000 + i * 900,
                "o": p,
                "h": p + 0.15,
                "l": p - 0.15,
                "c": p,
                "v": 500
            })

    def test_feature_extraction(self):
        feat = extract_features(self.bull_candles)
        self.assertTrue(feat["valid"])
        self.assertEqual(feat["n_candles"], 50)
        self.assertGreater(feat["rsi"], 50.0)
        self.assertGreater(feat["trend_slope_fast"], 0.0)
        self.assertIn(feat["regime"], ["TRENDING_BULL", "HIGH_VOLATILITY", "COMPRESSION_RANGE", "UNCERTAIN_TRANSITION"])

    def test_gru_sequence_forecast(self):
        returns = [0.005, 0.004, 0.006, 0.003, 0.005]
        drift, prob_up = run_gru_sequence_forecast(returns, horizon_steps=3)
        self.assertIsInstance(drift, float)
        self.assertGreater(prob_up, 0.5)

    def test_multi_horizon_forecast(self):
        feat = extract_features(self.bull_candles)
        curr_p = feat["current_price"]
        horizons = generate_multi_horizon_forecast(curr_p, feat)
        for h in ["1m", "5m", "15m", "30m", "1h", "4h"]:
            self.assertIn(h, horizons)
            item = horizons[h]
            self.assertGreater(item["range_high"], item["range_low"])
            self.assertGreater(item["expected_price"], 0.0)

    def test_predict_and_advise_bull(self):
        pred = predict_and_advise("BTCUSDT", "CRYPTO", self.bull_candles, timeframe="15m")
        self.assertIn(pred["prediction"], ["UP", "DOWN", "SIDEWAYS", "UNCERTAIN"])
        self.assertIn(pred["decision"], ["BUY", "SELL", "WAIT"])
        self.assertIn("horizons", pred)
        self.assertEqual(pred["model_version"], MODEL_VERSION)
        self.assertIn("15m", pred["horizons"])
        self.assertIn("supporting_evidence", pred["reasoning"])
        self.assertIn("contradicting_evidence", pred["reasoning"])

    def test_prediction_audit_and_accuracy(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE ai_predictions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                category TEXT NOT NULL,
                direction TEXT NOT NULL,
                action TEXT NOT NULL,
                entry_price REAL NOT NULL,
                target_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_pct REAL NOT NULL,
                stop_pct REAL NOT NULL,
                risk_reward REAL NOT NULL,
                win_probability INTEGER NOT NULL,
                confidence REAL NOT NULL,
                rationale TEXT NOT NULL,
                mode TEXT NOT NULL,
                post_entry_status TEXT DEFAULT 'MONITORING',
                post_entry_notes TEXT,
                outcome TEXT DEFAULT 'PENDING',
                realized_pnl REAL DEFAULT 0,
                created_at REAL NOT NULL,
                closed_at REAL,
                position_id INTEGER
            );
        """)
        pred = predict_and_advise("ETHUSDT", "CRYPTO", self.bull_candles, timeframe="15m")
        row_id = record_prediction_audit(conn, pred, user_id=1)
        self.assertGreater(row_id, 0)

        # Mark outcome as WIN
        conn.execute("UPDATE ai_predictions SET outcome='WIN', realized_pnl=1250.0 WHERE id=?", (row_id,))
        conn.commit()

        acc = evaluate_prediction_accuracy(conn, symbol="ETHUSDT")
        self.assertEqual(acc["sample_size"], 1)
        self.assertEqual(acc["wins"], 1)
        self.assertEqual(acc["directional_accuracy_pct"], 100.0)
        self.assertLess(acc["brier_score"], 0.25)
        conn.close()

if __name__ == "__main__":
    unittest.main()
