import sys, os, json, sqlite3, traceback
from datetime import datetime
import requests
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
KLINE_DB = os.path.join(PROJECT_DIR, "data", "kline.db")
CACHE_DB = os.path.join(PROJECT_DIR, "data", "stock_cache.db")

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QStatusBar, QPlainTextEdit,
    QStyleFactory, QFrame, QStackedWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt5.QtGui import QColor, QFont, QPalette
from frontend.panels.market_panel import MarketPanel
from frontend.panels.picks_panel import PicksPanel
from frontend.panels.holdings_panel import HoldingsPanel
from frontend.panels.dc_panel import DCPanel
from frontend.kline_widget import KlineWidget as KlineChart

API = "http://127.0.0.1:5000"

STYLE = """
/* ============================================================
   YeLight — Premium Dark Theme
   ============================================================ */
QMainWindow, QWidget {
    background-color: #0D1117;
    color: #E6EDF3;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}
/* ── Cards ── */
QFrame#card {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 8px;
}
QFrame#card:hover {
    border-color: #30363D;
}

/* ── Lists ── */
QListWidget {
    background: #0D1117;
    color: #E6EDF3;
    border: 1px solid #21262D;
    border-radius: 6px;
    outline: none;
}
QListWidget::item {
    padding: 6px 12px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QListWidget::item:hover:!selected {
    background: #1C2128;
}

/* ── Tables ── */
QTableWidget {
    background: #0D1117;
    color: #E6EDF3;
    border: 1px solid #21262D;
    border-radius: 6px;
    gridline-color: #1A1F28;
}
QTableWidget::item {
    padding: 4px 10px;
    border-bottom: 1px solid #1A1F28;
}
QTableWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QTableWidget::item:hover:!selected {
    background: #1C2128;
}
QHeaderView::section {
    background: #161B22;
    color: #8B949E;
    border: none;
    border-bottom: 2px solid #21262D;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 12px;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #1A1F28;
}

/* ── Line Edit ── */
QLineEdit {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #D4A574;
}
QLineEdit[placeholderText] {
    color: #484F58;
}

/* ── Push Button ── */
QPushButton {
    background: #1C2128;
    color: #C9D1D9;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 5px 16px;
    font-size: 12px;
}
QPushButton:hover {
    background: #252A35;
    border-color: #484F58;
}
QPushButton:pressed {
    background: #161B22;
}
QPushButton:checked {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border-color: #D4A574;
}

/* ── Refresh Button ── */
QPushButton#refreshBtn {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border: 1px solid #D4A574;
}
QPushButton#refreshBtn:hover {
    background: rgba(212, 165, 116, 0.18);
}

/* ── Nav Buttons (sidebar style) ── */
QPushButton#navBtn {
    background: transparent;
    color: #8B949E;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    text-align: left;
}
QPushButton#navBtn:hover {
    background: #1C2128;
    color: #C9D1D9;
}
QPushButton#navBtn:checked {
    background: rgba(212, 165, 116, 0.08);
    color: #D4A574;
    border-left: 3px solid #D4A574;
}

/* ── Indicator Buttons (segmented control) ── */
QPushButton#indBtn {
    background: #161B22;
    color: #8B949E;
    border: 1px solid #30363D;
    border-radius: 4px;
    padding: 3px 14px;
    font-size: 12px;
}
QPushButton#indBtn:checked {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border-color: #D4A574;
}

/* ── CheckBox ── */
QCheckBox {
    color: #8B949E;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30363D;
    border-radius: 3px;
    background: #161B22;
}
QCheckBox::indicator:checked {
    background: #D4A574;
    border-color: #D4A574;
}
QCheckBox::indicator:hover {
    border-color: #484F58;
}

/* ── ComboBox ── */
QComboBox {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 4px 10px;
}
QComboBox:hover { border-color: #484F58; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    selection-background-color: rgba(212, 165, 116, 0.12);
    selection-color: #D4A574;
}

/* ── Tree Widget ── */
QTreeWidget {
    background: #0D1117;
    color: #C9D1D9;
    border: 1px solid #21262D;
    border-radius: 6px;
    outline: none;
}
QTreeWidget::item {
    padding: 4px 8px;
    border-radius: 3px;
}
QTreeWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QTreeWidget::item:hover:!selected {
    background: #1C2128;
}
QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
    border: none;
}

/* ── ScrollBar ── */
QScrollBar:vertical {
    background: #0D1117;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363D;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #484F58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #0D1117;
    height: 8px;
    margin: 0;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #30363D;
    min-width: 30px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #484F58;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── ToolTip ── */
QToolTip {
    background: #1C2128;
    color: #E6EDF3;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
}

/* ── Splitter ── */
QSplitter::handle {
    background: #21262D;
    width: 1px;
}

/* ── StatusBar ── */
QStatusBar {
    background: #161B22;
    color: #8B949E;
    border-top: 1px solid #21262D;
    font-size: 11px;
    padding: 2px 12px;
}

/* ── Scroll Area ── */
QScrollArea {
    border: none;
}
"""


class ApiThread(QThread):
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


class LogStream(QObject):
    text_written = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        if '\n' in self._buffer:
            lines = self._buffer.split('\n')
            self._buffer = lines[-1]
            for line in lines[:-1]:
                if line.strip():
                    self.text_written.emit(line)

    def flush(self):
        if self._buffer.strip():
            self.text_written.emit(self._buffer)
            self._buffer = ""


class LogWindow(QWidget):
    """Floating log/terminal window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(700, 400)
        self.setGeometry(100, 100, 800, 480)
        self.setStyleSheet("background:#0D1117;")

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        hbar = QHBoxLayout()
        hbar.setContentsMargins(12, 6, 12, 6)
        lbl = QLabel("控制台输出")
        lbl.setStyleSheet("color:#D4A574;font-size:13px;font-weight:600;background:transparent")
        hbar.addWidget(lbl)
        hbar.addStretch()
        self._count_lbl = QLabel("0 行")
        self._count_lbl.setStyleSheet("color:#484F58;font-size:11px;background:transparent")
        hbar.addWidget(self._count_lbl)
        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 24)
        clear_btn.setStyleSheet(
            "QPushButton{background:#161B22;color:#8B949E;border:1px solid #30363D;border-radius:4px;font-size:10px}"
            "QPushButton:hover{background:#1C2128;border-color:#484F58}")
        clear_btn.clicked.connect(self._clear)
        hbar.addWidget(clear_btn)
        lo.addLayout(hbar)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QPlainTextEdit{background:#0D1117;color:#E6EDF3;border:none;"
            "font-family:Consolas,'Courier New',monospace;font-size:11px;"
            "line-height:1.4;padding:6px 12px;}")
        lo.addWidget(self._log, 1)
        self._line_count = 0

    def append(self, text):
        self._log.appendPlainText(text)
        self._line_count += 1
        self._count_lbl.setText(f"{self._line_count} 行")
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear(self):
        self._log.clear()
        self._line_count = 0
        self._count_lbl.setText("0 行")

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class DesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YeLight — 量化选股")
        self.setGeometry(50, 20, 1500, 920)
        self.setMinimumSize(1100, 700)
        self.search_results = []
        self._tab_loaded = [False, False, False, False]

        self._log_window = LogWindow()
        self._log_stream = LogStream()
        self._log_stream.text_written.connect(self._log_window.append)
        sys.stdout = self._log_stream
        sys.stderr = self._log_stream
        print("YeLight 启动")

        self.build_ui()
        self.status.showMessage("就绪 — 点击左侧导航加载数据")

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ═══ Top Bar ═══
        topbar = QFrame()
        topbar.setFixedHeight(48)
        topbar.setStyleSheet("background:#161B22; border-bottom:1px solid #21262D;")
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(16, 0, 16, 0)

        logo = QWidget()
        logo_lo = QHBoxLayout(logo)
        logo_lo.setContentsMargins(0, 0, 0, 0)
        logo_lo.setSpacing(4)
        lbl_brand = QLabel("YeLight")
        lbl_brand.setStyleSheet("color:#D4A574; font-size:17px; font-weight:700; border:none;")
        logo_lo.addWidget(lbl_brand)
        lbl_sub = QLabel("量化选股")
        lbl_sub.setStyleSheet("color:#8B949E; font-size:13px; font-weight:400; border:none;")
        logo_lo.addWidget(lbl_sub)
        tl.addWidget(logo)

        tl.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("输入代码或名称搜索")
        self.search.setFixedSize(300, 30)
        self.search.setStyleSheet(
            "QLineEdit{background:#1C2128;color:#E6EDF3;border:1px solid #30363D;"
            "border-radius:15px;padding:4px 16px;font-size:13px;}"
            "QLineEdit:focus{border-color:#D4A574;}")
        self.search.textChanged.connect(self.on_search)
        self.search.returnPressed.connect(self.on_search_enter)
        tl.addWidget(self.search)

        refresh = QPushButton("刷新")
        refresh.setObjectName("refreshBtn")
        refresh.setFixedHeight(30)
        refresh.clicked.connect(self.refresh_all)
        tl.addWidget(refresh)

        log_btn = QPushButton("日志")
        log_btn.setFixedSize(48, 30)
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setStyleSheet(
            "QPushButton{background:#161B22;color:#8B949E;border:1px solid #30363D;border-radius:6px;font-size:11px}"
            "QPushButton:hover{background:#1C2128;border-color:#484F58}")
        log_btn.clicked.connect(lambda: self._log_window.show() if self._log_window.isHidden() else self._log_window.hide())
        tl.addWidget(log_btn)
        layout.addWidget(topbar)

        # ═══ Main Splitter ═══
        outer = QSplitter(Qt.Horizontal)
        outer.setHandleWidth(1)

        # ── Left: Navigation + Panel ──
        left_widget = QWidget()
        left_lo = QVBoxLayout(left_widget)
        left_lo.setContentsMargins(0, 0, 0, 0)
        left_lo.setSpacing(0)

        nav_panel = QWidget()
        nav_panel.setFixedWidth(72)
        nav_panel.setStyleSheet("background:#0D1117; border-right:1px solid #21262D;")
        nav_lo = QVBoxLayout(nav_panel)
        nav_lo.setContentsMargins(6, 12, 6, 12)
        nav_lo.setSpacing(4)

        self.tab_btns = []
        nav_items = [
            ("market", "市场"),
            ("picks", "选股"),
            ("holdings", "持仓"),
            ("data", "数据"),
        ]
        for tag, name in nav_items:
            btn = QPushButton(name)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setFixedSize(60, 56)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton#navBtn {
                    background: transparent;
                    color: #8B949E;
                    border: none;
                    border-radius: 6px;
                     padding: 0px;
                     font-size: 14px;
                     font-weight: 500;
                }
                QPushButton#navBtn:hover {
                    background: #1C2128;
                    color: #C9D1D9;
                }
                QPushButton#navBtn:checked {
                    background: rgba(212, 165, 116, 0.10);
                    color: #D4A574;
                    font-weight: 600;
                }
            """)
            btn.clicked.connect(lambda checked, idx=len(self.tab_btns): self._switch_left_tab(idx))
            nav_lo.addWidget(btn)
            self.tab_btns.append(btn)

        nav_lo.addStretch()

        body_wrapper = QWidget()
        body_wrapper_lo = QHBoxLayout(body_wrapper)
        body_wrapper_lo.setContentsMargins(0, 0, 0, 0)
        body_wrapper_lo.setSpacing(0)
        body_wrapper_lo.addWidget(nav_panel)

        self.left_stack = QStackedWidget()
        self.left_stack.setStyleSheet("background:#0D1117;")

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
        self.holdings_panel.on_open_kline = self.open_kline
        self.left_stack.addWidget(self.holdings_panel)

        self.dc_panel = DCPanel()
        self.dc_panel.db_path = KLINE_DB
        self.dc_panel.cache_path = CACHE_DB
        self.dc_panel.on_status = lambda msg: self.status.showMessage(msg)
        self.left_stack.addWidget(self.dc_panel)

        body_wrapper_lo.addWidget(self.left_stack)
        left_lo.addWidget(body_wrapper)
        outer.addWidget(left_widget)

        # ── Right: K-line ──
        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(6)

        k_bar = QHBoxLayout()
        k_bar.setSpacing(8)

        self.k_search = QLineEdit()
        self.k_search.setPlaceholderText("搜索股票代码或名称")
        self.k_search.setStyleSheet(
            "QLineEdit{background:#161B22;color:#E6EDF3;border:1px solid #30363D;"
            "border-radius:6px;padding:5px 12px;font-size:12px;}"
            "QLineEdit:focus{border-color:#D4A574;}")
        self.k_search.returnPressed.connect(self._k_search_stock)
        k_bar.addWidget(self.k_search, 1)

        k_bar.addWidget(QLabel("指标", styleSheet="color:#8B949E;font-size:12px;font-weight:500;"))

        self.k_btn_macd = QPushButton("MACD")
        self.k_btn_macd.setObjectName("indBtn")
        self.k_btn_macd.setCheckable(True)
        self.k_btn_macd.setChecked(True)
        self.k_btn_macd.setFixedHeight(26)
        self.k_btn_macd.clicked.connect(lambda: self._switch_kline_indicator("macd"))
        k_bar.addWidget(self.k_btn_macd)

        self.k_btn_rsi = QPushButton("RSI")
        self.k_btn_rsi.setObjectName("indBtn")
        self.k_btn_rsi.setCheckable(True)
        self.k_btn_rsi.setFixedHeight(26)
        self.k_btn_rsi.clicked.connect(lambda: self._switch_kline_indicator("rsi"))
        k_bar.addWidget(self.k_btn_rsi)

        k_bar.addStretch()
        rl.addLayout(k_bar)

        self.kline_chart = KlineChart()
        rl.addWidget(self.kline_chart)

        outer.addWidget(right_widget)
        outer.setSizes([380, 820])

        layout.addWidget(outer)

        # ═══ Status Bar ═══
        self.status = QStatusBar()
        self.status.setStyleSheet(
            "QStatusBar{background:#161B22;color:#8B949E;border-top:1px solid #21262D;"
            "font-size:12px;padding:2px 12px;}")
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color:#3fb950;font-size:10px;border:none;padding-right:4px;")
        self.status.addPermanentWidget(self._status_dot)
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")

        QTimer.singleShot(100, lambda: self._switch_left_tab(0))

    # ─── Search ───
    def on_search(self, text):
        if len(text) < 2:
            return

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

    # ─── Navigation ───
    def _switch_left_tab(self, idx):
        for i, btn in enumerate(self.tab_btns):
            btn.setChecked(i == idx)
        self.left_stack.setCurrentIndex(idx)
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

    # ─── K-line ───
    def open_kline(self, code, name):
        try:
            self.k_search.setText(f'{name} ({code})')
            self.status.showMessage(f"加载 {name}({code}) K线...")
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

    def _switch_kline_indicator(self, ind_type):
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
        print("YeLight 量化选股 v4.0")
        print("启动: python desktop_app.py")
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
