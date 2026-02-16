"""
Streamlit 量化分析平台 — 主入口
"""

import sys
from pathlib import Path

import streamlit as st

# 確保專案根目錄在 sys.path
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

st.set_page_config(
    page_title="Stock Analysis Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 台灣股市量化分析平台")

st.markdown("""
### 功能模組

| 模組 | 說明 |
|---|---|
| **📈 個股分析** | 單股深度分析：K線、技術指標、籌碼面、基本面 |
| **🔍 因子篩選** | 多維度條件過濾，選股工具 |
| **🧪 策略回測** | 10 個內建策略 + 績效報告 + 交易明細 |
| **🔗 配對交易** | Engle-Granger 共整合檢定、Z-Score 監控 |
| **🛡️ 風險管理** | 持倉 VaR、回撤分析、相關性矩陣 |
| **🌐 市場總覽** | 全市場漲跌、法人動態、估值分佈 |

---

### 快速開始

👈 從左側選擇模組開始分析

### 資料來源

- **日K資料**: Yahoo Finance → `daily_price`
- **籌碼面**: FinMind → 6 張籌碼表
- **基本面**: FinMind + Yahoo → 財報、股利、月營收
- **估值面**: FinMind → PER/PBR、市值
""")

# 資料庫連線檢查
try:
    from core.db import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    st.success("資料庫連線正常")
except Exception as e:
    st.error(f"資料庫連線失敗: {e}")
    st.info("請確認 .env 檔案中的 SUPABASE_URL 設定正確")
