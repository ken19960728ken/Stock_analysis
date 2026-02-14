import os
import random
import time

import pandas as pd
from dotenv import load_dotenv
from FinMind.data import DataLoader
from sqlalchemy import create_engine
from tqdm import tqdm

# ==========================================
# 0. 環境設定與 VIP 通道認證
# ==========================================
load_dotenv()

# 1. 處理資料庫連線
DB_URL = os.getenv("SUPABASE_URL")
if not DB_URL:
    print("❌ 錯誤：找不到 SUPABASE_URL")
    exit()
engine = create_engine(DB_URL)

# 2. 處理 FinMind Token (關鍵升級)
FM_TOKEN = os.getenv("FINMIND_TOKEN")
fm_loader = DataLoader()

if FM_TOKEN:
    try:
        # 執行登入認證
        fm_loader.login_by_token(api_token=FM_TOKEN)
        print("✅ FinMind VIP 通道已開啟 (Token 認證成功)")
    except Exception as e:
        print(f"⚠️ FinMind 登入失敗 (將降級為一般限速模式): {e}")
else:
    print("⚠️ 警告：未發現 FINMIND_TOKEN，將使用一般限速模式 (容易被斷線)")


# ==========================================
# 1. 定義我們關注的核心指標
# ==========================================
FOCUS_METRICS = [
    "Revenue",
    "GrossProfit",
    "OperatingIncome",
    "NetIncome",
    "EarningsPerShare",
    "TotalAssets",
    "TotalLiabilities",
    "TotalEquity",
    "CashFlowsFromOperatingActivities",
]


# ==========================================
# 2. 核心邏輯：全方位財報抓取
# ==========================================
def fetch_financials_finmind(stock_id):
    """
    抓取並篩選關鍵財務數據
    """
    try:
        # 1. 抓取損益表 (Income Statement)
        # 注意：這裡我們要傳入 token=FM_TOKEN 以確保享受 VIP 速率
        df_income = fm_loader.taiwan_stock_financial_statement(
            stock_id=stock_id,
            start_date="2020-01-01",
            token=FM_TOKEN,  # <--- 這裡改用 Token
        )

        # 2. 抓取資產負債表 (Balance Sheet)
        df_balance = fm_loader.taiwan_stock_balance_sheet(
            stock_id=stock_id,
            start_date="2020-01-01",
            token=FM_TOKEN,  # <--- 這裡改用 Token
        )

        # 3. 合併數據
        df_list = []
        if not df_income.empty:
            df_list.append(df_income)
        if not df_balance.empty:
            df_list.append(df_balance)

        if not df_list:
            return None

        df_all = pd.concat(df_list, ignore_index=True)

        # --- 數據清洗 ---
        df_all["type"] = df_all["type"].astype(str).str.strip()
        df_filtered = df_all[df_all["type"].isin(FOCUS_METRICS)].copy()

        if df_filtered.empty:
            return None

        df_filtered = df_filtered[["date", "stock_id", "type", "value"]]
        df_filtered["date"] = pd.to_datetime(df_filtered["date"]).dt.date

        return df_filtered

    except Exception as e:
        # 如果是 429 Too Many Requests，代表即便有 Token 還是太快了
        if "429" in str(e):
            print(f"⚠️ [{stock_id}] 速度過快，觸發限制，休息 10 秒...")
            time.sleep(10)
        else:
            print(f"⚠️ [{stock_id}] 財報抓取失敗: {e}")
        return None


# ==========================================
# 3. 獲取目標清單
# ==========================================
def get_targets():
    try:
        sql = "SELECT DISTINCT stock_id FROM daily_price WHERE length(stock_id) = 4"
        df = pd.read_sql(sql, engine)
        return df["stock_id"].tolist()
    except:
        return ["2330", "2317", "2454"]


# ==========================================
# 4. 主程序
# ==========================================
if __name__ == "__main__":
    targets = get_targets()
    print(f"🚀 開始執行全方位財報掃描，目標：{len(targets)} 檔...")

    # 有了 Token，我們可以稍微大膽一點，把延遲時間縮短
    # 如果是付費版 Token，甚至可以設為 0
    # 免費版 Token 建議設為 1.5 ~ 2.5 秒
    delay_min = 1.5
    delay_max = 2.5

    if not FM_TOKEN:
        print("🐢 無 Token 模式：將大幅放慢速度以避免封鎖...")
        delay_min = 4.0
        delay_max = 6.0

    pbar = tqdm(targets)

    try:
        for stock_id in pbar:
            pbar.set_description(f"財報分析 {stock_id}")

            df_fin = fetch_financials_finmind(stock_id)

            if df_fin is not None:
                try:
                    df_fin.to_sql(
                        "financial_reports",
                        engine,
                        if_exists="append",
                        index=False,
                        method="multi",
                        chunksize=500,
                    )
                except:
                    pass

            # 動態調整休息時間
            time.sleep(random.uniform(delay_min, delay_max))

    except KeyboardInterrupt:
        print("\n🛑 收到中斷指令，安全退出。")
    finally:
        engine.dispose()
        print("\n✅ 財報入庫作業完成。")
