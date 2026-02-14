import os
import random
import time

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from tqdm import tqdm

# ==========================================
# 0. 環境設定與軍火庫連線
# ==========================================
load_dotenv()
DB_URL = os.getenv("SUPABASE_URL")

if not DB_URL:
    print("❌ 錯誤：找不到 SUPABASE_URL")
    exit()

# 建立資料庫引擎
engine = create_engine(DB_URL)


# ==========================================
# 1. 從資料庫獲取目標清單 (戰略核心)
# ==========================================
def get_targets_from_db():
    print("📋 正在從 twstock_code 表中讀取戰略清單...")

    # SQL 邏輯：
    # 1. 選擇 CFICode 為 ESVUFR (普通股) 或 商品類型 為 ETF
    # 2. 我們只需要 '商品代號' 和 '市場別' 來組裝 Yahoo 代號
    # 注意：如果你的欄位名稱是中文，建議加上雙引號以防 SQL 解析錯誤
    sql_query = """
    SELECT "商品代號", "市場別", "商品名稱", "商品類型"
    FROM twstock_code
    WHERE "CFICode" = 'ESVUFR' OR "商品類型" = 'ETF'
    """

    try:
        df_codes = pd.read_sql(sql_query, engine)

        target_list = []
        for index, row in df_codes.iterrows():
            code = str(row["商品代號"]).strip()
            market = str(row["市場別"]).strip()

            # --- Yahoo Finance 代號轉換邏輯 ---
            # 台灣上市 (包含創新板) -> .TW
            # 台灣上櫃 -> .TWO

            if "上市" in market:
                yahoo_symbol = f"{code}.TW"
            elif "上櫃" in market:
                yahoo_symbol = f"{code}.TWO"
            else:
                # 興櫃或其他未上市櫃的股票，Yahoo 通常抓不到，先跳過
                continue

            target_list.append(
                {
                    "yahoo_symbol": yahoo_symbol,
                    "stock_id": code,
                    "name": row["商品名稱"],
                    "type": row["商品類型"],
                }
            )

        print(f"📊 經篩選後，共鎖定 {len(target_list)} 檔標的 (普通股 + ETF)")
        return target_list

    except Exception as e:
        print(f"❌ 讀取 twstock_code 失敗: {e}")
        return []


# ==========================================
# 2. 檢查資料庫現有庫存 (增量更新檢查)
# ==========================================
def get_existing_data_date(stock_id):
    """
    (進階) 未來可以擴充為檢查該股票 '最新的日期' 是哪一天，
    目前先簡單檢查 '是否已存在'。
    """
    try:
        # 這裡做一個簡單的優化：只檢查是否有這檔股票，不檢查日期
        # 如果要嚴謹的增量更新，需要改寫這裡
        check_sql = text(
            f"SELECT 1 FROM daily_price WHERE stock_id = '{stock_id}' LIMIT 1"
        )
        with engine.connect() as conn:
            result = conn.execute(check_sql).fetchone()
            return result is not None  # 如果有資料回傳 True
    except Exception:
        return False


# ==========================================
# 3. 核心抓取與寫入 (執行單位)
# ==========================================
def fetch_and_store(target_info):
    ticker = target_info["yahoo_symbol"]
    stock_id = target_info["stock_id"]

    try:
        # 下載數據 (預設抓 3 年，你可以改成 "max" 抓全部)
        df = yf.download(ticker, period="3y", progress=False, auto_adjust=False)

        if df.empty:
            return False, "無數據 (Yahoo源)"

        # --- 數據清洗 ---
        df = df.reset_index()

        # 處理 MultiIndex (Yahoo 討厭的地方)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # 欄位標準化
        df.columns = [c.lower() for c in df.columns]
        df["stock_id"] = stock_id  # 寫入純數字代號 (如 2330)

        # 確保日期格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        # 選擇需要的欄位
        required_cols = ["date", "stock_id", "open", "high", "low", "close", "volume"]
        # 確保欄位都存在
        save_df = df[[c for c in required_cols if c in df.columns]]

        # --- 寫入資料庫 ---
        save_df.to_sql(
            "daily_price",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000,
        )

        return True, "成功"

    except Exception as e:
        return False, str(e)


# ==========================================
# 4. 指揮官 (Main Loop)
# ==========================================
if __name__ == "__main__":
    # 1. 獲取清單
    targets = get_targets_from_db()

    if not targets:
        print("⚠️ 無目標可執行，請檢查資料庫。")
        exit()

    print("🚀 開始執行全市場數據掃描...")
    print("💡 提示：隨時按下 'Ctrl + C' 可安全中斷程式。")

    # 2. 進度條迴圈
    pbar = tqdm(targets)
    success_count = 0
    skip_count = 0

    # --- 🛡️ 異常處理防護罩 ---
    try:
        for target in pbar:
            symbol = target["yahoo_symbol"]
            stock_id = target["stock_id"]
            name = target["name"]

            pbar.set_description(f"處理 {stock_id} {name}")

            # --- 檢查是否已存在 (簡單斷點續傳) ---
            if get_existing_data_date(stock_id):
                skip_count += 1
                continue

            # --- 執行抓取 ---
            status, msg = fetch_and_store(target)

            if status:
                success_count += 1
            else:
                pass

            # --- 防封鎖機制 ---
            time.sleep(random.uniform(0.8, 1.5))

    except KeyboardInterrupt:
        # 這是當你按下 Ctrl+C 時會執行的區塊
        pbar.close()  # 關閉進度條，避免顯示錯亂
        print("\n\n🛑 收到中斷指令 (SIGINT)！正在執行緊急剎車程序...")
        print("⚠️ 正在停止所有寫入操作...")
        # 在這裡可以加入額外的清理工作，例如關閉特定的連線

    except Exception as e:
        # 捕捉其他未預期的錯誤
        print(f"\n❌ 發生未預期錯誤: {e}")

    finally:
        # 無論是正常結束還是被中斷，這裡都會執行
        engine.dispose()  # 確保資料庫連線被釋放
        print("\n==========================================")
        print("📊 任務結算報告")
        print("==========================================")
        print(f"📥 本次成功下載: {success_count} 檔")
        print(f"⏭️ 跳過已存在: {skip_count} 檔")
        print("✅ 系統已安全著陸。")
