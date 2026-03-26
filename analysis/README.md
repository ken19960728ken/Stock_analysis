# 台灣股市量化分析平台

## 概述

本平台是一套完整的台灣股市量化交易分析系統，基於 Streamlit 建構，提供從個股研究到機器學習選股的全方位分析工具。資料來源為 Supabase PostgreSQL 資料庫，涵蓋日/週/月 K 線、籌碼面、基本面、估值面等多維度數據。

## 啟動方式

```bash
# 本地啟動
uv run python main.py --analysis
# 預設啟動於 http://localhost:8501

# Cloud Run 部署（持續運行）
# 詳見 deploy/部署流程.md
```

## 功能頁面總覽（12 個）

| 頁面 | 功能 | 說明 |
|------|------|------|
| **1. 個股分析** | 技術 + 籌碼 + 基本面 | K 線圖表、技術指標、三大法人、EPS/營收/股利、同業比較 |
| **2. 因子篩選** | 多維度條件選股 | 估值/技術/成長/籌碼四大維度篩選，支援 CSV 匯出 |
| **3. 策略回測** | 26 個內建策略 | 完整回測引擎（含手續費/稅/滑價）、0050 基準比較 |
| **4. 配對交易** | 統計套利 | Engle-Granger 共整合檢定、Z-Score 進出場訊號 |
| **5. 風險管理** | 持倉風險分析 | VaR/CVaR、Sharpe/Sortino、回撤分析、相關性矩陣 |
| **6. 市場總覽** | 全市場概覽 | 漲跌分佈、法人排行、產業熱力圖、估值分佈、FRED 經濟指標 |
| **7. 策略組合** | 多策略組合回測 | 等權/Sharpe 最大化/最小波動率/風險平價 四種權重 |
| **8. 因子分析** | 因子有效性驗證 | IC 回測、因子相關性、有效性排行、動態權重追蹤 |
| **9. 產業輪動** | 產業強弱排序 | 營收動能 + 法人流向 → 綜合排名 + 輪動熱力圖 + 供應鏈分析 |
| **10. 事件分析** | 事件驅動研究 | 除息/財報事件的 CAR/AAR 分析 + 事件策略回測 |
| **11. 機器學習** | LightGBM 選股 | 多因子非線性組合、特徵重要性、Walk-Forward 回測 |
| **12. 報告瀏覽** | 歷史報告查閱 | Markdown 渲染 + CSV 表格 + 檔案下載 |

## 內建策略清單（26 個）

### 技術面策略（10 個）

| 策略 | Class | 核心邏輯 |
|------|-------|---------|
| MA 交叉 | `MACrossStrategy` | 短期均線上穿/下穿長期均線 |
| MACD 訊號 | `MACDStrategy` | MACD 柱狀圖由負轉正/正轉負 |
| Bollinger 突破 | `BollingerStrategy` | 價格觸及下軌買入/上軌賣出 |
| RSI 反轉 | `RSIReversalStrategy` | RSI 超賣區買入/超買區賣出 |
| Parabolic SAR | `ParabolicSARStrategy` | SAR 翻多買入/翻空賣出 |
| Heikin-Ashi | `HeikinAshiStrategy` | HA K 線由陰轉陽/陽轉陰（含連續確認） |
| Dual Thrust | `DualThrustStrategy` | 前 N 日高低點計算上下軌突破 |
| 趨勢過濾MA | `TrendFilteredMAStrategy` | MA 交叉 + MA200 趨勢過濾 + 回檔反彈 |
| 量價動能 | `VolumePriceMomentumStrategy` | 放量突破 + OBV 資金流向確認 |
| 波動率壓縮突破 | `VolatilitySqueezeStrategy` | BB+KC Squeeze 壓縮後突破 |

### 籌碼面策略（7 個）

| 策略 | Class | 核心邏輯 |
|------|-------|---------|
| 法人跟單 | `InstitutionalStrategy` | 法人連續 N 日買超/賣超 |
| 融資融券訊號 | `MarginSignalStrategy` | 融資減少 + 股價上漲 = 籌碼沉澱 |
| 股權集中度 | `OwnershipConcentrationStrategy` | 大股東增持 + 股東人數減少 |
| 當沖情緒反轉 | `DayTradeSentimentStrategy` | 當沖比例 Z-Score 逆向交易（散戶情緒反指標） |
| 外資連續買超 | `ForeignBrokerTrackingStrategy` | 外資券商連續買超追蹤 |
| 散戶vs主力 | `RetailVsInstitutionalStrategy` | 散戶當沖 vs 主力籌碼背離 |
| 官股護盤 | `GovBankShieldStrategy` | 官股買超力道異常放大 + 大盤下跌時買入 |

### 基本面策略（4 個）

| 策略 | Class | 核心邏輯 |
|------|-------|---------|
| 價值投資 | `ValueInvestingStrategy` | 低 P/E + 高殖利率 + 營收正成長 |
| 財報三率 | `FundamentalRatioStrategy` | 毛利率/營業利益率/淨利率 達標判斷 |
| 自由現金流 | `FreeCashFlowStrategy` | OCF > 0 + FCF Yield 達標 |
| 營收動能 | `RevenueMomentumStrategy` | 營收 YoY 加速 + 營收創歷史新高 |

### 複合/產業策略（5 個）

| 策略 | Class | 核心邏輯 |
|------|-------|---------|
| 多因子綜合 | `MultiFactorStrategy` | 技術(40%) + 籌碼(30%) + 基本面(30%) 加權評分 |
| 多策略動態組合 | `AdaptiveEnsembleStrategy` | 技術+籌碼+基本面 動態加權 |
| 事件驅動 | `EventDrivenStrategy` | 除息/財報事件前買入、事件後賣出 |
| 機器學習選股 | `MLFactorStrategy` | LightGBM 多因子非線性組合預測 |
| 次產業輪動 | `SubIndustryRotationStrategy` | 次產業營收動能 + 法人流向排名 |

## 核心模組

### 策略模組 `strategies/`

所有策略繼承自 `Strategy` 抽象基類（`strategies/base.py`），統一介面：

```python
class Strategy(ABC):
    name: str                              # 策略名稱
    description: str                       # 策略說明
    params: dict                           # 可調參數及預設值

    def set_params(self, **kwargs)         # 更新參數
    def generate_signals(self, df) -> DataFrame  # 產生訊號（signal 欄位：1=買, -1=賣, 0=持有）
```

### 工具模組 `utils/`

| 模組 | 功能 |
|------|------|
| `data_loader.py` | DB 資料查詢 + `@st.cache_data` 快取（40+ 個查詢函數） |
| `indicators.py` | 純 pandas/numpy 技術指標（MA/EMA/MACD/RSI/KD/BB/SAR/HA/AO/ATR/OBV/KC） |
| `charts.py` | Plotly 圖表工廠（K 線、籌碼、基本面、權益曲線、熱力圖等） |
| `backtester.py` | 單策略回測引擎（含台灣手續費 0.1425%、證交稅 0.3%、滑價） |
| `portfolio_backtester.py` | 多策略組合回測引擎（支援 4 種權重最佳化） |
| `portfolio_optimizer.py` | 組合最佳化（Max Sharpe/Min Vol/Risk Parity/Black-Litterman） |
| `risk.py` | 風險指標（VaR/CVaR/Sharpe/Sortino/Beta/Alpha/MaxDD） |
| `factor_engine.py` | 因子引擎（Z-Score/IC 計算/因子相關性） |
| `dynamic_weights.py` | 動態因子權重（Rolling IC/ICIR/指數衰減） |
| `pair_trading.py` | 配對交易（Engle-Granger/Z-Score/半衰期） |
| `sector_rotation.py` | 產業輪動（營收動能 + 法人流向，支援 sector/sub_industry 兩層） |
| `event_study.py` | 事件研究引擎（CAR/AAR/異常報酬） |
| `ml_stock_picker.py` | ML 選股引擎（LightGBM/特徵工程/Walk-Forward） |
| `peer_comparison.py` | 同業比較分析（同業查詢、指標比較、百分位排名） |
| `supply_chain.py` | 產業供應鏈連動分析（營收動能傳導、領先落後矩陣） |

## 資料需求

平台需要以下 DB 表格的資料（透過 scanners 撈取）：

| 資料類型 | DB 表格 | Scanner |
|----------|---------|---------|
| 日K線 | `daily_price` | `price_scanner` |
| 週K線 | `weekly_price` | `price_scanner_weekly` |
| 月K線 | `monthly_price` | `price_scanner_monthly` |
| 財報 | `financial_reports` | `fundamental_scanner` |
| 股利 | `dividend_history` | `fundamental_scanner` |
| 三大法人 | `chip_institutional` | `chip_scanner` |
| 融資融券 | `chip_margin` | `chip_scanner` |
| 股權分散 | `chip_shareholding` | `chip_scanner` |
| 持股比例 | `chip_holding_pct` | `chip_scanner` |
| 借券 | `chip_securities_lending` | `chip_scanner` |
| 借券賣出 | `chip_short_sale` | `chip_scanner` |
| 月營收 | `month_revenue` | `valuation_scanner` |
| PER/PBR | `stock_per` | `valuation_scanner` |
| 市值 | `market_value` | `valuation_scanner` |
| 產業分類 | `industry_classification` | `industry_scanner` |

## 環境變數

| 變數 | 必要性 | 說明 |
|------|--------|------|
| `SUPABASE_URL` | **必要** | PostgreSQL 連線字串 |
| `FINMIND_TOKEN` | 選用 | FinMind JWT（提高 API 限速） |
| `FRED_API_KEY` | 選用 | FRED 經濟指標 API Key（市場總覽頁使用） |

## 文件索引

各頁面的詳細功能說明請參閱 `documents/` 資料夾：

- [1. 個股分析](documents/1_個股分析/)（含同業比較分析）
- [2. 因子篩選](documents/2_因子篩選/)
- [3. 策略回測](documents/3_策略回測/)（含 [26 個策略獨立文件](documents/3_策略回測/strategies/)）
- [4. 配對交易](documents/4_配對交易/)
- [5. 風險管理](documents/5_風險管理/)
- [6. 市場總覽](documents/6_市場總覽/)（含產業熱力圖）
- [7. 策略組合](documents/7_策略組合/)
- [8. 因子分析](documents/8_因子分析/)
- [9. 產業輪動](documents/9_產業輪動/)（含供應鏈分析）
- [10. 事件分析](documents/10_事件分析/)
- [11. 機器學習](documents/11_機器學習/)
- [12. 報告瀏覽](documents/12_報告瀏覽/)
