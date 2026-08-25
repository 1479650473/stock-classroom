# -*- coding: utf-8 -*-
"""Platform Shell — thin QMainWindow skeleton for stock-classroom."""

import sys, os, traceback, json

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QStackedWidget, QFrame, QStyleFactory
)
from PyQt5.QtCore import Qt, QTimer

from .theme import (
    STYLE, dp, dps, fs,
    C_BG, C_PANEL, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_RAISED, C_DOWN,
)
from .log_window import LogStream, LogWindow
from .plugin_base import PlatformBus, PlatformServices, PluginRegion
from .plugin_manager import PluginManager

APP_VERSION = "v4.3"

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

        ws = "large"
        self._font_size = 13
        try:
            from frontend.plugins.settings.config import load_settings
            _s = load_settings()
            ws = _s.get("window_size", "large")
            self._font_size = _s.get("font_size", 13)
        except Exception:
            pass
        sizes = {"small": (1400, 850), "medium": (1550, 950), "large": (1980, 1280)}
        w, h = sizes.get(ws, sizes["large"])
        self.setGeometry(50, 20, w, h)
        self.setMinimumSize(1200, 800)

        # ── Ensure data dir exists ──
        os.makedirs(os.path.join(PROJECT_DIR, "data"), exist_ok=True)

        # ── Frozen mode: ensure backend on sys.path ──
        if getattr(sys, 'frozen', False):
            be = os.path.join(_APP_DIR, "backend")
            if be not in sys.path:
                sys.path.insert(0, be)
            if _APP_DIR not in sys.path:
                sys.path.insert(0, _APP_DIR)

        # ── App config (cached once) ──
        self._config = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            except Exception:
                self._config = {}

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

        print("stock-classroom %s 启动" % APP_VERSION)
        print(f"[Platform] {len(self._plugin_mgr.all_plugins())} 插件已加载: "
              + ", ".join(self._plugin_mgr.all_plugins().keys()))

        self._build_ui()
        self.status.showMessage("就绪 — 点击左侧导航加载数据")

        # 主题切换即时重绘: 重建全局样式 + 通知各面板/图表
        from frontend.platform import theme as th
        th.signals.changed.connect(self._on_theme_changed)

        QTimer.singleShot(100, self._activate_defaults)

    def _activate_defaults(self):
        default_left = self._config.get("default_left", "market")
        default_right = self._config.get("default_right", "kline")
        for pid in [default_left, default_right]:
            if pid in self._plugin_mgr.all_plugins():
                self._activate_plugin(pid)

    # ──────────────────────────────────────────────────────────
    #  UI
    # ──────────────────────────────────────────────────────────

    def _on_theme_changed(self):
        """主题切换即时重绘：重建全局样式 + 通知各面板/图表重上色."""
        from PyQt5.QtWidgets import QApplication, QWidget
        from frontend.platform.theme import build_style
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_style(self._font_size))
        try:
            from frontend.plugins.kline.widget import resync_theme
            resync_theme()
        except Exception:
            pass
        # 通知每个控件：有 on_theme_changed 的调用之(MachinedWell 卡片/表格等会上新主题色)
        for w in self.findChildren(QWidget):
            h = getattr(w, "on_theme_changed", None)
            if callable(h):
                try:
                    h()
                except Exception:
                    pass
            else:
                w.update()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_topbar())

        # ── Main Splitter ──
        outer = QSplitter(Qt.Horizontal)
        outer.setHandleWidth(2)

        left_widget = QWidget()
        left_lo = QHBoxLayout(left_widget)
        left_lo.setContentsMargins(0, 0, 0, 0)
        left_lo.setSpacing(0)
        left_lo.addWidget(self._build_nav_rail())

        self._left_stack = QStackedWidget()
        left_lo.addWidget(self._left_stack, 1)
        outer.addWidget(left_widget)

        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.setSpacing(0)
        self._right_stack = QStackedWidget()
        rl.addWidget(self._right_stack)
        outer.addWidget(right_widget)

        outer.setSizes([360, 840])
        outer.setCollapsible(0, False)
        outer.setCollapsible(1, False)
        layout.addWidget(outer)

        # ── Watermark ──
        self._watermark = QLabel("develop by siyuan-chen & xiaoguang", self)
        self._watermark.setStyleSheet(
            f"color:rgba(139,148,158,60);font-size:{fs(9)};background:transparent;border:none;")
        self._watermark.adjustSize()

        # ── Status Bar ──
        self.status = QStatusBar()
        self._status_dot = QLabel("\u25cf")
        self._status_dot.setStyleSheet(f"color:{C_DOWN};font-size:{fs(9)};border:none;padding-right:2px;")
        self.status.addPermanentWidget(self._status_dot)
        self.setStatusBar(self.status)

    def _build_topbar(self) -> QFrame:
        topbar = QFrame()
        topbar.setFixedHeight(dp(46))
        topbar.setStyleSheet(f"border-bottom:1px solid {C_BORDER_SOFT};")
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(dp(14), 0, dp(10), 0)
        tl.setSpacing(dp(8))

        # Brand block
        lbl_brand = QLabel("stock-classroom")
        lbl_brand.setStyleSheet(
            f"color:{C_ACCENT};font-size:{fs(14)};font-weight:700;border:none;background:transparent;")
        tl.addWidget(lbl_brand)

        chip = QLabel(APP_VERSION)
        chip.setStyleSheet(
            f"color:{C_FAINT};font-size:{fs(9)};border:1px solid {C_BORDER};"
            f"border-radius:{dps(7)};padding:0 {dps(6)};background:transparent;")
        chip.setFixedHeight(dp(15))
        chip.setAlignment(Qt.AlignCenter)
        tl.addWidget(chip)
        tl.addSpacing(dp(10))

        # TOPBAR plugin slots: search next to brand, icon actions on the right
        icon_order = {"agent": 0, "settings": 1}
        right_widgets = []
        for pid, plugin in self._plugin_mgr.all_plugins().items():
            if plugin.region != PluginRegion.TOPBAR:
                continue
            try:
                w = self._plugin_mgr.get_widget(pid)
                if not w:
                    continue
                if pid == "search":
                    tl.addWidget(w)
                else:
                    right_widgets.append((icon_order.get(pid, 9), w))
            except Exception:
                pass

        tl.addStretch()
        for _, w in sorted(right_widgets, key=lambda t: t[0]):
            tl.addWidget(w)

        refresh = QPushButton("刷新")
        refresh.setObjectName("refreshBtn")
        refresh.setFixedHeight(dp(28))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setToolTip("刷新当前面板数据")
        refresh.clicked.connect(lambda: self._plugin_mgr.refresh_current())
        tl.addWidget(refresh)

        log_btn = QPushButton("日志")
        log_btn.setFixedHeight(dp(28))
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("查看运行日志")
        log_btn.clicked.connect(lambda: self._log_window.show()
                                if self._log_window.isHidden()
                                else self._log_window.hide())
        tl.addWidget(log_btn)
        return topbar

    def _build_nav_rail(self) -> QWidget:
        nav_panel = QWidget()
        nav_panel.setFixedWidth(dp(64))
        nav_panel.setStyleSheet(f"border-right:1px solid {C_BORDER_SOFT};")
        nav_lo = QVBoxLayout(nav_panel)
        nav_lo.setContentsMargins(dp(5), dp(10), dp(5), dp(10))
        nav_lo.setSpacing(dp(4))

        self._nav_btns = {}
        for pid, name, icon, region in self._plugin_mgr.get_nav_items():
            btn = self._make_nav_btn(pid, name, icon)
            nav_lo.addWidget(btn)
            self._nav_btns[pid] = btn

        nav_lo.addStretch()
        return nav_panel

    def _make_nav_btn(self, pid: str, name: str, icon: str):
        """Create a nav button with emoji icon on top + text below."""
        btn = QPushButton()
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        btn.setFixedSize(dp(54), dp(50))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(name)
        btn.setText(f"{icon}\n{name}")
        btn.setStyleSheet(f"QPushButton#navBtn{{font-size:{fs(10)};}}")
        btn.clicked.connect(lambda checked, pid=pid: self._activate_plugin(pid))
        return btn

    # ──────────────────────────────────────────────────────────
    #  Plugin activation
    # ──────────────────────────────────────────────────────────

    def _activate_plugin(self, plugin_id: str):
        """Activate a plugin and show its widget in the correct region."""
        plugin = self._plugin_mgr.get_plugin(plugin_id)
        if not plugin:
            return

        region = plugin.region

        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == plugin_id)

        if region == PluginRegion.TOPBAR:
            return

        self._plugin_mgr.activate(plugin_id)

        boundary = self._plugin_mgr.get_widget(plugin_id)
        if not boundary:
            return

        if region == PluginRegion.LEFT:
            self._place_in_stack(boundary, self._left_stack)
            self._route_companion(plugin)
        else:
            self._place_in_stack(boundary, self._right_stack)

    def _place_in_stack(self, widget, stack):
        for i in range(stack.count()):
            if stack.widget(i) is widget:
                stack.setCurrentIndex(i)
                return
        stack.addWidget(widget)
        stack.setCurrentWidget(widget)

    def _route_companion(self, plugin):
        companion = None
        try:
            companion = plugin.create_companion_widget()
        except Exception:
            companion = None

        if companion is not None:
            self._place_in_stack(companion, self._right_stack)
            return

        right_id = self._config.get("default_right", "kline")
        self._plugin_mgr.activate(right_id)
        boundary = self._plugin_mgr.get_widget(right_id)
        if boundary:
            self._place_in_stack(boundary, self._right_stack)

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
