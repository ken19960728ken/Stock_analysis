import pandas as pd

from core.db import get_engine
from core.logger import setup_logger

logger = setup_logger("stock_list")

FALLBACK_STOCKS = ["2330", "2317", "2454", "2603", "0050"]


def get_all_stocks():
    """
    從 twstock_code 取普通股 + ETF，返回 list of dict：
    [{"stock_id": "2330", "yahoo_symbol": "2330.TW", "name": "台積電", "type": "股票"}, ...]
    """
    sql = """
    SELECT "商品代號", "市場別", "商品名稱", "商品類型"
    FROM twstock_code
    WHERE "CFICode" = 'ESVUFR' OR "商品類型" = 'ETF'
    """
    try:
        df = pd.read_sql(sql, get_engine())
    except Exception as e:
        logger.warning(f"讀取 twstock_code 失敗: {e}，使用預設清單")
        return [{"stock_id": s, "yahoo_symbol": f"{s}.TW", "name": s, "type": "股票"}
                for s in FALLBACK_STOCKS]

    targets = []
    for _, row in df.iterrows():
        code = str(row["商品代號"]).strip()
        market = str(row["市場別"]).strip()

        if "上市" in market:
            yahoo_symbol = f"{code}.TW"
        elif "上櫃" in market:
            yahoo_symbol = f"{code}.TWO"
        else:
            continue

        targets.append({
            "stock_id": code,
            "yahoo_symbol": yahoo_symbol,
            "name": row["商品名稱"],
            "type": row["商品類型"],
        })

    logger.info(f"共鎖定 {len(targets)} 檔標的 (普通股 + ETF)")
    return targets


def get_stock_ids_from_daily_price():
    """從 daily_price 取已有資料的 4 碼 stock_id"""
    sql = "SELECT DISTINCT stock_id FROM daily_price WHERE length(stock_id) = 4"
    try:
        df = pd.read_sql(sql, get_engine())
        ids = df["stock_id"].tolist()
        if ids:
            return ids
    except Exception:
        pass

    logger.warning("無法從 daily_price 取得清單，使用預設清單")
    return FALLBACK_STOCKS
