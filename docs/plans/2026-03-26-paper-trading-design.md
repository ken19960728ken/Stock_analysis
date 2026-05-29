# Paper Trading 系統設計方向

> CEO Review (2026-03-26) 決定的下一階段核心工作
> 目標：3-6 個月內實盤，Paper Trading 是從回測到實盤的橋梁

## Accepted Scope

### 1. 策略淘汰賽（OOS 驗證篩選）
- 自動對 26 個策略跑 `oos_validation()`（已有工具）
- 產出策略排行榜：IS Sharpe / OOS Sharpe / 衰退率 / verdict
- 篩選規則：OOS Sharpe > 0.5 且 decay_rate < 0.5 的策略進入 Paper Trading
- 同時跑 `signal_decay_report()` 確認訊號有效期（T+5/10/20）
- 輸出：`reports/strategy_tournament.md`

### 2. Paper Trading 引擎
- 核心模組：`scripts/paper_trader.py`
- 每日收盤後自動：
  1. 對篩選出的策略掃描全市場訊號
  2. 用 `MultiStockBacktester` 的邏輯構建組合
  3. 模擬買賣（含動態滑價 + 流動性限制）
  4. 更新 Paper Portfolio（持倉 + 現金 + PnL）
- DB 表：`paper_portfolio`（持倉）、`paper_trades`（交易記錄）、`paper_daily_pnl`（每日損益）
- 整合到 `main.py --paper-trading`

### 3. 風控熔斷機制
- 單檔部位上限：總資金 20%
- 產業集中度上限：同產業 40%
- 最大同時持股：10 檔
- VaR(95%) 日限制：總資金 2%
- 回撤熔斷：-10% 暫停新建倉、-15% 全部減半、-20% 清倉
- 策略失效偵測：連續 5 次虧損交易 → 該策略暫停

### 4. 自動化 + 報告
- Cloud Run 排程：`--paper-trading`（18:50 UTC+8，在 daily-data 和 daily-report 之後）
- 每日 Email：今日交易 + 持倉 + PnL + 風控狀態
- 週報：策略貢獻拆解 + 與 0050 對照 + 風險指標
- 異常告警：回撤超閾值 / 策略失效 / 資料異常

## Deferred (TODOS)

- 策略歸因分析（每週拆解各策略報酬貢獻）
- 即時通訊推送（Telegram/LINE）
- 策略熱啟動（用回測結果預載歷史持倉）
- 對照組自動比較（vs 0050 Buy & Hold）

## Architecture Sketch

```
Cloud Run 排程（每日 18:50 UTC+8）
    │
    ▼
main.py --paper-trading
    │
    ├── Step 1: 策略篩選（首次或每月重新篩選）
    │   └── strategy_tournament.py → 篩選出 5-8 個策略
    │
    ├── Step 2: 訊號掃描
    │   └── 對全市場股票跑已篩選策略的 generate_signals()
    │
    ├── Step 3: 組合構建 + 風控檢查
    │   ├── MultiStockBacktester 邏輯的即時版
    │   ├── 風控約束檢查（部位/產業/VaR）
    │   └── 產生買賣訂單
    │
    ├── Step 4: 模擬執行
    │   ├── 記錄 paper_trades
    │   ├── 更新 paper_portfolio
    │   └── 計算 paper_daily_pnl
    │
    └── Step 5: 報告 + 告警
        ├── Email 日報
        └── 異常告警（回撤/策略失效）
```

## Dependencies

- 已完成：26 策略、signal_analysis 工具、MultiStockBacktester、動態滑價、流動性限制
- 需新增：paper_portfolio / paper_trades / paper_daily_pnl DB 表
- 需新增：strategy_tournament.py（策略篩選腳本）
- 需新增：paper_trader.py（Paper Trading 核心引擎）
- 需修改：main.py（新增 --paper-trading 入口）
- 需修改：deploy/（Cloud Run 排程新增）
