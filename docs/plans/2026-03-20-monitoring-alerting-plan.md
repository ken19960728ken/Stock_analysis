# 資料品質監控與系統穩定性 — 實作計畫

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立 scanner 執行日誌 + 資料健檢 + 告警 Email + /health 端點 + 告警升級，讓每日排程的資料品質可監控、異常可感知。

**Architecture:** 新增 `scanner_run_log` DB 表記錄執行歷史，`core/health_check.py` 提供資料健檢，`core/alert_manager.py` 管理告警升級，`core/notifier.py` 擴展支援告警 Email，`dashboard/app.py` 新增 `/health` 端點。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pandas, PostgreSQL (Supabase)

**設計文件:** `docs/plans/2026-03-20-monitoring-alerting-design.md`

---

### Task 1: DB 白名單 + Constraint + 建表 SQL

**Files:**
- Modify: `core/db.py:14-21` (VALID_TABLES)
- Modify: `scripts/db_add_constraints.py` (CONSTRAINTS)

**Step 1: 在 core/db.py 的 VALID_TABLES 加入 scanner_run_log**

```python
"recommendation_history",  # 選股推薦追蹤
"scanner_run_log",         # Scanner 執行日誌
```

**Step 2: 在 scripts/db_add_constraints.py 的 CONSTRAINTS 加入**

```python
    ("recommendation_history", "uq_recommendation_history", "report_date, stock_id"),
    ("scanner_run_log", "uq_scanner_run_log", "run_date, scanner_name, started_at"),
```

注意：scanner_run_log 的 unique key 用 `(run_date, scanner_name, started_at)` 避免同日同 scanner 多次執行衝突。

**Step 3: 準備建表 SQL（供 Supabase SQL Editor 執行）**

將以下 SQL 記錄在 commit message 中，實際建表由使用者手動執行：

```sql
CREATE TABLE scanner_run_log (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    scanner_name    VARCHAR(50) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    duration_sec    FLOAT,
    status          VARCHAR(20) NOT NULL,
    total_targets   INT,
    success_count   INT DEFAULT 0,
    skip_count      INT DEFAULT 0,
    fail_count      INT DEFAULT 0,
    error_message   TEXT,
    data_max_date   DATE,
    triggered_by    VARCHAR(20) DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scanner_run_date ON scanner_run_log(run_date, scanner_name);
```

**Step 4: Commit**

```bash
git add core/db.py scripts/db_add_constraints.py
git commit -m "feat: 註冊 scanner_run_log 到 DB 白名單與 constraint 清單"
```

---

### Task 2: alert_manager — 執行日誌記錄 + 告警升級（TDD）

**Files:**
- Create: `core/alert_manager.py`
- Create: `tests/test_alert_manager.py`

**Step 1: 寫測試**

```python
"""
告警管理測試 — 執行日誌記錄 + 告警升級

覆蓋：
  - log_scanner_run 建構正確 DataFrame
  - 告警升級邏輯（連續失敗判斷）
  - 空資料處理
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from core.alert_manager import (
    log_scanner_run,
    check_alert_escalation,
    _build_run_log_row,
)


class TestBuildRunLogRow:
    """建構執行日誌記錄"""

    def test_success_row(self):
        row = _build_run_log_row(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 30, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 35, 0, tzinfo=timezone.utc),
            total_targets=1800,
            success_count=1750,
            skip_count=30,
            fail_count=20,
            error_message=None,
            triggered_by="scheduler",
        )
        assert row["scanner_name"] == "price"
        assert row["status"] == "partial"  # fail_count > 0
        assert row["duration_sec"] == 300.0
        assert row["run_date"] == "2026-03-20"

    def test_all_success_status(self):
        row = _build_run_log_row(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc),
            total_targets=100,
            success_count=80,
            skip_count=20,
            fail_count=0,
        )
        assert row["status"] == "success"

    def test_all_fail_status(self):
        row = _build_run_log_row(
            scanner_name="chip",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 1, tzinfo=timezone.utc),
            total_targets=100,
            success_count=0,
            skip_count=0,
            fail_count=100,
            error_message="API quota exceeded",
        )
        assert row["status"] == "failed"
        assert row["error_message"] == "API quota exceeded"

    def test_zero_targets_status(self):
        row = _build_run_log_row(
            scanner_name="daily_report",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 2, tzinfo=timezone.utc),
            total_targets=0,
            success_count=0,
            skip_count=0,
            fail_count=0,
        )
        assert row["status"] == "success"


class TestCheckAlertEscalation:
    """告警升級邏輯"""

    @patch("core.alert_manager.safe_read_sql")
    def test_no_recent_runs_no_alert(self, mock_sql):
        mock_sql.return_value = pd.DataFrame()
        level = check_alert_escalation("price")
        assert level is None  # 無資料，不告警

    @patch("core.alert_manager.safe_read_sql")
    def test_all_success_no_alert(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["success", "success", "success"],
            "started_at": pd.date_range("2026-03-18", periods=3),
        })
        level = check_alert_escalation("price")
        assert level is None

    @patch("core.alert_manager.safe_read_sql")
    def test_one_fail_warning(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["failed", "success", "success"],
            "started_at": pd.date_range("2026-03-18", periods=3),
        })
        level = check_alert_escalation("price")
        assert level == "warning"

    @patch("core.alert_manager.safe_read_sql")
    def test_three_consecutive_fails_critical(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["failed", "failed", "failed", "success"],
            "started_at": pd.date_range("2026-03-17", periods=4),
        })
        level = check_alert_escalation("price")
        assert level == "critical"
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_alert_manager.py -v
```

**Step 3: 實作 core/alert_manager.py**

```python
"""
告警管理 — Scanner 執行日誌記錄 + 告警升級判斷
"""

from datetime import datetime, timezone

import pandas as pd

from core.db import safe_read_sql, save_to_db
from core.logger import setup_logger

logger = setup_logger("alert_manager")


def _build_run_log_row(
    scanner_name: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    total_targets: int = 0,
    success_count: int = 0,
    skip_count: int = 0,
    fail_count: int = 0,
    error_message: str | None = None,
    data_max_date: str | None = None,
    triggered_by: str = "manual",
) -> dict:
    """建構一筆執行日誌記錄"""
    duration = None
    if finished_at and started_at:
        duration = (finished_at - started_at).total_seconds()

    if fail_count > 0 and success_count > 0:
        status = "partial"
    elif fail_count > 0 and success_count == 0 and total_targets > 0:
        status = "failed"
    else:
        status = "success"

    return {
        "run_date": started_at.strftime("%Y-%m-%d"),
        "scanner_name": scanner_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration,
        "status": status,
        "total_targets": total_targets,
        "success_count": success_count,
        "skip_count": skip_count,
        "fail_count": fail_count,
        "error_message": error_message,
        "data_max_date": data_max_date,
        "triggered_by": triggered_by,
    }


def log_scanner_run(**kwargs) -> bool:
    """記錄一筆 scanner 執行日誌到 DB"""
    row = _build_run_log_row(**kwargs)
    df = pd.DataFrame([row])
    try:
        return save_to_db(df, "scanner_run_log")
    except Exception as e:
        logger.error(f"記錄執行日誌失敗（不影響主流程）: {e}")
        return False


def check_alert_escalation(scanner_name: str) -> str | None:
    """
    檢查告警升級等級。

    查詢最近 5 次執行記錄，計算連續失敗次數。

    Returns
    -------
    None : 無需告警
    "warning" : 最近一次失敗
    "critical" : 連續 ≥ 3 次失敗
    """
    recent = safe_read_sql(
        "SELECT status, started_at FROM scanner_run_log "
        "WHERE scanner_name = %(name)s "
        "ORDER BY started_at DESC LIMIT 5",
        params={"name": scanner_name},
    )

    if recent.empty:
        return None

    consecutive_fails = 0
    for _, row in recent.iterrows():
        if row["status"] in ("failed", "timeout"):
            consecutive_fails += 1
        else:
            break

    if consecutive_fails >= 3:
        return "critical"
    elif consecutive_fails >= 1:
        return "warning"
    return None
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_alert_manager.py -v
```

**Step 5: Commit**

```bash
git add core/alert_manager.py tests/test_alert_manager.py
git commit -m "feat: 新增 alert_manager — 執行日誌記錄 + 告警升級判斷"
```

---

### Task 3: send_alert_email — 擴展 notifier（TDD）

**Files:**
- Modify: `core/notifier.py`
- Modify: `tests/test_notifier.py`

**Step 1: 在 tests/test_notifier.py 新增測試**

在檔案末尾加入：

```python
from core.notifier import send_alert_email


class TestSendAlertEmail:
    """告警 Email"""

    @patch("core.notifier._send_smtp")
    def test_warning_subject_prefix(self, mock_smtp):
        mock_smtp.return_value = True
        with patch.dict(os.environ, {
            "EMAIL_SENDER": "test@gmail.com",
            "EMAIL_APP_PASSWORD": "pass",
            "EMAIL_RECIPIENTS": "user@example.com",
        }):
            result = send_alert_email(
                subject="資料缺漏",
                body="daily_price 缺少 50 支股票",
                severity="warning",
            )
        assert result is True
        call_args = mock_smtp.call_args
        msg = call_args[0][0]
        assert "[WARNING]" in msg["Subject"]

    @patch("core.notifier._send_smtp")
    def test_critical_subject_prefix(self, mock_smtp):
        mock_smtp.return_value = True
        with patch.dict(os.environ, {
            "EMAIL_SENDER": "test@gmail.com",
            "EMAIL_APP_PASSWORD": "pass",
            "EMAIL_RECIPIENTS": "user@example.com",
        }):
            result = send_alert_email(
                subject="Scanner 連續失敗",
                body="price scanner 連續 3 次失敗",
                severity="critical",
            )
        assert result is True
        call_args = mock_smtp.call_args
        msg = call_args[0][0]
        assert "[CRITICAL]" in msg["Subject"]

    def test_missing_env_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            result = send_alert_email("test", "body")
        assert result is False
```

**Step 2: 修改 core/notifier.py**

重構 SMTP 連線邏輯為內部共用函式 `_send_smtp()`，新增 `send_alert_email()`：

在 `send_report_email()` 的 SMTP 寄送區塊（第 94-111 行），提取為：

```python
def _send_smtp(msg, sender: str, password: str, recipients: list[str]) -> bool:
    """共用 SMTP 寄送邏輯"""
    proxy_url = os.getenv("EMAIL_PROXY")
    try:
        if proxy_url:
            server = _smtp_via_proxy(proxy_url)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)

        with server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"SMTP 寄送失敗: {e}")
        return False
```

然後 `send_report_email()` 改為呼叫 `_send_smtp()`。

新增 `send_alert_email()`：

```python
def send_alert_email(subject: str, body: str, severity: str = "warning") -> bool:
    """
    寄送告警 Email（純文字，無附件）。

    Parameters
    ----------
    subject : str
        告警主旨（自動加上嚴重等級前綴）
    body : str
        告警內容（純文字）
    severity : str
        "info" / "warning" / "critical"
    """
    load_dotenv()
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipients_str = os.getenv("EMAIL_RECIPIENTS")

    if not all([sender, password, recipients_str]):
        logger.warning("Email 環境變數未設定，跳過告警")
        return False

    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        return False

    prefix = {"info": "[INFO]", "warning": "[WARNING]", "critical": "[CRITICAL]"}
    full_subject = f"{prefix.get(severity, '[ALERT]')} {subject}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    success = _send_smtp(msg, sender, password, recipients)
    if success:
        logger.info(f"告警 Email 已寄送: {full_subject}")
    return success
```

**Step 3: 跑測試確認通過**

```bash
uv run pytest tests/test_notifier.py -v
```

**Step 4: Commit**

```bash
git add core/notifier.py tests/test_notifier.py
git commit -m "feat: 新增 send_alert_email — 告警 Email 支援嚴重等級標籤"
```

---

### Task 4: health_check — 資料健檢函式（TDD）

**Files:**
- Create: `core/health_check.py`
- Create: `tests/test_health_check.py`

**Step 1: 寫測試**

```python
"""
資料健檢測試

覆蓋：
  - DB 連線檢查
  - 資料最新日期偵測
  - 整體狀態判斷邏輯
  - 空資料處理
"""

from unittest.mock import patch, MagicMock
from datetime import date

import pandas as pd
import pytest

from core.health_check import run_health_check, HealthCheckResult


class TestHealthCheck:

    @patch("core.health_check.safe_read_sql")
    @patch("core.health_check.get_engine")
    def test_healthy_when_all_ok(self, mock_engine, mock_sql):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # MAX(date) = today
        mock_sql.side_effect = [
            pd.DataFrame({"max_date": [date.today()]}),  # data_max_date
            pd.DataFrame({"cnt": [1800]}),                 # daily count
            pd.DataFrame({"cnt": [1750]}),                 # median count
            pd.DataFrame({"cnt": [0]}),                    # zero volume
            pd.DataFrame({"cnt": [0]}),                    # abnormal price
            pd.DataFrame(),                                # scanner_run_log
        ]

        result = run_health_check()
        assert isinstance(result, HealthCheckResult)
        assert result.db_connected is True
        assert result.overall_status in ("healthy", "degraded")

    @patch("core.health_check.get_engine")
    def test_unhealthy_when_db_down(self, mock_engine):
        mock_engine.side_effect = Exception("connection refused")
        result = run_health_check()
        assert result.db_connected is False
        assert result.overall_status == "unhealthy"

    def test_result_has_required_fields(self):
        result = HealthCheckResult(
            check_date="2026-03-20",
            is_trading_day=True,
            checks=[],
            overall_status="healthy",
            db_connected=True,
            data_max_date="2026-03-20",
        )
        assert result.check_date == "2026-03-20"
        assert result.overall_status == "healthy"
```

**Step 2: 實作 core/health_check.py**

```python
"""
資料健檢 — DB 連線、資料完整性、異常值偵測

供 dashboard /health 端點和 --daily-data 自動檢查共用。
"""

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

from core.db import get_engine, safe_read_sql
from core.logger import setup_logger

logger = setup_logger("health_check")


@dataclass
class HealthCheckResult:
    check_date: str = ""
    is_trading_day: bool = True
    checks: list = field(default_factory=list)
    overall_status: str = "unknown"      # healthy / degraded / unhealthy
    db_connected: bool = False
    data_max_date: str = ""


def run_health_check() -> HealthCheckResult:
    """執行所有健檢項目，回傳結構化結果"""
    result = HealthCheckResult(check_date=date.today().isoformat())
    checks = []

    # 1. DB 連線
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        result.db_connected = True
        checks.append({"name": "DB 連線", "status": "ok", "detail": "連線正常"})
    except Exception as e:
        result.db_connected = False
        result.overall_status = "unhealthy"
        checks.append({"name": "DB 連線", "status": "critical", "detail": str(e)})
        result.checks = checks
        return result

    # 2. 資料最新日期
    try:
        df = safe_read_sql("SELECT MAX(date) AS max_date FROM daily_price")
        if not df.empty and df.iloc[0]["max_date"] is not None:
            max_date = pd.Timestamp(df.iloc[0]["max_date"]).date()
            result.data_max_date = max_date.isoformat()
            days_behind = (date.today() - max_date).days
            if days_behind > 4:  # 超過 4 天（含週末）
                checks.append({
                    "name": "資料最新日期",
                    "status": "warning",
                    "detail": f"最新日期 {max_date}，落後 {days_behind} 天",
                })
            else:
                checks.append({
                    "name": "資料最新日期",
                    "status": "ok",
                    "detail": f"最新日期 {max_date}",
                })
        else:
            checks.append({
                "name": "資料最新日期",
                "status": "warning",
                "detail": "daily_price 表為空",
            })
    except Exception as e:
        checks.append({"name": "資料最新日期", "status": "warning", "detail": str(e)})

    # 3. 當日資料筆數 vs 中位數
    try:
        latest = safe_read_sql(
            "SELECT COUNT(*) AS cnt FROM daily_price WHERE date = %(d)s",
            params={"d": result.data_max_date},
        )
        median_df = safe_read_sql(
            "SELECT COUNT(*) / COUNT(DISTINCT date) AS cnt "
            "FROM daily_price WHERE date >= NOW() - INTERVAL '30 days'"
        )
        today_cnt = int(latest.iloc[0]["cnt"]) if not latest.empty else 0
        median_cnt = float(median_df.iloc[0]["cnt"]) if not median_df.empty else 0

        if median_cnt > 0 and today_cnt < median_cnt * 0.8:
            checks.append({
                "name": "資料筆數",
                "status": "warning",
                "detail": f"最新日 {today_cnt} 筆，中位數 {median_cnt:.0f} 筆（偏差 > 20%）",
            })
        else:
            checks.append({
                "name": "資料筆數",
                "status": "ok",
                "detail": f"最新日 {today_cnt} 筆",
            })
    except Exception as e:
        checks.append({"name": "資料筆數", "status": "warning", "detail": str(e)})

    # 4. 成交量為 0
    try:
        zero_vol = safe_read_sql(
            "SELECT COUNT(*) AS cnt FROM daily_price "
            "WHERE date = %(d)s AND volume = 0",
            params={"d": result.data_max_date},
        )
        cnt = int(zero_vol.iloc[0]["cnt"]) if not zero_vol.empty else 0
        if cnt > 50:
            checks.append({
                "name": "零成交量",
                "status": "warning",
                "detail": f"{cnt} 支股票成交量為 0",
            })
        else:
            checks.append({"name": "零成交量", "status": "ok", "detail": f"{cnt} 支"})
    except Exception as e:
        checks.append({"name": "零成交量", "status": "warning", "detail": str(e)})

    # 5. 異常價格（漲跌幅 > 10%）
    try:
        abnormal = safe_read_sql(
            "SELECT COUNT(*) AS cnt FROM daily_price "
            "WHERE date = %(d)s AND open > 0 "
            "AND ABS(close - open) / open > 0.11",
            params={"d": result.data_max_date},
        )
        cnt = int(abnormal.iloc[0]["cnt"]) if not abnormal.empty else 0
        if cnt > 20:
            checks.append({
                "name": "異常價格",
                "status": "warning",
                "detail": f"{cnt} 支股票漲跌幅 > 11%（可能資料錯誤）",
            })
        else:
            checks.append({"name": "異常價格", "status": "ok", "detail": f"{cnt} 支"})
    except Exception as e:
        checks.append({"name": "異常價格", "status": "warning", "detail": str(e)})

    # 6. Scanner 最後執行
    try:
        run_log = safe_read_sql(
            "SELECT scanner_name, MAX(started_at) AS last_run, "
            "MAX(CASE WHEN status IN ('success', 'partial') THEN started_at END) AS last_success "
            "FROM scanner_run_log GROUP BY scanner_name"
        )
        if not run_log.empty:
            checks.append({
                "name": "Scanner 執行記錄",
                "status": "ok",
                "detail": f"{len(run_log)} 個 scanner 有執行記錄",
            })
        else:
            checks.append({
                "name": "Scanner 執行記錄",
                "status": "info",
                "detail": "尚無執行記錄（scanner_run_log 為空）",
            })
    except Exception:
        # 表可能不存在（首次部署前）
        checks.append({
            "name": "Scanner 執行記錄",
            "status": "info",
            "detail": "scanner_run_log 表尚未建立",
        })

    # 判斷整體狀態
    statuses = [c["status"] for c in checks]
    if "critical" in statuses:
        result.overall_status = "unhealthy"
    elif "warning" in statuses:
        result.overall_status = "degraded"
    else:
        result.overall_status = "healthy"

    result.checks = checks
    return result


def format_alert_body(checks: list[dict]) -> str:
    """將異常的健檢項目格式化為告警郵件內文"""
    lines = ["資料健檢發現以下異常：", ""]
    for c in checks:
        if c["status"] not in ("ok", "info"):
            lines.append(f"[{c['status'].upper()}] {c['name']}: {c['detail']}")
    lines.append("")
    lines.append(f"檢查時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)
```

**Step 3: 跑測試確認通過**

```bash
uv run pytest tests/test_health_check.py -v
```

**Step 4: Commit**

```bash
git add core/health_check.py tests/test_health_check.py
git commit -m "feat: 新增 health_check — 資料品質健檢（DB 連線 + 筆數 + 異常值）"
```

---

### Task 5: 串接 BaseScanner — scan() 結束時記錄執行日誌

**Files:**
- Modify: `core/scanner_base.py`

**Step 1: 修改 scanner_base.py**

在 imports 加入：

```python
from datetime import datetime, timezone
```

在 `scan()` 方法的開頭記錄開始時間：

```python
def scan(self):
    _scan_started = datetime.now(timezone.utc)
    targets = self.get_targets()
    ...
```

在 `finally` 區塊的結算報告後，加入執行日誌記錄：

```python
        finally:
            close_index()
            dispose_engine()
            logger.info("==========================================")
            logger.info(f"[{self.name}] 任務結算")
            logger.info("==========================================")
            logger.info(f"成功: {success_count} 檔")
            logger.info(f"跳過: {skip_count} 檔")
            logger.info(f"失敗: {fail_count} 檔")
            logger.info("系統已安全著陸。")

            # 記錄執行日誌到 DB
            try:
                from core.alert_manager import log_scanner_run
                log_scanner_run(
                    scanner_name=self.name,
                    started_at=_scan_started,
                    finished_at=datetime.now(timezone.utc),
                    total_targets=len(targets),
                    success_count=success_count,
                    skip_count=skip_count,
                    fail_count=fail_count,
                    triggered_by="manual",
                )
            except Exception as e:
                logger.debug(f"執行日誌記錄失敗（不影響主流程）: {e}")
```

**Step 2: 跑 scanner_base 測試**

```bash
uv run pytest tests/test_core_scanner_base.py -v
```

**Step 3: Commit**

```bash
git add core/scanner_base.py
git commit -m "feat: BaseScanner scan() 結束時自動記錄執行日誌"
```

---

### Task 6: 串接 main.py — daily-data 健檢 + 告警

**Files:**
- Modify: `main.py`

**Step 1: 修改 run_daily_data()**

```python
def run_daily_data():
    """執行每日資料抓取（價格 + 籌碼 + 估值面）。回傳 True 表示為交易日。"""
    from scanners.daily_updater import DailyUpdater
    is_trading_day = DailyUpdater().run()
    if not is_trading_day:
        logger.info("非交易日，跳過資料更新")
        return is_trading_day

    # 資料健檢 + 告警
    try:
        from core.health_check import run_health_check, format_alert_body
        from core.notifier import send_alert_email
        result = run_health_check()
        logger.info(f"資料健檢: {result.overall_status} ({len(result.checks)} 項)")
        if result.overall_status != "healthy":
            alerts = [c for c in result.checks if c["status"] not in ("ok", "info")]
            body = format_alert_body(alerts)
            send_alert_email(
                subject=f"資料健檢 — {result.overall_status}",
                body=body,
                severity="warning" if result.overall_status == "degraded" else "critical",
            )
    except Exception as e:
        logger.error(f"資料健檢失敗（不影響主流程）: {e}")

    return is_trading_day
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: --daily-data 完成後自動執行資料健檢 + 異常告警"
```

---

### Task 7: /health 端點 — Dashboard 健康檢查

**Files:**
- Modify: `dashboard/app.py`
- Modify: `deploy/deploy-analysis.sh`（可選）

**Step 1: 在 dashboard/app.py 加入 /health 端點**

在 imports 加入：

```python
from fastapi.responses import FileResponse, JSONResponse
```

在最後一個端點之後加入：

```python
@app.get("/health")
async def health():
    """健康檢查端點 — 供 Cloud Run liveness probe 和手動查詢"""
    try:
        from core.health_check import run_health_check
        result = run_health_check()
        status_code = 200 if result.overall_status == "healthy" else 503
        return JSONResponse(
            content={
                "status": result.overall_status,
                "check_date": result.check_date,
                "db_connected": result.db_connected,
                "data_max_date": result.data_max_date,
                "checks": result.checks,
            },
            status_code=status_code,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "unhealthy", "error": str(e)},
            status_code=503,
        )
```

**Step 2: Commit**

```bash
git add dashboard/app.py
git commit -m "feat: Dashboard 新增 /health 健康檢查端點"
```

---

### Task 8: 跑全量測試 + 更新文件

**Step 1: 跑全量測試**

```bash
uv run pytest tests/ -v
```

**Step 2: 修復任何失敗**

**Step 3: 更新文件**

- `CLAUDE.md` — 新增 core/health_check.py、core/alert_manager.py 到模組表、scanner_run_log 到 DB 表
- `CHANGELOG.md` — 記錄變更
- `analysis/documents/測試說明.md` — 加入新測試檔案
- `docs/選股策略藍圖.md` — 打勾完成的項目

**Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md analysis/documents/測試說明.md docs/選股策略藍圖.md
git commit -m "docs: 更新文件 — 監控告警系統的模組/DB/測試說明"
```
