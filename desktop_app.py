"""叶瞬光量化选股 桌面端 v3.0
PyQt5 + matplotlib K线图
本地模式：直接读 kline.db + 本地算分，零 HTTP 依赖
"""
import sys, os, json, sqlite3, traceback
from datetime import datetime
import requests
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
KLINE_DB = os.path.join(PROJECT_DIR, "data", "kline.db")
CACHE_DB = os.path.join(PROJECT_DIR, "data", "stock_cache.db")
API = ""  # 不再使用 Flask API，保留兼容旧代码

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLabel, QLineEdit, QStatusBar,
    QAbstractItemView, QStyleFactory, QListWidget, QListWidgetItem, QFrame,
    QScrollArea, QComboBox, QCompleter, QStackedWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QStringListModel
from PyQt5.QtGui import QColor, QFont
from frontend.panels.market_panel import MarketPanel
from frontend.panels.picks_panel import PicksPanel
from frontend.panels.holdings_panel import HoldingsPanel
from frontend.panels.dc_panel import DCPanel
from frontend.kline_widget import KlineWidget as KlineChart

API = "http://127.0.0.1:5000"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

STYLE = """
QMainWindow, QWidget { background-color: #111111; color: #EEEEEE; font-family: "Microsoft YaHei"; font-size: 12px; }
QFrame#card { background: #191919; border: 1px solid #201E18; border-radius: 6px; }
QListWidget { background: #111111; color: #EEEEEE; border: none; outline: none; }
QListWidget::item { padding: 10px 16px; }
QListWidget::item:selected { background: #393028; color: #FFE0C2; }
QListWidget::item:hover { background: #222222; }
QTableWidget { background: #111111; color: #EEEEEE; border: 1px solid #201E18; gridline-color: #201E18; }
QTableWidget::item { padding: 3px 8px; }
QTableWidget::item:selected { background: #393028; color: #FFE0C2; }
QTableWidget QHeaderView::section { background: #191919; color: #B4B4B4; border: none; border-bottom: 2px solid #2A2A2A; padding: 4px 8px; font-weight: bold; }
QHeaderView::section:horizontal { border-right: 1px solid #201E18; }
QLineEdit { background: #191919; color: #EEEEEE; border: 1px solid #2A2A2A; border-radius: 4px; padding: 6px 12px; }
QLineEdit:focus { border-color: #FFE0C2; }
QComboBox { background: #191919; color: #EEEEEE; border: 1px solid #2A2A2A; border-radius: 4px; padding: 4px 10px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: #191919; color: #EEEEEE; border: 1px solid #2A2A2A; selection-background-color: #393028; }
QPushButton { background: #2A2A2A; color: #EEEEEE; border: 1px solid #3A322A; border-radius: 4px; padding: 5px 14px; }
QPushButton:hover { background: #393028; }
QPushButton#refreshBtn { background: #393028; color: #FFE0C2; border-color: #FFE0C2; }
QPushButton#refreshBtn:hover { background: #3A322A; }
QStatusBar { background: #191919; color: #B4B4B4; border-top: 1px solid #201E18; }
QSplitter::handle { background: #201E18; width: 1px; }
QScrollArea { border: none; }
"""


class ApiThread(QThread):
    """后台HTTP请求，异常不崩溃"""
    result = pyqtSignal(str, object)

    def __init__(self, url, tag=""):
        super().__init__()
        self.url = url
        self.tag = tag

    def run(self):
        try:
            r = requests.get(self.url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                self.result.emit(self.tag, data)
            else:
                self.result.emit(self.tag, {"code": -1, "error": f"HTTP {r.status_code}"})
        except requests.Timeout:
            self.result.emit(self.tag, {"code": -1, "error": "请求超时"})
        except requests.ConnectionError:
            self.result.emit(self.tag, {"code": -1, "error": "无法连接"})
        except Exception as e:
            self.result.emit(self.tag, {"code": -1, "error": str(e)})


class LocalWorker(QThread):
    """本地工作线程：后台调 Python 函数（不走 HTTP），保持 UI 流畅"""
    result = pyqtSignal(str, object)
    def __init__(self, func, tag="", args=None, kwargs=None):
        super().__init__()
        self.func = func
        self.tag = tag
        self.args = args or []
        self.kwargs = kwargs or {}
    def run(self):
        try:
            r = self.func(*self.args, **self.kwargs)
            self.result.emit(self.tag, r if isinstance(r, dict) else {"code": 0, "data": r})
        except Exception as e:
            traceback.print_exc()
            self.result.emit(self.tag, {"code": -1, "error": str(e)})



class DesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("叶瞬光量化选股 v3.0")
        self.setGeometry(100, 40, 1280, 800)
        self.setMinimumSize(960, 600)
        self.search_results = []
        self._tab_loaded = [False, False, False, False]  # 懒加载标记
        self.build_ui()
        self.status.showMessage("就绪 — 点击左侧标签加载数据")

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        topbar = QFrame()
        topbar.setFixedHeight(44)
        topbar.setStyleSheet("background:#191919; border-bottom:1px solid #201E18;")
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("⚡ 叶瞬光 量化选股")
        title.setStyleSheet("color:#FFE0C2; font-size:15px; font-weight:bold; border:none;")
        tl.addWidget(title)
        tl.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("输入代码或名称搜索...")
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self.on_search)
        self.search.returnPressed.connect(self.on_search_enter)
        tl.addWidget(self.search)
        refresh = QPushButton("🔄 刷新")
        refresh.setObjectName("refreshBtn")
        refresh.clicked.connect(self.refresh_all)
        tl.addWidget(refresh)
        layout.addWidget(topbar)


        outer = QSplitter(Qt.Horizontal)
        outer.setHandleWidth(1)
        outer.setStyleSheet('QSplitter::handle{background:#201E18;width:1px}')

        # Left panel
        left_widget = QWidget()
        ll = QVBoxLayout(left_widget)
        ll.setContentsMargins(6, 4, 3, 4)
        ll.setSpacing(4)

        # Left tab buttons
        tab_row = QHBoxLayout()
        tab_row.setSpacing(3)
        self.tab_btns = []
        for i, name in enumerate(["📊 市场", "🎯 选股", "💼 持仓", "🗄 数据"]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet('QPushButton{background:#191919;color:#B4B4B4;border:1px solid #201E18;border-radius:4px;padding:4px 10px;font-size:11px}' + 'QPushButton:checked{background:rgba(255,224,194,0.12);color:#FFE0C2;border-color:#FFE0C2}')
            btn.clicked.connect(lambda checked, idx=i: self._switch_left_tab(idx))
            tab_row.addWidget(btn)
            self.tab_btns.append(btn)
        ll.addLayout(tab_row)

        # Left stack (reuse existing widgets)
        self.left_stack = QStackedWidget()
        # Left panel tabs (independent modules)
        self.market_panel = MarketPanel()
        self.market_panel.db_path = KLINE_DB
        self.market_panel.on_open_kline = self.open_kline
        self.market_panel.on_status = lambda msg: self.status.showMessage(msg)
        self.left_stack.addWidget(self.market_panel)

        self.picks_panel = PicksPanel()
        self.picks_panel.db_path = KLINE_DB
        self.picks_panel.on_open_kline = self.open_kline
        self.picks_panel.on_status = lambda msg: self.status.showMessage(msg)
        self.left_stack.addWidget(self.picks_panel)

        self.holdings_panel = HoldingsPanel()
        self.holdings_panel.db_path = KLINE_DB
        self.holdings_panel.on_status = lambda msg: self.status.showMessage(msg)
        self.left_stack.addWidget(self.holdings_panel)

        self.dc_panel = DCPanel()
        self.dc_panel.db_path = KLINE_DB
        self.dc_panel.cache_path = CACHE_DB
        self.dc_panel.on_status = lambda msg: self.status.showMessage(msg)
        self.left_stack.addWidget(self.dc_panel)

        # DC simplified

        ll.addWidget(self.left_stack)
        outer.addWidget(left_widget)

        # Right panel: K-line
        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(3, 4, 6, 4)
        rl.setSpacing(4)

        self.right_stack = QStackedWidget()

        # Page 0: K-line
        k_page = QWidget()
        k_lay = QVBoxLayout(k_page)
        k_lay.setContentsMargins(0,0,0,0)
        k_bar = QHBoxLayout()
        self.k_search = QLineEdit()
        self.k_search.setPlaceholderText("输入代码/名称搜索...")
        self.k_search.returnPressed.connect(self._k_search_stock)
        k_bar.addWidget(self.k_search, 1)
        k_bar.addWidget(QLabel("指标:"))
        self.k_btn_macd = QPushButton("MACD")
        self.k_btn_macd.setCheckable(True)
        self.k_btn_macd.setChecked(True)
        self.k_btn_macd.clicked.connect(lambda: self._switch_kline_indicator("macd"))
        k_bar.addWidget(self.k_btn_macd)
        self.k_btn_rsi = QPushButton("RSI")
        self.k_btn_rsi.setCheckable(True)
        self.k_btn_rsi.clicked.connect(lambda: self._switch_kline_indicator("rsi"))
        k_bar.addWidget(self.k_btn_rsi)
        k_lay.addLayout(k_bar)
        self.kline_chart = KlineChart()
        k_lay.addWidget(self.kline_chart)
        self.right_stack.addWidget(k_page)

        # Page 1: Data Center
        dc_page = QWidget()
        dc_lay = QVBoxLayout(dc_page)
        dc_lay.setContentsMargins(0,0,0,0)
        self.dc_overview = QHBoxLayout()
        dc_lay.addLayout(self.dc_overview)
        self.dc_list = QListWidget()
        self.dc_list.itemClicked.connect(self.on_dc_select)
        dc_lay.addWidget(self.dc_list)
        self.dc_table = QTableWidget()
        self.dc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.dc_table.horizontalHeader().setStretchLastSection(True)
        self.dc_table.verticalHeader().setVisible(False)
        self.dc_table.setShowGrid(False)
        dc_lay.addWidget(self.dc_table)
        self.right_stack.addWidget(dc_page)

        self.right_stack.setCurrentIndex(0)
        rl.addWidget(self.right_stack)
        outer.addWidget(right_widget)
        outer.setSizes([480, 720])

        layout.addWidget(outer)

        self.status = QStatusBar()
        self.status.setStyleSheet('background:#191919;color:#B4B4B4;border-top:1px solid #201E18;font-size:11px')
        self.setStatusBar(self.status)
        self.status.showMessage('就绪 — 点击左侧股票查看 K 线')

        # Trigger initial load
        QTimer.singleShot(100, lambda: self._switch_left_tab(0))
    def on_search(self, text):
        if len(text) < 2:
            return
        self.status.showMessage(f"搜索: {text}...")

    def on_search_enter(self):
        text = self.search.text().strip()
        if not text:
            return
        self.status.showMessage(f"搜索: {text}...")
        def _local_search(q):
            conn = sqlite3.connect(KLINE_DB)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM stock_list WHERE code LIKE ? OR name LIKE ? ORDER BY code LIMIT 50",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
            conn.close()
            return {"code": 0, "data": [dict(r) for r in rows]}
        t = LocalWorker(_local_search, "search", args=[text])
        t.result.connect(self._on_search_done)
        t.start()

    def _on_search_done(self, tag, data):
        if data.get("code") == 0 and data.get("data"):
            s = data["data"][0]
            self.open_kline(s["code"], s["name"])
        else:
            self.status.showMessage("未找到匹配股票")

    # === Market ===
    def _load_market(self):
        self.status.showMessage("加载市场数据...")
        def _local_market():
            import sqlite3 as _sq
            conn = _sq.connect(KLINE_DB)
            conn.row_factory = _sq.Row
            try:
                idx_map = {'000001':'上证指数','399001':'深证成指','399006':'创业板指'}
                idx_rows = conn.execute("SELECT code, close FROM kline_daily WHERE code IN ('000001','399001','399006') AND date = (SELECT MAX(date) FROM kline_daily)").fetchall()
                indices = [{'code':r['code'],'name':idx_map.get(r['code'],r['code']),'price':r['close'],'change_pct':0,'volume':0,'source':'local'} for r in idx_rows]
                latest = conn.execute("SELECT MAX(date) as d FROM kline_daily").fetchone()['d']
                total = conn.execute("SELECT COUNT(*) as c FROM stock_list WHERE status='active'").fetchone()['c']
                stats = {'date':latest,'total':total}
            finally:
                conn.close()
            return {"code":0,"data":indices,"stats":stats,"source":"local"}
        t = LocalWorker(_local_market, "market")
        t.result.connect(self._on_market)
        t.start()

    def _on_market(self, tag, data):
        if data.get("code") != 0:
            self.status.showMessage(f"市场数据失败: {data.get('error','')}")
            return
        indices = data.get("data", [])
        for i in reversed(range(self.card_row.count())):
            w = self.card_row.itemAt(i).widget()
            if w:
                w.deleteLater()
        for d in indices[:6]:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(180, 72)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 6, 12, 6)
            cl.setSpacing(2)
            nm = QLabel(d.get("name", ""))
            nm.setStyleSheet("color:#B4B4B4; font-size:10px; background:transparent;")
            cl.addWidget(nm)
            p = QLabel(f"{d.get('price', d.get('close', 0)):.2f}")
            p.setStyleSheet("color:#EEEEEE; font-size:18px; font-weight:bold; background:transparent;")
            cl.addWidget(p)
            chg = d.get("change_pct", 0)
            color = "#E54D2E" if chg >= 0 else "#3fb950"
            c = QLabel(f"{'+'if chg>=0 else ''}{chg:.2f}%")
            c.setStyleSheet(f"color:{color}; font-size:12px; background:transparent;")
            cl.addWidget(c)
            self.card_row.addWidget(card)
        self.status.showMessage("市场数据已加载")
        self._load_picks_async()

    def on_nav(self, idx):
        self._switch_left_tab(idx)

    def _switch_left_tab(self, idx):
        for i, btn in enumerate(self.tab_btns):
            btn.setChecked(i == idx)
        self.left_stack.setCurrentIndex(idx)
        if hasattr(self, "right_stack"):
            target = 1 if idx == 3 else 0
            if self.right_stack.currentIndex() != target:
                self.right_stack.setCurrentIndex(target)
        if not self._tab_loaded[idx]:
            self._tab_loaded[idx] = True
            if idx == 0:
                self.market_panel.load()
            elif idx == 1:
                self.picks_panel.load()
            elif idx == 2:
                self.holdings_panel.load()
            elif idx == 3:
                self.dc_panel.load()
    def _load_picks_async(self):
        def _local_picks():
            """直接查询 SQLite 评分，不依赖 data_manager 模块"""
            conn = sqlite3.connect(KLINE_DB)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute("SELECT code, name FROM stock_list WHERE status='active' ORDER BY code").fetchall()
                candidates = [(str(r['code']), str(r['name'])) for r in rows
                             if str(r['code'])[:2] in ('60','00','30','68') and 'ST' not in str(r['name'])]
                results = []
                for code, name in candidates:
                    try:
                        kd = conn.execute("SELECT * FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 60", (code,)).fetchall()
                        if len(kd) < 10: continue
                        last, prev = kd[0], kd[1]
                        close = float(last['close'])
                        prev_close = float(prev['close'])
                        volume = float(last['volume'])
                        if volume <= 0: continue
                        change_pct = round((close-prev_close)/prev_close*100,2) if prev_close else 0
                        avg_vol = sum(float(r['volume']) for r in kd[-10:]) / 10
                        score = 50
                        if close > prev_close: score += 20
                        if volume > avg_vol * 1.5: score += 20
                        elif volume > avg_vol: score += 10
                        if change_pct > 3: score += 15
                        elif change_pct > 0: score += 5
                        results.append({'code':code,'name':name,'price':close,
                            'change_pct':change_pct,'volume':int(volume),
                            'turnover':0.1,'score':score,'reasons':['简单评分']})
                    except:
                        continue
            finally:
                conn.close()
            results.sort(key=lambda x:x['score'], reverse=True)
            return {'code':0,'data':results[:20]}
        t = LocalWorker(_local_picks, "picks")
        t.result.connect(self._on_picks_result)
        t.start()
    
    def _on_picks_result(self, tag, data):
        self._on_market_picks(tag, data)
        self._on_picks(tag, data)

    def _on_market_picks(self, tag, data):
        if data.get("code") != 0:
            return
        picks = data.get("data", [])
        self._fill_stock_table(self.market_table, picks, with_rank=True, with_price=True, with_score=True)

    def on_market_click(self, row, col):
        code_item = self.market_table.item(row, 1)
        name_item = self.market_table.item(row, 2)
        if code_item:
            self.open_kline(code_item.text(), name_item.text() if name_item else "")

    # === Picks ===
    def _load_picks(self):
        self.status.showMessage("加载选股...")
        self._load_picks_async()

    def _on_picks(self, tag, data):
        if data.get("code") != 0:
            self.status.showMessage(f"选股失败: {data.get('error','')}")
            return
        picks = data.get("data", [])
        self._fill_stock_table(self.picks_table, picks, with_rank=True, with_price=True, with_score=True)
        self.status.showMessage(f"选股已加载 - {len(picks)} 只")

    def on_picks_click(self, row, col):
        code_item = self.picks_table.item(row, 1)
        name_item = self.picks_table.item(row, 2)
        if code_item:
            self.open_kline(code_item.text(), name_item.text() if name_item else "")

    # === Holdings ===
    def _load_holdings(self):
        self.status.showMessage("加载持仓...")
        def _local_holdings():
            holds = [
                {"code":"600519","name":"茅台","cost":1680.0,"shares":100},
                {"code":"000858","name":"五粮液","cost":145.0,"shares":1000},
                {"code":"300750","name":"宁德时代","cost":220.0,"shares":200},
                {"code":"601318","name":"中国平安","cost":48.0,"shares":500},
            ]
            conn = sqlite3.connect(KLINE_DB)
            for h in holds:
                row = conn.execute(
                    "SELECT close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1",
                    (h["code"],)
                ).fetchone()
                h["current"] = float(row[0]) if row else h["cost"]
            conn.close()
            return {"code":0,"data":holds}
        t = LocalWorker(_local_holdings, "holdings")
        t.result.connect(self._on_holdings)
        t.start()

    def _on_holdings(self, tag, data):
        for i in reversed(range(self.holdings_cards.count())):
            w = self.holdings_cards.itemAt(i).widget()
            if w:
                w.deleteLater()
        if data.get("code") != 0 or not data.get("data"):
            self.status.showMessage("暂无持仓")
            return
        holds = data.get("data", [])
        total_val = sum(h.get("current", 0) * h.get("shares", 0) for h in holds)
        total_pnl = sum((h.get("current", 0) - h.get("cost", 0)) * h.get("shares", 0) for h in holds)

        card_data = [
            ("持仓市值", f"{total_val:,.0f}", "#EEEEEE"),
            ("总盈亏", f"{'+'if total_pnl>=0 else ''}{total_pnl:,.0f}", "#E54D2E" if total_pnl >= 0 else "#3fb950"),
            ("持仓数", f"{len(holds)}只", "#EEEEEE"),
        ]
        for label, value, color in card_data:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(160, 60)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 6, 12, 6)
            l = QLabel(label)
            l.setStyleSheet("color:#B4B4B4; font-size:10px; background:transparent;")
            cl.addWidget(l)
            v = QLabel(value)
            v.setStyleSheet(f"color:{color}; font-size:16px; font-weight:bold; background:transparent;")
            cl.addWidget(v)
            self.holdings_cards.addWidget(card)

        self.holdings_table.setRowCount(len(holds))
        self.holdings_table.setColumnCount(5)
        self.holdings_table.setHorizontalHeaderLabels(["代码", "名称", "成本", "现价", "盈亏"])
        for i, h in enumerate(holds):
            pnl = (h.get("current", 0) - h.get("cost", 0)) * h.get("shares", 0)
            items = [
                QTableWidgetItem(h.get("code", "")),
                QTableWidgetItem(h.get("name", "")),
                QTableWidgetItem(f"{h.get('cost', 0):.2f}"),
                QTableWidgetItem(f"{h.get('current', 0):.2f}"),
                QTableWidgetItem(f"{'+'if pnl>=0 else ''}{pnl:,.0f}"),
            ]
            items[4].setForeground(QColor("#E54D2E" if pnl >= 0 else "#3fb950"))
            for j, item in enumerate(items):
                self.holdings_table.setItem(i, j, item)
        self.holdings_table.resizeColumnsToContents()
        self.status.showMessage(f"持仓: {len(holds)}只, 市值 {total_val:,.0f}")

    def on_holdings_click(self, row, col):
        code_item = self.holdings_table.item(row, 0)
        name_item = self.holdings_table.item(row, 1)
        if code_item:
            self.open_kline(code_item.text(), name_item.text() if name_item else "")

    # === Data Center ===
    def _load_dc(self):
        self.status.showMessage('加载数据表...')
        if not hasattr(self, 'dc_overview'):
            self.dc_overview = QHBoxLayout()
        try:
            for i in reversed(range(self.dc_overview.count())):
                w = self.dc_overview.itemAt(i).widget()
                if w: w.deleteLater()
            self.dc_list.clear()
            db_paths = [
                (os.path.join(PROJECT_DIR, 'data', 'kline.db'), 'K线库', '#3fb950'),
                (os.path.join(PROJECT_DIR, 'data', 'stock_cache.db'), '缓存库', '#FFE0C2'),
            ]
            self._dc_tables = []
            total_global_rows = 0
            for db_path, label, color in db_paths:
                if not os.path.exists(db_path):
                    card = self._make_info_card(label + chr(10) + '未找到', color, 140, 56)
                    self.dc_overview.addWidget(card)
                    continue

                sz_mb = os.path.getsize(db_path) / 1048576
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                names = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                for (name,) in names:
                    cnt = cur.execute('SELECT COUNT(*) FROM [%s]' % name).fetchone()[0]
                    cur.execute('PRAGMA table_info([%s])' % name)
                    col_info = [(c[1], c[2]) for c in cur.fetchall()]
                    t = {'name': name, 'count': cnt, 'db_path': db_path, 'db': label, 'cols': col_info}
                    self._dc_tables.append(t)
                    total_global_rows += cnt
                    txt = '[%s] %s    %s 行' % (label, name, '{:,}'.format(cnt))
                    item = QListWidgetItem(txt)
                    item.setData(Qt.UserRole, t)
                    self.dc_list.addItem(item)
                conn.close()

                card = self._make_info_card(label, color, 140, 56)
                self.dc_overview.addWidget(card)
                lbl = card.findChildren(QLabel)[-1]
                lbl.setText('%.0f MB - %d 个表' % (sz_mb, len(names)))

            msg = '%d 个表, %s 行' % (len(self._dc_tables), '{:,}'.format(total_global_rows))
            self.status.showMessage(msg)
        except Exception as e:
            import traceback as _tb
            self.status.showMessage('加载失败: ' + str(e))
            with open(os.path.join(PROJECT_DIR, "dc_err.txt"), "w") as f:
                _tb.print_exc(file=f)

    def _make_info_card(self, text, color, w=140, h=56):
        card = QFrame()
        card.setObjectName('card')
        card.setFixedSize(w, h)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 4, 8, 4)
        cl.setSpacing(0)
        lbl = QLabel(text)
        lbl.setStyleSheet('color:%s; font-size:12px; font-weight:bold; background:transparent;' % color)
        lbl.setAlignment(Qt.AlignCenter)
        cl.addWidget(lbl)
        self.dc_overview.addWidget(card)
        return card

    def on_dc_select(self, item):
        t = item.data(Qt.UserRole)
        if not t:
            return
        try:
            self.status.showMessage('加载 ' + t['name'] + '...')
            self._dc_selected_table = t
            conn = sqlite3.connect(t['db_path'])
            cur = conn.cursor()
            query = ('SELECT k.code, k.date, k.open, k.high, k.low, k.close, k.volume, k.amount'
                     ' FROM kline_daily k'
                     ' WHERE k.date = (SELECT MAX(date) FROM kline_daily WHERE code = k.code)'
                     ' ORDER BY k.volume DESC LIMIT 500'
                     if t['name'] == 'kline_daily'
                     else 'SELECT * FROM [%s] LIMIT 500' % t['name'])
            cur.execute(query)
            rows = cur.fetchall()
            cols_str = [d[0] for d in cur.description] if cur.description else []
            if t['name'] == 'kline_daily':
                # Add name column via separate query
                conn2 = sqlite3.connect(t['db_path'])
                names = dict(conn2.execute('SELECT code, name FROM stock_list').fetchall())
                conn2.close()
                rows = [list(r) + [names.get(r[0], '')] for r in rows]
                cols_str = cols_str + ['name']
            conn.close()

            self._dc_cols = cols_str
            self._dc_rows = rows
 
            self.status.showMessage('%s | %s 行 | %d 列 | %s' % (t['name'], '{:,}'.format(t['count']), len(cols_str), t['db']))

            self._fill_dc_table(rows, cols_str)
            msg = '%s -- %d/%s 行, %d 列, %s'
            self.status.showMessage(msg % (t['name'], len(rows), '{:,}'.format(t['count']), len(cols_str), t['db']))
        except Exception as e:
            self.status.showMessage('查询失败: ' + str(e))

    def _fill_dc_table(self, rows, cols):
        n_rows = len(rows)
        n_cols = len(cols)
        # 完全重置：先清为 0 再设置，避免旧状态干扰
        self.dc_table.setRowCount(0)
        self.dc_table.setColumnCount(0)
        self.dc_table.setRowCount(n_rows)
        self.dc_table.setColumnCount(n_cols + 1)
        CN = {
            'code':'代码','date':'日期','open':'开盘','high':'最高',
            'low':'最低','close':'收盘','volume':'成交量','amount':'成交额',
            'name':'名称','board':'板块','status':'状态','last_date':'最后日期',
            'total_days':'总天数','up_count':'上涨','down_count':'下跌',
            'id':'序号','update_date':'更新日期','rows_added':'新增行',
            'duration':'耗时','price':'价格','change_pct':'涨跌幅',
            'turnover':'换手率','score':'评分','reasons':'理由',
            'net_value':'净流入','main_net':'主力净流入','type':'类型',
            'change_amount':'成交额','count':'计数',
        }
        cols_cn = [CN.get(c, c) for c in cols]
        self.dc_table.setHorizontalHeaderLabels(['#'] + cols_cn)

        bg_even = QColor('#111111')
        bg_odd = QColor('#191919')
        for r, row in enumerate(rows):
            bg = bg_odd if r % 2 else bg_even
            rn = QTableWidgetItem(str(r + 1))
            rn.setForeground(QColor('#484848'))
            rn.setBackground(bg)
            rn.setFlags(Qt.ItemIsEnabled)
            self.dc_table.setItem(r, 0, rn)

            for c, val in enumerate(row):
                if val is None:
                    cell = QTableWidgetItem('NULL')
                    cell.setForeground(QColor('#E54D2E'))
                    cell.setBackground(bg)
                    cell.setFont(QFont('Consolas', 9, -1, True))
                else:
                    text = str(val)
                    cell = QTableWidgetItem(text)
                    cell.setBackground(bg)
                    if isinstance(val, (int, float)):
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        cell.setFont(QFont('Consolas', 10))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.dc_table.setItem(r, c + 1, cell)

        self.dc_table.setColumnWidth(0, 40)
        for i in range(n_cols):
            max_w = 80
            for j in range(min(50, n_rows)):
                txt = str(rows[j][i]) if rows[j][i] is not None else 'NULL'
                max_w = max(max_w, len(txt) * 9 + 20)
            self.dc_table.setColumnWidth(i + 1, min(250, max_w))
        self.dc_table.horizontalHeader().setStretchLastSection(False)
        self.dc_table.resizeRowsToContents()
        self.dc_table.update()
        self.status.showMessage('表格: %d 行 x %d 列' % (n_rows, n_cols + 1))

    def _dc_filter_table(self, text):
        if not hasattr(self, '_dc_rows') or not self._dc_rows:
            return
        q = text.strip().lower()
        if not q:
            # Reset to stock overview for kline_daily
            if self._dc_selected_table and self._dc_selected_table['name'] == 'kline_daily':
                item = self.dc_list.currentItem()
                if not item:
                    return
                self.on_dc_select(self.dc_list.currentItem())
                return
            self._fill_dc_table(self._dc_rows, self._dc_cols)
            return
        # For kline_daily: query all data for matching stock
        if self._dc_selected_table and self._dc_selected_table['name'] == 'kline_daily':
            code_q = q.upper()
            conn = sqlite3.connect(self._dc_selected_table['db_path'])
            rows = conn.execute('SELECT * FROM kline_daily WHERE code=? ORDER BY date',
                               (code_q,)).fetchall()
            cols_str = [d[0] for d in conn.description] if conn.description else []
            conn.close()
            self._dc_rows = rows
            self._dc_cols = cols_str
            self._fill_dc_table(rows, cols_str)
            self.status.showMessage('个股代码 %s | %d 条K线' % (code_q, len(rows)))
            return
        # Default: in-memory filter
        filtered = [row for row in self._dc_rows if any(str(v).lower().find(q) >= 0 for v in row if v is not None)]
        self._fill_dc_table(filtered, self._dc_cols)
        fmt = '%s | 过滤: %d/%s 行'
        self.status.showMessage(fmt % (self._dc_selected_table['name'], len(filtered), '{:,}'.format(len(self._dc_rows))))

    # === K-line ===
    def open_kline(self, code, name):
        try:
            self.k_search.setText(f'{name} ({code})')
            self.status.showMessage(f"加载 {name}({code}) K线...")
            self.right_stack.setCurrentIndex(0)
            self._kline_worker = ApiThread(f"{API}/api/kline?code={code}&days=180", "kline")
            self._kline_worker.result.connect(self._on_kline_data)
            self._kline_worker.start()
        except Exception as e:
            self.status.showMessage(f"K线请求失败: {e}")

    def _on_kline_data(self, tag, data):
        try:
            if data.get("code") != 0 or not data.get("data"):
                self.status.showMessage("K线数据加载失败")
                return
            bars = data.get("data", [])
            self.kline_chart.set_data(data, bars[0].get("code",""), bars[0].get("name",""))
            self.status.showMessage("K线已加载")
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            self.status.showMessage(f"显示K线失败: {e}")

    def _k_search_stock(self):
        text = self.k_search.text().strip()
        if not text:
            return
        conn = sqlite3.connect(KLINE_DB)
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
            self.k_search.setText(f'{row[1]} ({row[0]})')
            self.open_kline(row[0], row[1])
        else:
            self.status.showMessage(f'未找到: {text}')

    # === Helpers ===
    def _fill_stock_table(self, table, data, with_rank=False, with_price=False, with_score=False):
        cols = []
        if with_rank:
            cols.append("#")
        cols += ["代码", "名称"]
        if with_price:
            cols.append("价格")
        cols.append("涨跌幅")
        if with_score:
            cols.append("评分")

        table.setRowCount(len(data))
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)

        for i, s in enumerate(data):
            col_idx = 0
            if with_rank:
                table.setItem(i, col_idx, QTableWidgetItem(str(i + 1)))
                col_idx += 1
            table.setItem(i, col_idx, QTableWidgetItem(s.get("code", "")))
            col_idx += 1
            table.setItem(i, col_idx, QTableWidgetItem(s.get("name", "")))
            col_idx += 1
            if with_price:
                table.setItem(i, col_idx, QTableWidgetItem(f"{s.get('price', 0):.2f}"))
                col_idx += 1
            chg = s.get("change_pct", 0)
            chg_item = QTableWidgetItem(f"{'+'if chg>=0 else ''}{chg:.2f}%")
            chg_item.setForeground(QColor("#E54D2E" if chg >= 0 else "#3fb950"))
            table.setItem(i, col_idx, chg_item)
            col_idx += 1
            if with_score:
                sc = s.get("score", "--")
                score_item = QTableWidgetItem(str(sc) if sc is not None else "--")
                table.setItem(i, col_idx, score_item)
                col_idx += 1
        table.resizeColumnsToContents()
        table.setColumnWidth(1, 60)
        table.setColumnWidth(2, 100)


    def _switch_kline_indicator(self, ind_type):
        """Switch sub-indicator for K-line chart."""
        self.kline_chart.switch_indicator(ind_type)
        self.k_btn_macd.setChecked(ind_type == "macd")
        self.k_btn_rsi.setChecked(ind_type == "rsi")

    def refresh_all(self):
        for b in self.tab_btns:
            b.setChecked(False)
        self._tab_loaded = [False, False, False, False]
        self._switch_left_tab(0)
        self.status.showMessage("已刷新")


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("叶瞬光量化选股 桌面端 v3.0 (本地模式)")
        print("启动: python desktop_app.py")
        print("启动后点击导航栏加载数据，所有数据走本地 kline.db")
        print("依赖: PyQt5, matplotlib, numpy, data/kline.db")
        sys.exit(0)
    try:
        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("fusion"))
        app.setStyleSheet(STYLE)
        w = DesktopApp()
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        with open(os.path.join(PROJECT_DIR, "desktop_error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"FATAL: {e}")
