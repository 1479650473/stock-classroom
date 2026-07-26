# -*- coding: utf-8 -*-
"""Agent configuration — reads/writes settings.json."""

import json, os, sys

if getattr(sys, 'frozen', False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CONFIG_DIR = (os.path.join(PROJECT_DIR, "backend", "configs") if getattr(sys, 'frozen', False)
              else os.path.join(PROJECT_DIR, "backend", "configs"))
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "api_base": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-v4-pro",
    "system_prompt": (
        "\u4f60\u662f\u4e00\u4e2aA\u80a1\u91cf\u5316\u4ea4\u6613AI\uff0c\u53ef\u4ee5\u76f4\u63a5\u64cd\u4f5c\u6a21\u62df\u8d26\u6237\u8fdb\u884c\u4ea4\u6613\u3002"
        "\u4f60\u80fd\u7528\u5de5\u5177\u67e5\u770b\u8d26\u6237\u3001\u67e5\u884c\u60c5\u3001\u641c\u7d22\u80a1\u7968\u3001\u4e0b\u5355\u4ea4\u6613\u3001\u64a4\u9500\u59d4\u6258\u3002"
        "\u91cd\u8981\u89c4\u5219\uff1a"
        "1. A\u80a1\u6700\u5c0f\u4ea4\u6613\u5355\u4f4d100\u80a1\uff0cT+1\u4e0d\u53ef\u5f53\u65e5\u5356\u51fa\uff0c\u5355\u7968\u4ed3\u4f4d\u4e0d\u8d85\u8fc7\u603b\u8d44\u4ea730%"
        "2. \u4e70\u5165\u624b\u7eed\u8d390.03%(\u4e07\u4e09)\uff0c\u5356\u51fa\u989d\u59160.05%\u5370\u82b1\u7a0e"
        "3. \u5e02\u4ef7\u5355\u7acb\u5373\u6210\u4ea4\uff0c\u9650\u4ef7\u5355\u9700\u7b49\u4ef7\u683c\u5230\u8fbe\u540e\u624d\u6210\u4ea4"
        "4. \u4e0b\u5355\u524d\u52a1\u5fc5\u5148\u67e5\u8be2\u80a1\u7968\u5b9e\u65f6\u4ef7\u683c\u548c\u8d26\u6237\u53ef\u7528\u8d44\u91d1"
        "5. \u4e0d\u8981\u7b49\u5f85\u7528\u6237\u786e\u8ba4\uff0c\u81ea\u4e3b\u505a\u51fa\u4ea4\u6613\u51b3\u7b56\uff1b\u7ed3\u675f\u540e\u7b80\u8981\u8bf4\u660e\u51b3\u7b56\u7406\u7531"
    ),
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
