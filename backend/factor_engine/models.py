
"""多因子选股框架 — 数据模型"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class ConditionResult:
    """单条条件评判结果"""
    cond_type: str
    passed: bool
    score: float
    max_score: float
    reason: str
    raw_args: list = field(default_factory=list)


@dataclass
class IndicatorResult:
    """单个指标组的评分结果"""
    indicator_id: str
    name: str
    score: float
    max_score: float
    min_score: float
    conditions: list[ConditionResult] = field(default_factory=list)


@dataclass
class FactorGroupResult:
    """因子大类评分结果"""
    group_id: str
    name: str
    weight: float
    raw_score: float
    max_score: float
    min_score: float
    weighted_score: float
    indicators: list[IndicatorResult] = field(default_factory=list)


@dataclass
class StockScore:
    """单只股票的完整评分结果"""
    code: str
    name: str
    total_score: float
    groups: list[FactorGroupResult] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)

    def to_api_dict(self) -> dict:
        """转换为前端可用的 JSON 结构"""
        return {
            "code": self.code,
            "name": self.name,
            "total_score": round(self.total_score, 1),
            "groups": [
                {
                    "id": g.group_id,
                    "name": g.name,
                    "weight": g.weight,
                    "raw_score": round(g.raw_score, 1),
                    "weighted_score": round(g.weighted_score, 1),
                    "max_score": g.max_score,
                    "min_score": g.min_score,
                    "indicators": [
                        {
                            "id": ind.indicator_id,
                            "name": ind.name,
                            "score": round(ind.score, 1),
                            "max_score": ind.max_score,
                            "min_score": ind.min_score,
                            "conditions": [
                                {
                                    "type": c.cond_type,
                                    "passed": c.passed,
                                    "score": round(c.score, 1),
                                    "reason": c.reason,
                                }
                                for c in ind.conditions
                            ],
                        }
                        for ind in g.indicators
                    ],
                }
                for g in self.groups
            ],
            "factors": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.factors.items()
            },
        }


@dataclass
class ScorecardConfig:
    """完整的打分卡配置"""
    version: str = "1.0"
    name: str = "涓婚粯璁ゅ鍥犲瓙閫夎偂"
    description: str = ""
    data_window: int = 60
    groups: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> ScorecardConfig:
        return cls(
            version=d.get("version", "1.0"),
            name=d.get("name", "涓婚粯璁ら厤缃?"),
            description=d.get("description", ""),
            data_window=d.get("data_window", 60),
            groups=d.get("groups", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)
