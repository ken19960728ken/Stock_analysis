"""
兩層產業分類系統測試
- IndustryScanner 單元測試（mock FinMind）
- 產業標準化映射測試
- 兩層分類合併邏輯測試
- 產業集中度計算測試
- 產業中性化計算測試
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# 確保專案根目錄在 sys.path
import sys
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ===================================================================
# 1. 產業標準化映射測試
# ===================================================================

class TestNormalizeSector:
    def test_direct_match(self):
        from core.constants import normalize_sector
        assert normalize_sector("半導體業") == "半導體業"

    def test_alias_match(self):
        from core.constants import normalize_sector
        assert normalize_sector("半導體") == "半導體業"
        assert normalize_sector("觀光事業") == "觀光餐旅"
        assert normalize_sector("金融保險") == "金融保險業"

    def test_unknown_passthrough(self):
        from core.constants import normalize_sector
        assert normalize_sector("未知產業XYZ") == "未知產業XYZ"

    def test_none_input(self):
        from core.constants import normalize_sector
        assert normalize_sector(None) is None
        assert normalize_sector("") == ""

    def test_strip_whitespace(self):
        from core.constants import normalize_sector
        assert normalize_sector("  半導體  ") == "半導體業"

    def test_twse_sectors_has_33(self):
        from core.constants import TWSE_SECTORS
        assert len(TWSE_SECTORS) == 33


# ===================================================================
# 2. IndustryScanner 單元測試（mock FinMind）
# ===================================================================

class TestIndustryScanner:
    @patch("scanners.industry_scanner.get_fm_loader")
    @patch("scanners.industry_scanner.get_engine")
    def test_scan_basic(self, mock_engine, mock_fm_loader):
        """基本掃描流程：FinMind → 標準化 → 寫入 DB"""
        # Mock FinMind 回傳
        loader = MagicMock()
        fm_df = pd.DataFrame({
            "stock_id": ["2330", "2317", "2881"],
            "industry_category": ["半導體", "其他電子", "金融保險"],
        })
        loader.taiwan_stock_info.return_value = fm_df
        mock_fm_loader.return_value = loader

        # Mock engine
        engine = MagicMock()
        mock_engine.return_value = engine

        from scanners.industry_scanner import IndustryScanner
        scanner = IndustryScanner()

        # to_sql 會被呼叫兩次（industry_classification + industry_mapping）
        with patch.object(pd.DataFrame, "to_sql") as mock_to_sql:
            scanner.scan()
            assert mock_to_sql.call_count == 2
            # 第一次是 industry_classification
            call_args = mock_to_sql.call_args_list[0]
            assert call_args[0][0] == "industry_classification"

    @patch("scanners.industry_scanner.get_fm_loader")
    def test_scan_empty_data(self, mock_fm_loader):
        """FinMind 回傳空資料時不寫入"""
        loader = MagicMock()
        loader.taiwan_stock_info.return_value = pd.DataFrame()
        mock_fm_loader.return_value = loader

        from scanners.industry_scanner import IndustryScanner
        scanner = IndustryScanner()
        # Should not raise
        scanner.scan()

    @patch("scanners.industry_scanner.get_fm_loader")
    def test_scan_missing_column(self, mock_fm_loader):
        """缺少 industry_category 欄位"""
        loader = MagicMock()
        loader.taiwan_stock_info.return_value = pd.DataFrame({
            "stock_id": ["2330"], "name": ["台積電"]
        })
        mock_fm_loader.return_value = loader

        from scanners.industry_scanner import IndustryScanner
        scanner = IndustryScanner()
        scanner.scan()  # Should not raise


# ===================================================================
# 3. 兩層分類合併邏輯測試
# ===================================================================

class TestSubIndustryMapping:
    def test_load_sub_industry_mapping(self):
        """確認 sub_industry_mapping.json 可正常載入"""
        from scanners.industry_scanner import _load_sub_industry_mapping
        mapping = _load_sub_industry_mapping()
        # 至少應有 2330（IC 製造）和 2454（IC 設計）
        assert "2330" in mapping
        assert "2454" in mapping
        assert mapping["2330"] == "IC 製造"
        assert mapping["2454"] == "IC 設計"

    def test_sub_industry_json_valid(self):
        """JSON 格式正確"""
        json_path = Path(ROOT) / "data" / "sub_industry_mapping.json"
        assert json_path.exists()
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert len(data) > 0
        # 每個大類下應有次產業
        for sector, subs in data.items():
            assert isinstance(subs, dict), f"{sector} 應為 dict"
            for sub_name, stock_ids in subs.items():
                assert isinstance(stock_ids, list), f"{sector}/{sub_name} 應為 list"

    def test_sector_normalization_in_scanner(self):
        """Scanner 應將 FinMind 名稱標準化"""
        from core.constants import normalize_sector
        # 模擬 FinMind 回傳的名稱
        assert normalize_sector("半導體") == "半導體業"
        assert normalize_sector("電腦及週邊設備") == "電腦及週邊設備業"


# ===================================================================
# 4. 產業集中度計算測試
# ===================================================================

class TestIndustryConcentration:
    def test_basic_concentration(self):
        from analysis.utils.risk import calc_industry_concentration

        holdings = pd.DataFrame({
            "stock_id": ["2330", "2454", "2881"],
            "shares": [1000, 1000, 1000],
        })
        current_prices = {"2330": 600, "2454": 800, "2881": 50}
        industry_map = pd.DataFrame({
            "stock_id": ["2330", "2454", "2881"],
            "sector": ["半導體業", "半導體業", "金融保險業"],
        })

        result = calc_industry_concentration(holdings, current_prices, industry_map)
        assert "breakdown" in result
        assert "warnings" in result
        assert "hhi" in result
        assert len(result["breakdown"]) == 2  # 半導體 + 金融

        # 半導體佔比 = (600+800)/(600+800+50) ≈ 96.6%
        semi_row = result["breakdown"][result["breakdown"]["sector"] == "半導體業"]
        assert not semi_row.empty
        assert semi_row["weight"].values[0] > 0.9

        # 應有超過 40% 的警告
        assert len(result["warnings"]) >= 1

    def test_empty_holdings(self):
        from analysis.utils.risk import calc_industry_concentration
        result = calc_industry_concentration(
            pd.DataFrame(columns=["stock_id", "shares"]),
            {},
            pd.DataFrame(columns=["stock_id", "sector"]),
        )
        assert result["hhi"] == 0.0
        assert result["breakdown"].empty

    def test_single_industry(self):
        from analysis.utils.risk import calc_industry_concentration
        holdings = pd.DataFrame({
            "stock_id": ["2330", "2454"],
            "shares": [1000, 1000],
        })
        current_prices = {"2330": 500, "2454": 500}
        industry_map = pd.DataFrame({
            "stock_id": ["2330", "2454"],
            "sector": ["半導體業", "半導體業"],
        })
        result = calc_industry_concentration(holdings, current_prices, industry_map)
        assert result["hhi"] == 1.0  # 全部同一產業
        assert len(result["warnings"]) >= 1

    def test_fallback_industry_category(self):
        """若無 sector 欄位，應 fallback 到 industry_category"""
        from analysis.utils.risk import calc_industry_concentration
        holdings = pd.DataFrame({
            "stock_id": ["2330"], "shares": [1000],
        })
        industry_map = pd.DataFrame({
            "stock_id": ["2330"], "industry_category": ["半導體業"],
        })
        result = calc_industry_concentration(holdings, {"2330": 500}, industry_map)
        assert not result["breakdown"].empty


# ===================================================================
# 5. 產業中性化計算測試
# ===================================================================

class TestIndustryNeutral:
    def test_basic_neutralization(self):
        from analysis.utils.factor_engine import zscore_industry_neutral

        # 構造跨產業的因子資料
        df = pd.DataFrame({
            "date": ["2024-01-01"] * 6,
            "stock_id": ["A", "B", "C", "D", "E", "F"],
            "sector": ["半導體"] * 3 + ["金融"] * 3,
            "factor": [100, 200, 300, 10, 20, 30],
        })

        result = zscore_industry_neutral(df, "factor", "sector")
        assert len(result) == 6
        # 同產業內 z-score 應約為 [-1, 0, 1]
        semi = result.iloc[:3]
        assert abs(semi.mean()) < 0.01  # 均值約 0

    def test_single_stock_industry(self):
        """單支股票的產業，z-score 應為 0"""
        from analysis.utils.factor_engine import zscore_industry_neutral

        df = pd.DataFrame({
            "date": ["2024-01-01"] * 2,
            "stock_id": ["A", "B"],
            "sector": ["半導體", "金融"],
            "factor": [100, 200],
        })

        result = zscore_industry_neutral(df, "factor", "sector")
        assert all(result == 0.0)

    def test_missing_column(self):
        """缺少欄位時回傳全 0"""
        from analysis.utils.factor_engine import zscore_industry_neutral

        df = pd.DataFrame({
            "date": ["2024-01-01"],
            "stock_id": ["A"],
            "factor": [100],
        })
        result = zscore_industry_neutral(df, "factor", "sector")
        assert all(result == 0.0)


# ===================================================================
# 6. 產業輪動兩層分析測試
# ===================================================================

class TestSectorRotationTwoLevel:
    def _make_data(self):
        industry_map = pd.DataFrame({
            "stock_id": ["A", "B", "C", "D"],
            "industry_category": ["半導體業", "半導體業", "金融保險業", "金融保險業"],
            "sector": ["半導體業", "半導體業", "金融保險業", "金融保險業"],
            "sub_industry": ["IC 設計", "IC 製造", "銀行", "壽險"],
        })
        revenue_df = pd.DataFrame({
            "stock_id": ["A", "B", "C", "D"] * 3,
            "date": pd.to_datetime(["2024-01-15"] * 4 + ["2024-02-15"] * 4 + ["2024-03-15"] * 4),
            "revenue": [100, 200, 50, 80] * 3,
            "month_revenue_year_on_year": [10, 20, -5, 5] * 3,
        })
        return revenue_df, industry_map

    def test_sector_level(self):
        from analysis.utils.sector_rotation import calc_industry_momentum
        revenue_df, industry_map = self._make_data()
        result = calc_industry_momentum(revenue_df, industry_map, lookback_months=3, level="sector")
        assert not result.empty
        # 應有 2 個大類
        assert len(result) == 2

    def test_sub_industry_level(self):
        from analysis.utils.sector_rotation import calc_industry_momentum
        revenue_df, industry_map = self._make_data()
        result = calc_industry_momentum(revenue_df, industry_map, lookback_months=3, level="sub_industry")
        assert not result.empty
        # 應有 4 個次產業
        assert len(result) == 4

    def test_flow_two_level(self):
        from analysis.utils.sector_rotation import calc_industry_flow
        _, industry_map = self._make_data()
        chip_df = pd.DataFrame({
            "stock_id": ["A", "B", "C", "D"],
            "date": pd.to_datetime(["2024-03-10"] * 4),
            "foreign_investors_buy": [1000, 2000, 500, 800],
            "foreign_investors_sell": [500, 1000, 800, 200],
        })
        result_sector = calc_industry_flow(chip_df, industry_map, lookback_days=30, level="sector")
        result_sub = calc_industry_flow(chip_df, industry_map, lookback_days=30, level="sub_industry")
        assert len(result_sector) == 2
        assert len(result_sub) == 4


# ===================================================================
# 7. data_loader load_industry_mapping 向後相容測試
# ===================================================================

class TestDataLoaderIndustryMapping:
    @patch("analysis.utils.data_loader.safe_read_sql")
    def test_new_table_priority(self, mock_sql):
        """優先讀 industry_classification"""
        from analysis.utils.data_loader import load_industry_mapping
        # 清除 streamlit cache
        try:
            load_industry_mapping.clear()
        except AttributeError:
            pass

        mock_sql.return_value = pd.DataFrame({
            "stock_id": ["2330"],
            "sector": ["半導體業"],
            "sub_industry": ["IC 製造"],
            "industry_category": ["半導體業"],
        })
        result = load_industry_mapping()
        assert "sector" in result.columns
        assert "sub_industry" in result.columns
        assert result.iloc[0]["sector"] == "半導體業"

    @patch("analysis.utils.data_loader.safe_read_sql")
    def test_fallback_old_table(self, mock_sql):
        """新表空時 fallback 舊表"""
        from analysis.utils.data_loader import load_industry_mapping
        try:
            load_industry_mapping.clear()
        except AttributeError:
            pass

        # 第一次呼叫回空（新表），第二次回資料（舊表）
        mock_sql.side_effect = [
            pd.DataFrame(),
            pd.DataFrame({"stock_id": ["2330"], "industry_category": ["半導體業"]}),
        ]
        result = load_industry_mapping()
        assert not result.empty
        assert "sector" in result.columns
        assert result.iloc[0]["sector"] == "半導體業"
        assert result.iloc[0]["sub_industry"] is None

    @patch("analysis.utils.data_loader.safe_read_sql")
    def test_both_empty(self, mock_sql):
        """新舊表皆空"""
        from analysis.utils.data_loader import load_industry_mapping
        try:
            load_industry_mapping.clear()
        except AttributeError:
            pass

        mock_sql.side_effect = [pd.DataFrame(), pd.DataFrame()]
        result = load_industry_mapping()
        assert result.empty
        assert "stock_id" in result.columns


# ===================================================================
# 8. DB 白名單測試
# ===================================================================

class TestDBWhitelist:
    def test_industry_classification_in_valid_tables(self):
        from core.db import VALID_TABLES
        assert "industry_classification" in VALID_TABLES
        assert "industry_mapping" in VALID_TABLES
