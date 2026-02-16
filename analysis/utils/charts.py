"""
Plotly 圖表工廠 — K線圖、籌碼圖、基本面圖、經濟指標圖
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def create_candlestick_chart(
    df: pd.DataFrame,
    title: str = "",
    ma_periods: list = None,
    show_volume: bool = True,
    show_bollinger: bool = False,
    show_sar: bool = False,
    heikin_ashi: bool = False,
    indicators: list = None,
    trades: pd.DataFrame = None,
) -> go.Figure:
    """
    建立 K 線圖（含成交量、均線、技術指標子圖）

    Parameters:
        df: 含 date, open, high, low, close, volume 的 DataFrame
        title: 圖表標題
        ma_periods: 要顯示的均線週期，如 [5, 20, 60]
        show_volume: 是否顯示成交量
        show_bollinger: 是否顯示布林通道
        show_sar: 是否顯示 Parabolic SAR
        heikin_ashi: 是否使用 Heikin-Ashi K 線
        indicators: 要顯示的指標子圖列表，如 ["MACD", "RSI", "KD"]
        trades: 交易記錄 DataFrame (含 date, action, price)
    """
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="無資料")
        return fig

    if indicators is None:
        indicators = []

    # 計算子圖數量
    n_subplots = 1  # K 線主圖
    if show_volume:
        n_subplots += 1
    n_subplots += len(indicators)

    # 設定子圖高度比例
    row_heights = [0.5]
    subplot_titles = [title or "K 線圖"]
    if show_volume:
        row_heights.append(0.1)
        subplot_titles.append("成交量")
    for ind in indicators:
        row_heights.append(0.15)
        subplot_titles.append(ind)

    # 正規化高度比例
    total = sum(row_heights)
    row_heights = [h / total for h in row_heights]

    fig = make_subplots(
        rows=n_subplots, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # --- K 線主圖 ---
    if heikin_ashi and "HA_open" in df.columns:
        o, h, l, c = df["HA_open"], df["HA_high"], df["HA_low"], df["HA_close"]
        candle_name = "Heikin-Ashi"
    else:
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        candle_name = "K 線"

    fig.add_trace(
        go.Candlestick(
            x=df["date"], open=o, high=h, low=l, close=c,
            name=candle_name,
            increasing_line_color="#EF5350",
            decreasing_line_color="#26A69A",
            increasing_fillcolor="#EF5350",
            decreasing_fillcolor="#26A69A",
        ),
        row=1, col=1,
    )

    # 均線
    ma_colors = {5: "#FFD54F", 10: "#FF8A65", 20: "#4FC3F7", 60: "#BA68C8", 120: "#AED581", 240: "#FF7043"}
    if ma_periods:
        for p in ma_periods:
            col_name = f"MA{p}"
            if col_name in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["date"], y=df[col_name],
                        mode="lines", name=f"MA{p}",
                        line=dict(width=1, color=ma_colors.get(p, "#FFFFFF")),
                    ),
                    row=1, col=1,
                )

    # Bollinger Bands
    if show_bollinger and "BB_upper" in df.columns:
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["BB_upper"], mode="lines",
                       name="BB Upper", line=dict(width=1, color="#90CAF9", dash="dash")),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["BB_lower"], mode="lines",
                       name="BB Lower", line=dict(width=1, color="#90CAF9", dash="dash"),
                       fill="tonexty", fillcolor="rgba(144,202,249,0.08)"),
            row=1, col=1,
        )

    # Parabolic SAR
    if show_sar and "SAR" in df.columns:
        sar_vals = df["SAR"].dropna()
        fig.add_trace(
            go.Scatter(x=df.loc[sar_vals.index, "date"], y=sar_vals,
                       mode="markers", name="SAR",
                       marker=dict(size=3, color="#FFA726")),
            row=1, col=1,
        )

    # 買賣標記
    if trades is not None and not trades.empty:
        buys = trades[trades["action"] == "buy"]
        sells = trades[trades["action"] == "sell"]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["date"], y=buys["price"],
                    mode="markers", name="買入",
                    marker=dict(symbol="triangle-up", size=12, color="#26A69A",
                                line=dict(width=1, color="white")),
                ),
                row=1, col=1,
            )
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["date"], y=sells["price"],
                    mode="markers", name="賣出",
                    marker=dict(symbol="triangle-down", size=12, color="#EF5350",
                                line=dict(width=1, color="white")),
                ),
                row=1, col=1,
            )

    current_row = 2

    # --- 成交量子圖 ---
    if show_volume and "volume" in df.columns:
        colors = ["#EF5350" if c >= o else "#26A69A"
                  for c, o in zip(df["close"], df["open"])]
        fig.add_trace(
            go.Bar(x=df["date"], y=df["volume"], name="成交量",
                   marker_color=colors, showlegend=False),
            row=current_row, col=1,
        )
        current_row += 1

    # --- 指標子圖 ---
    for ind in indicators:
        if ind == "MACD" and "MACD" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["MACD"], mode="lines",
                           name="MACD", line=dict(color="#4FC3F7", width=1.5)),
                row=current_row, col=1,
            )
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["MACD_signal"], mode="lines",
                           name="Signal", line=dict(color="#FFA726", width=1.5)),
                row=current_row, col=1,
            )
            if "MACD_histogram" in df.columns:
                hist_colors = ["#EF5350" if v >= 0 else "#26A69A"
                               for v in df["MACD_histogram"]]
                fig.add_trace(
                    go.Bar(x=df["date"], y=df["MACD_histogram"], name="MACD Hist",
                           marker_color=hist_colors, showlegend=False),
                    row=current_row, col=1,
                )

        elif ind == "RSI" and "RSI" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["RSI"], mode="lines",
                           name="RSI", line=dict(color="#BA68C8", width=1.5)),
                row=current_row, col=1,
            )
            fig.add_hline(y=70, line_dash="dash", line_color="red",
                          opacity=0.5, row=current_row, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green",
                          opacity=0.5, row=current_row, col=1)

        elif ind == "KD" and "K" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["K"], mode="lines",
                           name="K", line=dict(color="#4FC3F7", width=1.5)),
                row=current_row, col=1,
            )
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["D"], mode="lines",
                           name="D", line=dict(color="#FFA726", width=1.5)),
                row=current_row, col=1,
            )
            fig.add_hline(y=80, line_dash="dash", line_color="red",
                          opacity=0.5, row=current_row, col=1)
            fig.add_hline(y=20, line_dash="dash", line_color="green",
                          opacity=0.5, row=current_row, col=1)

        elif ind == "威廉" and "WilliamsR" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["WilliamsR"], mode="lines",
                           name="Williams %R", line=dict(color="#FF7043", width=1.5)),
                row=current_row, col=1,
            )
            fig.add_hline(y=-20, line_dash="dash", line_color="red",
                          opacity=0.5, row=current_row, col=1)
            fig.add_hline(y=-80, line_dash="dash", line_color="green",
                          opacity=0.5, row=current_row, col=1)

        elif ind == "AO" and "AO" in df.columns:
            ao_colors = ["#26A69A" if v >= 0 else "#EF5350" for v in df["AO"]]
            fig.add_trace(
                go.Bar(x=df["date"], y=df["AO"], name="AO",
                       marker_color=ao_colors, showlegend=False),
                row=current_row, col=1,
            )

        current_row += 1

    # Layout
    fig.update_layout(
        template="plotly_dark",
        height=250 + 200 * n_subplots,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=80, b=30),
    )

    # Hide weekend gaps
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    return fig


def create_chip_chart(
    price_df: pd.DataFrame,
    institutional_df: pd.DataFrame,
    title: str = "籌碼分析",
) -> go.Figure:
    """三大法人買賣超 + 股價雙Y軸"""
    if institutional_df.empty:
        fig = go.Figure()
        fig.update_layout(title="無籌碼資料", template="plotly_dark")
        return fig

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 判斷法人買賣超欄位名稱
    buy_col = None
    for col in institutional_df.columns:
        if "buy" in col.lower() or "買" in col or "Foreign" in col:
            buy_col = col
            break

    if buy_col:
        colors = ["#EF5350" if v >= 0 else "#26A69A" for v in institutional_df[buy_col]]
        fig.add_trace(
            go.Bar(x=institutional_df["date"], y=institutional_df[buy_col],
                   name="法人買賣超", marker_color=colors),
            secondary_y=False,
        )

    if not price_df.empty:
        fig.add_trace(
            go.Scatter(x=price_df["date"], y=price_df["close"],
                       name="收盤價", line=dict(color="#FFD54F", width=2)),
            secondary_y=True,
        )

    fig.update_layout(
        title=title, template="plotly_dark",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="買賣超(張)", secondary_y=False)
    fig.update_yaxes(title_text="股價", secondary_y=True)
    return fig


def create_margin_chart(margin_df: pd.DataFrame, title: str = "融資融券") -> go.Figure:
    """融資融券餘額圖"""
    if margin_df.empty:
        fig = go.Figure()
        fig.update_layout(title="無融資融券資料", template="plotly_dark")
        return fig

    fig = go.Figure()
    for col in margin_df.columns:
        if col in ("date", "stock_id"):
            continue
        fig.add_trace(
            go.Scatter(x=margin_df["date"], y=margin_df[col],
                       mode="lines", name=col)
        )

    fig.update_layout(
        title=title, template="plotly_dark", height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def create_fundamental_chart(
    financial_df: pd.DataFrame,
    revenue_df: pd.DataFrame,
    per_df: pd.DataFrame,
    dividend_df: pd.DataFrame,
) -> dict:
    """建立基本面圖表組 — 返回 dict of figures"""
    figs = {}

    # EPS 季度趨勢 — financial_reports 是 pivot 格式 (type, value)
    if not financial_df.empty and "type" in financial_df.columns and "value" in financial_df.columns:
        eps_data = financial_df[financial_df["type"] == "EarningsPerShare"].copy()
        if not eps_data.empty:
            eps_data["value"] = pd.to_numeric(eps_data["value"], errors="coerce")
            fig = go.Figure()
            fig.add_trace(
                go.Bar(x=eps_data["date"], y=eps_data["value"], name="EPS")
            )
            fig.update_layout(title="EPS 季度趨勢", template="plotly_dark", height=300)
            figs["eps"] = fig

    # 月營收 — 欄位名: revenue, month_revenue_year_on_year
    if not revenue_df.empty and "revenue" in revenue_df.columns:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(x=revenue_df["date"], y=revenue_df["revenue"], name="月營收")
        )
        fig.update_layout(title="月營收趨勢", template="plotly_dark", height=300)
        figs["revenue"] = fig

    # P/E 歷史河流圖 — 欄位名: per
    if not per_df.empty and "per" in per_df.columns:
        vals = pd.to_numeric(per_df["per"], errors="coerce").dropna()
        valid = vals[vals > 0]
        if not valid.empty:
            fig = go.Figure()
            mean_val = valid.mean()
            std_val = valid.std()
            fig.add_trace(
                go.Scatter(x=per_df["date"], y=pd.to_numeric(per_df["per"], errors="coerce"),
                           mode="lines", name="P/E", line=dict(color="#4FC3F7"))
            )
            fig.add_hline(y=mean_val, line_dash="dash", line_color="white",
                          annotation_text=f"均值 {mean_val:.1f}")
            fig.add_hline(y=mean_val + std_val, line_dash="dot", line_color="red",
                          annotation_text="偏高")
            fig.add_hline(y=mean_val - std_val, line_dash="dot", line_color="green",
                          annotation_text="偏低")
            fig.update_layout(title="P/E 歷史河流圖", template="plotly_dark", height=300)
            figs["per"] = fig

    # 股利紀錄 — 欄位名: dividend
    if not dividend_df.empty and "dividend" in dividend_df.columns:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(x=dividend_df["date"], y=dividend_df["dividend"], name="股利")
        )
        fig.update_layout(title="股利歷史", template="plotly_dark", height=300)
        figs["dividend"] = fig

    return figs


def create_equity_curve(
    equity: pd.Series,
    benchmark: pd.Series = None,
    drawdown: pd.Series = None,
    title: str = "權益曲線",
) -> go.Figure:
    """權益曲線 + 回撤"""
    n_rows = 2 if drawdown is not None else 1
    row_heights = [0.7, 0.3] if n_rows == 2 else [1.0]

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=row_heights,
        subplot_titles=[title, "回撤"] if n_rows == 2 else [title],
    )

    fig.add_trace(
        go.Scatter(x=equity.index, y=equity.values, name="策略",
                   line=dict(color="#4FC3F7", width=2)),
        row=1, col=1,
    )

    if benchmark is not None:
        fig.add_trace(
            go.Scatter(x=benchmark.index, y=benchmark.values, name="大盤",
                       line=dict(color="#BDBDBD", width=1.5, dash="dash")),
            row=1, col=1,
        )

    if drawdown is not None:
        fig.add_trace(
            go.Scatter(x=drawdown.index, y=drawdown.values, name="回撤",
                       fill="tozeroy", fillcolor="rgba(239,83,80,0.3)",
                       line=dict(color="#EF5350", width=1)),
            row=2, col=1,
        )

    fig.update_layout(
        template="plotly_dark", height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def create_monthly_heatmap(monthly_returns: pd.Series, title: str = "月報酬率") -> go.Figure:
    """月報酬率熱力圖 (年 x 月)"""
    if monthly_returns.empty:
        fig = go.Figure()
        fig.update_layout(title="無資料", template="plotly_dark")
        return fig

    idx = monthly_returns.index
    if hasattr(idx, "to_timestamp"):
        idx = idx.to_timestamp()
    years = [d.year for d in idx]
    months = [d.month for d in idx]

    pivot_data = pd.DataFrame({
        "year": years, "month": months, "return": monthly_returns.values
    })
    pivot = pivot_data.pivot_table(index="year", columns="month", values="return")

    month_labels = ["1月", "2月", "3月", "4月", "5月", "6月",
                    "7月", "8月", "9月", "10月", "11月", "12月"]

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=month_labels[:pivot.shape[1]],
        y=[str(y) for y in pivot.index],
        colorscale=[[0, "#EF5350"], [0.5, "#424242"], [1, "#26A69A"]],
        zmid=0,
        text=np.round(pivot.values * 100, 1),
        texttemplate="%{text}%",
        textfont={"size": 10},
    ))

    fig.update_layout(
        title=title, template="plotly_dark", height=300,
        xaxis_title="月份", yaxis_title="年度",
    )
    return fig


def create_correlation_heatmap(corr_matrix: pd.DataFrame, title: str = "相關性矩陣") -> go.Figure:
    """相關性矩陣熱力圖"""
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.index,
        colorscale="RdBu_r",
        zmid=0,
        text=np.round(corr_matrix.values, 2),
        texttemplate="%{text}",
        textfont={"size": 10},
    ))
    fig.update_layout(title=title, template="plotly_dark", height=500)
    return fig


def create_treemap(data: pd.DataFrame, labels_col: str, values_col: str,
                   colors_col: str, title: str = "") -> go.Figure:
    """市值 Treemap"""
    if data.empty:
        fig = go.Figure()
        fig.update_layout(title="無資料", template="plotly_dark")
        return fig

    fig = go.Figure(go.Treemap(
        labels=data[labels_col],
        parents=[""] * len(data),
        values=data[values_col],
        marker=dict(
            colors=data[colors_col],
            colorscale=[[0, "#EF5350"], [0.5, "#424242"], [1, "#26A69A"]],
            cmid=0,
        ),
        texttemplate="<b>%{label}</b><br>%{customdata[0]:.1f}%",
        customdata=data[[colors_col]].values,
    ))
    fig.update_layout(title=title, template="plotly_dark", height=600)
    return fig


def create_economic_indicator_chart(
    data: pd.DataFrame,
    indicator_config: dict,
    height: int = 350,
) -> go.Figure:
    """通用經濟指標折線圖

    Parameters:
        data: 含 date, value 的 DataFrame
        indicator_config: FRED_INDICATORS 中的單一指標 dict (name, unit, ...)
        height: 圖表高度
    """
    if data.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{indicator_config.get('name', '')} — 無資料", template="plotly_dark", height=height)
        return fig

    name = indicator_config.get("name", "")
    unit = indicator_config.get("unit", "")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["value"],
        mode="lines", name=name,
        line=dict(color="#4FC3F7", width=2),
        fill="tozeroy", fillcolor="rgba(79,195,247,0.1)",
    ))
    fig.update_layout(
        title=name,
        yaxis_title=unit,
        template="plotly_dark",
        height=height,
        margin=dict(l=50, r=20, t=40, b=30),
    )
    return fig


def create_yield_spread_chart(
    df_10y: pd.DataFrame,
    df_2y: pd.DataFrame,
    height: int = 450,
) -> go.Figure:
    """公債殖利率 + 利差圖（利差反轉區間以紅色 bar 標記）"""
    if df_10y.empty and df_2y.empty:
        fig = go.Figure()
        fig.update_layout(title="殖利率曲線 — 無資料", template="plotly_dark", height=height)
        return fig

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=["美國公債殖利率", "10Y - 2Y 利差"],
    )

    # 10Y
    if not df_10y.empty:
        fig.add_trace(go.Scatter(
            x=df_10y["date"], y=df_10y["value"],
            mode="lines", name="10Y",
            line=dict(color="#4FC3F7", width=1.5),
        ), row=1, col=1)

    # 2Y
    if not df_2y.empty:
        fig.add_trace(go.Scatter(
            x=df_2y["date"], y=df_2y["value"],
            mode="lines", name="2Y",
            line=dict(color="#FFA726", width=1.5),
        ), row=1, col=1)

    # Spread
    if not df_10y.empty and not df_2y.empty:
        merged = pd.merge(
            df_10y.rename(columns={"value": "y10"}),
            df_2y.rename(columns={"value": "y2"}),
            on="date", how="inner",
        )
        if not merged.empty:
            merged["spread"] = merged["y10"] - merged["y2"]
            colors = ["#EF5350" if s < 0 else "#26A69A" for s in merged["spread"]]
            fig.add_trace(go.Bar(
                x=merged["date"], y=merged["spread"],
                name="利差", marker_color=colors,
                showlegend=False,
            ), row=2, col=1)
            fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5, row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=60, b=30),
    )
    fig.update_yaxes(title_text="%", row=1, col=1)
    fig.update_yaxes(title_text="利差 (%)", row=2, col=1)
    return fig
