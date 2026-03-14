#!/usr/bin/env python3
"""
從 HiStock 爬取台股次產業分類，輸出到 data/sub_industry_mapping.json

用法:
    uv run python scripts/scrape_sub_industry.py              # 爬取並更新 JSON
    uv run python scripts/scrape_sub_industry.py --dry-run    # 預覽不寫入
    uv run python scripts/scrape_sub_industry.py --diff       # 比較新舊差異

資料來源:
  - 電子次分類: https://histock.tw/global/globalclass.aspx?mid=0&id=XX
  - TWSE 大類:   https://histock.tw/twclass/XXXX

次產業 ID 對照（電子相關）:
  68=DRAM, 69=DRAM模組, 70=IC設計, 71=IC生產, 72=IC封測,
  73=TFT-LCD, 74=Flash模組, 75=主機板, 76=光碟片, 77=光碟機,
  78=光通訊, 79=伺服器, 80=軟體業, 82=導線架, 85=連接器,
  86=機殼, 87=消費性電子, 89=電信設備, 90=電腦系統, 91=電腦週邊,
  92=筆記型電腦, 94=網路設備, 95=資訊通路, 96=資訊服務,
  97=印刷電路板, 99=行動電話, 101=被動元件, 102=電源供應器,
  104=晶圓代工, 105=電信/數據服務, 107=LED

概念股 ID（選用）:
  108=太陽節能, 115=電動車Tesla, 132=5G
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "sub_industry_mapping.json"

# HiStock 電子次分類 → 我們的次產業名稱 + 對應大類（sector）
# 格式: histock_id -> (sector, sub_industry_name)
HISTOCK_SUB_CATEGORIES = {
    # --- 半導體業 ---
    70:  ("半導體業", "IC 設計"),
    71:  ("半導體業", "IC 製造"),
    104: ("半導體業", "晶圓代工"),
    72:  ("半導體業", "IC 封測"),
    68:  ("半導體業", "DRAM"),
    82:  ("半導體業", "導線架"),
    # --- 電子零組件業 ---
    97:  ("電子零組件業", "印刷電路板"),
    101: ("電子零組件業", "被動元件"),
    85:  ("電子零組件業", "連接器"),
    102: ("電子零組件業", "電源供應器"),
    86:  ("電子零組件業", "機殼"),
    # --- 電腦及週邊設備業 ---
    79:  ("電腦及週邊設備業", "伺服器"),
    75:  ("電腦及週邊設備業", "主機板"),
    92:  ("電腦及週邊設備業", "筆記型電腦"),
    90:  ("電腦及週邊設備業", "電腦系統"),
    91:  ("電腦及週邊設備業", "電腦週邊"),
    # --- 光電業 ---
    73:  ("光電業", "TFT-LCD"),
    107: ("光電業", "LED"),
    78:  ("光電業", "光通訊"),
    # --- 通信網路業 ---
    94:  ("通信網路業", "網路設備"),
    89:  ("通信網路業", "電信設備"),
    105: ("通信網路業", "電信/數據服務"),
    99:  ("通信網路業", "行動電話"),
    # --- 資訊服務業 ---
    96:  ("資訊服務業", "資訊服務"),
    80:  ("資訊服務業", "軟體業"),
    # --- 電子通路業 ---
    95:  ("電子通路業", "資訊通路"),
    # --- 其他電子業 ---
    87:  ("其他電子業", "消費性電子"),
    69:  ("其他電子業", "DRAM 模組"),
    74:  ("其他電子業", "Flash 模組"),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def fetch_stock_ids(histock_id: int, retries: int = 3) -> list[str]:
    """從 HiStock 次分類頁面抓取所有股票代碼"""
    url = f"https://histock.tw/global/globalclass.aspx?mid=0&id={histock_id}"

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  [WARN] id={histock_id} 抓取失敗: {e}")
                return []
            time.sleep(2 * (attempt + 1))

    soup = BeautifulSoup(resp.text, "html.parser")

    stock_ids = []

    # 精確解析: 股票代碼在 <span class="... stockno"> 裡面
    # HTML 結構: <ul class="stock-list"> > <li> > <span class="stockno">XXXX</span>
    stock_list = soup.find("ul", class_="stock-list")
    if stock_list:
        for span in stock_list.find_all("span", class_="stockno"):
            code = span.get_text(strip=True)
            if re.match(r"^\d{4,5}$", code):
                stock_ids.append(code)

    # 去重但保留順序
    seen = set()
    unique = []
    for code in stock_ids:
        if code not in seen:
            seen.add(code)
            unique.append(code)

    return sorted(unique)


def build_mapping(dry_run: bool = False) -> dict:
    """爬取所有次分類，組裝成 sub_industry_mapping.json 格式"""
    result: dict[str, dict[str, list[str]]] = {}
    total = len(HISTOCK_SUB_CATEGORIES)

    for i, (hid, (sector, sub_name)) in enumerate(HISTOCK_SUB_CATEGORIES.items(), 1):
        print(f"  [{i}/{total}] 抓取 {sector} / {sub_name} (id={hid}) ...", end=" ")
        stock_ids = fetch_stock_ids(hid)
        print(f"{len(stock_ids)} 檔")

        if not stock_ids:
            continue

        if sector not in result:
            result[sector] = {}
        result[sector][sub_name] = stock_ids

        # 禮貌性延遲
        if i < total:
            time.sleep(1.0)

    # 加入非電子類的靜態分類（這些 HiStock 沒有次分類頁面）
    non_electronic = _get_non_electronic_mapping()
    for sector, subs in non_electronic.items():
        if sector not in result:
            result[sector] = subs
        else:
            # 合併
            for sub_name, ids in subs.items():
                if sub_name not in result[sector]:
                    result[sector][sub_name] = ids

    return result


def _get_non_electronic_mapping() -> dict:
    """非電子類的靜態次產業映射（HiStock 無專門頁面，沿用手動整理）"""
    return {
        "化學工業": {
            "特用化學": ["4763", "1723", "4720", "6509"],
            "塑化原料": ["1326", "1301", "6505"],
            "電子化學": ["4763", "4720", "6509", "3164"],
        },
        "生技醫療業": {
            "新藥研發": ["4743", "6547", "4174", "6446"],
            "醫材/醫療器材": ["4105", "4120", "4137", "6576"],
            "原料藥/學名藥": ["1760", "4746", "1799"],
            "醫美/保健": ["4137", "1795", "6446"],
        },
        "金融保險業": {
            "銀行": ["2880", "2881", "2882", "2884", "2886", "2887", "2891", "2892", "5880"],
            "壽險": ["2823", "2816"],
            "產險": ["2850", "2852"],
            "證券": ["6005", "2855", "6024"],
            "金控": ["2880", "2881", "2882", "2884", "2886", "2887", "2891", "2892"],
        },
        "鋼鐵工業": {
            "鋼鐵": ["2002", "2006", "2014", "2027"],
            "不鏽鋼": ["2010", "2023"],
            "特殊鋼/合金": ["2009", "2020"],
        },
        "食品工業": {
            "食品加工": ["1216", "1227", "1217"],
            "飼料/油脂": ["1215", "1231"],
            "飲料/乳品": ["1234", "1256"],
        },
        "紡織纖維": {
            "成衣/代工": ["1476", "9910", "1477"],
            "機能布/紡紗": ["1434", "1455", "1402"],
        },
        "航運業": {
            "貨櫃航運": ["2603", "2609", "2615"],
            "散裝航運": ["2605", "2606", "2637"],
            "航空": ["2610", "2618"],
        },
        "建材營造業": {
            "營造": ["2501", "2504", "2515"],
            "建設/房地產": ["2520", "2548", "2534", "2542"],
        },
        "汽車工業": {
            "汽車零件": ["2201", "1536", "2231"],
            "整車": ["2201", "2207"],
        },
        "電機機械": {
            "工具機": ["1536", "4510", "4532"],
            "自動化設備": ["2049", "3622", "6271"],
            "馬達/發電機": ["1503", "1504", "1513"],
        },
        "觀光餐旅": {
            "飯店": ["2707", "5703", "2706"],
            "旅行社": ["2731"],
            "餐飲": ["1268", "2727"],
        },
    }


def show_diff(old: dict, new: dict):
    """比較新舊 JSON 差異"""
    old_sectors = set(old.keys())
    new_sectors = set(new.keys())

    added_sectors = new_sectors - old_sectors
    removed_sectors = old_sectors - new_sectors

    if added_sectors:
        print(f"\n新增大類: {', '.join(sorted(added_sectors))}")
    if removed_sectors:
        print(f"\n移除大類: {', '.join(sorted(removed_sectors))}")

    for sector in sorted(old_sectors & new_sectors):
        old_subs = set(old[sector].keys())
        new_subs = set(new[sector].keys())
        added = new_subs - old_subs
        removed = old_subs - new_subs

        if added:
            print(f"\n[{sector}] 新增次產業: {', '.join(sorted(added))}")
        if removed:
            print(f"[{sector}] 移除次產業: {', '.join(sorted(removed))}")

        for sub in sorted(old_subs & new_subs):
            old_ids = set(old[sector][sub])
            new_ids = set(new[sector][sub])
            add_ids = new_ids - old_ids
            rm_ids = old_ids - new_ids
            if add_ids or rm_ids:
                print(f"  [{sector}/{sub}] +{len(add_ids)} -{len(rm_ids)} 檔")
                if add_ids:
                    print(f"    新增: {', '.join(sorted(add_ids))}")
                if rm_ids:
                    print(f"    移除: {', '.join(sorted(rm_ids))}")

    # 統計
    old_total = sum(len(ids) for subs in old.values() for ids in subs.values())
    new_total = sum(len(ids) for subs in new.values() for ids in subs.values())
    old_sub_count = sum(len(subs) for subs in old.values())
    new_sub_count = sum(len(subs) for subs in new.values())
    print(f"\n統計: {len(old)}/{old_sub_count}/{old_total} → "
          f"{len(new)}/{new_sub_count}/{new_total} "
          f"(大類/次產業/股票映射)")


def main():
    parser = argparse.ArgumentParser(description="從 HiStock 爬取台股次產業分類")
    parser.add_argument("--dry-run", action="store_true", help="預覽不寫入")
    parser.add_argument("--diff", action="store_true", help="比較新舊差異")
    args = parser.parse_args()

    print("=== 從 HiStock 爬取台股次產業分類 ===\n")

    mapping = build_mapping(dry_run=args.dry_run)

    # 統計
    total_sectors = len(mapping)
    total_subs = sum(len(subs) for subs in mapping.values())
    total_stocks = sum(len(ids) for subs in mapping.values() for ids in subs.values())
    print(f"\n結果: {total_sectors} 大類 / {total_subs} 次產業 / {total_stocks} 股票映射")

    if args.diff and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)
        print("\n=== 新舊差異 ===")
        show_diff(old, mapping)

    if args.dry_run:
        print("\n[DRY-RUN] 不寫入檔案")
        print(json.dumps(mapping, ensure_ascii=False, indent=2)[:2000] + "\n...")
        return

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"\n已寫入 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
