import sys, os, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox, QPushButton)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from .local_worker import LocalWorker

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
from factor_engine import FactorScorer, DEFAULT_FILTERS


class PicksPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self._filters = dict(DEFAULT_FILTERS)  # 当前过滤配置
        self._last_results = []

        self.setStyleSheet("background:#111111")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # ── 过滤栏 ──
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(4)
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
            cb.setStyleSheet(
                "QCheckBox{color:#B4B4B4;font-size:11px;spacing:4px;}"
                "QCheckBox::indicator{width:14px;height:14px;"
                "border:1px solid #3A322A;border-radius:3px;background:#191919;}"
                "QCheckBox::indicator:checked{background:#FFE0C2;border-color:#FFE0C2;}"
            )
            filter_bar.addWidget(cb)

        filter_bar.addStretch()
        self._btn_apply = QPushButton("应用过滤")
        self._btn_apply.setObjectName("refreshBtn")
        self._btn_apply.setStyleSheet(
            "QPushButton{background:#393028;color:#FFE0C2;border:1px solid #FFE0C2;"
            "border-radius:4px;padding:3px 10px;font-size:11px;}"
            "QPushButton:hover{background:#3A322A;}"
        )
        self._btn_apply.clicked.connect(self.load)
        filter_bar.addWidget(self._btn_apply)

        layout.addLayout(filter_bar)

        # ── 表格 ──
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_right_click)
        layout.addWidget(self.table, 1)

    def _on_filter_change(self):
        """过滤选项变更时同步到 _filters"""
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
            self.on_status("加载选股... (过滤:%d项)" % count)
        # 传递当前过滤配置给工作线程
        self._worker = LocalWorker(self._work, "picks", args=[self._filters])
        self._worker.result.connect(self._on_data)
        self._worker.start()

    def _work(self, filters):
        """评分 + 前过滤"""
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
            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(s.get("code", "")),
                QTableWidgetItem(s.get("name", "")),
                QTableWidgetItem("{:.2f}".format(s.get("factors", {}).get("CLOSE", 0))),
                QTableWidgetItem("{}{:.2f}%".format(
                    "+" if (s.get("factors", {}).get("CHANGE_PCT", 0) or 0) >= 0 else "",
                    s.get("factors", {}).get("CHANGE_PCT", 0) or 0,
                )),
                QTableWidgetItem("{:.1f}".format(s.get("total_score", 0))),
                QTableWidgetItem("{:.0f}".format(groups.get("trend", 0))),
                QTableWidgetItem("{:.0f}".format(groups.get("momentum", 0))),
                QTableWidgetItem("{:.0f}".format(groups.get("volume", 0))),
                QTableWidgetItem("{:.0f}".format(groups.get("price", 0))),
                QTableWidgetItem("{:.0f}".format(groups.get("stability", 0))),
            ]
            for j, it in enumerate(items):
                it.setToolTip(self._make_tooltip(s))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j == 4:
                    chg = s.get("factors", {}).get("CHANGE_PCT", 0) or 0
                    it.setForeground(QColor("#E54D2E" if chg >= 0 else "#3fb950"))
                if j == 5:
                    sc = s.get("total_score", 0)
                    if sc >= 70:
                        it.setForeground(QColor("#FFE0C2"))
                    elif sc >= 50:
                        it.setForeground(QColor("#B4B4B4"))
                    else:
                        it.setForeground(QColor("#666666"))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 90)
        if self.on_status:
            self.on_status("选股已加载 - %d只" % len(picks))

    def _make_tooltip(self, s):
        lines = ["%s(%s) 总分: %.1f" % (s.get("name", ""), s.get("code", ""), s.get("total_score", 0))]
        for g in s.get("groups", []):
            ind_lines = []
            for ind in g.get("indicators", []):
                passes = [c for c in ind.get("conditions", []) if c.get("passed")]
                if passes:
                    parts = []
                    for c in passes:
                        if c["score"] > 0:
                            parts.append("%s(+%d)" % (c["reason"], c["score"]))
                        else:
                            parts.append("%s(%d)" % (c["reason"], c["score"]))
                    ind_lines.append("  %s: %s" % (ind["name"], "; ".join(parts)))
            if ind_lines:
                lines.append("[%s] %.1f/%d" % (g["name"], g["weighted_score"], g["max_score"]))
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
