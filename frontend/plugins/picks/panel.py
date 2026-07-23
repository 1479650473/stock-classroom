import sys, os, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox, QPushButton)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
from factor_engine import FactorScorer, DEFAULT_FILTERS

C_ACCENT = "#D4A574"
C_RISE = "#EF5350"
C_FALL = "#4CAF50"
C_SUCCESS = "#4CAF50"


class PicksPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self._filters = dict(DEFAULT_FILTERS)
        self._last_results = []

        self.setStyleSheet("background:#0D1117")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)
        self._cb_st = QCheckBox("剔除ST")
        self._cb_st.setChecked(self._filters["exclude_st"])
        self._cb_st.stateChanged.connect(self._on_filter_change)
        self._cb_bj = QCheckBox("剔除北证")
        self._cb_bj.setChecked(self._filters["exclude_bj"])
        self._cb_bj.stateChanged.connect(self._on_filter_change)
        self._cb_kcb = QCheckBox("剔除科创板")
        self._cb_kcb.setChecked(self._filters["exclude_kcb"])
        self._cb_kcb.stateChanged.connect(self._on_filter_change)
        self._cb_cyb = QCheckBox("剔除创业板")
        self._cb_cyb.setChecked(self._filters["exclude_cyb"])
        self._cb_cyb.stateChanged.connect(self._on_filter_change)

        for cb in [self._cb_st, self._cb_bj, self._cb_kcb, self._cb_cyb]:
            filter_bar.addWidget(cb)

        filter_bar.addStretch()
        self._btn_apply = QPushButton("应用过滤")
        self._btn_apply.setObjectName("refreshBtn")
        self._btn_apply.setCursor(Qt.PointingHandCursor)
        self._btn_apply.setFixedHeight(28)
        self._btn_apply.setStyleSheet(
            "QPushButton{background:rgba(212,165,116,0.10);color:#D4A574;"
            "border:1px solid #D4A574;border-radius:6px;padding:4px 16px;font-size:11px;font-weight:500}"
            "QPushButton:hover{background:rgba(212,165,116,0.18)}")
        self._btn_apply.clicked.connect(self.load)
        filter_bar.addWidget(self._btn_apply)

        layout.addLayout(filter_bar)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_right_click)
        layout.addWidget(self.table, 1)

    def _on_filter_change(self):
        self._filters["exclude_st"] = self._cb_st.isChecked()
        self._filters["exclude_bj"] = self._cb_bj.isChecked()
        self._filters["exclude_kcb"] = self._cb_kcb.isChecked()
        self._filters["exclude_cyb"] = self._cb_cyb.isChecked()

    def load(self):
        if not self.db_path:
            return
        self._last_results = []
        if self.on_status:
            count = sum(1 for v in self._filters.values() if isinstance(v, bool) and v)
            self.on_status(f"加载选股... (过滤:{count}项)")
        self._worker = LocalWorker(self._work, "picks", args=[self._filters])
        self._worker.result.connect(self._on_data)
        self._worker.start()

    def _work(self, filters):
        try:
            scorer = FactorScorer()
            scores = scorer.score_batch(
                self.db_path, top_n=20, min_klines=10, filters=filters
            )
            return {"code": 0, "data": [s.to_api_dict() for s in scores]}
        except Exception as e:
            traceback.print_exc()
            return {"code": -1, "error": str(e)}

    def _on_data(self, tag, data):
        if data.get("code") != 0:
            return
        picks = data.get("data", [])
        self._last_results = picks
        cols = ["#", "代码", "名称", "价格", "涨跌幅", "总分", "趋势", "动量", "量价", "形态", "稳定"]
        self.table.setRowCount(len(picks))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        for i, s in enumerate(picks):
            groups = {g["id"]: g["weighted_score"] for g in s.get("groups", [])}
            chg = s.get("factors", {}).get("CHANGE_PCT", 0) or 0
            score = s.get("total_score", 0)
            items = [
                (str(i + 1), "#484F58"),
                (s.get("code", ""), "#E6EDF3"),
                (s.get("name", ""), "#E6EDF3"),
                ("{:.2f}".format(s.get("factors", {}).get("CLOSE", 0)), "#E6EDF3"),
                ("{}{:.2f}%".format("+" if chg >= 0 else "", chg), C_RISE if chg >= 0 else C_FALL),
                ("{:.1f}".format(score), C_ACCENT if score >= 70 else ("#8B949E" if score >= 50 else "#484F58")),
                ("{:.0f}".format(groups.get("trend", 0)), "#E6EDF3"),
                ("{:.0f}".format(groups.get("momentum", 0)), "#E6EDF3"),
                ("{:.0f}".format(groups.get("volume", 0)), "#E6EDF3"),
                ("{:.0f}".format(groups.get("price", 0)), "#E6EDF3"),
                ("{:.0f}".format(groups.get("stability", 0)), "#E6EDF3"),
            ]
            for j, (text, color) in enumerate(items):
                it = QTableWidgetItem(text)
                it.setToolTip(self._make_tooltip(s))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setForeground(QColor(color))
                if j == 5:
                    it.setFont(QFont("", -1, QFont.Bold))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 65)
        self.table.setColumnWidth(2, 90)
        if self.on_status:
            self.on_status(f"选股已加载 - {len(picks)}只")

    def _make_tooltip(self, s):
        lines = ["%s(%s) 总分: %.1f" % (s.get("name", ""), s.get("code", ""), s.get("total_score", 0))]
        for g in s.get("groups", []):
            ind_lines = []
            for ind in g.get("indicators", []):
                passes = [c for c in ind.get("conditions", []) if c.get("passed")]
                if passes:
                    parts = [f"{c['reason']}({c['score']:+d})" for c in passes
                             if isinstance(c.get('score'), int)]
                    if parts:
                        ind_lines.append(f"  {ind['name']}: {'; '.join(parts)}")
            if ind_lines:
                lines.append(f"[{g['name']}] {g['weighted_score']:.1f}/{g['max_score']}")
                lines.extend(ind_lines)
        return "\n".join(lines)

    def _on_right_click(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._last_results):
            return
        s = self._last_results[row]
        if self.on_status:
            self.on_status(self._make_tooltip(s)[:60] + "...")

    def _on_click(self, row, col):
        code = self.table.item(row, 1)
        name = self.table.item(row, 2)
        if code and self.on_open_kline:
            self.on_open_kline(code.text(), name.text() if name else "")
