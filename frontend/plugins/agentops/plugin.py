# -*- coding: utf-8 -*-
"""AgentOps plugin (LEFT) — 模型驱动的 AI 操盘台: agent 自主做研究→决策→下单, 用户旁观."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class AgentOpsPlugin(IPlugin):
    plugin_id = "agentops"
    name = u"AI\u64cd\u76d8"
    icon = u"\u2699"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import AgentOpsPanel
        return AgentOpsPanel()
