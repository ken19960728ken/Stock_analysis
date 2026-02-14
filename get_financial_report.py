import os
import random
import time

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from FinMind.data import DataLoader
from sqlalchemy import create_engine
from tqdm import tqdm

# ==========================================
# 0. 環境設定
# ==========================================
load_dotenv()
DB_URL = os.getenv("SUPABASE_URL")
if not DB_URL:
    print("❌ 錯誤：找不到 SUPABASE_URL")
    exit()

engine = create_engine(DB_URL)

# 初始化 FinMind Loader
fm_loader = DataLoader()


# ==========================================
# 1. 功能模組：抓取股利 (Yahoo Finance)
# ==========================================
def fetch_dividends_yahoo(stock_id):
    """
    抓取歷史配息紀錄
    """
    ticker = f"{stock_id}.TW"
    try:
        stock = yf.Ticker(ticker)
        divs = stock.dividends

        if divs.empty:
            return None

        # 整理格式
        df = divs.reset_index()
        df.columns = ["date", "dividend"]
        df["stock_id"] = stock_id
        df["date"] = pd.to_datetime(df["date"]).dt.date

        # 只要這三個欄位
        return df[["date", "stock_id", "dividend"]]

    except Exception as e:
        print(f"⚠️ [{stock_id}] 股利抓取失敗: {e}")
        return None


# ==========================================
# 2. 功能模組：抓取財報 EPS (FinMind)
# ==========================================
def fetch_eps_finmind(stock_id):
    """
    抓取季報 EPS (每股盈餘)
    """
    try:
        # 抓取最近 3 年的季報
        df = fm_loader.taiwan_stock_financial_statement(
            stock_id=stock_id,
            start_date="2020-01-01",
            token=None,  # 免費版不需要 token，但在頻繁呼叫時可能會受限
        )

        if df.empty:
            return None

        # 篩選我們感興趣的欄位：EPS
        # FinMind 的 type 欄位裡有 'EPS'
        df_eps = df[df["type"].str.contains("EarningsPerShare", case=False, na=False)]

        if df_eps.empty:
            # 嘗試找中文
            df_eps = df[df["type"].str.contains("每股盈餘", na=False)]

        if df_eps.empty:
            return None

        # 整理
        df_eps = df_eps[["date", "stock_id", "value"]]
        df_eps.rename(columns={"value": "eps"}, inplace=True)
        # date 通常是財報發布日或季度結束日
        df_eps["date"] = pd.to_datetime(df_eps["date"]).dt.date

        return df_eps

    except Exception as e:
        print(f"⚠️ [{stock_id}] FinMind EPS 抓取失敗: {e}")
        return None


# ==========================================
# 3. 獲取目標清單 (從我們自己的資料庫)
# ==========================================
def get_targets():
    # 只抓股票，不抓期貨或 ETF (ETF 通常沒有 EPS)
    sql = "SELECT DISTINCT stock_id FROM daily_price WHERE stock_id NOT LIKE '%_%' AND length(stock_id) = 4"
    try:
        df = pd.read_sql(sql, engine)
        return df["stock_id"].tolist()
    except Exception:
        # 如果 daily_price 沒資料，先用測試清單
        return ["2330", "2454", "2317"]


# ==========================================
# 4. 指揮官
# ==========================================
if __name__ == "__main__":
    targets = get_targets()
    print(f"🚀 開始執行基本面掃描，目標：{len(targets)} 檔...")

    pbar = tqdm(targets)

    for stock_id in pbar:
        pbar.set_description(f"分析 {stock_id}")

        # 1. 抓股利
        df_div = fetch_dividends_yahoo(stock_id)
        if df_div is not None:
            try:
                df_div.to_sql(
                    "dividend_history",
                    engine,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
            except:
                pass  # 忽略重複鍵值錯誤

        # 2. 抓 EPS (FinMind)
        # 注意：FinMind 免費版有 API 限制，不能跑太快
        time.sleep(20)  # 這裡要睡久一點

        df_eps = fetch_eps_finmind(stock_id)
        if df_eps is not None:
            try:
                df_eps.to_sql(
                    "financial_reports",
                    engine,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
            except:
                pass

        # 休息一下，避免被封鎖
        time.sleep(random.uniform(1.5, 3.0))

    print("\n✅ 基本面數據更新完成。")
