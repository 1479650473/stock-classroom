import sqlite3, traceback, os, re
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QFrame, QLineEdit, QPushButton, QStackedWidget,
    QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

CN = {
    "code":"代码","date":"日期","open":"开盘","high":"最高",
    "low":"最低","close":"收盘","volume":"成交量","amount":"成交额",
    "turnover":"换手率","name":"名称","board":"板块","status":"状态",
    "last_date":"最后日期","total_days":"总天数","up_count":"上涨",
    "down_count":"下跌","price":"价格","change_pct":"涨跌幅",
    "net_value":"净流入","count":"计数",
    "获利比例":"获利%","平均成本":"均价","90集中度":"90集中",
    "70集中度":"70集中","updated_at":"更新于",
}

BG_EVEN = QColor("#0D1117")
BG_ODD = QColor("#161B22")
C_ACCENT = "#D4A574"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_BORDER = "#21262D"


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
        self._sort_col = -1
        self._sort_asc = True
        self.setStyleSheet("background:#0D1117")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 4, 6, 4)
        lo.setSpacing(4)

        self.overview = QHBoxLayout()
        self.overview.setSpacing(6)
        lo.addLayout(self.overview)

        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(4)
        mode_label = QLabel("模式:")
        mode_label.setStyleSheet("color:#8B949E;font-size:12px;background:transparent")
        mode_bar.addWidget(mode_label)

        self._mode_btns = []
        for i, name in enumerate(["表浏览", "股票分层"]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton{background:#161B22;color:#8B949E;border:1px solid #21262D;"
                "border-radius:6px;padding:2px 10px;font-size:12px}"
                "QPushButton:hover{background:#1C2128}"
                "QPushButton:checked{background:rgba(212,165,116,0.10);color:#D4A574;"
                "border-color:#D4A574}"
            )
            btn.clicked.connect(lambda checked, idx=i: self._switch_mode(idx))
            mode_bar.addWidget(btn)
            self._mode_btns.append(btn)
        mode_bar.addStretch()
        lo.addLayout(mode_bar)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_table_view())
        self._stack.addWidget(self._build_stock_view())
        lo.addWidget(self._stack, 1)

        self._status_bar = QLabel("")
        self._status_bar.setStyleSheet("color:#484F58;font-size:12px;padding:2px 4px;background:transparent")
        lo.addWidget(self._status_bar)

    def _switch_mode(self, idx):
        for i, btn in enumerate(self._mode_btns):
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)

    # ─── table view ─────────────────────────────────────────
    def _build_table_view(self):
        w = QWidget()
        body = QHBoxLayout(w)
        body.setSpacing(6)
        body.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setFixedWidth(220)
        self.tree.setHeaderLabel("数据表")
        self.tree.itemClicked.connect(self._on_tree_select)
        self.tree.setStyleSheet("QTreeWidget{background:#0D1117;color:#C9D1D9;border:1px solid #21262D}")
        body.addWidget(self.tree)

        right = QVBoxLayout()
        right.setSpacing(4)
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
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_click)
        self.table.setStyleSheet("QTableWidget{background:#0D1117;color:#E6EDF3;gridline-color:#1A1F28}"
                                 "QHeaderView::section{background:#161B22;color:#8B949E;"
                                 "border:1px solid #21262D;padding:3px;font-size:11px}")
        right.addWidget(self.table, 1)
        body.addLayout(right, 1)
        return w

    # ─── stock view ─────────────────────────────────────────
    def _build_stock_view(self):
        w = QWidget()
        body = QHBoxLayout(w)
        body.setSpacing(6)
        body.setContentsMargins(0, 0, 0, 0)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(4)
        self.stock_search = QLineEdit()
        self.stock_search.setPlaceholderText("搜股票代码/名称...")
        self.stock_search.textChanged.connect(self._filter_stocks)
        left_panel.addWidget(self.stock_search)
        self.stock_list = QListWidget()
        self.stock_list.itemClicked.connect(self._on_stock_select)
        self.stock_list.setStyleSheet("QListWidget{background:#0D1117;color:#C9D1D9;border:1px solid #21262D}")
        left_panel.addWidget(self.stock_list, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.stock_info = QLabel("请从左侧选择一只股票")
        self.stock_info.setStyleSheet("color:#8B949E;padding:2px 4px;font-size:11px;background:transparent")
        right.addWidget(self.stock_info)
        self.stock_table = QTableWidget()
        self.stock_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stock_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        self.stock_table.verticalHeader().setVisible(False)
        self.stock_table.setShowGrid(False)
        self.stock_table.horizontalHeader().setSortIndicatorShown(True)
        self.stock_table.horizontalHeader().sectionClicked.connect(self._on_stock_header_click)
        self.stock_table.setStyleSheet("QTableWidget{background:#0D1117;color:#E6EDF3;gridline-color:#1A1F28}"
                                       "QHeaderView::section{background:#161B22;color:#8B949E;"
                                       "border:1px solid #21262D;padding:3px;font-size:11px}")
        right.addWidget(self.stock_table, 1)

        body.addLayout(left_panel, 1)
        body.addLayout(right, 2)
        return w

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
        paths = [(self.db_path, "kline.db", "#3fb950"),
                 (self.cache_path, "cache", "#FFE0C2") if self.cache_path else None]
        paths = [p for p in paths if p is not None]
        db_infos = []
        tables = []
        for dbp, label, color in paths:
            if not os.path.exists(dbp):
                db_infos.append({"label": label, "color": color, "size_mb": 0,
                                 "table_count": 0, "total_rows": 0, "found": False})
                continue
            sz = os.path.getsize(dbp) / 1048576
            conn = sqlite3.connect(dbp)
            cur = conn.cursor()
            names = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            db_total = 0
            for (name,) in names:
                if name == "kline_daily_legacy": continue
                try:
                    cnt = cur.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                except Exception:
                    cnt = 0
                cur.execute(f"PRAGMA table_info([{name}])")
                cols = [(c[1], c[2]) for c in cur.fetchall()]
                tables.append({"name": name, "count": cnt, "db_path": dbp,
                               "db": label, "cols": cols})
                db_total += cnt
            conn.close()
            db_infos.append({"label": label, "color": color, "size_mb": sz,
                             "table_count": len(names), "total_rows": db_total, "found": True})
        self._dc_tables = tables
        return {"code": 0, "data": tables, "db_infos": db_infos}

    def _on_loaded(self, tag, data):
        if data.get("code") != 0: return
        tables = data.get("data", [])
        db_infos = data.get("db_infos", [])

        # Clear and rebuild overview cards (on main thread)
        while self.overview.count():
            item = self.overview.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

        for info in db_infos:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(160, 52)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 3, 8, 3)
            cl.setSpacing(1)
            if info["found"]:
                title = QLabel(info["label"])
                title.setStyleSheet(f"color:{info['color']};font-size:12px;font-weight:bold;background:transparent")
                title.setAlignment(Qt.AlignCenter)
                cl.addWidget(title)
                detail = QLabel(f"{info['size_mb']:.0f}MB  ·  {info['table_count']}表  ·  {info['total_rows']:,}行")
                detail.setStyleSheet("color:#666;font-size:10px;background:transparent")
                detail.setAlignment(Qt.AlignCenter)
                cl.addWidget(detail)
                card.setToolTip(f"{info['label']}: {info['size_mb']:.1f}MB, {info['table_count']} tables, {info['total_rows']:,} rows")
            else:
                title = QLabel(info["label"] + "\n未找到")
                title.setStyleSheet(f"color:{info['color']};font-size:11px;font-weight:bold;background:transparent")
                title.setAlignment(Qt.AlignCenter)
                cl.addWidget(title)
            self.overview.addWidget(card)

        # Rebuild tree
        self.tree.clear()
        kline_root = QTreeWidgetItem(["K线数据 (分年表)"])
        kline_root.setForeground(0, QColor(C_ACCENT))
        self.tree.addTopLevelItem(kline_root)
        other_root = QTreeWidgetItem(["其他数据表"])
        other_root.setForeground(0, QColor(C_SUBTEXT))
        self.tree.addTopLevelItem(other_root)

        kline_tables = []
        other_tables = []
        for t in tables:
            if re.match(r"kline_\d{4}$", t["name"]):
                kline_tables.append(t)
            else:
                other_tables.append(t)
        kline_tables.sort(key=lambda x: x["name"])
        other_tables.sort(key=lambda x: -x["count"])

        for t in kline_tables:
            text = f"{t['name']}    {t['count']:,}行"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, t)
            item.setForeground(0, QColor(C_TEXT))
            kline_root.addChild(item)
        for t in other_tables:
            text = f"{t['name']}    {t['count']:,}行"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, t)
            item.setForeground(0, QColor(C_TEXT))
            other_root.addChild(item)

        kline_root.setExpanded(True)
        other_root.setExpanded(True)

        if self.on_status:
            total_rows = sum(t["count"] for t in tables)
            self.on_status(f"{len(tables)} 个数据表 · {total_rows:,} 行")

        self._load_stock_list()

    def _load_stock_list(self):
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT code, name FROM stock_list WHERE status='active' ORDER BY code").fetchall()
            conn.close()
            self._all_stocks = [{"code": r[0], "name": r[1]} for r in rows]
            self.stock_list.clear()
            for s in self._all_stocks:
                item = QListWidgetItem(f"{s['code']} {s['name']}")
                item.setData(Qt.UserRole, s)
                self.stock_list.addItem(item)
            self._status_bar.setText(f"{len(self._all_stocks):,} 只股票")
        except Exception as e:
            if self.on_status:
                self.on_status(f"股票列表加载失败: {e}")

    # ─── table view ─────────────────────────────────────────
    def _on_tree_select(self, item, col):
        t = item.data(0, Qt.UserRole)
        if not t:
            return
        self._dc_selected_table = t
        self._sort_col = -1
        self._sort_asc = True
        self.search.clear()
        self._load_table_data(t)

    def _load_table_data(self, t):
        try:
            conn = sqlite3.connect(t["db_path"])
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM [{t['name']}] LIMIT 500")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            self._dc_rows = list(rows)
            self._dc_cols = cols
            self._fill_table(self._dc_rows, cols, self.table)
            self._update_status_bar(len(self._dc_rows), t["count"], len(cols), t["name"])
        except Exception as e:
            if self.on_status:
                self.on_status(f"查询失败: {e}")

    def _fill_table(self, rows, cols, table):
        n_rows = len(rows)
        n_cols = len(cols)
        table.setRowCount(n_rows)
        table.setColumnCount(n_cols + 1)
        cols_cn = [CN.get(c, c) for c in cols]
        table.setHorizontalHeaderLabels(["#"] + cols_cn)
        for r, row in enumerate(rows):
            bg = BG_ODD if r % 2 else BG_EVEN
            rn = QTableWidgetItem(str(r + 1))
            rn.setForeground(QColor("#484F58"))
            rn.setBackground(bg)
            rn.setFlags(Qt.ItemIsEnabled)
            table.setItem(r, 0, rn)
            for c, val in enumerate(row):
                if val is None:
                    cell = QTableWidgetItem("NULL")
                    cell.setForeground(QColor("#EF5350"))
                    cell.setBackground(bg)
                    cell.setFont(QFont("Consolas", 9, -1, True))
                else:
                    cell = QTableWidgetItem(str(val))
                    cell.setBackground(bg)
                    if isinstance(val, (int, float)):
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        cell.setFont(QFont("Consolas", 10))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(r, c + 1, cell)
        table.setColumnWidth(0, 40)
        for i in range(n_cols):
            mx = 80
            for j in range(min(50, n_rows)):
                txt = str(rows[j][i]) if rows[j][i] is not None else "NULL"
                mx = max(mx, len(txt) * 9 + 20)
            table.setColumnWidth(i + 1, min(250, mx))
        self._apply_sort_indicator(table)

    def _on_header_click(self, col_idx):
        table = self.table
        rows = self._dc_rows
        if not rows or col_idx < 1:
            return
        data_idx = col_idx - 1
        if self._sort_col == data_idx:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = data_idx
            self._sort_asc = True
        try:
            sorted_rows = sorted(rows, key=lambda r: (r[data_idx] is None, r[data_idx] if r[data_idx] is not None else ""),
                                 reverse=not self._sort_asc)
            self._fill_table(sorted_rows, self._dc_cols, table)
        except Exception:
            pass

    def _apply_sort_indicator(self, table):
        header = table.horizontalHeader()
        header.setSortIndicatorShown(True)
        if self._sort_col >= 0 and self._sort_col < len(self._dc_cols):
            header.setSortIndicator(self._sort_col + 1,
                                    Qt.SortOrder.AscendingOrder if self._sort_asc else Qt.SortOrder.DescendingOrder)
        else:
            header.setSortIndicatorShown(False)

    def _on_filter(self, text):
        if not hasattr(self, "_dc_rows") or not self._dc_rows: return
        q = text.strip().lower()
        if not q:
            self._fill_table(self._dc_rows, self._dc_cols, self.table)
            self._update_status_bar(len(self._dc_rows),
                                     self._dc_selected_table["count"] if self._dc_selected_table else 0,
                                     len(self._dc_cols),
                                     self._dc_selected_table["name"] if self._dc_selected_table else "")
            return
        filtered = [row for row in self._dc_rows
                    if any(str(v).lower().find(q) >= 0 for v in row if v is not None)]
        self._fill_table(filtered, self._dc_cols, self.table)
        total = len(self._dc_rows)
        self._update_status_bar(len(filtered), total, len(self._dc_cols),
                                 self._dc_selected_table["name"] if self._dc_selected_table else "")

    def _update_status_bar(self, shown, total, cols, name=""):
        label = f"显示 {shown:,} / {total:,} 行 · {cols} 列"
        if name:
            label = name + " · " + label
        self._status_bar.setText(label)
        if self.on_status:
            self.on_status(label)

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
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT date, open, high, low, close, volume, amount, turnover "
                "FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 200",
                (code,)
            )
            rows = cur.fetchall()
            cols = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
            conn.close()
            self.stock_info.setText(f"{code} {s['name']}  —  最近 {len(rows)} 个交易日")
            self._fill_table(rows, cols, self.stock_table)
            self._status_bar.setText(f"{code} {s['name']} · {len(rows)} 行 K线")
        except Exception as e:
            self.stock_info.setText(f"查询失败: {e}")

    def _on_stock_header_click(self, col_idx):
        pass
