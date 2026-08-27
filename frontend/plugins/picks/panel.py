import sys, os, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox, QPushButton)
from PyQt5.QtCore import Qt
from frontend.platform.theme import (
    dp, dps, fs, C_ACCENT, C_BG, C_UP as C_RISE, C_DOWN as C_FALL,
    qss_table, qss_btn_accent_outline, style_h2,
)
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
from factor_engine import FactorScorer, DEFAULT_FILTERS

C_SUCCESS = C_FALL


class PicksPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self._filters = dict(DEFAULT_FILTERS)
        self._last_results = []

        self.setStyleSheet("background:%s" % C_BG)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # ── 页头: 选股 + 数据截至标签 ──
        head = QHBoxLayout(); head.setSpacing(10)
        title = QLabel("选股")
        title.setStyleSheet(f"color:{C_ACCENT};font-size:{fs(18)};font-weight:700;background:transparent;")
        head.addWidget(title)
        self._asof_lbl = QLabel("数据截至 --")
        self._asof_lbl.setStyleSheet(f"color:#8B949E;font-size:{fs(11)};background:transparent;padding-top:4px;")
        head.addWidget(self._asof_lbl)
        head.addStretch()
        layout.addLayout(head)

        # ── 过滤条(简洁) + 一键模拟买入 ──
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
        self._btn_apply.setFixedHeight(dp(28))
        self._btn_apply.setStyleSheet(qss_btn_accent_outline())
        self._btn_apply.clicked.connect(self.load)
        filter_bar.addWidget(self._btn_apply)

        # 一键模拟买入(醒目主按钮)
        self._btn_sim_buy = QPushButton("一键模拟买入")
        self._btn_sim_buy.setObjectName("refreshBtn")
        self._btn_sim_buy.setCursor(Qt.PointingHandCursor)
        self._btn_sim_buy.setFixedHeight(dp(28))
        self._btn_sim_buy.setToolTip("把当前选股结果等权分配模拟账户资金市价买入")
        self._btn_sim_buy.clicked.connect(self._on_sim_buy)
        filter_bar.addWidget(self._btn_sim_buy)
        layout.addLayout(filter_bar)

        # ── 选股结果表(核心6列) ──
        self.table = QTableWidget()
        self.table.setStyleSheet(qss_table())
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_right_click)
        layout.addWidget(self.table, 1)

        # 模拟买入结果 caption
        self._buy_cap = QLabel("")
        self._buy_cap.setStyleSheet(f"color:#8B949E;font-size:{fs(10)};background:transparent;")
        self._buy_cap.setWordWrap(True)
        layout.addWidget(self._buy_cap)

    def _on_filter_change(self):
        self._filters["exclude_st"] = self._cb_st.isChecked()
        self._filters["exclude_bj"] = self._cb_bj.isChecked()
        self._filters["exclude_kcb"] = self._cb_kcb.isChecked()
        self._filters["exclude_cyb"] = self._cb_cyb.isChecked()

    def on_theme_changed(self):
        self.table.setStyleSheet(qss_table())
        self._btn_apply.setStyleSheet(qss_btn_accent_outline())
        self.table.viewport().update()
        self.update()

    def load(self):
        if not self.db_path:
            return
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
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
            # 数据截至 = kline 最新日
            as_of = None
            try:
                import sqlite3
                conn = sqlite3.connect(self.db_path)
                as_of = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
                conn.close()
            except Exception:
                pass
            return {"code": 0, "data": [s.to_api_dict() for s in scores], "as_of": as_of}
        except Exception as e:
            traceback.print_exc()
            return {"code": -1, "error": str(e)}

    def _on_data(self, tag, data):
        if data.get("code") != 0:
            return
        picks = data.get("data", [])
        self._last_results = picks
        # 数据截至标签
        as_of = data.get("as_of")
        if as_of:
            s = str(as_of)
            self._asof_lbl.setText(f"数据截至 {s[:4]}-{s[4:6]}-{s[6:8]}")
        # 核心 6 列 (维度分收进 tooltip, 减少桌面文字)
        cols = ["#", "代码", "名称", "现价", "涨跌幅", "总分"]
        self.table.setRowCount(len(picks))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        for i, s in enumerate(picks):
            chg = s.get("factors", {}).get("CHANGE_PCT", 0) or 0
            score = s.get("total_score", 0)
            items = [
                (str(i + 1), "#484F58"),
                (s.get("code", ""), "#E6EDF3"),
                (s.get("name", ""), "#E6EDF3"),
                ("{:.2f}".format(s.get("factors", {}).get("CLOSE", 0)), "#E6EDF3"),
                ("{}{:.2f}%".format("+" if chg >= 0 else "", chg), C_RISE if chg >= 0 else C_FALL),
                ("{:.1f}".format(score), C_ACCENT if score >= 70 else ("#8B949E" if score >= 50 else "#484F58")),
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
        self.table.setColumnWidth(0, dp(30))
        self.table.setColumnWidth(1, dp(65))
        self.table.setColumnWidth(2, dp(90))
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

    def _on_sim_buy(self):
        """把当前选股结果一键模拟买入(等权分配模拟账户资金)."""
        codes = [{"code": s.get("code")} for s in self._last_results if s.get("code")]
        if not codes:
            if self.on_status:
                self.on_status("无可买入的选股(先加载选股)")
            return
        if self.on_status:
            self.on_status(f"模拟买入 {len(codes)} 只...")
        w = LocalWorker(self._work_sim_buy, "sim_buy", args=[codes])
        w.result.connect(self._on_sim_buy_data)
        w.start()

    def _work_sim_buy(self, codes):
        try:
            from frontend.plugins.research.worker import sim_buy_picks
            return sim_buy_picks(codes)
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    def _on_sim_buy_data(self, tag, data):
        if not isinstance(data, dict) or data.get("error"):
            if self.on_status:
                self.on_status("模拟买入失败: %s" % (data.get("error") if data else "无数据"))
            return
        nb = len(data.get("bought", []))
        nskip = len(data.get("skipped", []))
        self._buy_cap.setText(
            f"模拟买入 {nb} 只 / 跳过 {nskip} 只 · 花费 {data.get('total_cost', 0):,.0f} · 账户#{data.get('account_id')}")
        if self.on_status:
            self.on_status(f"模拟买入完成: {nb}只 花费 {data.get('total_cost', 0):,.0f} (跳过{nskip})")

    def _on_click(self, row, col):
        code = self.table.item(row, 1)
        name = self.table.item(row, 2)
        if code and self.on_open_kline:
            self.on_open_kline(code.text(), name.text() if name else "")
