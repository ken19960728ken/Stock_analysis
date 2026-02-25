"""
機器學習選股引擎 — LightGBM 因子非線性組合
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class MLModelResult:
    model: object = None
    feature_importance: pd.DataFrame = field(default_factory=pd.DataFrame)
    train_metrics: dict = field(default_factory=dict)
    val_metrics: dict = field(default_factory=dict)
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)


def prepare_features(
    price_df: pd.DataFrame,
    per_df: pd.DataFrame = None,
    chip_df: pd.DataFrame = None,
    forward_days: int = 5,
    n_quantiles: int = 3,
) -> tuple:
    """
    準備特徵和標籤

    Parameters:
        price_df: 日K (stock_id, date, open, high, low, close, volume)
        per_df: PER/PBR/殖利率 (可選)
        chip_df: 法人買賣超 (可選)
        forward_days: 前瞻天數
        n_quantiles: 標籤分位數 (3=好/中/差)

    Returns:
        (X, y, meta) - X 是特徵 DataFrame, y 是標籤 Series, meta 含 date/stock_id
    """
    if price_df.empty:
        return pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame()

    price_df = price_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"])
    price_df = price_df.sort_values(["stock_id", "date"])

    features = []
    for sid, grp in price_df.groupby("stock_id"):
        g = grp.copy()
        if len(g) < 60:
            continue

        # 技術面因子
        g["return_5d"] = g["close"].pct_change(5)
        g["return_20d"] = g["close"].pct_change(20)
        g["volatility_20d"] = g["close"].pct_change().rolling(20).std()
        g["volume_ratio"] = g["volume"] / g["volume"].rolling(20).mean()

        # RSI
        delta = g["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        g["rsi"] = 100 - 100 / (1 + rs)

        # MACD histogram
        ema12 = g["close"].ewm(span=12).mean()
        ema26 = g["close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        g["macd_hist"] = macd_line - signal_line

        # MA 斜率
        g["ma20"] = g["close"].rolling(20).mean()
        g["ma20_slope"] = g["ma20"].pct_change(5)

        # Bollinger %B
        g["bb_mid"] = g["close"].rolling(20).mean()
        bb_std = g["close"].rolling(20).std()
        g["bb_upper"] = g["bb_mid"] + 2 * bb_std
        g["bb_lower"] = g["bb_mid"] - 2 * bb_std
        g["bb_pct"] = (g["close"] - g["bb_lower"]) / (g["bb_upper"] - g["bb_lower"]).replace(0, np.nan)

        # 前瞻報酬（標籤）
        g["forward_return"] = g["close"].shift(-forward_days) / g["close"] - 1

        features.append(g)

    if not features:
        return pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame()

    all_data = pd.concat(features, ignore_index=True)

    # 合併基本面因子
    if per_df is not None and not per_df.empty:
        per = per_df.copy()
        per["date"] = pd.to_datetime(per["date"])
        all_data = all_data.merge(per[["stock_id", "date", "per", "pbr", "dividend_yield"]],
                                  on=["stock_id", "date"], how="left")
        for col in ["per", "pbr", "dividend_yield"]:
            if col in all_data.columns:
                all_data[col] = all_data.groupby("stock_id")[col].ffill()

    # 合併籌碼面因子
    if chip_df is not None and not chip_df.empty:
        chip = chip_df.copy()
        chip["date"] = pd.to_datetime(chip["date"])
        buy_cols = [c for c in chip.columns if c.endswith("_buy")]
        sell_cols = [c for c in chip.columns if c.endswith("_sell")]
        if buy_cols and sell_cols:
            chip["institutional_net"] = sum(chip[c] for c in buy_cols) - sum(chip[c] for c in sell_cols)
            all_data = all_data.merge(chip[["stock_id", "date", "institutional_net"]],
                                      on=["stock_id", "date"], how="left")

    # 定義特徵欄位
    feature_cols = [
        "return_5d", "return_20d", "volatility_20d", "volume_ratio",
        "rsi", "macd_hist", "ma20_slope", "bb_pct",
    ]
    if "per" in all_data.columns:
        feature_cols.append("per")
    if "pbr" in all_data.columns:
        feature_cols.append("pbr")
    if "dividend_yield" in all_data.columns:
        feature_cols.append("dividend_yield")
    if "institutional_net" in all_data.columns:
        feature_cols.append("institutional_net")

    # 去除缺失值
    all_data = all_data.dropna(subset=feature_cols + ["forward_return"])
    if all_data.empty:
        return pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame()

    # 標籤：forward_return 分位數
    all_data["label"] = pd.qcut(
        all_data["forward_return"], q=n_quantiles, labels=False, duplicates="drop"
    )

    X = all_data[feature_cols]
    y = all_data["label"]
    meta = all_data[["date", "stock_id", "forward_return"]].reset_index(drop=True)

    return X.reset_index(drop=True), y.reset_index(drop=True), meta


def train_lightgbm(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame = None,
    y_val: pd.Series = None,
    n_splits: int = 5,
) -> MLModelResult:
    """
    訓練 LightGBM 分類模型

    Parameters:
        X_train, y_train: 訓練資料
        X_val, y_val: 驗證資料（可選，若不提供用 TimeSeriesSplit CV）
        n_splits: CV 摺數

    Returns:
        MLModelResult
    """
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import TimeSeriesSplit

    if X_train.empty or y_train.empty:
        return MLModelResult()

    n_classes = y_train.nunique()

    params = {
        "objective": "multiclass" if n_classes > 2 else "binary",
        "num_class": n_classes if n_classes > 2 else 1,
        "metric": "multi_logloss" if n_classes > 2 else "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "n_jobs": -1,
    }

    if X_val is not None and y_val is not None and not X_val.empty:
        # 直接訓練
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        model = lgb.train(
            params, train_data,
            num_boost_round=200,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
        )
        val_pred = model.predict(X_val)
        if n_classes > 2:
            val_pred_label = val_pred.argmax(axis=1)
        else:
            val_pred_label = (val_pred > 0.5).astype(int)

        val_metrics = {
            "accuracy": float(accuracy_score(y_val, val_pred_label)),
            "f1": float(f1_score(y_val, val_pred_label, average="weighted")),
        }
        train_pred = model.predict(X_train)
        if n_classes > 2:
            train_pred_label = train_pred.argmax(axis=1)
        else:
            train_pred_label = (train_pred > 0.5).astype(int)
        train_metrics = {
            "accuracy": float(accuracy_score(y_train, train_pred_label)),
            "f1": float(f1_score(y_train, train_pred_label, average="weighted")),
        }
    else:
        # TimeSeriesSplit CV
        tscv = TimeSeriesSplit(n_splits=n_splits)
        cv_scores = []
        model = None

        for train_idx, val_idx in tscv.split(X_train):
            X_tr = X_train.iloc[train_idx]
            y_tr = y_train.iloc[train_idx]
            X_va = X_train.iloc[val_idx]
            y_va = y_train.iloc[val_idx]

            train_data = lgb.Dataset(X_tr, label=y_tr)
            val_data = lgb.Dataset(X_va, label=y_va, reference=train_data)

            model = lgb.train(
                params, train_data,
                num_boost_round=200,
                valid_sets=[val_data],
                callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
            )

            pred = model.predict(X_va)
            if n_classes > 2:
                pred_label = pred.argmax(axis=1)
            else:
                pred_label = (pred > 0.5).astype(int)

            cv_scores.append({
                "accuracy": float(accuracy_score(y_va, pred_label)),
                "f1": float(f1_score(y_va, pred_label, average="weighted")),
            })

        train_metrics = {
            "accuracy": np.mean([s["accuracy"] for s in cv_scores]),
            "f1": np.mean([s["f1"] for s in cv_scores]),
        }
        val_metrics = train_metrics.copy()

    # 特徵重要性
    importance = model.feature_importance(importance_type="gain")
    feat_imp = pd.DataFrame({
        "feature_name": X_train.columns.tolist(),
        "importance": importance,
    }).sort_values("importance", ascending=False)
    feat_imp["rank"] = range(1, len(feat_imp) + 1)

    return MLModelResult(
        model=model,
        feature_importance=feat_imp,
        train_metrics=train_metrics,
        val_metrics=val_metrics,
    )


def predict_scores(model, X_latest: pd.DataFrame) -> pd.DataFrame:
    """
    對最新截面資料預測

    Returns:
        DataFrame 加上 pred_score 和 pred_label 欄位
    """
    if model is None or X_latest.empty:
        return pd.DataFrame()

    pred = model.predict(X_latest)
    result = X_latest.copy()
    if pred.ndim == 2:
        # 多分類：取最高分類的機率作為 score
        result["pred_score"] = pred[:, -1]  # 最高分位的機率
        result["pred_label"] = pred.argmax(axis=1)
    else:
        result["pred_score"] = pred
        result["pred_label"] = (pred > 0.5).astype(int)

    return result


def walk_forward_backtest(
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    train_window: int = 252,
    step: int = 20,
) -> pd.DataFrame:
    """
    Walk-Forward 回測（滾動訓練 + 預測）

    Returns:
        DataFrame[date, stock_id, pred_score, actual_return]
    """
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score

    if X.empty or y.empty:
        return pd.DataFrame()

    n_classes = y.nunique()
    params = {
        "objective": "multiclass" if n_classes > 2 else "binary",
        "num_class": n_classes if n_classes > 2 else 1,
        "metric": "multi_logloss" if n_classes > 2 else "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "verbose": -1,
        "n_jobs": -1,
    }

    results = []
    n = len(X)

    for start in range(train_window, n - step, step):
        train_end = start
        test_end = min(start + step, n)

        X_train = X.iloc[:train_end]
        y_train = y.iloc[:train_end]
        X_test = X.iloc[train_end:test_end]
        y_test = y.iloc[train_end:test_end]
        test_dates = dates.iloc[train_end:test_end]

        if len(X_train) < 50 or len(X_test) == 0:
            continue

        train_data = lgb.Dataset(X_train, label=y_train)
        model = lgb.train(params, train_data, num_boost_round=100,
                          callbacks=[lgb.log_evaluation(0)])

        pred = model.predict(X_test)
        if pred.ndim == 2:
            pred_score = pred[:, -1]
            pred_label = pred.argmax(axis=1)
        else:
            pred_score = pred
            pred_label = (pred > 0.5).astype(int)

        for i in range(len(X_test)):
            results.append({
                "date": test_dates.iloc[i] if i < len(test_dates) else None,
                "pred_score": float(pred_score[i]),
                "pred_label": int(pred_label[i]),
                "actual_label": int(y_test.iloc[i]),
            })

    return pd.DataFrame(results)
