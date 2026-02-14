import os

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine
from tqdm import tqdm  # 進度條工具

# ==========================================
# 1. 初始化與設定
# ==========================================
# 載入 .env 檔案中的密碼
load_dotenv()

# 獲取資料庫連線字串
DB_URL = os.getenv("SUPABASE_URL")

if not DB_URL:
    print("❌ 錯誤：找不到 SUPABASE_URL。請檢查你的 .env 檔案。")
    exit()

# 建立資料庫連線引擎
try:
    db_engine = create_engine(DB_URL)
    print(f"get url ={DB_URL}")
    print("✅ 成功連線到 Supabase 資料庫")
except Exception as e:
    print(f"❌ 資料庫連線失敗: {e}")
    exit()


# ==========================================
# 2. 核心邏輯：抓取公開數據 (Yahoo Finance)
# ==========================================
def fetch_and_upload_history(stock_id, period="3y"):
    """
    從 Yahoo Finance 抓取指定股票的歷史數據並上傳到 Supabase
    :param stock_id: 台股代號 (e.g., "2330")
    :param period: 抓取時間長度 (預設 3年: "3y")
    """
    ticker = f"{stock_id}.TW"

    try:
        # 下載數據 (auto_adjust=False 確保拿到原始開高低收)
        df = yf.download(ticker, period=period, progress=False, auto_adjust=False)

        if df.empty:
            print(f"⚠️ [{stock_id}] 抓取不到數據 (可能是下市或代號錯誤)")
            return

        # --- 數據清洗 (Data Cleaning) ---
        df = df.reset_index()

        # 處理 yfinance 可能出現的 MultiIndex 欄位問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # 統一欄位名稱為小寫，方便 SQL 查詢
        df.columns = [c.lower() for c in df.columns]

        # 補上股票代號欄位
        df["stock_id"] = stock_id

        # 確保日期格式正確
        df["date"] = pd.to_datetime(df["date"]).dt.date

        # 只保留我們需要的核心欄位
        required_cols = ["date", "stock_id", "open", "high", "low", "close", "volume"]
        # 過濾掉不需要的欄位 (如 Adj Close)
        df = df[[c for c in required_cols if c in df.columns]]

        # --- 上傳數據 (Data Upload) ---
        # 使用 'append' 模式，如果表不存在會自動建立
        # method='multi' 加速上傳

    except Exception as e:
        # 捕捉並顯示錯誤，但不中斷整個程式
        print(f"❌ [{stock_id}] 處理失敗: {e}")

    df.to_sql(
        "daily_price",
        db_engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )


# ==========================================
# 3. 指揮中心 (Main Execution)
# ==========================================
if __name__ == "__main__":
    # 這是你的觀察清單 (Watchlist)
    # 你可以在這裡加入任何你想分析的台股代號
    target_stocks = [
        "2330",  # 台積電
        "2317",  # 鴻海
        "2454",  # 聯發科
        "2603",  # 長榮
        "0050",  # 元大台灣50
    ]

    print(f"🚀 開始執行任務：抓取 {len(target_stocks)} 檔股票的近 3 年數據...")

    # 使用 tqdm 顯示進度條，讓你感覺像個專業工程師
    for stock in tqdm(target_stocks):
        fetch_and_upload_history(stock, period="3y")

    print("\n✅ 任務完成。數據已安全存入你的 Supabase 雲端資料庫。")
