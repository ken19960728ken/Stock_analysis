# 回測前視偏差修正 — 設計文件

> 日期：2026-03-20
> 狀態：已確認，待實作
> 範圍：方案 B（引擎 + 策略修正），Universe-Level 重構列入 Phase 3.7a 待辦

---

## 1. 動機

對 22 個策略的前視偏差審計發現三層「偷看答案」：

### 審計結果摘要

| 偏差層 | 問題 | 影響範圍 | 偷看天數 |
|--------|------|---------|---------|
| **資料層** | `merge_asof(backward)` 未考慮資料公布延遲 | 7 個策略 | 1-60 天 |
| **統計量層** | `zscore_normalize()` 用全期均值/標準差 | multi_factor | 全期 |
| **統計量層** | `expanding().max()` 用全期最大值 | multi_factor | 全期 |

### 策略風險等級

| 風險等級 | 策略 |
|---------|------|
| ✅ 安全 | MA 交叉、MACD、Bollinger、RSI、SAR、Heikin-Ashi、Dual Thrust、趨勢過濾MA、量價動能、波動率壓縮突破 |
| ⚠️ 低風險 | 法人跟單、融資融券、股權集中度、機器學習選股（延遲 ≤ 1 天） |
| 🔴 中風險 | 價值投資、財報三率、自由現金流、事件驅動、多策略動態組合、次產業輪動 |
| 🔴 高風險 | 營收動能（ffill + 8-10 天延遲）、多因子綜合（全期統計量） |

## 2. 設計決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| 延遲處理位置 | 資料載入層（`enrich_data`） | 策略層不需知道延遲，修改集中 |
| 延遲單位 | 日曆日 | 公布延遲是日曆日概念（如每月 10 日） |
| zscore 修正 | `rolling(252)` | 一年窗口足夠穩定，不汙染全期 |
| 修正原則 | 不改策略的 generate_signals 介面 | 最小破壞性 |

## 3. 資料延遲模型

### 公布延遲常數

```python
# core/constants.py 新增
DATA_PUBLICATION_DELAY = {
    "daily_price":          0,   # 當日收盤後即可用
    "chip_institutional":   1,   # 隔日公布
    "chip_margin":          1,   # 隔日公布
    "chip_holding_pct":     1,   # 隔日公布
    "chip_securities_lending": 1,
    "chip_short_sale":      1,
    "stock_per":            1,   # 隔日公布（需 EPS + 收盤價計算）
    "month_revenue":       10,   # 每月 10 日公布上月
    "financial_reports":   45,   # 季末後 45 天內公布
    "dividend_history":     0,   # 除息日前已公告
    "market_value":         1,   # 隔日公布
}
```

### 延遲偏移機制

在 `enrich_data()` 的 `merge_asof` 之前，對 extra 資料加入延遲：

```python
delay = DATA_PUBLICATION_DELAY.get(table, 0)
if delay > 0:
    extra = extra.copy()
    extra["date"] = extra["date"] + pd.Timedelta(days=delay)
df = pd.merge_asof(df, extra, on="date", direction="backward")
```

效果：2025-02-28 的月營收（date=2025-02-28）被偏移到 2025-03-10，
在 3 月 10 日之前的交易日看不到這筆資料。

## 4. 統計量偏差修正

### zscore_normalize — rolling 化

```python
# factor_engine.py
def zscore_normalize(series, window=252):
    rolling_mean = series.rolling(window=window, min_periods=60).mean()
    rolling_std = series.rolling(window=window, min_periods=60).std()
    z = (series - rolling_mean) / rolling_std.replace(0, np.nan)
    return z.clip(-3, 3)
```

### expanding().max() — rolling 化

```python
# multi_factor.py
# 現有：tech_max = tech_score.abs().expanding(min_periods=1).max()
# 修正：
tech_max = tech_score.abs().rolling(window=252, min_periods=20).max()
```

## 5. 修正檔案清單

| 檔案 | 變更 | 說明 |
|------|------|------|
| `core/constants.py` | 新增 | `DATA_PUBLICATION_DELAY` 常數 |
| `scripts/strategy_report.py` | 修改 `enrich_data()` | 加入延遲偏移 |
| `scripts/daily_stock_picker.py` | 修改 `enrich_data()` + `_enrich_from_cache()` | 加入延遲偏移 |
| `analysis/pages/3_策略回測.py` | 修改 `_enrich_data()` | 加入延遲偏移 |
| `analysis/utils/factor_engine.py` | 修改 `zscore_normalize()` | 改為 rolling |
| `analysis/strategies/multi_factor.py` | 修改 `expanding().max()` | 改為 rolling |

## 6. 不做的事

- 不改策略的 `generate_signals()` 介面
- 不做 Universe-Level 回測（列入 3.7a 待辦）
- 不做存活偏差修正（列入 3.7a 待辦）
- 不改純技術面策略（已安全）
- 延遲常數先用固定值，未來可改為更精確的日曆計算

## 7. 測試策略

- 修正後重跑受影響的 7 個策略測試，確認不 break
- 新增 `test_data_publication_delay.py`：驗證延遲偏移邏輯
- 新增 `test_zscore_rolling.py`（或併入現有 `test_factor_engine.py`）：驗證 rolling zscore 不使用未來資料
