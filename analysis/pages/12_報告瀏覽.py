"""
Page 12: 報告瀏覽 — 瀏覽 reports/ 目錄下的各類報告
"""

import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REPORTS_DIR = Path(ROOT) / "reports"

# --- 報告類型常數 ---
TYPE_DAILY_PICK = "daily_pick"
TYPE_FULL_SCAN = "full_scan"
TYPE_VALUE_INVESTING = "value_investing"
TYPE_OTHER = "other"

TYPE_LABELS = {
    TYPE_DAILY_PICK: "每日選股",
    TYPE_FULL_SCAN: "策略掃描",
    TYPE_VALUE_INVESTING: "價值投資",
    TYPE_OTHER: "其他",
}


def _extract_date(name: str) -> str:
    """從檔名中提取日期字串，用於排序。"""
    # 匹配 YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    # 匹配 YYYYMMDD
    m = re.search(r"(\d{4})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "0000-00-00"


@st.cache_data(ttl=60)
def scan_reports() -> list[dict]:
    """掃描 reports/ 目錄，回傳報告清單（按日期倒序）。"""
    if not REPORTS_DIR.exists():
        return []

    reports = []

    for entry in REPORTS_DIR.iterdir():
        name = entry.name

        # full_scan 資料夾
        if entry.is_dir() and name.startswith("full_scan_"):
            main_md = entry / "full_scan_report.md"
            if main_md.exists():
                reports.append({
                    "type": TYPE_FULL_SCAN,
                    "name": name,
                    "path": str(entry),
                    "date": _extract_date(name),
                })
            continue

        if not entry.is_file():
            continue

        suffix = entry.suffix.lower()
        if suffix not in (".md", ".csv", ".html", ".txt"):
            continue

        if name.startswith("daily_pick_"):
            rtype = TYPE_DAILY_PICK
        elif "value_investing" in name:
            rtype = TYPE_VALUE_INVESTING
        else:
            rtype = TYPE_OTHER

        reports.append({
            "type": rtype,
            "name": name,
            "path": str(entry),
            "date": _extract_date(name),
        })

    reports.sort(key=lambda r: r["date"], reverse=True)
    return reports


def render_markdown_report(filepath: str):
    """渲染 Markdown 報告。"""
    content = Path(filepath).read_text(encoding="utf-8")
    st.markdown(content, unsafe_allow_html=True)
    st.download_button(
        label="下載 Markdown",
        data=content,
        file_name=Path(filepath).name,
        mime="text/markdown",
    )


def render_csv_report(filepath: str):
    """渲染 CSV 報告為互動表格。"""
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        st.error(f"讀取 CSV 失敗：{e}")
        return

    st.dataframe(df, use_container_width=True)

    csv_bytes = Path(filepath).read_bytes()
    st.download_button(
        label="下載 CSV",
        data=csv_bytes,
        file_name=Path(filepath).name,
        mime="text/csv",
    )


def render_text_report(filepath: str):
    """渲染純文字報告。"""
    content = Path(filepath).read_text(encoding="utf-8")
    st.code(content, language=None)
    st.download_button(
        label="下載檔案",
        data=content,
        file_name=Path(filepath).name,
        mime="text/plain",
    )


def render_full_scan(dirpath: str):
    """渲染 full_scan 資料夾：主報告 + 各策略 CSV tabs。"""
    scan_dir = Path(dirpath)

    # 主報告
    main_md = scan_dir / "full_scan_report.md"
    if main_md.exists():
        content = main_md.read_text(encoding="utf-8")
        st.markdown(content, unsafe_allow_html=True)
        st.download_button(
            label="下載主報告",
            data=content,
            file_name=main_md.name,
            mime="text/markdown",
        )

    # 策略 CSV
    csv_files = sorted(scan_dir.glob("strategy_*.csv"))
    if not csv_files:
        return

    st.divider()
    st.subheader("各策略詳細結果")

    tab_names = [f.stem.replace("strategy_", "") for f in csv_files]
    tabs = st.tabs(tab_names)
    for tab, csv_file in zip(tabs, csv_files):
        with tab:
            try:
                df = pd.read_csv(csv_file)
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    label=f"下載 {csv_file.name}",
                    data=csv_file.read_bytes(),
                    file_name=csv_file.name,
                    mime="text/csv",
                    key=f"dl_{csv_file.name}",
                )
            except Exception as e:
                st.error(f"讀取 {csv_file.name} 失敗：{e}")


def render_report(report: dict):
    """根據報告類型分派渲染。"""
    filepath = report["path"]

    if report["type"] == TYPE_FULL_SCAN:
        render_full_scan(filepath)
        return

    suffix = Path(filepath).suffix.lower()
    if suffix == ".md":
        render_markdown_report(filepath)
    elif suffix == ".csv":
        render_csv_report(filepath)
    else:
        render_text_report(filepath)


# ===== 頁面主體 =====
st.set_page_config(page_title="報告瀏覽", page_icon="📋", layout="wide")
st.title("📋 報告瀏覽")

# --- Sidebar ---
with st.sidebar:
    st.header("篩選條件")

    type_options = ["全部", "每日選股", "策略掃描", "價值投資", "其他"]
    type_filter = st.radio("報告類型", type_options, index=0)

    if st.button("🔄 重新整理"):
        scan_reports.clear()
        st.rerun()

all_reports = scan_reports()

if not all_reports:
    st.info("reports/ 目錄下沒有找到任何報告。請先執行選股或回測產生報告。")
    st.stop()

# 過濾
type_key_map = {
    "全部": None,
    "每日選股": TYPE_DAILY_PICK,
    "策略掃描": TYPE_FULL_SCAN,
    "價值投資": TYPE_VALUE_INVESTING,
    "其他": TYPE_OTHER,
}
filter_key = type_key_map[type_filter]
filtered = [r for r in all_reports if filter_key is None or r["type"] == filter_key]

if not filtered:
    st.warning(f"沒有找到「{type_filter}」類型的報告。")
    st.stop()

# 報告選擇下拉
with st.sidebar:
    report_labels = [
        f"[{TYPE_LABELS.get(r['type'], r['type'])}] {r['name']}"
        for r in filtered
    ]
    selected_idx = st.selectbox(
        "選擇報告",
        range(len(report_labels)),
        format_func=lambda i: report_labels[i],
    )

selected = filtered[selected_idx]

# 顯示報告資訊
st.caption(f"類型：{TYPE_LABELS.get(selected['type'], selected['type'])}　|　"
           f"日期：{selected['date']}　|　路徑：{selected['path']}")

st.divider()

# 渲染報告
render_report(selected)
