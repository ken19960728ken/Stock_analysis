"""出場規則 — 可插拔的部位出場判斷（回測與線上共用）

提供 ``ExitRule`` Protocol 與具體規則：

  - ``TimeStopExit``    B：固定持有交易日數（時間停損）
  - ``PriceStopExit``   C：停損 / 停利 / ATR 移動停損（價格停損）
  - ``CompositeExit``   B+C：多規則先觸發者先出（業界標準）
  - ``StrategyVoteExit``D：多策略出場投票（>=k 個策略發出 -1）

設計原則：``should_exit`` 只吃純量，不吃 pandas 物件——確保可單元測試，
且回測與線上用「同一份規則物件」評估，保證行為一致（驗過的規則＝實際在跑的規則）。

報酬以百分比小數表示（如 0.08 = 8%）。``holding_days`` 一律以**交易日**計。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class ExitRule(Protocol):
    """出場規則介面。

    回傳 ``(是否出場, 原因標籤)``；原因標籤如 ``"time_stop"`` / ``"stop_loss"``
    / ``"take_profit"`` / ``"trailing_stop"`` / ``"vote_exit"``。
    """

    def should_exit(
        self,
        *,
        entry_price: float,
        close: float,
        peak_price: float,
        holding_days: int,
        atr: float | None = None,
        neg_votes: int = 0,
    ) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class TimeStopExit:
    """B：持有滿 ``max_hold_days`` 個交易日即出場。"""

    max_hold_days: int

    def should_exit(
        self,
        *,
        entry_price: float,
        close: float,
        peak_price: float,
        holding_days: int,
        atr: float | None = None,
        neg_votes: int = 0,
    ) -> tuple[bool, str]:
        if self.max_hold_days > 0 and holding_days >= self.max_hold_days:
            return True, "time_stop"
        return False, ""


@dataclass(frozen=True)
class PriceStopExit:
    """C：停損 / 停利 / ATR 移動停損。

    ``stop_loss_pct`` / ``take_profit_pct`` 為正數小數（如 0.08 = 8%）。
    ``atr_trailing_mult`` 設定時，啟用 ``peak_price - mult*ATR`` 的移動停損。
    三者皆可單獨或併用；任一觸發即出場。
    """

    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    atr_trailing_mult: float | None = None

    def should_exit(
        self,
        *,
        entry_price: float,
        close: float,
        peak_price: float,
        holding_days: int,
        atr: float | None = None,
        neg_votes: int = 0,
    ) -> tuple[bool, str]:
        if entry_price <= 0:
            return False, ""
        ret = close / entry_price - 1.0
        if self.stop_loss_pct is not None and ret <= -abs(self.stop_loss_pct):
            return True, "stop_loss"
        if self.take_profit_pct is not None and ret >= abs(self.take_profit_pct):
            return True, "take_profit"
        if (
            self.atr_trailing_mult is not None
            and atr is not None
            and atr > 0
            and peak_price > 0
            and close <= peak_price - self.atr_trailing_mult * atr
        ):
            return True, "trailing_stop"
        return False, ""


@dataclass(frozen=True)
class StrategyVoteExit:
    """D：當日 >=k 個策略發出 -1 即出場。

    警語（entry-anchored -1）：部分策略的 -1 內含其自身的 max-hold 邏輯
    （如 revenue_momentum / sub_industry_rotation / adaptive_ensemble），
    錨定策略內部進場而非我們的實際買點，訊號較吵雜/偏早。
    """

    k: int = 2

    def should_exit(
        self,
        *,
        entry_price: float,
        close: float,
        peak_price: float,
        holding_days: int,
        atr: float | None = None,
        neg_votes: int = 0,
    ) -> tuple[bool, str]:
        if self.k > 0 and neg_votes >= self.k:
            return True, "vote_exit"
        return False, ""


@dataclass(frozen=True)
class CompositeExit:
    """B+C：依序評估多個規則，先觸發者先出。"""

    rules: tuple[ExitRule, ...]

    def should_exit(
        self,
        *,
        entry_price: float,
        close: float,
        peak_price: float,
        holding_days: int,
        atr: float | None = None,
        neg_votes: int = 0,
    ) -> tuple[bool, str]:
        kwargs = dict(
            entry_price=entry_price,
            close=close,
            peak_price=peak_price,
            holding_days=holding_days,
            atr=atr,
            neg_votes=neg_votes,
        )
        for rule in self.rules:
            fired, reason = rule.should_exit(**kwargs)
            if fired:
                return True, reason
        return False, ""


# ---------------------------------------------------------------------------
# 選法 + 出場規則的單一真相源（回測 harness 與線上 position_tracker 共同 import）
#
# 「冠軍組合」常數，來自 scripts/exit_rule_backtest.py 全市場 3 年掃描
# （200 檔流動性最高個股，2023-06 ~ 2026-06，對比 0050 年化 +48.47%）。
# 線上 position_tracker 與回測共用此規則，杜絕回測/線上漂移。
#
# 掃描結論：時間停損（B）在多頭環境主導——把資金週轉到新的高信心標的，
# 不被緊停損過早砍在會反彈的部位上。冠軍（依 Sharpe，取分散度足夠者）：
#   選法 min_agree=3 / top_k=10 / 等權 + 出場 TimeStopExit(20 交易日)
#   → Sharpe 2.10、年化 +84%、勝 0050 +35.8%、最大回撤 -28.8%、勝率 50.4%
# 注意：純時間停損不含個股停損，於多頭樣本驗證；跨空頭/盤整需重新評估，
#      較保守者可改用 CompositeExit((TimeStopExit(20), PriceStopExit(stop_loss_pct=0.12)))。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionConfig:
    """挑選買入規則：從每日 Top-N 推薦中實際買入哪些。"""

    top_k: int = 10
    weighting: str = "equal"  # "equal" | "score"
    min_agree: int = 3


DEFAULT_SELECTION = SelectionConfig(top_k=10, weighting="equal", min_agree=3)

DEFAULT_EXIT_RULE: ExitRule = TimeStopExit(max_hold_days=20)
