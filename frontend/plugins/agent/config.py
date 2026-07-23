# -*- coding: utf-8 -*-
"""Agent configuration — reads/writes settings.json."""

import json, os, sys

if getattr(sys, 'frozen', False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CONFIG_DIR = os.path.join(PROJECT_DIR, "backend", "configs") if getattr(sys, 'frozen', False) else os.path.join(PROJECT_DIR, "backend", "configs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "api_base": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-v4-pro",
    "system_prompt": u"你是一个专业的A股智能助手，可以帮助用户解答股票相关问题。请用简洁专业的中文回答。",
}


def load_agent_config():
    result = dict(DEFAULTS)
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            agent_cfg = data.get("agent", {})
            if isinstance(agent_cfg, dict):
                result.update({k: v for k, v in agent_cfg.items() if k in DEFAULTS})
    except Exception:
        pass
    return result


def save_agent_config(config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        full_data = {}
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                full_data = json.load(f)
        full_data["agent"] = config
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
