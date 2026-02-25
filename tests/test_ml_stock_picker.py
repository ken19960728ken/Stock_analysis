"""
機器學習選股測試 — prepare_features, train_lightgbm, predict_scores, walk_forward
"""

import numpy as np
import pandas as pd
import pytest

lgb = pytest.importorskip("lightgbm", reason="lightgbm not available (requires libomp)")

from analysis.utils.ml_stock_picker import (
    MLModelResult,
    predict_scores,
    prepare_features,
    train_lightgbm,
    walk_forward_backtest,
)


@pytest.fixture
def sample_price_ml():
    """3 支股票 × 200 天日K"""
    dates = pd.date_range("2023-01-01", periods=200, freq="B")
    np.random.seed(42)
    rows = []
    for sid, base in [("2330", 500), ("2317", 100), ("2454", 300)]:
        prices = base + np.cumsum(np.random.randn(200) * 2)
        for i, d in enumerate(dates):
            rows.append({
                "stock_id": sid, "date": d,
                "open": float(prices[i] - 1),
                "high": float(prices[i] + 3),
                "low": float(prices[i] - 3),
                "close": float(prices[i]),
                "volume": np.random.randint(10_000_000, 50_000_000),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_per_ml():
    dates = pd.date_range("2023-01-01", periods=200, freq="B")
    rows = []
    for sid, per_base in [("2330", 18), ("2317", 12), ("2454", 25)]:
        for d in dates:
            rows.append({
                "stock_id": sid, "date": d,
                "per": per_base + np.random.randn() * 2,
                "pbr": 2.5 + np.random.randn() * 0.3,
                "dividend_yield": 3.0 + np.random.randn() * 0.5,
            })
    return pd.DataFrame(rows)


class TestPrepareFeatures:
    def test_output_shape(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        assert isinstance(X, pd.DataFrame)
        assert isinstance(y, pd.Series)
        assert len(X) == len(y)
        assert len(X) > 0

    def test_feature_columns_present(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        expected_cols = ["return_5d", "return_20d", "volatility_20d", "rsi", "macd_hist"]
        for col in expected_cols:
            assert col in X.columns

    def test_with_per_data(self, sample_price_ml, sample_per_ml):
        X, y, meta = prepare_features(sample_price_ml, per_df=sample_per_ml)
        assert "per" in X.columns

    def test_labels_are_quantiles(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml, n_quantiles=3)
        assert set(y.unique()).issubset({0, 1, 2})

    def test_empty_input(self):
        X, y, meta = prepare_features(pd.DataFrame())
        assert X.empty

    def test_short_data_skipped(self):
        """短資料的股票應被跳過"""
        short_data = pd.DataFrame({
            "stock_id": ["A"] * 10,
            "date": pd.date_range("2023-01-01", periods=10),
            "open": range(10), "high": range(10),
            "low": range(10), "close": range(10),
            "volume": [1000] * 10,
        })
        X, y, meta = prepare_features(short_data)
        assert X.empty


class TestTrainLightGBM:
    def test_returns_ml_model_result(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty:
            pytest.skip("No features prepared")
        split = int(len(X) * 0.8)
        result = train_lightgbm(X.iloc[:split], y.iloc[:split],
                                X.iloc[split:], y.iloc[split:])
        assert isinstance(result, MLModelResult)
        assert result.model is not None

    def test_has_feature_importance(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty:
            pytest.skip("No features prepared")
        split = int(len(X) * 0.8)
        result = train_lightgbm(X.iloc[:split], y.iloc[:split],
                                X.iloc[split:], y.iloc[split:])
        assert not result.feature_importance.empty
        assert "feature_name" in result.feature_importance.columns
        assert "importance" in result.feature_importance.columns

    def test_has_metrics(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty:
            pytest.skip("No features prepared")
        split = int(len(X) * 0.8)
        result = train_lightgbm(X.iloc[:split], y.iloc[:split],
                                X.iloc[split:], y.iloc[split:])
        assert "accuracy" in result.train_metrics
        assert "accuracy" in result.val_metrics

    def test_cv_mode(self, sample_price_ml):
        """不提供驗證集 → 用 TimeSeriesSplit CV"""
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty:
            pytest.skip("No features prepared")
        result = train_lightgbm(X, y, n_splits=3)
        assert result.model is not None

    def test_empty_input(self):
        result = train_lightgbm(pd.DataFrame(), pd.Series(dtype=int))
        assert isinstance(result, MLModelResult)
        assert result.model is None


class TestPredictScores:
    def test_prediction_output(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty:
            pytest.skip("No features prepared")
        split = int(len(X) * 0.8)
        ml_result = train_lightgbm(X.iloc[:split], y.iloc[:split],
                                   X.iloc[split:], y.iloc[split:])
        pred = predict_scores(ml_result.model, X.iloc[-10:])
        assert not pred.empty
        assert "pred_score" in pred.columns
        assert "pred_label" in pred.columns

    def test_none_model(self):
        pred = predict_scores(None, pd.DataFrame())
        assert pred.empty


class TestWalkForwardBacktest:
    def test_output_structure(self, sample_price_ml):
        X, y, meta = prepare_features(sample_price_ml)
        if X.empty or len(X) < 300:
            pytest.skip("Insufficient data for walk-forward")
        dates = meta["date"]
        result = walk_forward_backtest(X, y, dates, train_window=100, step=20)
        if not result.empty:
            assert "pred_score" in result.columns
            assert "actual_label" in result.columns

    def test_empty_input(self):
        result = walk_forward_backtest(
            pd.DataFrame(), pd.Series(dtype=int),
            pd.Series(dtype="datetime64[ns]"),
        )
        assert result.empty
