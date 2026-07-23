# -*- coding: utf-8 -*-
"""Settings load/save for stock-classroom."""

import json, os, sys

if getattr(sys, 'frozen', False):
    PROJECT_DIR = os.path.dirname(sys.executable)
    _APP_DIR = sys._MEIPASS
else:
    _APP_DIR = PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CONFIG_DIR = os.path.join(PROJECT_DIR, "backend", "configs") if getattr(sys, 'frozen', False) else os.path.join(PROJECT_DIR, "backend", "configs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "font_size": 13,
    "agent": {
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-v4-pro",
    },
}


def _deep_merge(defaults, overrides):
    """Merge overrides into defaults dict recursively, keeping only keys in defaults."""
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
                data = json.load(f)
            return _deep_merge(DEFAULTS, data)
    except Exception:
        pass
    return _deep_merge(DEFAULTS, {})


def save_settings(settings):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
