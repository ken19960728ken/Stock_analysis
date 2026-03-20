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
            "SELECT COUNT(*) / NULLIF(COUNT(DISTINCT date), 0) AS cnt "
            "FROM daily_price WHERE date >= NOW() - INTERVAL '30 days'"
        )
        today_cnt = int(latest.iloc[0]["cnt"]) if not latest.empty else 0
        median_cnt = float(median_df.iloc[0]["cnt"]) if not median_df.empty and pd.notna(median_df.iloc[0]["cnt"]) else 0

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

    # 5. 異常價格（漲跌幅 > 11%）
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
            "SELECT scanner_name, MAX(started_at) AS last_run "
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
