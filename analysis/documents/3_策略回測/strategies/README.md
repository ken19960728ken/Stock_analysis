# 策略文件索引

本目錄包含 26 個內建策略的獨立文件，每個策略的 README.md 整合了：
- 核心邏輯與買賣條件
- 完整參數說明（預設值、建議範圍）
- 學理基礎與參考文獻
- Code Review 修復記錄（如適用）
- 相關 PDF 論文（如適用）

---

## 技術面策略（10 個）

| # | 策略 | Class | 資料夾 |
|---|------|-------|--------|
| 1 | MA 交叉 | `MACrossStrategy` | [01_MA交叉](01_MA交叉/) |
| 2 | MACD 訊號 | `MACDStrategy` | [02_MACD訊號](02_MACD訊號/) |
| 3 | Bollinger 突破 | `BollingerStrategy` | [03_Bollinger突破](03_Bollinger突破/) |
| 4 | RSI 反轉 | `RSIReversalStrategy` | [04_RSI反轉](04_RSI反轉/) |
| 5 | Parabolic SAR | `ParabolicSARStrategy` | [05_Parabolic_SAR](05_Parabolic_SAR/) |
| 6 | Heikin-Ashi | `HeikinAshiStrategy` | [06_Heikin_Ashi](06_Heikin_Ashi/) |
| 7 | Dual Thrust | `DualThrustStrategy` | [07_Dual_Thrust](07_Dual_Thrust/) |
| 8 | 趨勢過濾MA | `TrendFilteredMAStrategy` | [08_趨勢過濾MA](08_趨勢過濾MA/) |
| 9 | 量價動能 | `VolumePriceMomentumStrategy` | [09_量價動能](09_量價動能/) |
| 10 | 波動率壓縮突破 | `VolatilitySqueezeStrategy` | [10_波動率壓縮突破](10_波動率壓縮突破/) |

## 籌碼面策略（7 個）

| # | 策略 | Class | 資料夾 |
|---|------|-------|--------|
| 11 | 法人跟單 | `InstitutionalStrategy` | [11_法人跟單](11_法人跟單/) |
| 12 | 融資融券訊號 | `MarginSignalStrategy` | [12_融資融券訊號](12_融資融券訊號/) |
| 13 | 股權集中度 | `OwnershipConcentrationStrategy` | [13_股權集中度](13_股權集中度/) |
| 23 | 當沖情緒反轉 | `DayTradeSentimentStrategy` | [23_當沖情緒反轉](23_當沖情緒反轉/) |
| 24 | 外資連續買超 | `ForeignBrokerTrackingStrategy` | 24_外資連續買超/ |
| 25 | 散戶vs主力 | `RetailVsInstitutionalStrategy` | 25_散戶vs主力/ |
| 26 | 官股護盤 | `GovBankShieldStrategy` | [26_官股護盤](26_官股護盤/) |

## 基本面策略（4 個）

| # | 策略 | Class | 資料夾 |
|---|------|-------|--------|
| 14 | 價值投資 | `ValueInvestingStrategy` | [14_價值投資](14_價值投資/) |
| 15 | 財報三率 | `FundamentalRatioStrategy` | [15_財報三率](15_財報三率/) |
| 16 | 自由現金流 | `FreeCashFlowStrategy` | [16_自由現金流](16_自由現金流/) |
| 17 | 營收動能 | `RevenueMomentumStrategy` | [17_營收動能](17_營收動能/) |

## 複合/產業策略（5 個）

| # | 策略 | Class | 資料夾 |
|---|------|-------|--------|
| 18 | 多因子綜合 | `MultiFactorStrategy` | [18_多因子綜合](18_多因子綜合/) |
| 19 | 事件驅動 | `EventDrivenStrategy` | [19_事件驅動](19_事件驅動/) |
| 20 | 多策略動態組合 | `AdaptiveEnsembleStrategy` | [20_多策略動態組合](20_多策略動態組合/) |
| 21 | 機器學習選股 | `MLFactorStrategy` | [21_機器學習選股](21_機器學習選股/) |
| 22 | 次產業輪動 | `SubIndustryRotationStrategy` | [22_次產業輪動](22_次產業輪動/) |

---

## 含 PDF 論文的策略

| 策略 | PDF |
|------|-----|
| 20. 多策略動態組合 | `breiman-1996-bagging.pdf` — Breiman (1996) Bagging Predictors |
| 21. 機器學習選股 | `gu-kelly-xiu-2020-ml-asset-pricing.pdf` — Gu, Kelly & Xiu (2020) ML Asset Pricing |
