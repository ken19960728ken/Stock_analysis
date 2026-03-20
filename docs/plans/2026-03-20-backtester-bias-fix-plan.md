# 回測前視偏差修正 — 實作計畫

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修正回測引擎的三層前視偏差 — 資料公布延遲、全期統計量、未來資料洩漏 — 讓回測績效數字可信。

**Architecture:** 在資料載入層（`enrich_data`）加入 `DATA_PUBLICATION_DELAY` 延遲偏移，在統計工具層（`factor_engine`、`multi_factor`）將全期統計量改為 rolling 統計量。策略的 `generate_signals` 介面不變。

**Tech Stack:** Python 3.11, pandas (merge_asof, rolling), numpy

**設計文件:** `docs/plans/2026-03-20-backtester-bias-fix-design.md`

---

### Task 1: 新增 DATA_PUBLICATION_DELAY 常數

**Files:**
- Modify: `core/constants.py`
- Create: `tests/test_data_publication_delay.py`

**Step 1: 寫測試**

建立 `tests/test_data_publication_delay.py`：

```python
"""
資料公布延遲常數測試

覆蓋：
  - 常數存在且完整
  - 延遲值合理範圍
  - 延遲偏移工具函式正確
"""

import pandas as pd
import pytest

from core.constants import DATA_PUBLICATION_DELAY, apply_publication_delay


class TestPublicationDelayConstants:
    """延遲常數完整性"""

    def test_all_data_tables_have_delay(self):
        expected_tables = {
            "daily_price", "chip_institutional", "chip_margin",
            "chip_holding_pct", "chip_securities_lending", "chip_short_sale",
            "stock_per", "month_revenue", "financial_reports",
            "dividend_history", "market_value",
        }
        for table in expected_tables:
            assert table in DATA_PUBLICATION_DELAY, f"{table} 缺少延遲定義"

    def test_daily_price_has_zero_delay(self):
        assert DATA_PUBLICATION_DELAY["daily_price"] == 0

    def test_month_revenue_delay_is_10(self):
        assert DATA_PUBLICATION_DELAY["month_revenue"] == 10

    def test_financial_reports_delay_is_45(self):
        assert DATA_PUBLICATION_DELAY["financial_reports"] == 45

    def test_all_delays_are_non_negative(self):
        for table, delay in DATA_PUBLICATION_DELAY.items():
            assert delay >= 0, f"{table} 延遲為負: {delay}"


class TestApplyPublicationDelay:
    """延遲偏移工具函式"""

    def test_zero_delay_returns_unchanged(self):
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=5),
            "value": [1, 2, 3, 4, 5],
        })
        result = apply_publication_delay(df, "daily_price")
        pd.testing.assert_frame_equal(result, df)

    def test_delay_shifts_dates_forward(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-02-28")],
            "revenue": [1000],
        })
        result = apply_publication_delay(df, "month_revenue")
        # 月營收延遲 10 天：2025-02-28 → 2025-03-10
        assert result.iloc[0]["date"] == pd.Timestamp("2025-03-10")

    def test_delay_preserves_other_columns(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-03-31")],
            "value": [42.0],
            "type": ["EPS"],
        })
        result = apply_publication_delay(df, "financial_reports")
        assert result.iloc[0]["value"] == 42.0
        assert result.iloc[0]["type"] == "EPS"

    def test_unknown_table_returns_unchanged(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-01-01")],
            "value": [1],
        })
        result = apply_publication_delay(df, "unknown_table")
        pd.testing.assert_frame_equal(result, df)

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=["date", "value"])
        result = apply_publication_delay(df, "month_revenue")
        assert result.empty
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_data_publication_delay.py -v
```

預期：ImportError

**Step 3: 在 core/constants.py 末尾新增**

```python
# ---------------------------------------------------------------------------
# 資料公布延遲（日曆日）
# 回測時，各類資料在公布延遲後才可被策略使用，避免前視偏差。
# ---------------------------------------------------------------------------
DATA_PUBLICATION_DELAY = {
    "daily_price":             0,   # 當日收盤後即可用
    "chip_institutional":      1,   # 隔日公布
    "chip_margin":             1,   # 隔日公布
    "chip_holding_pct":        1,   # 隔日公布
    "chip_securities_lending": 1,   # 隔日公布
    "chip_short_sale":         1,   # 隔日公布
    "stock_per":               1,   # 隔日公布（需 EPS + 收盤價計算）
    "month_revenue":          10,   # 每月 10 日公布上月
    "financial_reports":      45,   # 季末後 45 天內公布
    "dividend_history":        0,   # 除息日前已公告
    "market_value":            1,   # 隔日公布
}


def apply_publication_delay(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """
    對資料 DataFrame 套用公布延遲偏移。

    將 date 欄位往後推移指定天數，使 merge_asof(direction="backward")
    在延遲期間內無法對齊到該筆資料，模擬真實的資料可得性。

    Parameters
    ----------
    df : DataFrame
        必須含 date 欄位
    table_name : str
        資料表名稱，用來查詢延遲天數

    Returns
    -------
    DataFrame : date 已偏移的副本（delay=0 時回傳原 df，不複製）
    """
    delay = DATA_PUBLICATION_DELAY.get(table_name, 0)
    if delay == 0 or df.empty:
        return df
    result = df.copy()
    result["date"] = result["date"] + pd.Timedelta(days=delay)
    return result
```

注意：`core/constants.py` 頂部需確認有 `import pandas as pd`，如果沒有需要加上。檢查方式：

```bash
head -5 core/constants.py
```

如果沒有 pandas import，在檔案開頭加上 `import pandas as pd`（放在 docstring 之後）。

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_data_publication_delay.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add core/constants.py tests/test_data_publication_delay.py
git commit -m "feat: 新增 DATA_PUBLICATION_DELAY — 資料公布延遲常數與偏移工具"
```

---

### Task 2: 修正 zscore_normalize — 全期改 rolling（TDD）

**Files:**
- Modify: `analysis/utils/factor_engine.py:11-20`
- Modify: `tests/test_factor_engine.py`

**Step 1: 在 tests/test_factor_engine.py 新增 rolling 行為測試**

在 `TestZScoreNormalize` class 末尾加入：

```python
    def test_no_look_ahead_bias(self):
        """前半段的 z-score 不應受後半段資料影響"""
        base = pd.Series(np.random.randn(300) * 10 + 50)
        z_full = zscore_normalize(base)

        # 只給前 150 筆，前 150 筆的 z-score 應該相同
        z_partial = zscore_normalize(base.iloc[:150])
        # rolling 模式下，前 150 筆的結果不受後 150 筆影響
        overlap = min(len(z_full), 150)
        non_nan_mask = z_partial.notna() & z_full.iloc[:overlap].notna()
        if non_nan_mask.sum() > 60:
            pd.testing.assert_series_equal(
                z_partial[non_nan_mask].reset_index(drop=True),
                z_full.iloc[:overlap][non_nan_mask].reset_index(drop=True),
                atol=1e-10,
            )

    def test_early_period_has_nan(self):
        """rolling 模式下前 min_periods 筆應為 NaN"""
        s = pd.Series(np.random.randn(100) * 10 + 50)
        z = zscore_normalize(s)
        # 預設 window=252, min_periods=60，前 59 筆應為 NaN
        assert z.iloc[:59].isna().all()

    def test_backward_compatible_clip(self):
        """仍然 winsorize 到 [-3, 3]"""
        s = pd.Series([1] * 100 + [1000])
        z = zscore_normalize(s)
        valid = z.dropna()
        assert valid.max() <= 3.0
        assert valid.min() >= -3.0
```

**Step 2: 跑測試確認部分失敗**

```bash
uv run pytest tests/test_factor_engine.py::TestZScoreNormalize -v
```

預期：`test_no_look_ahead_bias` 和 `test_early_period_has_nan` 失敗

**Step 3: 修改 factor_engine.py 的 zscore_normalize**

將 `analysis/utils/factor_engine.py:11-20` 替換為：

```python
def zscore_normalize(series: pd.Series, window: int = 252,
                     min_periods: int = 60) -> pd.Series:
    """Z-Score 標準化（單股時序，rolling 模式避免前視偏差）。

    使用 rolling 窗口計算均值和標準差，確保每個時間點只使用
    過去的資料進行標準化。Winsorize 到 [-3, 3]。

    Parameters
    ----------
    series : pd.Series
        原始因子值
    window : int
        rolling 窗口大小（預設 252 = 一年交易日）
    min_periods : int
        最少需要的觀測值（預設 60 = 約三個月）
    """
    if series.dropna().empty or len(series.dropna()) <= 1:
        return pd.Series(0.0, index=series.index)

    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()

    # 避免除以零
    safe_std = rolling_std.replace(0, np.nan)
    z = (series - rolling_mean) / safe_std

    return z.clip(-3, 3)
```

**Step 4: 修正受影響的舊測試**

`test_mean_near_zero` 和 `test_std_near_one` 預期全期均值≈0、標準差≈1，但 rolling 模式下不再成立。修改為：

```python
    def test_mean_near_zero(self):
        """rolling z-score 的有效值均值應接近零"""
        s = pd.Series(np.random.randn(300) * 10 + 50)
        z = zscore_normalize(s)
        valid = z.dropna()
        # rolling 模式下均值不一定精確為 0，但應在合理範圍
        assert abs(valid.mean()) < 1.0

    def test_std_near_one(self):
        """rolling z-score 的有效值標準差應接近一"""
        s = pd.Series(np.random.randn(300) * 10 + 50)
        z = zscore_normalize(s)
        valid = z.dropna()
        assert 0.3 < valid.std() < 2.0
```

**Step 5: 跑測試確認通過**

```bash
uv run pytest tests/test_factor_engine.py::TestZScoreNormalize -v
```

預期：全部 PASSED

**Step 6: Commit**

```bash
git add analysis/utils/factor_engine.py tests/test_factor_engine.py
git commit -m "fix: zscore_normalize 改為 rolling 模式，消除前視偏差"
```

---

### Task 3: 修正 multi_factor.py 的 expanding().max()

**Files:**
- Modify: `analysis/strategies/multi_factor.py:62-64`
- Test: `tests/test_strategies.py` 或 `tests/test_all_strategies.py`（現有測試）

**Step 1: 修改 multi_factor.py**

將第 62-64 行：

```python
        # 正規化到 [-1, 1]（使用 expanding max 避免 look-ahead bias）
        tech_max = tech_score.abs().expanding(min_periods=1).max()
        tech_score = tech_score / tech_max.replace(0, 1)
```

替換為：

```python
        # 正規化到 [-1, 1]（rolling max，只看過去一年資料）
        tech_max = tech_score.abs().rolling(window=252, min_periods=20).max()
        tech_score = tech_score / tech_max.replace(0, 1)
```

**Step 2: 跑現有策略測試確認不破壞**

```bash
uv run pytest tests/test_all_strategies.py -k "multi_factor or MultiFactor" -v
uv run pytest tests/test_strategies.py -k "multi_factor or MultiFactor" -v
```

預期：全部 PASSED（rolling 改動不影響 generate_signals 的介面和基本行為）

**Step 3: Commit**

```bash
git add analysis/strategies/multi_factor.py
git commit -m "fix: multi_factor expanding().max() 改為 rolling(252).max()，消除前視偏差"
```

---

### Task 4: 修正 strategy_report.py 的 enrich_data — 加入延遲偏移

**Files:**
- Modify: `scripts/strategy_report.py:195-287`

**Step 1: 在 strategy_report.py 頂部加入 import**

在現有 import 區塊（約第 36 行附近 `from core.constants import ...`）加入：

```python
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR, apply_publication_delay
```

**Step 2: 修改 enrich_data() 函式**

在每個 `merge_asof` 或 `merge` 呼叫之前，對 extra 資料套用延遲。具體修改模式：

對於使用 `merge_asof` 的資料表（chip_holding_pct, financial_reports, market_value, stock_per, month_revenue），在 merge 之前加入一行：

```python
                agg = apply_publication_delay(agg, "chip_holding_pct")  # 延遲偏移
                df = pd.merge_asof(df, agg, on="date", direction="backward")
```

```python
                pivoted = apply_publication_delay(pivoted, "financial_reports")  # 延遲偏移
                df = pd.merge_asof(df, pivoted, on="date", direction="backward")
```

```python
                extra = apply_publication_delay(extra, "market_value")  # 延遲偏移
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

```python
                extra = apply_publication_delay(extra, "stock_per")  # 延遲偏移
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

```python
                extra = apply_publication_delay(extra, "month_revenue")  # 延遲偏移
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

對於使用 `merge(..., how="left")` 的資料表（chip_institutional, chip_margin），exact-match 合併本身就要求日期完全對齊。延遲 1 天意味著需要改為 merge_asof + 延遲，但這改動較大。**保守做法**：對 chip_institutional 和 chip_margin 也改用 `apply_publication_delay` + `merge_asof`：

```python
        if table == "chip_institutional":
            extra = load_chip_institutional(engine, stock_id, start_date)
            if not extra.empty:
                buy_cols = [c for c in extra.columns if c.endswith("_buy")]
                sell_cols = [c for c in extra.columns if c.endswith("_sell")]
                if buy_cols and sell_cols:
                    extra["institutional_net_buy"] = (
                        extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                    )
                keep_set = {"date", "institutional_net_buy"}
                for c in extra.columns:
                    if (c.endswith("_buy") or c.endswith("_sell")) and c != "institutional_net_buy":
                        keep_set.add(c)
                extra = extra[[c for c in extra.columns if c in keep_set]]
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "chip_institutional")
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

chip_margin 同理。

**注意**：`dividend_history` 延遲為 0，不需要改。

**Step 3: 跑現有策略報告測試**

```bash
uv run pytest tests/test_strategy_report.py -v
```

預期：全部 PASSED

**Step 4: Commit**

```bash
git add scripts/strategy_report.py
git commit -m "fix: strategy_report enrich_data 加入資料公布延遲偏移"
```

---

### Task 5: 修正 daily_stock_picker.py 的兩個 enrich 函式

**Files:**
- Modify: `scripts/daily_stock_picker.py`

**Step 1: 加入 import**

在 `scripts/daily_stock_picker.py` 頂部的 import 區塊加入：

```python
from core.constants import apply_publication_delay
```

**Step 2: 修改 `_enrich_from_cache()`（第 253 行起）**

與 Task 4 相同模式，對每個 `merge` / `merge_asof` 前加入 `apply_publication_delay`。

chip_institutional（約第 293-294 行）：
```python
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "chip_institutional")
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

stock_per（約第 298 行）：
```python
            extra = apply_publication_delay(extra, "stock_per")
            df = pd.merge_asof(df, extra, on="date", direction="backward")
```

month_revenue（約第 302 行）：
```python
            extra = apply_publication_delay(extra, "month_revenue")
            df = pd.merge_asof(df, extra, on="date", direction="backward")
```

**Step 3: 修改 `enrich_data()`（第 489 行起）**

同樣模式。chip_institutional、stock_per、month_revenue 各加一行 `apply_publication_delay`。

**Step 4: 跑選股報告測試**

```bash
uv run pytest tests/test_daily_stock_picker.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add scripts/daily_stock_picker.py
git commit -m "fix: daily_stock_picker enrich 函式加入資料公布延遲偏移"
```

---

### Task 6: 修正 3_策略回測.py 的 _enrich_data

**Files:**
- Modify: `analysis/pages/3_策略回測.py:56-142`

**Step 1: 加入 import**

在 `analysis/pages/3_策略回測.py` 頂部加入：

```python
from core.constants import apply_publication_delay
```

**Step 2: 修改 `_enrich_data()`**

與 Task 4 相同模式。以下資料表的 `merge_asof` 前加入 `apply_publication_delay`：

- `chip_holding_pct`（第 101 行）
- `financial_reports`（第 111 行）
- `market_value`（第 118 行）
- `stock_per`（第 125 行）
- `month_revenue`（第 131 行）

chip_institutional（第 81 行）和 chip_margin（第 87 行）目前用 `merge(..., how="left")`，改為：

```python
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "chip_institutional")
                df = pd.merge_asof(df, extra, on="date", direction="backward")
```

chip_margin 同理。

**Step 3: 手動驗證 Streamlit 頁面（可選）**

```bash
uv run python main.py --analysis
# 開啟 3_策略回測 頁面，選任意技術面策略，確認正常運作
```

**Step 4: Commit**

```bash
git add analysis/pages/3_策略回測.py
git commit -m "fix: 策略回測頁面 _enrich_data 加入資料公布延遲偏移"
```

---

### Task 7: 跑全量測試 + 修復

**Step 1: 跑全量測試**

```bash
uv run pytest tests/ -v --timeout=120
```

**Step 2: 修復任何失敗的測試**

常見預期失敗：
- 使用 `zscore_normalize` 的測試可能因 rolling 模式（前 59 筆為 NaN）而失敗，需調整測試資料長度到 300+
- chip_institutional 改為 merge_asof 後，`test_daily_stock_picker.py` 中的 mock 可能需要調整

逐一修復，確保全部 PASSED。

**Step 3: Commit**

```bash
git add -u
git commit -m "fix: 修復前視偏差修正後的測試適配"
```

---

### Task 8: 更新文件

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/選股策略藍圖.md`
- Modify: `analysis/documents/測試說明.md`

**Step 1: CLAUDE.md**

在 Key Patterns 區塊加入：

```markdown
- **資料公布延遲模型**：所有 `enrich_data()` 在合併非價格資料前，會根據 `DATA_PUBLICATION_DELAY`（`core/constants.py`）對資料日期做延遲偏移，避免回測中使用尚未公布的資料。月營收延遲 10 天、季報延遲 45 天、籌碼/估值延遲 1 天。
```

**Step 2: CHANGELOG.md**

```markdown
### Fixed
- 修正 7 個策略的前視偏差：資料公布延遲模型（月營收 +10 天、季報 +45 天、籌碼 +1 天）
- 修正 `zscore_normalize()` 從全期統計量改為 rolling(252) 模式
- 修正 `multi_factor.py` 的 `expanding().max()` 改為 `rolling(252).max()`
```

**Step 3: 選股策略藍圖**

將 3.7a 的「前視偏差修正」從 `[ ]` 改為 `[x]`。

**Step 4: 測試說明**

加入 `test_data_publication_delay.py` 到測試清單。

**Step 5: Commit**

```bash
git add CLAUDE.md CHANGELOG.md docs/選股策略藍圖.md analysis/documents/測試說明.md
git commit -m "docs: 更新文件 — 前視偏差修正的說明與記錄"
```
