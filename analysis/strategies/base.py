"""
策略基類 — Strategy Pattern
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class BacktestResult:
    """回測結果"""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    trade_count: int = 0
    avg_holding_days: float = 0.0
    equity_curve: pd.Series = field(default_factory=pd.Series)
    drawdown_curve: pd.Series = field(default_factory=pd.Series)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_returns: pd.Series = field(default_factory=pd.Series)


class Strategy(ABC):
    """策略抽象基類"""

    name: str = "Base Strategy"
    description: str = ""
    params: dict = {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易訊號

        Parameters:
            data: 含 OHLCV 的 DataFrame

        Returns:
            data 加上 'signal' 欄位:
              1 = 買入訊號
             -1 = 賣出訊號
              0 = 無訊號
        """
        pass

    def get_params(self) -> dict:
        """返回策略參數（可供 UI 調整）"""
        return self.params.copy()

    def set_params(self, **kwargs):
        """設定策略參數"""
        for k, v in kwargs.items():
            if k in self.params:
                self.params[k] = v
