"""
產業分類 Scanner — 兩層產業分類（大類 sector + 次產業 sub_industry）

1. 從 FinMind taiwan_stock_info() 取得 industry_category → 標準化為 sector
2. 讀取 data/sub_industry_mapping.json → 匹配 sub_industry
3. 寫入 industry_classification 表（replace）
4. 同步寫入舊表 industry_mapping（向後相容）
"""

import json
from pathlib import Path

import pandas as pd

from core.constants import normalize_sector
from core.db import get_engine
from core.finmind_client import get_fm_loader
from core.logger import setup_logger

logger = setup_logger("industry_scanner")

# 次產業對照表路徑
_SUB_INDUSTRY_JSON = Path(__file__).resolve().parent.parent / "data" / "sub_industry_mapping.json"


def _load_sub_industry_mapping() -> dict[str, str]:
    """讀取 sub_industry_mapping.json，回傳 {stock_id: sub_industry}"""
    if not _SUB_INDUSTRY_JSON.exists():
        logger.warning(f"次產業對照表不存在: {_SUB_INDUSTRY_JSON}")
        return {}

    try:
        with open(_SUB_INDUSTRY_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"讀取次產業對照表失敗: {e}")
        return {}

    mapping = {}
    for sector, sub_industries in data.items():
        for sub_name, stock_ids in sub_industries.items():
            for sid in stock_ids:
                # 同一股票可能出現在多個次產業（如金控同時在銀行和金控）
                # 取第一個匹配的
                if sid not in mapping:
                    mapping[sid] = sub_name
    return mapping


class IndustryScanner:
    """兩層產業分類掃描：大類 (sector) + 次產業 (sub_industry)"""

    name = "IndustryScanner"

    def scan(self):
        logger.info(f"[{self.name}] 開始取得產業分類資料...")

        # --- 1. 從 FinMind 取得大類 ---
        try:
            loader = get_fm_loader()
            df = loader.taiwan_stock_info()
        except Exception as e:
            logger.error(f"取得 taiwan_stock_info 失敗: {e}")
            return

        if df is None or df.empty:
            logger.warning("taiwan_stock_info 回傳空資料")
            return

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

        # --- 2. 標準化 sector ---
        result["sector"] = result["industry_category"].apply(normalize_sector)

        # --- 3. 匹配 sub_industry ---
        sub_map = _load_sub_industry_mapping()
        if sub_map:
            result["sub_industry"] = result["stock_id"].map(sub_map)
            matched = result["sub_industry"].notna().sum()
            logger.info(f"次產業匹配: {matched}/{len(result)} 筆")
        else:
            result["sub_industry"] = None

        # --- 4. 組裝 industry_classification ---
        classification = result[["stock_id", "sector", "sub_industry"]].copy()
        classification["source"] = "finmind"

        logger.info(f"取得 {len(classification)} 筆產業分類資料 "
                    f"({classification['sector'].nunique()} 大類)")

        # --- 5. 寫入 DB ---
        try:
            engine = get_engine()

            # 寫入新表 industry_classification（全量替換）
            classification.to_sql(
                "industry_classification",
                engine,
                if_exists="replace",
                index=False,
                method="multi",
            )
            logger.info(f"[{self.name}] 成功寫入 {len(classification)} 筆至 industry_classification")

            # 同步寫入舊表 industry_mapping（向後相容）
            legacy = result[["stock_id", "industry_category"]].copy()
            legacy.to_sql(
                "industry_mapping",
                engine,
                if_exists="replace",
                index=False,
                method="multi",
            )
            logger.info(f"[{self.name}] 同步寫入 {len(legacy)} 筆至 industry_mapping（相容）")

        except Exception as e:
            logger.error(f"寫入 DB 失敗: {e}")
            return

        logger.info(f"[{self.name}] 完成。")


if __name__ == "__main__":
    IndustryScanner().scan()
