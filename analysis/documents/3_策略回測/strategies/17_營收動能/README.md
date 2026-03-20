# 營收動能（RevenueMomentumStrategy）

> 類型：基本面 ｜ 檔案：`analysis/strategies/revenue_momentum.py`

## 核心邏輯

追蹤月營收年增率（YoY）的加速趨勢，營收 YoY 持續加速且創歷史新高時買入。支援 PE 估值過濾與最大持有天數控制。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `yoy_threshold` | 15.0 | float | 營收 YoY 門檻（%） |
| `acceleration_months` | 2 | int | YoY 加速回溯月數 |
| `pe_upper_limit` | 60.0 | float | PE 上限（過濾過度高估） |
| `enable_pe_filter` | True | bool | 是否啟用 PE 過濾 |
| `max_holding_days` | 180 | int | 最大持有天數 |
| `yoy_exit_threshold` | 5.0 | float | YoY 低於此值觸發賣出（%） |

### 參數詳解

- **`yoy_threshold`**（營收 YoY 門檻）
  - 月營收年增率需超過此值
  - 15.0 → 原 20%→15%，涵蓋更多成長股
  - 建議範圍：5.0 ~ 30.0

- **`acceleration_months`**（YoY 加速回溯月數）
  - 檢查連續 N 個月 YoY 是否呈加速趨勢
  - 2 → 原 3→2，降低嚴格度
  - 建議範圍：2 ~ 6

- **`pe_upper_limit`**（PE 上限）
  - PE 超過此值的股票不買入
  - 60.0 → 不排除高成長龍頭（原 40→60）
  - 建議範圍：30.0 ~ 100.0

- **`max_holding_days`**（最大持有天數）
  - 持有超過 N 天自動賣出
  - 180 → 約 6 個月（原 120→180）
  - 建議範圍：60 ~ 252

- **`yoy_exit_threshold`**（YoY 退出門檻）
  - YoY 低於此值觸發賣出
  - 5.0% → 原 10→5%，避免正常波動就出場
  - 建議範圍：0.0 ~ 15.0

### 營收新高/新低判定（排除自身，避免自含偏差）

```
rev_6m_max = max(revenue[t-127 : t-1])  # 前 126 日最大值（不含當期）
rev_6m_min = min(revenue[t-127 : t-1])  # 前 126 日最小值（不含當期）
買入條件之一：revenue[t] > rev_6m_max（真正創新高）
賣出條件之一：revenue[t] < rev_6m_min（跌破前低）
```

## 買賣條件

- **買入**：月營收 YoY > yoy_threshold + YoY 連續 N 月加速 + 營收創 6 月新高（+ 可選 PE < pe_upper_limit）
- **賣出**：YoY < yoy_exit_threshold 或 營收跌破 6 月新低 或 持有超過 max_holding_days

## 學理基礎

Jegadeesh & Titman (1993) 的動量效應延伸至基本面：營收 YoY 加速成長的公司往往具有持續的超額報酬。Chan, Jegadeesh & Lakonishok (1996) *Momentum Strategies* 進一步驗證收益動量（Earnings Momentum）的有效性。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Chan, L.K.C., Jegadeesh, N. & Lakonishok, J. (1996). *Momentum Strategies*. Journal of Finance, 51(5). | 收益動量效應 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 8 | **HIGH** | `rev_6m_max/min` 包含自身 → 營收新高幾乎永遠成立 + 賣出永不觸發 → 加 `shift(1)` | ✓ 已修復 |
