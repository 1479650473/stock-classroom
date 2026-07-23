# -*- coding: utf-8 -*-
"""DataPipeline Companion Panel — right-side stats for pipeline tab."""

import sqlite3, os, time
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"
C_GREEN = "#3fb950"
C_RED = "#EF5350"

API_LIST = [
    ("spot",        "实时行情"),
    ("index",       "指数行情"),
    ("industry",    "行业板块"),
    ("concept",     "概念板块"),
    ("north_flow",  "北向资金"),
    ("stock_hist",  "日K线"),
    ("news",        "个股新闻"),
    ("gdhs",        "股东户数"),
    ("etf",         "ETF行情"),
    ("limit_up",    "涨停板"),
    ("lhb",         "龙虎榜统计"),
    ("high_low",    "创新高/低"),
    ("fund_flow",   "资金流向"),
    ("lhb_detail",  "龙虎榜详情"),
]


class PingWorker(QThread):
    done = pyqtSignal(list)

    def run(self):
        results = []
        try:
            from backend.akshare_source import diagnose_akshare
            diag = diagnose_akshare()
            for api_id, name_cn in API_LIST:
                info = diag.get(api_id, {})
                results.append({
                    "name": name_cn,
                    "ok": info.get("ok", False),
                    "rows": info.get("rows", 0),
                    "time": info.get("time", 0),
                })
        except Exception:
            for api_id, name_cn in API_LIST:
                results.append({"name": name_cn, "ok": False, "rows": 0, "time": 0})
        self.done.emit(results)


class PipelineCompanion(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.cache_path = None
        self._ping_worker = None
        self._api_labels = {}
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0D1117}")

        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(10)

        # ── API Health ──
        api_section = self._section_label("\U0001f50d API \u5065\u5eb7\u72b6\u6001")
        lo.addWidget(api_section)

        self._api_frame = QFrame()
        self._api_frame.setObjectName("card")
        self._api_frame.setStyleSheet(
            f"QFrame#card{{background:{C_PANEL};border:1px solid {C_BORDER};border-radius:8px}}")
        api_lo = QVBoxLayout(self._api_frame)
        api_lo.setContentsMargins(12, 8, 12, 8)
        api_lo.setSpacing(4)

        for _, name in API_LIST:
            row = QVBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(f"  {name}")
            lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;background:transparent")
            row.addWidget(lbl)
            row_w = QWidget()
            row_w.setLayout(row)
            api_lo.addWidget(row_w)
            self._api_labels[name] = lbl

        api_lo.addStretch()
        lo.addWidget(self._api_frame)

        # ── DB Size ──
        db_section = self._section_label("\U0001f4d0 \u6570\u636e\u5e93")
        lo.addWidget(db_section)

        self._db_info = QLabel("")
        self._db_info.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;padding:6px 12px;background:transparent")
        self._db_info.setWordWrap(True)
        lo.addWidget(self._db_info)

        # ── Today stats ──
        stats_section = self._section_label("\U0001f4c8 \u4eca\u65e5\u7edf\u8ba1")
        lo.addWidget(stats_section)

        self._stats_info = QLabel("")
        self._stats_info.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;padding:6px 12px;background:transparent")
        self._stats_info.setWordWrap(True)
        lo.addWidget(self._stats_info)

        lo.addStretch()
        scroll.setWidget(w)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{C_ACCENT};font-size:13px;font-weight:600;background:transparent")
        return lbl

    def refresh(self):
        self._ping_apis()
        self._show_db_size()
        self._show_today_stats()

    def _ping_apis(self):
        self._ping_worker = PingWorker()
        self._ping_worker.done.connect(self._on_ping_done)
        self._ping_worker.start()

    def _on_ping_done(self, results):
        for r in results:
            lbl = self._api_labels.get(r["name"])
            if not lbl:
                continue
            if r["ok"]:
                lbl.setText(f"  \u2713  {r['name']}     {r['time']:.1f}s")
                lbl.setStyleSheet(f"color:{C_GREEN};font-size:12px;background:transparent")
            else:
                lbl.setText(f"  \u2717  {r['name']}     \u8fde\u63a5\u5931\u8d25")
                lbl.setStyleSheet(f"color:{C_RED};font-size:12px;background:transparent")

    def _show_db_size(self):
        if not self.db_path:
            return
        try:
            kline_sz = os.path.getsize(self.db_path) / 1048576 if os.path.exists(self.db_path) else 0
            cache_sz = os.path.getsize(self.cache_path) / 1048576 if self.cache_path and os.path.exists(self.cache_path) else 0
            self._db_info.setText(
                f"  kline.db    {kline_sz:.0f} MB\n"
                f"  stock_cache.db    {cache_sz:.0f} MB"
            )
        except Exception:
            self._db_info.setText("  \u65e0\u6cd5\u8bfb\u53d6")

    def _show_today_stats(self):
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT rows_added, duration_sec, message FROM data_update_log "
                "WHERE update_date = ? ORDER BY id DESC LIMIT 1",
                (datetime.now().strftime("%Y-%m-%d"),)
            ).fetchone()
            conn.close()
            if row:
                self._stats_info.setText(
                    f"  \u65b0\u589e\u884c\u6570: {row[0] or 0}\n"
                    f"  \u8017\u65f6: {row[1]}s\n"
                    f"  \u8be6\u60c5: {row[2] or ''}"
                )
            else:
                self._stats_info.setText("  \u4eca\u65e5\u5c1a\u672a\u66f4\u65b0")
        except Exception:
            self._stats_info.setText("  \u65e0\u6cd5\u8bfb\u53d6")
