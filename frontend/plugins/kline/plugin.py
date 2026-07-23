# -*- coding: utf-8 -*-
"""K-line plugin — chart display with search bar + indicator toggle."""

import sqlite3, traceback, sys, os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
)

from frontend.platform.plugin_base import IPlugin, PluginRegion
from frontend.platform.local_worker import LocalWorker


# Ensure backend/ is importable for data_manager + indicators
_bd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "backend")
if _bd not in sys.path:
    sys.path.insert(0, _bd)


class KlinePlugin(IPlugin):
    plugin_id = "kline"
    name = "K\u7ebf"
    icon = "\U0001f4c8"
    region = PluginRegion.RIGHT

    def set_services(self, services):
        super().set_services(services)
        services.bus.open_kline.connect(self._on_open_kline)

    def create_widget(self):
        container = QWidget()
        lo = QVBoxLayout(container)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)

        # ── Toolbar: search + indicators ──
        k_bar = QHBoxLayout()
        k_bar.setSpacing(8)

        self._k_search = QLineEdit()
        self._k_search.setPlaceholderText("搜索股票代码或名称")
        self._k_search.setStyleSheet(
            "QLineEdit{background:#161B22;color:#E6EDF3;border:1px solid #30363D;"
            "border-radius:6px;padding:5px 12px;font-size:12px;}"
            "QLineEdit:focus{border-color:#D4A574;}")
        self._k_search.returnPressed.connect(self._search_stock)
        k_bar.addWidget(self._k_search, 1)

        k_bar.addWidget(QLabel("指标", styleSheet="color:#8B949E;font-size:12px;font-weight:500;"))

        self._btn_macd = QPushButton("MACD")
        self._btn_macd.setObjectName("indBtn")
        self._btn_macd.setCheckable(True)
        self._btn_macd.setChecked(True)
        self._btn_macd.setFixedHeight(26)
        self._btn_macd.clicked.connect(lambda: self._switch_indicator("macd"))

        self._btn_rsi = QPushButton("RSI")
        self._btn_rsi.setObjectName("indBtn")
        self._btn_rsi.setCheckable(True)
        self._btn_rsi.setFixedHeight(26)
        self._btn_rsi.clicked.connect(lambda: self._switch_indicator("rsi"))

        k_bar.addWidget(self._btn_macd)
        k_bar.addWidget(self._btn_rsi)
        k_bar.addStretch()
        lo.addLayout(k_bar)

        # ── Chart ──
        from .widget import KlineWidget as KlineChart
        self._chart = KlineChart()
        lo.addWidget(self._chart)

        return container

    def _switch_indicator(self, ind_type):
        self._chart.switch_indicator(ind_type)
        self._btn_macd.setChecked(ind_type == "macd")
        self._btn_rsi.setChecked(ind_type == "rsi")

    def _search_stock(self):
        text = self._k_search.text().strip()
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
                self._k_search.setText(f'{row[1]} ({row[0]})')
                self._on_open_kline(row[0], row[1])
            else:
                self._services.status(f"未找到: {text}")
        except Exception as e:
            self._services.status(f"搜索失败: {e}")

    def _on_open_kline(self, code, name):
        try:
            self._k_search.setText(f'{name} ({code})')
            self._services.status(f"加载 {name}({code}) K线...")

            def _load_kline(c):
                from data_manager import get_kline_data
                from indicators import enrich_kline
                kd = get_kline_data(c, 180)
                if not kd:
                    return {"code": -1, "error": "无数据"}
                enriched = enrich_kline(kd)
                return {"code": 0, "data": enriched}

            self._kline_worker = LocalWorker(_load_kline, "kline", args=[code])
            self._kline_worker.result.connect(self._on_kline_data)
            self._kline_worker.start()
        except Exception as e:
            self._services.status(f"K线请求失败: {e}")

    def _on_kline_data(self, tag, data):
        try:
            if data.get("code") != 0 or not data.get("data"):
                self._services.status("K线数据加载失败")
                return
            bars = data.get("data", [])
            self._chart.set_data(data, bars[0].get("code", ""), bars[0].get("name", ""))
            self._services.status("K线已加载")
        except Exception as e:
            traceback.print_exc()
            self._services.status(f"显示K线失败: {e}")
