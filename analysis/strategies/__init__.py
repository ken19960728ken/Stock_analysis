from analysis.strategies.base import Strategy
from analysis.strategies.ma_cross import MACrossStrategy
from analysis.strategies.macd_signal import MACDStrategy
from analysis.strategies.bollinger import BollingerStrategy
from analysis.strategies.rsi_reversal import RSIReversalStrategy
from analysis.strategies.parabolic_sar import ParabolicSARStrategy
from analysis.strategies.heikin_ashi import HeikinAshiStrategy
from analysis.strategies.institutional import InstitutionalStrategy
from analysis.strategies.value_investing import ValueInvestingStrategy
from analysis.strategies.dual_thrust import DualThrustStrategy
from analysis.strategies.multi_factor import MultiFactorStrategy

STRATEGY_MAP = {
    "MA 交叉": MACrossStrategy,
    "MACD 訊號": MACDStrategy,
    "Bollinger 突破": BollingerStrategy,
    "RSI 反轉": RSIReversalStrategy,
    "Parabolic SAR": ParabolicSARStrategy,
    "Heikin-Ashi": HeikinAshiStrategy,
    "法人跟單": InstitutionalStrategy,
    "價值投資": ValueInvestingStrategy,
    "Dual Thrust": DualThrustStrategy,
    "多因子綜合": MultiFactorStrategy,
}
