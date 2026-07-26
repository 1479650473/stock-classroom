# -*- coding: utf-8 -*-
"""Backtest training plugin — placeholder, under external development."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class TrainerPlugin(IPlugin):
    plugin_id = "trainer"
    name = "\u56de\u6d4b\u8bad\u7ec3"
    icon = "\U0001f4ca"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import TrainerPlaceholder
        return TrainerPlaceholder()

    def create_companion_widget(self):
        return None

    def on_activate(self):
        pass
