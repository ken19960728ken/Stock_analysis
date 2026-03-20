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
    "critical" : 連續 >= 3 次失敗
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
