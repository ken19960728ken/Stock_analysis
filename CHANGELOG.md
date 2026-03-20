# Changelog

本專案遵循 [Keep a Changelog](https://keepachangelog.com/) 格式與 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added
- **選股推薦追蹤機制**：每份報告記錄 git commit SHA + 策略檔案 hash + 參數快照（`recommendation_history` 表）
- **績效自動回填**：追蹤推薦股票 T+5/T+10/T+20（交易日）的實際表現（`scripts/performance_tracker.py`）
- **績效追蹤報告**：整體勝率、按策略拆分、版本變更記錄（`reports/performance_tracking.md`）
- **每日選股報告版本資訊**：報告末尾新增 Git Commit、App Version、策略權重、選股參數
- **Git 分支模型**：建立 `develop → main` 開發/正式環境分離，日常開發在 `develop`，部署只從 `main`
- **部署腳本 branch guard**：`release.sh` 和 `pre-deploy-check.sh` 強制檢查必須在 main 分支
- **策略文件重構**：22 個策略各建獨立子資料夾，整合參數詳解 + 學理來源 + PDF 論文，取代原 1014 行單一大檔

### Changed
- **Workflow Conventions 重構**：移除「改動即部署」規則，部署時機由使用者決定
- **發布流程更新**：加入 `develop → main` merge 步驟

### Fixed
- **回測前視偏差修正**：新增 `DATA_PUBLICATION_DELAY` 資料公布延遲模型（月營收 +10 天、季報 +45 天、籌碼/估值 +1 天），修正 3 個 `enrich_data()` 函式，消除 7 個策略的資料偷看問題
- **zscore_normalize 前視偏差**：從全期統計量改為 `rolling(252)` 模式，確保每個時間點只使用過去資料
- **multi_factor expanding().max()**：改為 `rolling(252).max()`，消除全期最大值汙染
- **策略參數詳解文件同步**：修正 9 個策略（MACD、Dual Thrust、法人跟單、融資融券、自由現金流、營收動能、多因子綜合、多策略動態組合、波動率壓縮突破）的文件與程式碼不一致問題，共 30 處修正（參數預設值、遺漏參數、核心邏輯描述）
- **策略學理來源**：更新 MACD 策略的核心邏輯描述（連續確認 + 趨勢過濾 + 背離偵測）

## [1.0.0] - 2026-03-20

首個正式版本，標誌系統功能成熟、部署自動化完成。

### Added
- **版本管控體系**：SemVer 版本號、版本化 Docker 映像標籤、pre-deploy-check、release 腳本
- **CHANGELOG.md**：版本變更追蹤

### 功能回顧（v0.1.0 至 v1.0.0 累計）

#### 資料撈取
- 日/週/月 K 線（Yahoo Finance）
- 三大法人、融資融券、股權分散、持股比例、借券、借券賣出（FinMind）
- 財務報表 + 股利（FinMind + Yahoo）
- 月營收、PER/PBR、市值（FinMind）
- 兩層產業分類（sector + sub_industry）
- 每日批量更新（DailyUpdater）
- BaseScanner 框架（tqdm 進度條、Ctrl+C 安全中斷、斷點續傳）
- RateLimiter 統一限速 + 預算控制
- safe_read_sql() 防殭屍連線

#### 量化分析平台（12 頁面）
- 個股分析、因子篩選、策略回測、配對交易、風險管理
- 市場總覽、策略組合、因子分析、產業輪動
- 事件分析、機器學習選股、報告瀏覽

#### 量化策略（22 個）
- 技術面：MA 交叉、MACD、Bollinger、RSI 反轉、Parabolic SAR、Heikin-Ashi、Dual Thrust、趨勢過濾MA、量價動能、波動率壓縮突破
- 籌碼面：法人跟單、融資融券訊號、股權集中度
- 基本面：價值投資、財報三率、自由現金流、營收動能
- 綜合：多因子綜合、事件驅動、機器學習選股、多策略動態組合、次產業輪動

#### 產業分析
- 產業輪動模型（營收動能 + 法人流向 + 估值面）
- 同業比較分析
- 供應鏈連動分析
- Granger 因果供應鏈自動發現

#### 部署與運維
- Cloud Run 雙 Job 架構（stock-data + stock-report）
- Cloud Run Analysis Service（Streamlit）
- Cloud Scheduler 每日自動排程
- GCP Secret Manager 敏感變數管理
- 每日選股報告 + Email 自動推送

#### 測試
- 808 測試案例全通過（清理重複測試後）
- 覆蓋所有 scanner、策略、引擎、核心模組

## [0.1.0] - 2025-01-01

### Added
- 專案初始化
- 基礎資料撈取架構
- Supabase PostgreSQL 整合
