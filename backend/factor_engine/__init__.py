"""多因子选股框架

使用方式:
    from backend.factor_engine import FactorScorer, load_config, list_factors

    scorer = FactorScorer()
    score = scorer.score_stock("600519", "贵州茅台", klines)
    print(scorer.explain(score))
"""

from .scorer import FactorScorer
from .config import load_config, load_config_from_dict, list_configs
from .calculator import FactorCalculator, compute_factors
from .models import StockScore, ScorecardConfig
from .filters import apply_filters, DEFAULT_FILTERS


def list_factors():
    return FactorCalculator.list_factors()


__all__ = [
    "FactorScorer",
    "StockScore",
    "ScorecardConfig",
    "FactorCalculator",
    "load_config",
    "load_config_from_dict",
    "list_configs",
    "list_factors",
    "compute_factors",
    "apply_filters",
    "DEFAULT_FILTERS",
]
