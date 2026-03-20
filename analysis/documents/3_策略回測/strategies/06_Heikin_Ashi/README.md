# Heikin-Ashi（HeikinAshiStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/heikin_ashi.py`

## 核心邏輯

HA K 線由陰轉陽（含連續確認）時買入，由陽轉陰時賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `confirm_bars` | 2 | int | 連續確認 K 棒數 |

### 參數詳解

- **`confirm_bars`**（連續確認 K 棒數）
  - 轉換方向後需連續 N 根同方向 HA K 棒才確認訊號
  - 2 表示至少連續 2 根陽線才買入（避免假突破）
  - 1 → 最靈敏，可能有較多假訊號
  - 3 → 更保守，會錯過行情初段但訊號更可靠
  - 建議範圍：1 ~ 4

### Heikin-Ashi 的特點

- HA K 線平滑了原始價格波動，趨勢更容易辨識
- 連續陽線（HA_Close > HA_Open）→ 上漲趨勢
- 連續陰線（HA_Close < HA_Open）→ 下跌趨勢
- 不適合用來判斷精確的進出場價格（HA 價格非實際成交價）

## 買賣條件

- **買入**：HA 陽線（無下影線）+ 收盤 > EMA → 買入
- **賣出**：HA 陰線（無上影線）→ 賣出

## 學理基礎

平均足（Heikin-Ashi）源自日本蠟燭圖技術，透過修正開高低收使趨勢更平滑。Valcu (2004) *Using The Heikin-Ashi Technique*（Technical Analysis of Stocks & Commodities 期刊）是現代量化應用的代表文獻。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Valcu, D. (2004). *Using The Heikin-Ashi Technique*. Technical Analysis of S&C. | Heikin-Ashi 量化應用 | — (期刊文章) |
