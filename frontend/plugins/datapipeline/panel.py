# -*- coding: utf-8 -*-
"""DataPipeline Panel — data update dashboard with one-click fetch + per-step retry."""

import sqlite3, os
from frontend.platform.theme import (
    dp, dps, fs,
    C_BG, C_PANEL, C_BORDER, C_TEXT, C_SUBTEXT, C_ACCENT,
    qss_table, qss_btn_accent, qss_btn_accent_outline, style_caption,
)
from frontend.platform.premium import (
    PAL, card_qss, value_ss, label_ss, SectionTitle,
)
from datetime import datetime, time as dtime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from .worker import UpdateWorker, STEP_DEFS

C_GREEN = "#3FB950"
C_RED = "#E5484D"

STEP_NAMES = [name for name, _, _ in STEP_DEFS]


class PipelinePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.cache_path = None
        self.on_status = None
        self.on_update_done = None
        self._worker = None
        self._running = False
        self._retry_workers = {}
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(10)

        # ── Header ──
        hdr = QVBoxLayout()
        hdr.setSpacing(0)
        title = QLabel("数据管道")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:{fs(17)};font-weight:600;letter-spacing:{dp(2)}px;background:transparent")
        hdr.addWidget(title)
        self._auto_hint = QLabel("")
        self._auto_hint.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent")
        hdr.addWidget(self._auto_hint)
        lo.addLayout(hdr)

        # ── Last update status card ──
        self._status_card = QFrame()
        self._status_card.setObjectName("card")
        self._status_card.setStyleSheet(card_qss("card"))
        cl = QVBoxLayout(self._status_card)
        cl.setContentsMargins(dp(16), dp(12), dp(16), dp(12))
        cl.setSpacing(dp(4))

        self._last_date = QLabel("上次更新: --")
        self._last_date.setStyleSheet(value_ss(color=C_TEXT, size=15))
        cl.addWidget(self._last_date)

        self._last_status = QLabel("状态: 未知")
        self._last_status.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:{fs(12)};background:transparent")
        cl.addWidget(self._last_status)
        lo.addWidget(self._status_card)

        # ── Step table ──
        self._step_table = QTableWidget()
        self._step_table.setColumnCount(4)
        self._step_table.setHorizontalHeaderLabels(["\u6570\u636e\u5206\u7c7b", "\u884c\u6570", "\u72b6\u6001", "\u64cd\u4f5c"])
        self._step_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._step_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._step_table.verticalHeader().setVisible(False)
        self._step_table.setShowGrid(False)
        self._step_table.setFixedHeight(dp(300))
        self._step_table.horizontalHeader().setStretchLastSection(True)
        self._step_table.setStyleSheet(qss_table())
        self._step_table.setRowCount(len(STEP_NAMES))
        for i, name in enumerate(STEP_NAMES):
            bg = QColor("#151A24") if i % 2 == 0 else QColor("#10141B")
            nm = QTableWidgetItem(name)
            nm.setForeground(QColor(C_SUBTEXT))
            nm.setBackground(bg)
            nm.setFlags(Qt.ItemIsEnabled)
            self._step_table.setItem(i, 0, nm)

            cnt = QTableWidgetItem("--")
            cnt.setForeground(QColor(C_TEXT))
            cnt.setBackground(bg)
            cnt.setFlags(Qt.ItemIsEnabled)
            cnt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._step_table.setItem(i, 1, cnt)

            st = QTableWidgetItem("\u25cb")
            st.setForeground(QColor("#484F58"))
            st.setBackground(bg)
            st.setFlags(Qt.ItemIsEnabled)
            st.setTextAlignment(Qt.AlignCenter)
            self._step_table.setItem(i, 2, st)

            self._step_table.setCellWidget(i, 3, QWidget())
        self._step_table.setColumnWidth(0, dp(130))
        self._step_table.setColumnWidth(1, dp(80))
        self._step_table.setColumnWidth(2, dp(50))
        lo.addWidget(self._step_table)

        # ── Progress bar ──
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(dp(6))
        self._progress.setStyleSheet(
            "QProgressBar{background:#141A23;border:1px solid #1E2530;border-radius:3px}"
            "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #D4A574,stop:1 #E0BE96);border-radius:3px}")
        lo.addWidget(self._progress)

        # ── Button ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_fetch = QPushButton("一键拉取全部数据")
        self._btn_fetch.setFixedSize(dp(200), dp(38))
        self._btn_fetch.setCursor(Qt.PointingHandCursor)
        self._btn_fetch.setStyleSheet(qss_btn_accent())
        self._btn_fetch.clicked.connect(self._on_fetch)
        btn_row.addWidget(self._btn_fetch)
        btn_row.addStretch()
        lo.addLayout(btn_row)

        lo.addStretch()

    def load(self):
        if not self.db_path:
            return
        self._load_last_status()
        self._check_auto_update()

    def _load_last_status(self):
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT update_date, status, stocks_new, rows_added, message, duration_sec "
                "FROM data_update_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                self._last_date.setText(f"\u4e0a\u6b21\u66f4\u65b0: {row[0]}")
                status_text = "\u5b8c\u6210" if row[1] == "ok" else ("\u90e8\u5206\u5931\u8d25" if row[1] == "partial" else "\u5931\u8d25")
                detail = f"\u72b6\u6001: {status_text}  \u00b7  \u65b0\u589e {row[3] or 0} \u884c  \u00b7  \u8017\u65f6 {row[5]}s"
                self._last_status.setText(detail)
                if row[1] == "ok":
                    self._last_status.setStyleSheet(f"color:{C_GREEN};font-size:{fs(12)};background:transparent")
                else:
                    self._last_status.setStyleSheet(f"color:{C_RED};font-size:{fs(12)};background:transparent")
            else:
                self._last_date.setText("上次更新: 无记录")
                self._last_status.setText("状态: 尚未执行过更新")
                self._last_status.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(12)};background:transparent")
        except Exception:
            pass

    def _check_auto_update(self):
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT update_date FROM data_update_log WHERE update_date = ? LIMIT 1",
                (datetime.now().strftime("%Y-%m-%d"),)
            ).fetchone()
            conn.close()
            now = datetime.now().time()
            market_close = dtime(15, 30)
            if not row and now > market_close:
                self._auto_hint.setText("今日数据未更新, 可点击一键拉取")
                self._auto_hint.setStyleSheet(f"color:#E8C9A0;font-size:{fs(11)};background:transparent")
            elif not row:
                self._auto_hint.setText("盘中, 数据待更新")
                self._auto_hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent")
            else:
                self._auto_hint.setText("\u2714 今日已更新")
                self._auto_hint.setStyleSheet(f"color:{C_GREEN};font-size:{fs(11)};background:transparent")
        except Exception:
            pass

    def _build_retry_btn(self, step_idx):
        btn = QPushButton("重试")
        btn.setFixedSize(dp(48), dp(24))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(qss_btn_accent_outline())
        btn.clicked.connect(lambda: self._on_retry(step_idx))
        return btn

    def _on_fetch(self):
        if self._running:
            return
        self._running = True
        self._btn_fetch.setEnabled(False)
        self._btn_fetch.setText("\u66f4\u65b0\u4e2d...")
        self._progress.setValue(0)
        self._reset_steps()
        self._clear_retry_btns()

        self._worker = UpdateWorker(self.db_path, self.cache_path)
        self._worker.progress.connect(self._on_step)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _reset_steps(self):
        for i in range(len(STEP_NAMES)):
            self._step_table.item(i, 1).setText("--")
            self._step_table.item(i, 1).setForeground(QColor(C_TEXT))
            st = self._step_table.item(i, 2)
            st.setText("\u25cb")
            st.setForeground(QColor("#484F58"))

    def _clear_retry_btns(self):
        for i in range(len(STEP_NAMES)):
            w = QWidget()
            w.setStyleSheet("background:transparent")
            self._step_table.setCellWidget(i, 3, w)

    def _on_step(self, step_name, data):
        try:
            idx = STEP_NAMES.index(step_name)
        except ValueError:
            return
        self._update_step_row(idx, data)

    def _update_step_row(self, idx, data):
        cnt = self._step_table.item(idx, 1)
        st = self._step_table.item(idx, 2)
        if data.get("ok"):
            cnt.setText(str(data.get("rows", 0)))
            cnt.setForeground(QColor(C_TEXT))
            st.setText("\u2713")
            st.setForeground(QColor(C_GREEN))
            w = QWidget()
            w.setStyleSheet("background:transparent")
            self._step_table.setCellWidget(idx, 3, w)
        else:
            cnt.setText("0")
            cnt.setForeground(QColor(C_RED))
            st.setText("\u2717")
            st.setForeground(QColor(C_RED))
            self._step_table.setCellWidget(idx, 3, self._build_retry_btn(idx))

        done = sum(1 for i in range(len(STEP_NAMES))
                   if self._step_table.item(i, 2).text() in ("\u2713", "\u2717"))
        pct = int(done / len(STEP_NAMES) * 100)
        self._progress.setValue(pct)

        if self.on_status:
            if data.get("ok"):
                self.on_status(f"\u2713 {STEP_NAMES[idx]}: +{data.get('rows', 0)} \u884c")
            else:
                self.on_status(f"\u2717 {STEP_NAMES[idx]}: {data.get('error', '失败')}")

    def _on_done(self, result):
        self._running = False
        self._btn_fetch.setEnabled(True)
        self._btn_fetch.setText("一键拉取全部数据")
        self._progress.setValue(100)

        if result.get("ok"):
            elapsed = result.get("elapsed", 0)
            total = result.get("total_rows", 0)
            if self.on_status:
                self.on_status(f"\u66f4\u65b0\u5b8c\u6210: +{total} \u884c, \u8017\u65f6 {elapsed}s")
            self._load_last_status()
            self._auto_hint.setText("\u2714 \u4eca\u65e5\u5df2\u66f4\u65b0")
            self._auto_hint.setStyleSheet(f"color:{C_GREEN};font-size:{fs(11)};background:transparent")
        else:
            if self.on_status:
                self.on_status(f"更新失败: {result.get('error', '未知错误')}")

        if self.on_update_done:
            try:
                self.on_update_done()
            except Exception:
                pass

    def _on_retry(self, step_idx):
        step_name = STEP_NAMES[step_idx]
        st = self._step_table.item(step_idx, 2)
        st.setText("\u25cb")
        st.setForeground(QColor("#484F58"))
        cnt = self._step_table.item(step_idx, 1)
        cnt.setText("...")
        cnt.setForeground(QColor(C_ACCENT))

        # Disable retry btn
        btn = self._step_table.cellWidget(step_idx, 3)
        if btn and isinstance(btn, QPushButton):
            btn.setEnabled(False)

        worker = UpdateWorker(self.db_path, self.cache_path, single_step=step_name)
        worker.progress.connect(lambda name, data, idx=step_idx: self._update_step_row(idx, data))
        worker.finished.connect(lambda result: self._on_retry_done(result))
        worker.start()
        self._retry_workers[step_name] = worker

    def _on_retry_done(self, result):
        if result.get("ok"):
            if self.on_status:
                self.on_status(f"\u91cd\u8bd5\u6210\u529f: {result.get('step_name', '')} +{result.get('total_rows', 0)} \u884c")
        else:
            if self.on_status:
                self.on_status(f"\u91cd\u8bd5\u5931\u8d25: {result.get('error', '')}")
        if self.on_update_done:
            try:
                self.on_update_done()
            except Exception:
                pass
