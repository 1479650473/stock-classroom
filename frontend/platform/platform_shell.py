# -*- coding: utf-8 -*-
"""Platform Shell — thin QMainWindow skeleton for stock-classroom."""

import sys, os, traceback, json

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QStackedWidget, QFrame, QStyleFactory
)
from PyQt5.QtCore import Qt, QTimer

from .theme import STYLE
from .log_window import LogStream, LogWindow
from .plugin_base import PlatformBus, PlatformServices, PluginRegion
from .plugin_manager import PluginManager


if getattr(sys, 'frozen', False):
    _APP_DIR = sys._MEIPASS
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KLINE_DB = os.path.join(PROJECT_DIR, "data", "kline.db")
CACHE_DB = os.path.join(PROJECT_DIR, "data", "stock_cache.db")
PLUGINS_DIR = os.path.join(_APP_DIR, "frontend", "plugins")
CONFIG_PATH = os.path.join(PLUGINS_DIR, "plugins.json")


class PlatformShell(QMainWindow):
    """The platform skeleton. Holds PluginManager and all chrome."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("stock-classroom")
        self.setGeometry(50, 20, 1500, 920)
        self.setMinimumSize(1100, 700)

        # ── Ensure data dir exists ──
        os.makedirs(os.path.join(PROJECT_DIR, "data"), exist_ok=True)

        # ── Frozen mode: ensure backend on sys.path ──
        if getattr(sys, 'frozen', False):
            be = os.path.join(_APP_DIR, "backend")
            if be not in sys.path:
                sys.path.insert(0, be)
            if _APP_DIR not in sys.path:
                sys.path.insert(0, _APP_DIR)

        # ── Log terminal ──
        self._log_window = LogWindow()
        self._log_stream = LogStream()
        self._log_stream.text_written.connect(self._log_window.append)
        sys.stdout = self._log_stream
        sys.stderr = self._log_stream

        # ── Event bus + services ──
        self._bus = PlatformBus()
        self._services = PlatformServices(
            db_path=KLINE_DB,
            cache_path=CACHE_DB,
            bus=self._bus,
        )
        self._bus.status_message.connect(lambda msg: self.status.showMessage(msg))
        self._bus.log_message.connect(self._log_window.append)

        # ── Plugin manager ──
        self._plugin_mgr = PluginManager(CONFIG_PATH, PLUGINS_DIR)
        self._plugin_mgr.inject_services(self._services)

        print("stock-classroom v4.0 启动")
        print(f"[Platform] {len(self._plugin_mgr.all_plugins())} 插件已加载: "
              + ", ".join(self._plugin_mgr.all_plugins().keys()))

        self._build_ui()
        self.status.showMessage("就绪 — 点击左侧导航加载数据")

        # Activate defaults
        config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        QTimer.singleShot(100, lambda: self._activate_defaults(config))

    def _activate_defaults(self, config: dict):
        default_left = config.get("default_left", "market")
        default_right = config.get("default_right", "kline")
        for pid in [default_left, default_right]:
            if pid in self._plugin_mgr.all_plugins():
                self._activate_plugin(pid)

    def _build_ui(self):
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
        lbl_brand = QLabel("stock-classroom")
        lbl_brand.setStyleSheet("color:#D4A574; font-size:17px; font-weight:700; border:none;")
        logo_lo.addWidget(lbl_brand)
        tl.addWidget(logo)
        tl.addStretch()

        # TOPBAR plugin slot
        for pid, plugin in self._plugin_mgr.all_plugins().items():
            if plugin.region == PluginRegion.TOPBAR:
                try:
                    w = self._plugin_mgr.get_widget(pid)
                    if w:
                        tl.addWidget(w)
                except Exception:
                    pass

        refresh = QPushButton("刷新")
        refresh.setObjectName("refreshBtn")
        refresh.setFixedHeight(30)
        refresh.clicked.connect(lambda: self._plugin_mgr.refresh_current())
        tl.addWidget(refresh)

        log_btn = QPushButton("日志")
        log_btn.setFixedSize(48, 30)
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setStyleSheet(
            "QPushButton{background:#161B22;color:#8B949E;border:1px solid #30363D;"
            "border-radius:6px;font-size:11px}"
            "QPushButton:hover{background:#1C2128;border-color:#484F58}")
        log_btn.clicked.connect(lambda: self._log_window.show()
                                if self._log_window.isHidden()
                                else self._log_window.hide())
        tl.addWidget(log_btn)
        layout.addWidget(topbar)

        # ═══ Main Splitter ═══
        outer = QSplitter(Qt.Horizontal)
        outer.setHandleWidth(1)

        # ── Left: Nav + Panel Stack ──
        left_widget = QWidget()
        left_lo = QHBoxLayout(left_widget)
        left_lo.setContentsMargins(0, 0, 0, 0)
        left_lo.setSpacing(0)

        nav_panel = QWidget()
        nav_panel.setFixedWidth(72)
        nav_panel.setStyleSheet("background:#0D1117; border-right:1px solid #21262D;")
        nav_lo = QVBoxLayout(nav_panel)
        nav_lo.setContentsMargins(6, 12, 6, 12)
        nav_lo.setSpacing(4)

        self._nav_btns = {}
        for pid, name, icon, region in self._plugin_mgr.get_nav_items():
            btn = self._make_nav_btn(pid, name, icon)
            nav_lo.addWidget(btn)
            self._nav_btns[pid] = btn

        nav_lo.addStretch()
        left_lo.addWidget(nav_panel)

        self._left_stack = QStackedWidget()
        self._left_stack.setStyleSheet("background:#0D1117;")
        left_lo.addWidget(self._left_stack, 1)
        outer.addWidget(left_widget)

        # ── Right: Panel Stack ──
        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(0)

        self._right_stack = QStackedWidget()
        self._right_stack.setStyleSheet("background:#0D1117;")
        rl.addWidget(self._right_stack)
        outer.addWidget(right_widget)

        outer.setSizes([380, 820])
        layout.addWidget(outer)

        # ═══ Watermark (platform layer) ═══
        self._watermark = QLabel("develop by siyuan-chen & xiaoguang", self)
        self._watermark.setStyleSheet(
            "color:rgba(139,148,158,60);font-size:10px;background:transparent;border:none;")
        self._watermark.adjustSize()

        # ═══ Status Bar ═══
        self.status = QStatusBar()
        self.status.setStyleSheet(
            "QStatusBar{background:#161B22;color:#8B949E;border-top:1px solid #21262D;"
            "font-size:12px;padding:2px 12px;}")
        self._status_dot = QLabel("\u25cf")
        self._status_dot.setStyleSheet("color:#3fb950;font-size:10px;border:none;padding-right:4px;")
        self.status.addPermanentWidget(self._status_dot)
        self.setStatusBar(self.status)

    def _make_nav_btn(self, pid: str, name: str, icon: str):
        """Create a nav button with emoji icon on top + text below."""
        btn = QPushButton()
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        btn.setFixedSize(60, 56)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setText(f"{icon}\n{name}")
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
        btn.clicked.connect(lambda checked, pid=pid: self._activate_plugin(pid))
        return btn

    def _activate_plugin(self, plugin_id: str):
        """Activate a plugin and show its widget in the correct region."""
        plugin = self._plugin_mgr.get_plugin(plugin_id)
        if not plugin:
            return

        region = plugin.region

        # Update nav button states
        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == plugin_id)

        # TOPBAR widgets are always shown, no stack needed
        if region == PluginRegion.TOPBAR:
            return

        # Activate in PluginManager (handles deactivation + error wrapping)
        self._plugin_mgr.activate(plugin_id)

        # Get the error-wrapped widget
        boundary = self._plugin_mgr.get_widget(plugin_id)
        if not boundary:
            return

        # Place in correct stack
        if region == PluginRegion.LEFT:
            stack = self._left_stack
        else:
            stack = self._right_stack

        for i in range(stack.count()):
            if stack.widget(i) is boundary:
                stack.setCurrentIndex(i)
                return
        stack.addWidget(boundary)
        stack.setCurrentWidget(boundary)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_watermark'):
            self._watermark.move(
                self.width() - self._watermark.width() - 14,
                self.height() - self._watermark.height() - 36
            )

    def closeEvent(self, event):
        self._plugin_mgr.shutdown_all()
        event.accept()
