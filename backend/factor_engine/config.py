
"""配置加载与校验模块"""
import json
import os

from .models import ScorecardConfig


_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs",
    "default_scorecard.json",
)


#: 可命名的评分卡（selection 的 source 参数用）
SCORECARDS = {
    "default": "default_scorecard.json",
    "smallcap": "smallcap_scorecard.json",     # 小盘动量（规模×历史涨跌幅）
}


def load_config(path: str = None, name: str = None) -> ScorecardConfig:
    """加载 JSON 评分配置文件（name 可用 SCORECARDS 里的别名）。"""
    if name and not path:
        fname = SCORECARDS.get(str(name))
        if fname:
            path = os.path.join(os.path.dirname(_DEFAULT_CONFIG_PATH), fname)
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


#: 预设评分口径。值是「因子组 id → 目标满分(权重)」，缺省不覆盖。
WEIGHT_PRESETS: dict = {
    "default": {},
    # 稳健偏向：把模型的教训（"只买趋势与稳定双达标的均衡股，不追纯趋势腿"）落成评分口径。
    # 稳定性 10 → 30 成为主导，趋势 30 → 18、动量 25 → 15 让位。
    "steady": {"trend": 18, "momentum": 15, "volume": 10, "price": 10, "stability": 30},
}


def resolve_weights(spec) -> dict:
    """把外部传入的权重描述统一成 {组id: 目标满分}。

    支持：预设名（'steady'）、dict、逗号/分号分隔的 "trend:18,momentum:15" 字符串。
    非法输入返回 {}（走默认口径），不抛异常。
    """
    if not spec:
        return {}
    if isinstance(spec, str):
        s = spec.strip()
        if s in WEIGHT_PRESETS:
            return dict(WEIGHT_PRESETS[s])
        out: dict = {}
        for part in s.replace(";", ",").split(","):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            try:
                out[k.strip()] = float(v)
            except ValueError:
                continue
        return out
    if isinstance(spec, dict):
        out = {}
        for k, v in spec.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    return {}


def load_config_with_weights(weights=None, path: str = None) -> ScorecardConfig:
    """加载评分卡并按目标权重改写各因子组。

    实现语义：把某组内**所有条件分值按 s = 目标满分 / 原满分 等比缩放**，同时更新
    该组与指标的上下限（条件 `score`/`max`/`min`、指标级 `max_score`/`min_score`）。

    注意：只缩放 `score` 而不缩放上限会被指标级 clamp 截断（稳定性组条件放大到 21 分
    却仍被指标上限 10 卡住，效果等于「权重没改」），因此上限必须同步缩放。
    """
    w = resolve_weights(weights)
    if not w:
        return load_config(path)
    if path is None:
        path = _DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    for g in raw.get("groups", []):
        gid = str(g.get("id") or "")
        if gid not in w:
            continue
        cur = float(g.get("max_score", g.get("weight", 0)) or 0)
        target = float(w[gid])
        if cur <= 0 or target <= 0:
            continue
        s = target / cur
        for ind in g.get("indicators", []):
            for cond in ind.get("conditions", []):
                for key in ("score", "max", "min"):
                    if key not in cond:
                        continue
                    try:
                        cond[key] = round(float(cond[key]) * s, 2)
                    except (TypeError, ValueError):
                        continue
            for key in ("max_score", "min_score"):
                if ind.get(key) is None:
                    continue
                try:
                    ind[key] = round(float(ind[key]) * s, 2)
                except (TypeError, ValueError):
                    pass
        g["max_score"] = round(target, 2)
        g["weight"] = round(target, 2)
        if g.get("min_score") is not None:
            try:
                g["min_score"] = round(float(g["min_score"]) * s, 2)
            except (TypeError, ValueError):
                pass
    raw["weights_override"] = w
    _validate(raw)
    return ScorecardConfig.from_dict(raw)


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
