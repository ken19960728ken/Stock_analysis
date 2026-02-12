import os

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv  # 引入讀取套件
from sqlalchemy import create_engine

# ==========================================
# 1. 載入機密資訊
# ==========================================
# 這行會尋找當前目錄下的 .env 檔案並載入環境變數
load_dotenv()

# 從環境變數中讀取連線字串
DB_URL = os.getenv("SUPABASE_URL")

# 進行安全檢查：如果沒讀到，立刻報錯停止
if not DB_URL:
    raise ValueError("錯誤：找不到 SUPABASE_URL，請檢查你的 .env 檔案設定！")

# 建立資料庫引擎
try:
    db_engine = create_engine(DB_URL)
    # 測試連線 (Optional)
    with db_engine.connect() as connection:
        print("✅ 成功連線到 Supabase 資料庫！")
except Exception as e:
    print(f"❌ 資料庫連線失敗: {e}")
    exit()


# ==========================================
# 2. 數據抓取與上傳邏輯 (同前)
# ==========================================
def upload_price_data(stock_id):
    print(f"正在處理 {stock_id} ...")
    ticker = f"{stock_id}.TW"

    # 抓取數據 (這裡示範抓 3 年)
    df = yf.download(ticker, period="3y", progress=False, auto_adjust=False)

    if df.empty:
        print(f"⚠️ {stock_id} 無數據")
        return

    # 數據清洗
    df = df.reset_index()
    # 處理 yfinance 多層索引問題
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    # 標準化欄位名稱
    df.columns = [c.lower() for c in df.columns]  # 轉小寫
    df["stock_id"] = stock_id

    # 確保只有需要的欄位
    required_cols = ["date", "stock_id", "open", "high", "low", "close", "volume"]
    # 檢查欄位是否存在 (防止 yfinance 改版)
    available_cols = [c for c in required_cols if c in df.columns]
    df = df[available_cols]

    # 上傳到 Supabase
    try:
        # method='multi' 可以加速批量寫入
        df.to_sql(
            "daily_price",
            db_engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000,
        )
        print(f"🚀 [{stock_id}] {len(df)} 筆數據已入庫")
    except Exception as e:
        # 通常是 Primary Key 重複 (已經存過了)，這裡可以選擇 pass 或 print
        print(f"ℹ️ [{stock_id}] 寫入略過 (可能是重複數據): {str(e).splitlines()[0]}")


# ==========================================
# 執行
# ==========================================
if __name__ == "__main__":
    target_stocks = ["2330", "2317", "2454"]
    for stock in target_stocks:
        upload_price_data(stock)
