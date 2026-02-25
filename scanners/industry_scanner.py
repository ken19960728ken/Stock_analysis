"""
產業分類 Scanner — 從 FinMind 取得 taiwan_stock_info 的 industry_category
寫入 DB 表 industry_mapping（stock_id, industry_category）
"""

import pandas as pd

from core.db import get_engine, save_to_db
from core.finmind_client import get_fm_loader
from core.logger import setup_logger

logger = setup_logger("industry_scanner")


class IndustryScanner:
    """一次性掃描：取得全市場產業分類並寫入 DB"""

    name = "IndustryScanner"

    def scan(self):
        logger.info(f"[{self.name}] 開始取得產業分類資料...")

        try:
            loader = get_fm_loader()
            df = loader.taiwan_stock_info()
        except Exception as e:
            logger.error(f"取得 taiwan_stock_info 失敗: {e}")
            return

        if df is None or df.empty:
            logger.warning("taiwan_stock_info 回傳空資料")
            return

        # 篩選有 industry_category 的記錄
        col_map = {}
        if "stock_id" in df.columns:
            col_map["stock_id"] = "stock_id"
        elif "industry_category" in df.columns:
            pass  # stock_id must exist

        if "industry_category" not in df.columns:
            logger.error(f"資料缺少 industry_category 欄位，可用欄位: {df.columns.tolist()}")
            return

        result = df[["stock_id", "industry_category"]].copy()
        result = result.dropna(subset=["industry_category"])
        result = result[result["industry_category"].str.strip() != ""]
        result = result.drop_duplicates(subset=["stock_id"])

        if result.empty:
            logger.warning("過濾後無有效產業分類資料")
            return

        logger.info(f"取得 {len(result)} 筆產業分類資料")

        # 寫入 DB（先清空再寫入，因為是全量更新）
        try:
            engine = get_engine()
            result.to_sql(
                "industry_mapping",
                engine,
                if_exists="replace",
                index=False,
                method="multi",
            )
            logger.info(f"[{self.name}] 成功寫入 {len(result)} 筆至 industry_mapping")
        except Exception as e:
            logger.error(f"寫入 DB 失敗: {e}")
            return

        logger.info(f"[{self.name}] 完成。")


if __name__ == "__main__":
    IndustryScanner().scan()
