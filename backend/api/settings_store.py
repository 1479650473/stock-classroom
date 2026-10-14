# -*- coding: utf-8 -*-
"""Read/write backend/configs/settings.json (shared with the desktop app)."""
import json
import os

from .paths import CONFIG_DIR, SETTINGS_PATH

EXAMPLE_PATH = os.path.join(CONFIG_DIR, "settings.example.json")

DEFAULTS = {
    "font_size": 13,
    "theme": "graphite",
    "window_size": "large",
    # ---- 外观维度（2026-10-15 新增）----
    # ⚠️ 这些必须同时存在于 DEFAULTS 与 system.py 的 POST 白名单里：
    #    _deep_merge() 只遍历 DEFAULTS 的键 → 不在 DEFAULTS 里的键会在
    #    load 阶段被**静默丢弃**（即使 POST 白名单放行了也一样存不下来）。
    "density": "comfortable",   # comfortable | compact | roomy
    "radius": "default",        # sharp | default | round
    "motion": "full",           # full | reduced
    "backdrop": "grid",         # grid | plain | none
    "agent": {
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-v4-pro",
    },
}


def _deep_merge(defaults, overrides):
    result = {}
    for k, dv in defaults.items():
        if k in overrides:
            ov = overrides[k]
            if isinstance(dv, dict) and isinstance(ov, dict):
                result[k] = _deep_merge(dv, ov)
            else:
                result[k] = ov
        else:
            result[k] = dict(dv) if isinstance(dv, dict) else dv
    return result


def load_settings():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return _deep_merge(DEFAULTS, json.load(f))
    except Exception:
        pass
    return _deep_merge(DEFAULTS, {})


def save_settings(settings):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    return True
