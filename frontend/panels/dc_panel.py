"""Data Center Panel — Browse kline.db tables + hierarchical stock view"""
import sqlite3, traceback, os, re
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QFrame, QLineEdit, QPushButton, QStackedWidget,
    QListWidget, QListWidgetItem, QSplitter)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from .local_worker import LocalWorker

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

CN = {
    "code":"代码","date":"日期","open":"开盘","high":"最高",
    "low":"最低","close":"收盘","volume":"成交量","amount":"成交额",
    "turnover":"换手率","name":"名称","board":"板块","status":"状态",
    "last_date":"最后日期","total_days":"总天数","up_count":"上涨",
    "down_count":"下跌","price":"价格","change_pct":"涨跌幅",
    "net_value":"净流入","amount":"成交额","count":"计数",
    "获利比例":"获利%","平均成本":"均价","90集中度":"90集中",
    "70集中度":"70集中","updated_at":"更新于",
}

BG_EVEN = QColor("#111111")
BG_ODD = QColor("#191919")


class DCPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.cache_path = None
        self.on_status = None
        self._dc_tables = []
        self._dc_rows = []
        self._dc_cols = []
        self._dc_selected_table = None
        self.setStyleSheet("background:#111111")
        self._build_ui()
        # Start background loading after event loop ready

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 4, 6, 4)
        lo.setSpacing(6)

        self.overview = QHBoxLayout()
        lo.addLayout(self.overview)

        # Mode switch
        mode_bar = QHBoxLayout()
        self._mode_btn_table = QPushButton("表浏览")
        self._mode_btn_stock = QPushButton("股票分层")
        for b in (self._mode_btn_table, self._mode_btn_stock):
            b.setFixedHeight(24)
            b.setStyleSheet(
                "QPushButton{background:#201E18;color:#B4B4B4;border:1px solid #333;padding:2px 10px;border-radius:3px}"
                "QPushButton:hover{background:#393028;color:#EEE}"
            )
        self._mode_btn_table.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._mode_btn_stock.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        mode_bar.addWidget(QLabel("模式:"))
        mode_bar.addWidget(self._mode_btn_table)
        mode_bar.addWidget(self._mode_btn_stock)
        mode_bar.addStretch()
        lo.addLayout(mode_bar)

        # Stack: 0=table view, 1=stock view
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_table_view())
        self._stack.addWidget(self._build_stock_view())
        lo.addWidget(self._stack, 1)

    def _build_table_view(self):
        w = QWidget()
        body = QHBoxLayout(w)
        body.setSpacing(6)
        body.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setFixedWidth(220)
        self.tree.setHeaderLabel("数据表")
        self.tree.itemClicked.connect(self._on_tree_select)
        self.tree.setStyleSheet("QTreeWidget{background:#111;color:#CCC;border:1px solid #201E18}")
        body.addWidget(self.tree)

        right = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索过滤...")
        self.search.textChanged.connect(self._on_filter)
        right.addWidget(self.search)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("QTableWidget{background:#111;color:#CCC;gridline-color:#201E18}"
                                 "QHeaderView::section{background:#191919;color:#B4B4B4;border:1px solid #201E18;padding:3px}")
        right.addWidget(self.table, 1)
        body.addLayout(right, 1)
        return w

    def _build_stock_view(self):
        w = QWidget()
        body = QHBoxLayout(w)
        body.setSpacing(6)
        body.setContentsMargins(0, 0, 0, 0)

        left_panel = QVBoxLayout()
        self.stock_search = QLineEdit()
        self.stock_search.setPlaceholderText("搜股票代码/名称...")
        self.stock_search.textChanged.connect(self._filter_stocks)
        left_panel.addWidget(self.stock_search)
        self.stock_list = QListWidget()
        self.stock_list.itemClicked.connect(self._on_stock_select)
        self.stock_list.setStyleSheet("QListWidget{background:#111;color:#CCC;border:1px solid #201E18}")
        left_panel.addWidget(self.stock_list, 1)

        right = QVBoxLayout()
        self.stock_info = QLabel("请从左侧选择一只股票")
        self.stock_info.setStyleSheet("color:#B4B4B4;padding:4px")
        right.addWidget(self.stock_info)
        self.stock_table = QTableWidget()
        self.stock_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stock_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        self.stock_table.verticalHeader().setVisible(False)
        self.stock_table.setShowGrid(False)
        self.stock_table.setStyleSheet("QTableWidget{background:#111;color:#CCC;gridline-color:#201E18}"
                                       "QHeaderView::section{background:#191919;color:#B4B4B4;border:1px solid #201E18;padding:3px}")
        right.addWidget(self.stock_table, 1)

        body.addLayout(left_panel, 1)
        body.addLayout(right, 2)
        return w

    # ─── helpers ────────────────────────────────────────────
    def _make_card(self, text, color, w=140, h=50):
        card = QFrame()
        card.setObjectName("card")
        card.setFixedSize(w, h)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{color};font-size:11px;font-weight:bold;background:transparent")
        lbl.setAlignment(Qt.AlignCenter)
        cl.addWidget(lbl)
        self.overview.addWidget(card)

    # ─── load ────────────────────────────────────────────────
    def load(self):
        if not self.db_path:
            if self.on_status: self.on_status("数据库未配置")
            return
        if self.on_status: self.on_status("加载数据表...")
        self._worker = LocalWorker(self._work_load, "dc")
        self._worker.result.connect(self._on_loaded)
        self._worker.start()

    def _work_load(self):
        while self.overview.count():
            w = self.overview.itemAt(0).widget()
            if w: w.deleteLater(); self.overview.removeWidget(w)
        paths = [(self.db_path, "kline.db", "#3fb950"), (self.cache_path, "cache", "#FFE0C2")]
        tables = []
        for dbp, label, color in paths:
            if not os.path.exists(dbp): continue
            sz = os.path.getsize(dbp) / 1048576
            conn = sqlite3.connect(dbp)
            cur = conn.cursor()
            names = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            for (name,) in names:
                if name == "kline_daily_legacy": continue  # skip backup
                try:
                    cnt = cur.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                except: cnt = 0
                cur.execute(f"PRAGMA table_info([{name}])")
                cols = [(c[1], c[2]) for c in cur.fetchall()]
                tables.append({"name":name,"count":cnt,"db_path":dbp,"db":label,"cols":cols})
            conn.close()
            self._make_card(label, color, 140, 50)
            self.overview.itemAt(self.overview.count()-1).widget().setToolTip(f"{sz:.1f}MB")
        self._dc_tables = tables
        return {"code":0, "data":tables}

    def _on_loaded(self, tag, data):
        if data.get("code") != 0: return
        self.tree.clear()
        # Group kline_* under "K线数据"
        kline_root = QTreeWidgetItem(["K线数据 (27年分表)"])
        kline_root.setForeground(0, QColor("#FFE0C2"))
        self.tree.addTopLevelItem(kline_root)
        other_root = QTreeWidgetItem(["其他数据表"])
        other_root.setForeground(0, QColor("#B4B4B4"))
        self.tree.addTopLevelItem(other_root)

        for t in self._dc_tables:
            name = t["name"]
            if re.match(r"kline_\d{4}$", name):
                parent = kline_root
            else:
                parent = other_root
            text = f"{name}    {t['count']:,}行"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, t)
            item.setForeground(0, QColor("#EEEEEE"))
            parent.addChild(item)

        kline_root.setExpanded(True)
        if self.on_status:
            self.on_status(f"{len(self._dc_tables)} 个数据表")

        # Load stock list for stock view
        self._load_stock_list()

    def _load_stock_list(self):
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT code, name FROM stock_list WHERE status='active' ORDER BY code").fetchall()
            conn.close()
            self._all_stocks = [{"code":r[0],"name":r[1]} for r in rows]
            self.stock_list.clear()
            for s in self._all_stocks:
                item = QListWidgetItem(f"{s['code']} {s['name']}")
                item.setData(Qt.UserRole, s)
                self.stock_list.addItem(item)
            if self.on_status:
                self.on_status(f"{len(self._all_stocks)} 只股票已加载")
        except Exception as e:
            if self.on_status:
                self.on_status(f"股票列表加载失败: {e}")

    # ─── table view ─────────────────────────────────────────
    def _on_tree_select(self, item, col):
        t = item.data(0, Qt.UserRole)
        if not t:
            return  # Group header
        self._dc_selected_table = t
        self._load_table_data(t)

    def _load_table_data(self, t):
        try:
            conn = sqlite3.connect(t["db_path"])
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM [{t['name']}] LIMIT 500")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            self._dc_rows = rows
            self._dc_cols = cols
            self._fill_table(rows, cols, self.table)
            if self.on_status:
                self.on_status(f"{t['name']} - {len(rows)}行, {len(cols)}列")
        except Exception as e:
            if self.on_status:
                self.on_status(f"查询失败: {e}")

    def _fill_table(self, rows, cols, table):
        n_rows = len(rows)
        n_cols = len(cols)
        cols_cn = [CN.get(c, c) for c in cols]
        table.setRowCount(n_rows)
        table.setColumnCount(n_cols + 1)
        table.setHorizontalHeaderLabels(["#"] + cols_cn)
        for r, row in enumerate(rows):
            bg = BG_ODD if r % 2 else BG_EVEN
            rn = QTableWidgetItem(str(r+1))
            rn.setForeground(QColor("#484848"))
            rn.setBackground(bg)
            rn.setFlags(Qt.ItemIsEnabled)
            table.setItem(r, 0, rn)
            for c, val in enumerate(row):
                if val is None:
                    cell = QTableWidgetItem("NULL")
                    cell.setForeground(QColor("#E54D2E"))
                    cell.setBackground(bg)
                    cell.setFont(QFont("Consolas", 9, -1, True))
                else:
                    txt = str(val)
                    cell = QTableWidgetItem(txt)
                    cell.setBackground(bg)
                    if isinstance(val, (int, float)):
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        cell.setFont(QFont("Consolas", 10))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(r, c+1, cell)
        table.setColumnWidth(0, 40)
        for i in range(n_cols):
            mx = 80
            for j in range(min(50, n_rows)):
                txt = str(rows[j][i]) if rows[j][i] is not None else "NULL"
                mx = max(mx, len(txt) * 9 + 20)
            table.setColumnWidth(i+1, min(250, mx))

    def _on_filter(self, text):
        if not hasattr(self, "_dc_rows") or not self._dc_rows: return
        q = text.strip().lower()
        if not q:
            self._fill_table(self._dc_rows, self._dc_cols, self.table)
            return
        filtered = [row for row in self._dc_rows
                    if any(str(v).lower().find(q) >= 0 for v in row if v is not None)]
        self._fill_table(filtered, self._dc_cols, self.table)

    # ─── stock view ─────────────────────────────────────────
    def _filter_stocks(self, text):
        q = text.strip().lower()
        self.stock_list.clear()
        for s in self._all_stocks:
            if not q or q in s["code"].lower() or q in s["name"].lower():
                item = QListWidgetItem(f"{s['code']} {s['name']}")
                item.setData(Qt.UserRole, s)
                self.stock_list.addItem(item)

    def _on_stock_select(self, item):
        s = item.data(Qt.UserRole)
        if not s: return
        code = s["code"]
        try:
            # Query kline_daily view for this stock, get latest 200 rows
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT date, open, high, low, close, volume, amount, turnover "
                "FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 200",
                (code,)
            )
            rows = cur.fetchall()
            cols = ["date","open","high","low","close","volume","amount","turnover"]
            conn.close()
            self.stock_info.setText(f"{code} {s['name']}  —  最近 {len(rows)} 个交易日")
            self._fill_table(rows, cols, self.stock_table)
        except Exception as e:
            self.stock_info.setText(f"查询失败: {e}")
