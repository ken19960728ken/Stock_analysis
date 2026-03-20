# 資料品質監控與系統穩定性 — 設計文件

> 日期：2026-03-20
> 狀態：已確認，待實作
> 範圍：Phase 3.6a（資料品質）+ 3.6d（系統穩定性）的 A+B 階段

---

## 1. 動機

每日排程（Cloud Scheduler 18:30/18:40 UTC+8）自動抓取資料和產出報告，但目前：
- Scanner 失敗無人知曉（需手動 `--show-failures`）
- 資料缺漏或延遲無法偵測
- Cloud Run 無健康檢查端點
- 無執行歷史可查，無法判斷趨勢

## 2. 架構

```
                    ┌─────────────────────────────┐
                    │     scanner_run_log (DB)     │
                    │  每次執行的結構化記錄         │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────────┐
    │ data_health_   │  │ alert_     │  │ /health endpoint│
    │ check()        │  │ manager    │  │ (Dashboard)     │
    │ 資料健檢       │  │ 告警升級   │  │ Cloud Run probe │
    └─────────┬──────┘  └─────┬──────┘  └─────────────────┘
              │               │
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │ send_alert_   │
              │ email()       │
              │ 告警 Email    │
              └───────────────┘
```

## 3. DB Schema — scanner_run_log

```sql
CREATE TABLE scanner_run_log (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    scanner_name    VARCHAR(50) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    duration_sec    FLOAT,
    status          VARCHAR(20) NOT NULL,    -- success / partial / failed / timeout
    total_targets   INT,
    success_count   INT DEFAULT 0,
    skip_count      INT DEFAULT 0,
    fail_count      INT DEFAULT 0,
    error_message   TEXT,
    data_max_date   DATE,                    -- 執行後 DB 中最新資料日期
    triggered_by    VARCHAR(20) DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scanner_run_date ON scanner_run_log(run_date, scanner_name);
```

## 4. 健檢項目（data_health_check）

| 檢查項 | 邏輯 | 等級 |
|--------|------|------|
| DB 連線 | `SELECT 1` | critical |
| 資料最新日期 | `MAX(date) FROM daily_price`，落後 > 2 交易日 | warning |
| 當日資料筆數 | 與近 20 日中位數比較，偏差 > 20% | warning |
| 異常價格 | 當日漲跌幅 > 10% 的股票數 | warning |
| 成交量為 0 | 當日 volume = 0 的股票數 | warning |
| Scanner 最後執行 | 從 run_log 查，超過 24h 未執行 | warning |

## 5. 告警升級規則

| 連續失敗次數 | 動作 | 嚴重等級 |
|-------------|------|---------|
| 1 | Email 告警 | warning |
| ≥ 3 | Email 告警 + 標記 critical | critical |

## 6. 修改檔案清單

| 檔案 | 變更 |
|------|------|
| `core/notifier.py` | 重構 SMTP → `_send_email()`，新增 `send_alert_email()` |
| `core/health_check.py` | **新增**：`HealthCheckResult`、`run_health_check()` |
| `core/alert_manager.py` | **新增**：`log_scanner_run()`、`check_alert_escalation()` |
| `core/scanner_base.py` | scan() 結束時呼叫 `log_scanner_run()` |
| `core/db.py` | 白名單加入 `scanner_run_log` |
| `scripts/db_add_constraints.py` | 加入 constraint |
| `dashboard/app.py` | 新增 `/health` 端點 |
| `main.py` | `run_daily_data()` 串接健檢 + 告警 |
| `deploy/deploy-analysis.sh` | 加入 liveness probe |

## 7. 不做的事（Phase C 待辦）

- Scanner 失敗自動重試（改 BaseScanner）
- 歷史資料一致性校驗排程化
- GCS 資料備份
