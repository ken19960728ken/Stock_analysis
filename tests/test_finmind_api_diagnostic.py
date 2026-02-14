"""
FinMind API 診斷測試

直接呼叫 FinMind REST API（繞過 SDK），記錄完整 response，歸納失敗類型。
標記為 @pytest.mark.api，預設不執行，需 -m api 才跑。

執行方式:
    uv run pytest tests/test_finmind_api_diagnostic.py -v -m api -s
"""
import json
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.finmindtrade.com/api/v4/data"


@pytest.mark.api
class TestFinMindAPIDiagnostic:
    """直接呼叫 FinMind REST API 診斷各 dataset 的回應"""

    DATASETS = [
        ("TaiwanStockFinancialStatements", "financial_reports"),
        ("TaiwanStockBalanceSheet", "financial_reports"),
        ("TaiwanStockInstitutionalInvestorsBuySell", "chip_institutional"),
        ("TaiwanStockMarginPurchaseShortSale", "chip_margin"),
        ("TaiwanStockShareholding", "chip_shareholding"),
        ("TaiwanStockHoldingSharesPer", "chip_holding_pct"),
        ("TaiwanStockSecuritiesLending", "chip_securities_lending"),
        ("TaiwanDailyShortSaleBalances", "chip_short_sale"),
        ("TaiwanStockMonthRevenue", "month_revenue"),
        ("TaiwanStockPER", "stock_per"),
        ("TaiwanStockMarketValue", "market_value"),
    ]

    STOCK_IDS = ["2330", "0050", "2888", "00878", "9958"]

    def test_dataset_responses(self):
        """測試每個 dataset + stock 的 API 回應，記錄到 logs/api_diagnostic.json"""
        token = os.getenv("FINMIND_TOKEN", "")
        params_base = {"start_date": "2024-01-01"}
        if token:
            params_base["token"] = token

        results = []
        for dataset_name, table_name in self.DATASETS:
            for stock_id in self.STOCK_IDS:
                params = {
                    **params_base,
                    "dataset": dataset_name,
                    "data_id": stock_id,
                }
                try:
                    resp = requests.get(API_URL, params=params, timeout=30)
                    body = resp.json()
                except Exception as e:
                    results.append({
                        "dataset": dataset_name,
                        "table_name": table_name,
                        "stock_id": stock_id,
                        "error": str(e),
                    })
                    continue

                result = {
                    "dataset": dataset_name,
                    "table_name": table_name,
                    "stock_id": stock_id,
                    "status_code": resp.status_code,
                    "has_data_key": "data" in body,
                    "data_count": len(body.get("data", [])),
                    "response_keys": list(body.keys()),
                    "msg": body.get("msg", ""),
                    "status": body.get("status", ""),
                }
                if not body.get("data"):
                    result["full_response"] = body
                results.append(result)

        # 寫入 logs/api_diagnostic.json
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        output_path = os.path.join(log_dir, "api_diagnostic.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n診斷結果已寫入: {output_path}")

        # 歸納失敗類型
        failures = [
            r for r in results
            if r.get("error") or not r.get("has_data_key") or r.get("data_count", 0) == 0
        ]

        # 成功 / 失敗統計
        success_count = len(results) - len(failures)
        print(f"\n=== 診斷摘要 ===")
        print(f"  總測試: {len(results)} 筆")
        print(f"  成功:   {success_count} 筆")
        print(f"  失敗:   {len(failures)} 筆")

        if failures:
            failure_types = {}
            for f in failures:
                if "error" in f:
                    key = ("error", f["error"], "")
                else:
                    key = (f.get("status_code", "?"), f.get("msg", ""), f.get("status", ""))
                failure_types.setdefault(key, []).append(
                    f"{f['dataset']}+{f['stock_id']}"
                )

            print(f"\n=== 失敗類型歸納 ===")
            for (code, msg, status), items in failure_types.items():
                print(f"  HTTP {code} | msg={msg} | status={status}")
                preview = ", ".join(items[:5])
                suffix = "..." if len(items) > 5 else ""
                print(f"    影響: {len(items)} 筆 ({preview}{suffix})")
