# -*- coding: utf-8 -*-
"""Platform Shell — thin QMainWindow skeleton for stock-classroom."""

import sys, os, traceback, json, math

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QStackedWidget, QFrame, QStyleFactory
)
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QPainter, QColor, QLinearGradient

try:
    import ctypes
    from ctypes import wintypes
    _HAS_CTYPES = True
except Exception:
    _HAS_CTYPES = False

from .theme import (
    STYLE, dp, dps, fs, tr,
    C_BG, C_PANEL, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_RAISED, C_DOWN, C_GOLD,
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


class _ThemeWipe(QWidget):
    """Brief soft light sweep across the window when the theme changes.

    Transparent to mouse clicks (WA_TransparentForMouseEvents), so it never
    blocks input. A diagonal band ramps in, sweeps left→right, and fades out
    over ~300ms — a quiet '扫过/淡入' transition so the theme change reads as
    an intentional reveal rather than an instant hard swap.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._active = False
        self._t = 0.0
        self._duration = 300.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def trigger(self):
        self._t = 0.0
        self._active = True
        parent = self.parentWidget()
        if parent:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        self._timer.start()

    def _tick(self):
        self._t += 16.0 / self._duration
        if self._t >= 1.0:
            self._t = 1.0
            self._active = False
            self._timer.stop()
            self.hide()
        self.update()

    def paintEvent(self, _ev):
        if not self._active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            p.end()
            return
        t = self._t
        env = math.sin(t * math.pi)           # 0 → 1 → 0 envelope
        from frontend.platform import theme as _th
        is_dark = _th.current_theme().get("dark", True)
        alpha = int((34 if is_dark else 30) * env)
        p.save()
        p.translate(w / 2.0, h / 2.0)
        p.rotate(-16)
        p.translate(-w / 2.0, -h / 2.0)
        band_w = max(w, h) * 0.30
        x0 = -band_w * 2 + t * (w + band_w * 4)
        g = QLinearGradient(x0, 0, x0 + band_w, 0)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.22, QColor(255, 255, 255, int(alpha * 0.55)))
        g.setColorAt(0.5, QColor(255, 255, 255, alpha))
        g.setColorAt(0.78, QColor(255, 255, 255, int(alpha * 0.55)))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(x0, -h, band_w, h * 3), g)
        p.restore()
        p.end()


class PlatformShell(QMainWindow):
    """The platform skeleton. Holds PluginManager and all chrome."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("stock-classroom")
        # 自定义标题栏: 去掉系统蓝条边框(难看), 自绘主题化标题栏 + 原生拖拽/边缘缩放
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._drag_pos = None
        self._win_resizing = False

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
        self._bus.navigate_plugin.connect(self._on_navigate)
        self._bus.open_kline.connect(self._on_kline_request)

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
        if default_left in self._plugin_mgr.all_plugins():
            self._activate_plugin(default_left)
        # 不默认启动 kline —— 右栏抽屉默认收起(左插件全屏), 点K线/双击股票才滑出

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
        # 主题切换过渡动效: 一笔柔光扫过(透明, 不拦鼠标)
        try:
            self._theme_wipe.trigger()
        except Exception:
            pass

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_topbar())
        layout.addWidget(self._build_stepbar())

        # ── Main Splitter (右栏=抽屉, 默认收起; 开K线/手动展开才滑出) ──
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
        right_widget.setMinimumWidth(0)
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.setSpacing(0)
        self._right_stack = QStackedWidget()
        rl.addWidget(self._right_stack)
        outer.addWidget(right_widget)

        self._outer = outer
        self._drawer_visible = False
        self._drawer_w = 780          # 展开宽度(小窗口取较窄)
        outer.setCollapsible(0, False)
        outer.setCollapsible(1, True)
        layout.addWidget(outer)

        # ── Watermark ──
        self._watermark = QLabel("develop by siyuan-chen & xiaoguang", self)
        self._watermark.setStyleSheet(
            f"color:rgba(139,148,158,60);font-size:{fs(9)};background:transparent;border:none;")
        self._watermark.adjustSize()

        # ── Theme-transition wipe overlay (transparent to mouse) ──
        self._theme_wipe = _ThemeWipe(central)
        self._theme_wipe.setGeometry(central.rect())

        # ── Status Bar ──
        self.status = QStatusBar()
        self._status_dot = QLabel("\u25cf")
        self._status_dot.setStyleSheet(f"color:{C_DOWN};font-size:{fs(9)};border:none;padding-right:2px;")
        self.status.addPermanentWidget(self._status_dot)
        self.setStatusBar(self.status)

    def _build_stepbar(self) -> QFrame:
        """方案B · 顶层工作流步骤条: 看盘→研究→选股→交易→持仓 (每步=激活对应插件).

        5 步是产品的"主流程", 放顶栏正下方一条独立横条, 清晰不挤占顶栏.
        高亮当前步; 点步 = 跳转插件(复用 _activate_plugin).
        """
        strip = QFrame()
        strip.setFixedHeight(dp(44))
        strip.setStyleSheet(f"background:{C_PANEL};border-bottom:1px solid {C_BORDER_SOFT};")
        stl = QHBoxLayout(strip)
        stl.setContentsMargins(dp(14), 0, dp(10), 0)
        stl.setSpacing(dp(4))

        # 5 个主步骤: (插件id, 显示名, 可选payload)
        self._steps = [
            ("market",   "看盘", None),
            ("research", "研究", None),
            ("picks",    "选股", None),
            ("trade",    "交易", None),
            ("holdings", "持仓", None),
        ]
        self._step_btns = {}
        for pid, label, payload in self._steps:
            if pid not in self._plugin_mgr.all_plugins():
                continue
            b = QPushButton(label)
            b.setObjectName("stepBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(dp(34))
            b.clicked.connect(lambda _=False, p=pid, pl=payload: self._on_step(p, pl))
            stl.addWidget(b)
            self._step_btns[pid] = b

        stl.addStretch()

        # 步骤条右侧: 次要功能的快捷入口(数据工具等), 不打扰主流程
        self._drawer_btn_step = self._drawer_btn  # 已有K线开合钮, 放顶栏了; 这里留个占位
        hint = QLabel("主流程 · 点步骤跳转")
        hint.setStyleSheet(f"color:{C_FAINT};font-size:{fs(tr(9))};letter-spacing:1px;")
        hint.setToolTip("看盘→研究→选股→交易→持仓")
        stl.addWidget(hint)
        return strip

    def _on_step(self, pid, payload=None):
        """点步骤条 → 激活对应插件 + (可带 payload)."""
        self._activate_plugin(pid)
        if payload:
            w = self._plugin_mgr.get_widget(pid)
            if w is not None:
                fn = getattr(w, "apply_navigation", None)
                if callable(fn):
                    try:
                        fn(payload)
                    except Exception:
                        pass

    def _build_topbar(self) -> QFrame:
        topbar = QFrame()
        topbar.setFixedHeight(dp(52))
        topbar.setStyleSheet(f"border-bottom:1px solid {C_BORDER_SOFT};")
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(dp(14), 0, dp(10), 0)
        tl.setSpacing(dp(8))

        # Brand block
        lbl_brand = QLabel("stock-classroom")
        lbl_brand.setStyleSheet(
            f"color:{C_GOLD};font-size:{fs(18)};font-weight:700;border:none;background:transparent;"
            f"letter-spacing:{dp(1)}px;")
        tl.addWidget(lbl_brand)

        chip = QLabel(APP_VERSION)
        chip.setStyleSheet(
            f"color:{C_GOLD};font-size:{fs(tr(13))};border:1px solid {C_BORDER};"
            f"border-top:1px solid {C_BORDER_SOFT};border-radius:{dps(7)};padding:0 {dps(6)};"
            f"background:transparent;font-weight:600;")
        chip.setFixedHeight(dp(21))
        chip.setAlignment(Qt.AlignCenter)
        tl.addWidget(chip)
        tl.addSpacing(dp(12))

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
        refresh.setFixedHeight(dp(30))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setToolTip("刷新当前面板数据")
        refresh.clicked.connect(lambda: self._plugin_mgr.refresh_current())
        tl.addWidget(refresh)

        log_btn = QPushButton("日志")
        log_btn.setFixedHeight(dp(30))
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("查看运行日志")
        log_btn.clicked.connect(lambda: self._log_window.show()
                                if self._log_window.isHidden()
                                else self._log_window.hide())
        tl.addWidget(log_btn)

        # 右栏抽屉(K线)开合开关 —— 平时左插件全屏, 点K线/双击股票才滑出
        self._drawer_btn = QPushButton("K线")
        self._drawer_btn.setObjectName("indBtn")
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.setFixedHeight(dp(30))
        self._drawer_btn.setCursor(Qt.PointingHandCursor)
        self._drawer_btn.setToolTip("打开/收起右侧K线抽屉")
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        tl.addWidget(self._drawer_btn)

        # ── 窗口控制(自绘标题栏: 最小化/最大化/关闭) ──
        tl.addSpacing(dp(4))
        for txt, tip, slot in [("—", "最小化", self._win_minimize),
                               ("□", "最大化/还原", self._win_maximize),
                               ("✕", "关闭", self.close)]:
            b = QPushButton(txt)
            b.setObjectName("winBtn")
            b.setFixedSize(dp(26), dp(26))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tl.addWidget(b)
        return topbar

    def _build_nav_rail(self) -> QWidget:
        nav_panel = QWidget()
        nav_panel.setFixedWidth(dp(64))
        nav_panel.setStyleSheet(f"border-right:1px solid {C_BORDER_SOFT};")
        nav_lo = QVBoxLayout(nav_panel)
        nav_lo.setContentsMargins(dp(5), dp(8), dp(5), dp(8))
        nav_lo.setSpacing(dp(2))

        self._nav_btns = {}
        try:
            groups = self._plugin_mgr.get_nav_groups()
        except Exception:
            groups = [{"label": "", "items": self._plugin_mgr.get_nav_items()}]
        first = True
        for g in groups:
            label = g.get("label", "")
            items = g.get("items", [])
            if label and items:
                if not first:
                    nav_lo.addSpacing(dp(8))
                head = QLabel(label)
                head.setStyleSheet(
                    f"color:{C_FAINT};font-size:{fs(tr(8))};letter-spacing:1px;"
                    f"border:none;background:transparent;padding-left:{dps(4)};")
                head.setFixedHeight(dp(14))
                nav_lo.addWidget(head)
            for pid, name, icon, region in items:
                btn = self._make_nav_btn(pid, name, icon)
                nav_lo.addWidget(btn)
                self._nav_btns[pid] = btn
            first = False

        nav_lo.addStretch()
        return nav_panel

    def _make_nav_btn(self, pid: str, name: str, icon: str):
        """Create a nav button with emoji icon on top + text below."""
        btn = QPushButton()
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        btn.setFixedSize(dp(56), dp(52))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(name)
        btn.setText(f"{icon}\n{name}")
        btn.setStyleSheet(f"QPushButton#navBtn{{font-size:{fs(tr(10))};letter-spacing:0.5px;}}")
        btn.clicked.connect(lambda checked, pid=pid: self._activate_plugin(pid))
        return btn

    # ──────────────────────────────────────────────────────────
    #  Plugin activation
    # ──────────────────────────────────────────────────────────

    def _on_navigate(self, plugin_id, payload=None):
        """总览主功能入口等触发跨插件跳转. payload 透传给落地插件(如 research 带 hp)."""
        if plugin_id not in self._plugin_mgr.all_plugins():
            return
        self._activate_plugin(plugin_id)
        if payload:
            w = self._plugin_mgr.get_widget(plugin_id)
            if w is not None:
                # 通用约定: 落地插件实现 apply_navigation(payload) 则调用
                fn = getattr(w, "apply_navigation", None)
                if callable(fn):
                    try:
                        fn(payload)
                    except Exception:
                        pass

    def _activate_plugin(self, plugin_id: str):
        """Activate a plugin and show its widget in the correct region."""
        plugin = self._plugin_mgr.get_plugin(plugin_id)
        if not plugin:
            return

        region = plugin.region

        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == plugin_id)

        # 同步高亮顶部步骤条(当前步对应插件)
        for spid, sbtn in getattr(self, "_step_btns", {}).items():
            sbtn.setChecked(spid == plugin_id)

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
            # RIGHT区域(K线等): 放进右栏 + 展开抽屉
            self._place_in_stack(boundary, self._right_stack)
            self._set_drawer(True)

    def _place_in_stack(self, widget, stack):
        for i in range(stack.count()):
            if stack.widget(i) is widget:
                stack.setCurrentIndex(i)
                return
        stack.addWidget(widget)
        stack.setCurrentWidget(widget)

    def _route_companion(self, plugin):
        """落地左插件后决定右栏(抽屉): 有companion→展开并显示; 无→收起(左插件全屏, 无死区).
        默认永远不塞"空的 kline 占位" —— 只有真正点了股票/点了K线按钮才滑出."""
        companion = None
        try:
            companion = plugin.create_companion_widget()
        except Exception:
            companion = None
        if companion is not None:
            self._place_in_stack(companion, self._right_stack)
            self._set_drawer(True)
            return
        # 无 companion → 收起右栏, 左插件全屏
        self._set_drawer(False)

    def _ensure_kline(self):
        """把 kline 插件放进右栏并激活."""
        right_id = self._config.get("default_right", "kline")
        self._plugin_mgr.activate(right_id)
        boundary = self._plugin_mgr.get_widget(right_id)
        if boundary:
            self._place_in_stack(boundary, self._right_stack)
        return boundary

    def _set_drawer(self, visible, kline=False):
        """控制右栏抽屉: visible=True 展开(宽度 _drawer_w), False 收起(0)."""
        self._drawer_visible = visible
        if visible and kline:
            self._ensure_kline()
        total = max(self._outer.width(), 100)
        if visible:
            w = min(self._drawer_w, max(320, total - 420))
            self._outer.setSizes([max(total - w, 60), w])
        else:
            self._outer.setSizes([total, 0])

    def _toggle_drawer(self):
        """顶部'K线'按钮: 展开显示kline / 收起."""
        if self._drawer_visible:
            self._set_drawer(False)
        else:
            self._set_drawer(True, kline=True)
        self._update_drawer_btn()

    def _update_drawer_btn(self):
        try:
            self._drawer_btn.setChecked(self._drawer_visible)
        except Exception:
            pass

    def _on_kline_request(self, code, name):
        """任意插件打开股票K线 → 展开右栏显示 kline."""
        self._set_drawer(True, kline=True)
        self._update_drawer_btn()

    # ── 自绘标题栏: 窗口控制 + 拖拽 + 边缘缩放 ──
    def _win_minimize(self):
        self.showMinimized()

    def _win_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _titlebar_hit_test(self, pos):
        """返回标题栏可拖拽区(顶部 ~48px, 不含右上窗口控制钮). True=可拖拽."""
        return pos.y() <= dp(48)

    # WM_NCHITTEST —— 让无边框窗仍支持边缘/角缩放手柄(更像正经软件)
    def nativeEvent(self, etype, message):
        if _HAS_CTYPES and etype == b"windows_generic_MSG":
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0084:  # WM_NCHITTEST
                    gx, gy = msg.lParam & 0xFFFF, (msg.lParam >> 16) & 0xFFFF
                    gx = ctypes.c_short(gx).value
                    gy = ctypes.c_short(gy).value
                    # 屏幕坐标 → 本窗口坐标
                    local = self.mapFromGlobal(Qt.QPoint(gx, gy))
                    # 边缘判定(8 方向)
                    bw = 6
                    if local.y() <= dp(48) and not self.isMaximized():
                        # 标题栏 → HTCAPTION(可拖拽, 自动吸附)
                        return True, 2  # HTCAPTION
                    on_left = local.x() < bw
                    on_right = local.x() > self.width() - bw
                    on_top = local.y() < bw
                    on_bottom = local.y() > self.height() - bw
                    if on_top and on_left: return True, 13   # HTTOPLEFT
                    if on_top and on_right: return True, 14  # HTTOPRIGHT
                    if on_bottom and on_left: return True, 16  # HTBOTTOMLEFT
                    if on_bottom and on_right: return True, 17  # HTBOTTOMRIGHT
                    if on_left: return True, 10   # HTLEFT
                    if on_right: return True, 11  # HTRIGHT
                    if on_top: return True, 12    # HTTOP
                    if on_bottom: return True, 15 # HTBOTTOM
            except Exception:
                pass
        return super().nativeEvent(etype, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._titlebar_hit_test(event.pos()):
            win = self.windowHandle()
            if win is not None and not self.isMaximized():
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton and not self.isMaximized():
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 双击标题栏空白区 → 最大化/还原
        if self._titlebar_hit_test(event.pos()):
            self._win_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # 窗口真正显示、宽高就绪后, 把右栏抽屉压到初始态(默认收起, 左插件全屏)
        try:
            QTimer.singleShot(50, lambda: self._set_drawer(self._drawer_visible))
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_watermark'):
            self._watermark.move(
                self.width() - self._watermark.width() - 14,
                self.height() - self._watermark.height() - 36
            )
        if hasattr(self, '_theme_wipe'):
            parent = self._theme_wipe.parentWidget()
            if parent:
                self._theme_wipe.setGeometry(parent.rect())

    def closeEvent(self, event):
        self._plugin_mgr.shutdown_all()
        event.accept()
