# -*- coding: utf-8 -*-
"""Search plugin — top bar stock search."""

import sqlite3
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit

from frontend.platform.plugin_base import IPlugin, PluginRegion
from frontend.platform.theme import (
    dp, dps, fs, C_RAISED, C_TEXT, C_BORDER, C_ACCENT)


class SearchPlugin(IPlugin):
    plugin_id = "search"
    name = "搜索"
    icon = "\U0001f50e"
    region = PluginRegion.TOPBAR

    def create_widget(self):
        w = QLineEdit()
        w.setPlaceholderText("输入代码或名称搜索")
        w.setFixedSize(dp(300), dp(30))
        w.setStyleSheet(
            f"QLineEdit{{background:{C_RAISED};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(15)};padding:4px 16px;font-size:{fs(13)}}}"
            f"QLineEdit:focus{{border-color:{C_ACCENT};}}")
        w.returnPressed.connect(self._on_search)
        return w

    def _on_search(self):
        text = self._widget.text().strip()
        if not text:
            return
        try:
            conn = sqlite3.connect(self._services.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT code, name FROM stock_list
                WHERE code LIKE ? OR name LIKE ?
                ORDER BY
                    CASE WHEN code=? THEN 0 WHEN code LIKE ? THEN 1 ELSE 2 END,
                    LENGTH(code), code
                LIMIT 1
            """, (f'%{text}%', f'%{text}%', text, f'{text}%'))
            row = cur.fetchone()
            conn.close()
            if row:
                self._widget.setText(f'{row[1]} ({row[0]})')
                self._services.open_kline(row[0], row[1])
            else:
                self._services.status(f"未找到: {text}")
        except Exception as e:
            self._services.status(f"搜索失败: {e}")
