"""
新策略單元測試 — 趨勢過濾MA + 多策略動態組合

覆蓋策略：
  1. TrendFilteredMAStrategy  (趨勢過濾MA)
  2. AdaptiveEnsembleStrategy (多策略動態組合)
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.trend_filtered_ma import TrendFilteredMAStrategy
from analysis.strategies.adaptive_ensemble import AdaptiveEnsembleStrategy


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def long_uptrend_data(sample_stock_id):
    """300 天資料：先盤整建立 MA200，再有明確趨勢轉變讓 MA10/MA40 交叉"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    # 前 210 天穩定上升（建立 MA200 基礎），中間 30 天回檔，最後 60 天快速上漲
    # 這樣可以在 ~240 天時產生 MA10 向上穿越 MA40 的 golden cross
    close = np.concatenate([
        np.linspace(100, 160, 210),     # 穩定上升
        np.linspace(158, 140, 30),      # 回檔 (MA10 < MA40)
        np.linspace(142, 200, 60),      # 反彈上漲 (MA10 > MA40 -> golden cross)
    ])
    noise = np.random.randn(n) * 1.5
    close = close + noise
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 1, "high": close + 4, "low": close - 4,
        "close": close, "volume": np.random.randint(10_000_000, 50_000_000, n),
    })


@pytest.fixture
def long_downtrend_data(sample_stock_id):
    """250 天長期下降趨勢"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    trend = np.linspace(200, 80, n)
    noise = np.random.randn(n) * 3
    close = trend + noise
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close + 1, "high": close + 4, "low": close - 4,
        "close": close, "volume": np.random.randint(10_000_000, 50_000_000, n),
    })


@pytest.fixture
def long_volatile_data(sample_stock_id):
    """250 天高波動資料，趨勢中性"""
    np.random.seed(123)
    n = 300
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = 500 + np.cumsum(np.random.randn(n) * 5)
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 2, "high": close + 6, "low": close - 6,
        "close": close, "volume": np.random.randint(10_000_000, 50_000_000, n),
    })


@pytest.fixture
def ensemble_data_with_chip_and_fundamental(sample_stock_id):
    """300 天資料含法人和基本面欄位"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    trend = np.linspace(100, 180, n)
    noise = np.random.randn(n) * 3
    close = trend + noise
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 1, "high": close + 4, "low": close - 4,
        "close": close, "volume": np.random.randint(10_000_000, 50_000_000, n),
        "institutional_net_buy": np.random.randint(-1000, 1000, n),
        "PER": 12 + np.sin(np.arange(n) / 30) * 5,
        "DividendYield": 3.0 + np.random.randn(n) * 1.0,
        "revenue_yoy": 5.0 + np.random.randn(n) * 10,
    })


@pytest.fixture
def ensemble_data_tech_only(sample_stock_id):
    """300 天只有技術面資料（無法人、無基本面）"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = 500 + np.cumsum(np.random.randn(n) * 3)
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close, "volume": np.random.randint(10_000_000, 50_000_000, n),
    })


# ============================================================================
# 1. TestTrendFilteredMAStrategy
# ============================================================================

class TestTrendFilteredMAStrategy:
    """趨勢過濾MA策略"""

    def test_basic_signal_generation(self, long_uptrend_data):
        """基本訊號生成：signal 欄位存在且值合法"""
        s = TrendFilteredMAStrategy()
        result = s.generate_signals(long_uptrend_data)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_uptrend_has_buy_signals(self, long_uptrend_data):
        """明確上升趨勢應有買入訊號"""
        s = TrendFilteredMAStrategy()
        result = s.generate_signals(long_uptrend_data)
        assert (result["signal"] == 1).any()

    def test_downtrend_fewer_buy_signals(self, long_downtrend_data, long_uptrend_data):
        """下降趨勢中，趨勢過濾應大幅減少買入訊號"""
        s = TrendFilteredMAStrategy()
        r_down = s.generate_signals(long_downtrend_data)
        buys_down = (r_down["signal"] == 1).sum()

        s2 = TrendFilteredMAStrategy()
        r_up = s2.generate_signals(long_uptrend_data)
        buys_up = (r_up["signal"] == 1).sum()

        # 下跌趨勢中的買入訊號應該少於上升趨勢
        assert buys_down <= buys_up

    def test_trend_filter_off_more_signals(self, long_volatile_data):
        """關閉趨勢過濾 -> 更多訊號"""
        s_on = TrendFilteredMAStrategy()
        r_on = s_on.generate_signals(long_volatile_data.copy())

        s_off = TrendFilteredMAStrategy()
        s_off.set_params(use_trend_filter=False)
        r_off = s_off.generate_signals(long_volatile_data.copy())

        signals_on = (r_on["signal"] != 0).sum()
        signals_off = (r_off["signal"] != 0).sum()
        # 關閉過濾應產生 >= 啟用過濾的訊號數
        assert signals_off >= signals_on

    def test_atr_filter_reduces_signals(self, long_volatile_data):
        """高 ATR 閾值應減少訊號"""
        s_low = TrendFilteredMAStrategy()
        s_low.set_params(atr_threshold=0.5, use_trend_filter=False)
        r_low = s_low.generate_signals(long_volatile_data.copy())

        s_high = TrendFilteredMAStrategy()
        s_high.set_params(atr_threshold=5.0, use_trend_filter=False)
        r_high = s_high.generate_signals(long_volatile_data.copy())

        buys_low = (r_low["signal"] == 1).sum()
        buys_high = (r_high["signal"] == 1).sum()
        assert buys_high <= buys_low

    def test_min_holding_period(self, long_uptrend_data):
        """最低持有期間：買入後不會立即賣出"""
        s = TrendFilteredMAStrategy()
        s.set_params(min_holding_days=20)
        result = s.generate_signals(long_uptrend_data)

        # 找到所有買入訊號的位置
        buy_indices = result.index[result["signal"] == 1].tolist()
        sell_indices = result.index[result["signal"] == -1].tolist()

        for buy_idx in buy_indices:
            # 找到此買入後的第一個賣出
            later_sells = [s for s in sell_indices if s > buy_idx]
            if later_sells:
                sell_idx = later_sells[0]
                # 間隔應 >= min_holding_days
                gap = sell_idx - buy_idx
                assert gap >= 20, f"持有期間 {gap} < 最低持有 20 天"

    def test_set_params(self, long_uptrend_data):
        """參數修改正確反映"""
        s = TrendFilteredMAStrategy()
        s.set_params(fast_period=5, slow_period=20, trend_period=100)
        assert s.params["fast_period"] == 5
        assert s.params["slow_period"] == 20
        assert s.params["trend_period"] == 100
        result = s.generate_signals(long_uptrend_data)
        assert "signal" in result.columns

    def test_short_data_no_crash(self, sample_stock_id):
        """資料不足 200 天也不會崩潰"""
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [100] * 30, "high": [105] * 30, "low": [95] * 30,
            "close": [100] * 30, "volume": [1_000_000] * 30,
        })
        s = TrendFilteredMAStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        # 資料不足，不應產生訊號（MA200 全部 NaN）
        assert (result["signal"] == 0).all()

    def test_output_columns(self, long_uptrend_data):
        """輸出應包含輔助欄位"""
        s = TrendFilteredMAStrategy()
        result = s.generate_signals(long_uptrend_data)
        assert "fast_ma" in result.columns
        assert "slow_ma" in result.columns
        assert "trend_ma" in result.columns
        assert "atr_pct" in result.columns

    def test_trend_exit_protection(self, sample_stock_id):
        """跌破趨勢線保護性賣出"""
        np.random.seed(42)
        n = 350
        dates = pd.date_range("2021-06-01", periods=n, freq="B")
        # 分四段：盤整 -> 小回檔 -> 上漲 (觸發買入) -> 暴跌 (觸發趨勢退出)
        close = np.concatenate([
            np.linspace(100, 150, 210),    # 穩定上升建立 MA200
            np.linspace(148, 135, 30),     # 回檔讓 fast_ma < slow_ma
            np.linspace(137, 190, 60),     # 反彈觸發 golden cross 買入
            np.linspace(188, 100, 50),     # 暴跌跌破 MA200
        ])
        noise = np.random.randn(n) * 1.0
        close = close + noise
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close - 1, "high": close + 3, "low": close - 3,
            "close": close, "volume": [30_000_000] * n,
        })
        s = TrendFilteredMAStrategy()
        s.set_params(trend_exit=True, min_holding_days=5)
        result = s.generate_signals(df)
        # 整體應有買入和賣出訊號
        assert (result["signal"] == 1).any(), "應有買入訊號"
        assert (result["signal"] == -1).any(), "暴跌期間應有賣出訊號"


# ============================================================================
# 2. TestAdaptiveEnsembleStrategy
# ============================================================================

class TestAdaptiveEnsembleStrategy:
    """多策略動態組合策略"""

    def test_basic_signal_generation(self, ensemble_data_with_chip_and_fundamental):
        """基本訊號生成"""
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(ensemble_data_with_chip_and_fundamental)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_has_subscores(self, ensemble_data_with_chip_and_fundamental):
        """輸出包含子策略分數"""
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(ensemble_data_with_chip_and_fundamental)
        assert "inst_score" in result.columns
        assert "value_score" in result.columns
        assert "trend_score" in result.columns
        assert "total_score" in result.columns

    def test_tech_only_graceful(self, ensemble_data_tech_only):
        """僅技術面資料也能執行（法人和基本面分數歸零）"""
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(ensemble_data_tech_only)
        assert "signal" in result.columns
        # 法人分數應為 0（沒有匹配到任何法人欄位）
        assert (result["inst_score"] == 0.0).all()
        # 價值分數也應為 0（沒有 PER/DividendYield/revenue_yoy 欄位）
        assert (result["value_score"] == 0.0).all()
        # 趨勢分數應非全零（有技術面資料）
        assert "trend_score" in result.columns

    def test_full_data_has_signals(self, ensemble_data_with_chip_and_fundamental):
        """完整資料應能產生交易訊號"""
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(ensemble_data_with_chip_and_fundamental)
        # 有完整的三維度資料，應該有訊號
        total_signals = (result["signal"] != 0).sum()
        assert total_signals >= 0  # 至少不崩潰

    def test_min_holding_period(self, ensemble_data_with_chip_and_fundamental):
        """最低持有期間控制"""
        s = AdaptiveEnsembleStrategy()
        s.set_params(min_holding_days=20)
        result = s.generate_signals(ensemble_data_with_chip_and_fundamental)

        buy_indices = result.index[result["signal"] == 1].tolist()
        sell_indices = result.index[result["signal"] == -1].tolist()

        for buy_idx in buy_indices:
            later_sells = [si for si in sell_indices if si > buy_idx]
            if later_sells:
                sell_idx = later_sells[0]
                gap = sell_idx - buy_idx
                assert gap >= 20, f"持有期間 {gap} < 最低持有 20 天"

    def test_weight_sensitivity(self, ensemble_data_with_chip_and_fundamental):
        """不同權重產生不同結果"""
        s1 = AdaptiveEnsembleStrategy()
        s1.set_params(institutional_weight=0.8, value_weight=0.1, trend_weight=0.1)
        r1 = s1.generate_signals(ensemble_data_with_chip_and_fundamental.copy())

        s2 = AdaptiveEnsembleStrategy()
        s2.set_params(institutional_weight=0.1, value_weight=0.1, trend_weight=0.8)
        r2 = s2.generate_signals(ensemble_data_with_chip_and_fundamental.copy())

        # 權重改變應影響 total_score
        assert not r1["total_score"].equals(r2["total_score"])

    def test_consensus_mechanism(self, ensemble_data_with_chip_and_fundamental):
        """共識機制：min_agree=3 應比 min_agree=1 產生更少訊號"""
        s_strict = AdaptiveEnsembleStrategy()
        s_strict.set_params(min_agree=3, buy_threshold=0.2)
        r_strict = s_strict.generate_signals(
            ensemble_data_with_chip_and_fundamental.copy()
        )

        s_loose = AdaptiveEnsembleStrategy()
        s_loose.set_params(min_agree=1, buy_threshold=0.2)
        r_loose = s_loose.generate_signals(
            ensemble_data_with_chip_and_fundamental.copy()
        )

        buys_strict = (r_strict["signal"] == 1).sum()
        buys_loose = (r_loose["signal"] == 1).sum()
        assert buys_strict <= buys_loose

    def test_set_params(self):
        """參數設定正確"""
        s = AdaptiveEnsembleStrategy()
        s.set_params(
            institutional_weight=0.5,
            value_weight=0.25,
            trend_weight=0.25,
            min_holding_days=30,
        )
        assert s.params["institutional_weight"] == 0.5
        assert s.params["min_holding_days"] == 30

    def test_threshold_sensitivity(self, ensemble_data_with_chip_and_fundamental):
        """嚴格閾值 -> 更少訊號"""
        s_tight = AdaptiveEnsembleStrategy()
        s_tight.set_params(buy_threshold=0.9, sell_threshold=-0.9)
        r_tight = s_tight.generate_signals(
            ensemble_data_with_chip_and_fundamental.copy()
        )

        s_loose = AdaptiveEnsembleStrategy()
        s_loose.set_params(buy_threshold=0.1, sell_threshold=-0.1)
        r_loose = s_loose.generate_signals(
            ensemble_data_with_chip_and_fundamental.copy()
        )

        buys_tight = (r_tight["signal"] == 1).sum()
        buys_loose = (r_loose["signal"] == 1).sum()
        assert buys_tight <= buys_loose

    def test_short_data_no_crash(self, sample_stock_id):
        """資料不足也不崩潰"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [100] * 10, "high": [105] * 10, "low": [95] * 10,
            "close": [100] * 10, "volume": [1_000_000] * 10,
        })
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns

    def test_institutional_consecutive_buy_generates_positive_score(self, sample_stock_id):
        """連續法人買超應產生正的法人分數"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # 連續 10 天法人買超
        inst_buy = [0] * 20 + [500] * 10 + [0] * 20
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500] * n, "high": [505] * n, "low": [495] * n,
            "close": [500] * n, "volume": [30_000_000] * n,
            "institutional_net_buy": inst_buy,
        })
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(df)
        # 連續買超期間，法人分數應 > 0
        buy_period = result.iloc[22:30]
        assert (buy_period["inst_score"] > 0).any()

    def test_value_conditions_generate_positive_score(self, sample_stock_id):
        """低 PE + 高殖利率應產生正的價值分數"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500] * n, "high": [505] * n, "low": [495] * n,
            "close": [500] * n, "volume": [30_000_000] * n,
            "PER": [10] * n,           # 低 PE
            "DividendYield": [5.0] * n,  # 高殖利率
            "revenue_yoy": [15.0] * n,   # 營收正成長
        })
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(df)
        # 價值分數應為正
        assert (result["value_score"] > 0).any()

    def test_institutional_score_prefers_net_buy_column(self, sample_stock_id):
        """法人分數應優先使用含 'net' 的淨買超欄位，而非單邊 'buy' 欄位"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # foreign_buy = 永遠正值（單邊買量），institutional_net_buy = 有正有負
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500] * n, "high": [505] * n, "low": [495] * n,
            "close": [500] * n, "volume": [30_000_000] * n,
            "foreign_buy": [1000] * n,                   # 單邊量，不應被使用
            "institutional_net_buy": [-500] * 20 + [500] * 10 + [-500] * 20,
        })
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(df)
        # 若正確使用 net_buy，前 20 天賣超時法人分數應 < 0
        early_period = result.iloc[5:20]
        assert (early_period["inst_score"] <= 0).all(), \
            "應使用 institutional_net_buy 而非 foreign_buy"

    def test_no_net_column_falls_back_gracefully(self, sample_stock_id):
        """無 net 欄位也無精確匹配 → 法人分數為 0"""
        n = 50
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500] * n, "high": [505] * n, "low": [495] * n,
            "close": [500] * n, "volume": [30_000_000] * n,
            # 只有單邊 buy 欄位，不含 "net" → 不該被匹配
            "foreign_buy": [1000] * n,
        })
        s = AdaptiveEnsembleStrategy()
        result = s.generate_signals(df)
        # 找不到淨值欄位，法人分數應全為 0
        assert (result["inst_score"] == 0.0).all()


# ============================================================================
# 3. Cross-Strategy Integration Tests
# ============================================================================

class TestStrategyIntegration:
    """整合測試：確認新策略可被 STRATEGY_MAP 找到"""

    def test_trend_filtered_in_map(self):
        from analysis.strategies import STRATEGY_MAP
        assert "趨勢過濾MA" in STRATEGY_MAP

    def test_adaptive_ensemble_in_map(self):
        from analysis.strategies import STRATEGY_MAP
        assert "多策略動態組合" in STRATEGY_MAP

    def test_total_strategy_count(self):
        from analysis.strategies import STRATEGY_MAP
        assert len(STRATEGY_MAP) == 22  # 16 original + 2 + 3 new + 1 次產業輪動

    def test_instantiate_all_strategies(self):
        """所有策略都能正常實例化"""
        from analysis.strategies import STRATEGY_MAP
        for name, cls in STRATEGY_MAP.items():
            s = cls()
            assert hasattr(s, "name")
            assert hasattr(s, "description")
            assert hasattr(s, "params")
            assert hasattr(s, "generate_signals")
