# -*- coding: utf-8 -*-
"""Trade plugin — simulated trading panel + profit-curve companion."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class TradePlugin(IPlugin):
    plugin_id = "trade"
    name = "交易"
    icon = "\U0001f4b0"
    region = PluginRegion.LEFT

    def __init__(self):
        super().__init__()
        self._companion = None

    def create_widget(self):
        from .panel import TradePanel
        w = TradePanel()
        w.set_kline_db(self._services.db_path)
        w.on_open_kline = self._services.open_kline
        w.on_status = self._services.status
        w.on_account_changed = self._on_panel_account_changed
        return w

    def create_companion_widget(self):
        if self._companion is None:
            from .companion import TradeCompanion
            self._companion = TradeCompanion()
            self._companion.on_account_changed = self._on_companion_account_changed
            # sync the initial account (the panel's combo is blocked during load)
            if self._widget is not None:
                aid = self._widget.current_account_id()
                if aid is not None:
                    self._companion.set_account(aid)
        return self._companion

    def _on_panel_account_changed(self, aid):
        if self._companion is not None:
            self._companion.set_account(aid)

    def _on_companion_account_changed(self, aid):
        if self._widget is not None:
            self._widget.reload_accounts(aid)

    def on_activate(self):
        if self._widget and hasattr(self._widget, 'refresh'):
            self._widget.refresh()
        # resync the right-side companion with the panel's current account
        if self._companion is not None and self._widget is not None:
            aid = self._widget.current_account_id()
            if aid is not None:
                self._companion.set_account(aid)

    def refresh(self):
        self.on_activate()
