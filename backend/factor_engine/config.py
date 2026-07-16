
"""配置加载与校验模块"""
import json
import os

from .models import ScorecardConfig


_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs",
    "default_scorecard.json",
)


def load_config(path: str = None) -> ScorecardConfig:
    """加载 JSON 评分配置文件"""
    if path is None:
        path = _DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"评分配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    _validate(raw)
    return ScorecardConfig.from_dict(raw)


def load_config_from_dict(d: dict) -> ScorecardConfig:
    """从字典加载评分配置"""
    _validate(d)
    return ScorecardConfig.from_dict(d)


def _validate(raw: dict):
    """基础结构校验"""
    if "groups" not in raw:
        raise ValueError("配置缺少 'groups' 字段")
    total_weight = 0
    for g in raw["groups"]:
        if "id" not in g:
            raise ValueError(f"因子组缺少 'id': {g}")
        weight = g.get("weight", 0)
        total_weight += weight
        if "indicators" not in g:
            raise ValueError(f"因子组 '{g['id']}' 缺少 'indicators'")
        for ind in g["indicators"]:
            if "conditions" not in ind:
                raise ValueError(f"指标 '{ind.get('id', '?')}' 缺少 'conditions'")
            for cond in ind["conditions"]:
                if "type" not in cond:
                    raise ValueError(f"条件缺少 'type': {cond}")
    # 允许权重和不等于100（前端可调），但要给警告
    if total_weight > 100:
        import warnings
        warnings.warn(f"因子权重总和 {total_weight}%，建议调整至100%以内")


def list_configs(config_dir: str = None) -> list[dict]:
    """列出 configs 目录下的所有可用配置"""
    if config_dir is None:
        config_dir = os.path.dirname(_DEFAULT_CONFIG_PATH)
    if not os.path.exists(config_dir):
        return []
    configs = []
    for fname in sorted(os.listdir(config_dir)):
        if fname.endswith(".json"):
            path = os.path.join(config_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                configs.append({
                    "file": fname,
                    "name": raw.get("name", fname),
                    "version": raw.get("version", "?"),
                    "groups": len(raw.get("groups", [])),
                })
            except Exception:
                configs.append({"file": fname, "name": fname, "version": "?", "error": True})
    return configs
