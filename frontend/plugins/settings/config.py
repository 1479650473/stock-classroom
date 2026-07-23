# -*- coding: utf-8 -*-
"""Settings load/save for stock-classroom."""

import json, os, sys

if getattr(sys, 'frozen', False):
    PROJECT_DIR = os.path.dirname(sys.executable)
    _APP_DIR = sys._MEIPASS
else:
    _APP_DIR = PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_DIR = os.path.join(PROJECT_DIR, "backend", "configs") if getattr(sys, 'frozen', False) else os.path.join(PROJECT_DIR, "backend", "configs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "font_size": 13,
}


def load_settings():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Merge with defaults for any missing keys
                result = dict(DEFAULTS)
                result.update({k: v for k, v in data.items() if k in DEFAULTS})
                return result
    except Exception:
        pass
    return dict(DEFAULTS)


def save_settings(settings):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
