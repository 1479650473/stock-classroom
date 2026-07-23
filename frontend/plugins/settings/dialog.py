# -*- coding: utf-8 -*-
"""Settings dialog — left nav + right content with display & AI provider presets."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QApplication, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .config import load_settings, save_settings
from frontend.platform.theme import build_style, fs

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"
C_GREEN = "#3fb950"
C_RED = "#EF5350"
C_NAV_BG = "#0B1016"
C_NAV_HOVER = "#1A1F2A"
C_NAV_SELECTED = "#1C2330"

FONT_OPTIONS = [
    (11, u"\u5c0f (11px)"),
    (13, u"\u4e2d (13px)"),
    (15, u"\u5927 (15px)"),
    (17, u"\u7279\u5927 (17px)"),
]

AI_PROVIDERS = [
    (u"\u81ea\u5b9a\u4e49",               "",                                    ""),
    (u"DeepSeek V4 Pro",                "https://api.deepseek.com/v1",         "deepseek-v4-pro"),
    (u"DeepSeek V4 Flash",              "https://api.deepseek.com/v1",         "deepseek-v4-flash"),
    (u"\u667a\u8c31 GLM-4 Flash",       "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    (u"Kimi K2.6",                      "https://api.moonshot.cn/v1",          "kimi-k2.6"),
]

_INPUT_STYLE = (
    "QLineEdit{background:%s;color:%s;border:1px solid %s;"
    "border-radius:4px;padding:6px 10px;font-size:%s}" % (C_BG, C_TEXT, C_BORDER, fs(12))
    + "QLineEdit:focus{border-color:%s}" % C_ACCENT
)

NAV_STYLE = (
    "QListWidget{background:%s;border:none;outline:none;padding:4px}"
    "QListWidget::item{color:%s;font-size:%s;padding:10px 14px;border-left:3px solid transparent;border-radius:2px}"
    "QListWidget::item:hover{background:%s;color:%s;border-left-color:#484F58}"
    "QListWidget::item:selected{background:%s;color:%s;border-left-color:%s;font-weight:700}"
    % (C_NAV_BG, C_SUBTEXT, fs(12), C_NAV_HOVER, C_TEXT, C_NAV_SELECTED, C_TEXT, C_ACCENT)
)

SECTION_TITLE_STYLE = f"color:{C_TEXT};font-size:{fs(14)};font-weight:700;background:transparent;padding-bottom:2px"
SECTION_DESC_STYLE = f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent"
LABEL_STYLE = f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent"


def _section_title(text):
    lb = QLabel(text)
    lb.setStyleSheet(SECTION_TITLE_STYLE)
    return lb


def _section_desc(text):
    lb = QLabel(text)
    lb.setStyleSheet(SECTION_DESC_STYLE)
    lb.setWordWrap(True)
    return lb


def _field_row(label_text, widget, label_width=60):
    r = QHBoxLayout()
    r.setSpacing(12)
    lb = QLabel(label_text)
    lb.setFixedWidth(label_width)
    lb.setStyleSheet(LABEL_STYLE)
    r.addWidget(lb)
    r.addWidget(widget)
    return r


def _divider():
    d = QFrame()
    d.setFixedHeight(1)
    d.setStyleSheet(f"background:{C_BORDER}")
    return d


class SettingsWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = load_settings()
        self._original_font_size = self._settings.get("font_size", 13)
        self._original_agent = dict(self._settings.get("agent", {}))
        self._app = QApplication.instance()

        self.setWindowTitle(u"\u8bbe\u7f6e")
        self.setFixedSize(1080, 950)
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()
        self._update_preview()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # ── Header ──
        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(f"background:{C_PANEL};border-bottom:1px solid {C_BORDER}")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        icon = QLabel(u"\u2699")
        icon.setStyleSheet(f"font-size:{fs(18)};background:transparent;color:{C_ACCENT}")
        hl.addWidget(icon)
        title = QLabel(u"\u8bbe\u7f6e")
        title.setStyleSheet(f"color:{C_TEXT};font-size:{fs(15)};font-weight:700;background:transparent")
        hl.addWidget(title)
        hl.addStretch()
        lo.addWidget(hdr)

        # ── Body: nav + content ──
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setFixedWidth(140)
        self._nav.setStyleSheet(NAV_STYLE)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        nav_items = [
            (u"\U0001f4fa  \u663e\u793a", 0),
            (u"\U0001f916 AI", 1),
        ]
        for text, idx in nav_items:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, idx)
            item.setSizeHint(item.sizeHint())
            self._nav.addItem(item)

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        body.addWidget(self._nav)

        nav_sep = QFrame()
        nav_sep.setFixedWidth(1)
        nav_sep.setStyleSheet(f"background:{C_BORDER}")
        body.addWidget(nav_sep)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:transparent")
        self._stack.addWidget(self._build_display_page())
        self._stack.addWidget(self._build_ai_page())
        body.addWidget(self._stack)

        lo.addLayout(body)

        # ── Footer ──
        footer = QWidget()
        footer.setFixedHeight(48)
        footer.setStyleSheet(f"background:{C_PANEL};border-top:1px solid {C_BORDER}")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.addStretch()

        cancel = QPushButton(u"\u53d6\u6d88")
        cancel.setFixedSize(80, 32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C_PANEL};color:{C_SUBTEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;font-size:{fs(12)}}}"
            f"QPushButton:hover{{border-color:#484F58;color:{C_TEXT}}}")
        cancel.clicked.connect(self._on_cancel)
        fl.addWidget(cancel)

        apply_btn = QPushButton(u"\u5e94\u7528")
        apply_btn.setFixedSize(80, 32)
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#0D1117;border:none;"
            f"border-radius:6px;font-size:{fs(12)};font-weight:700}}"
            f"QPushButton:hover{{background:#E0B888}}")
        apply_btn.clicked.connect(self._on_apply)
        fl.addWidget(apply_btn)
        lo.addWidget(footer)

        self._nav.setCurrentRow(0)

    # ──────────────────── Display Page ────────────────────

    def _build_display_page(self):
        w = QWidget()
        w.setStyleSheet(f"background:{C_BG}")
        lo = QVBoxLayout(w)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(16)

        lo.addWidget(_section_title(u"\u663e\u793a\u504f\u597d"))
        lo.addWidget(_section_desc(u"\u8c03\u6574\u754c\u9762\u5b57\u4f53\u5927\u5c0f\uff0c\u5b9e\u65f6\u9884\u89c8\u53d8\u5316\u3002"))

        fs_row = QHBoxLayout()
        fs_row.setSpacing(12)
        fs_label = QLabel(u"\u5b57\u4f53\u5927\u5c0f")
        fs_label.setStyleSheet(LABEL_STYLE)
        fs_row.addWidget(fs_label)

        self._font_combo = QComboBox()
        self._font_combo.setFixedWidth(140)
        current_idx = 1
        for i, (val, name) in enumerate(FONT_OPTIONS):
            self._font_combo.addItem(name, val)
            if val == self._settings.get("font_size", 13):
                current_idx = i
        self._font_combo.setCurrentIndex(current_idx)
        self._font_combo.currentIndexChanged.connect(self._update_preview)
        self._font_combo.setStyleSheet(
            f"QComboBox{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:4px;padding:5px 10px;font-size:{fs(12)}}}"
            f"QComboBox:hover{{border-color:#484F58}}"
            f"QComboBox QAbstractItemView{{background:{C_PANEL};color:{C_TEXT};"
            f"selection-background:{C_ACCENT};selection-color:#0D1117;border:1px solid {C_BORDER}}}"
        )
        fs_row.addWidget(self._font_combo)
        fs_row.addStretch()
        lo.addLayout(fs_row)

        preview_frame = QFrame()
        preview_frame.setObjectName("preview")
        preview_frame.setStyleSheet(
            f"QFrame#preview{{background:{C_PANEL};border:1px solid {C_BORDER};border-radius:8px;padding:6px}}")
        pv = QVBoxLayout(preview_frame)
        pv.setContentsMargins(16, 12, 16, 12)
        pv.setSpacing(4)

        preview_hint = QLabel(u"\u5b9e\u65f6\u9884\u89c8")
        preview_hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(10)};background:transparent")
        pv.addWidget(preview_hint)

        self._preview_label = QLabel("123 ABC \u793a\u4f8b\u6587\u5b57 A\u80a1\u667a\u80fd\u52a9\u624b \u2709")
        self._preview_label.setStyleSheet(f"color:{C_TEXT};background:transparent")
        self._preview_label.setWordWrap(True)
        pv.addWidget(self._preview_label)
        lo.addWidget(preview_frame)
        lo.addStretch()
        return w

    # ──────────────────── AI Page ────────────────────

    def _build_ai_page(self):
        w = QWidget()
        w.setStyleSheet(f"background:{C_BG}")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{C_BG};border:none}}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setStyleSheet(f"background:{C_BG}")
        lo = QVBoxLayout(inner)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(14)

        lo.addWidget(_section_title(u"AI \u5bf9\u8bdd\u914d\u7f6e"))
        lo.addWidget(_section_desc(u"\u9009\u62e9\u6a21\u578b\u4f9b\u5e94\u5546\uff0c\u586b\u5199 API Key \u5373\u53ef\u5f00\u59cb\u5bf9\u8bdd\u3002"))

        # Provider selector
        prov_row = QHBoxLayout()
        prov_row.setSpacing(12)
        prov_label = QLabel(u"\u4f9b\u5e94\u5546")
        prov_label.setStyleSheet(LABEL_STYLE)
        prov_row.addWidget(prov_label)

        self._provider_combo = QComboBox()
        for name, _, _ in AI_PROVIDERS:
            self._provider_combo.addItem(name)
        self._provider_combo.setStyleSheet(
            f"QComboBox{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:4px;padding:5px 10px;font-size:{fs(12)}}}"
            f"QComboBox:hover{{border-color:#484F58}}"
            f"QComboBox QAbstractItemView{{background:{C_PANEL};color:{C_TEXT};"
            f"selection-background:{C_ACCENT};selection-color:#0D1117;border:1px solid {C_BORDER}}}"
        )
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        prov_row.addWidget(self._provider_combo)
        prov_row.addStretch()
        lo.addLayout(prov_row)

        lo.addWidget(_divider())

        agent_cfg = self._settings.get("agent", {})

        self._ai_url = QLineEdit(agent_cfg.get("api_base", ""))
        self._ai_url.setPlaceholderText("https://api.openai.com/v1")
        self._ai_url.setStyleSheet(_INPUT_STYLE)
        lo.addLayout(_field_row("API URL", self._ai_url))

        self._ai_key = QLineEdit(agent_cfg.get("api_key", ""))
        self._ai_key.setPlaceholderText(u"\u8f93\u5165 API Key\uff0c\u672c\u5730 Ollama \u53ef\u7559\u7a7a")
        self._ai_key.setEchoMode(QLineEdit.Password)
        self._ai_key.setStyleSheet(_INPUT_STYLE)
        lo.addLayout(_field_row("API Key", self._ai_key))

        self._ai_model = QLineEdit(agent_cfg.get("model", ""))
        self._ai_model.setPlaceholderText("gpt-4o / deepseek-chat / glm-4-flash ...")
        self._ai_model.setStyleSheet(_INPUT_STYLE)
        lo.addLayout(_field_row(u"\u6a21\u578b", self._ai_model))

        # Detect saved provider and select it
        saved_url = agent_cfg.get("api_base", "")
        saved_model = agent_cfg.get("model", "")
        matched = False
        for i, (_, purl, pmodel) in enumerate(AI_PROVIDERS):
            if purl and purl == saved_url and pmodel == saved_model:
                self._provider_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched and saved_url:
            self._provider_combo.setCurrentIndex(0)

        lo.addWidget(_divider())

        # Test connection
        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self._test_btn = QPushButton(u"\u6d4b\u8bd5\u8fde\u63a5")
        self._test_btn.setFixedSize(88, 30)
        self._test_btn.setCursor(Qt.PointingHandCursor)
        self._test_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#0D1117;border:none;"
            f"border-radius:6px;font-size:{fs(11)};font-weight:700}}"
            f"QPushButton:hover{{background:#E0B888}}"
            f"QPushButton:disabled{{background:{C_BORDER};color:{C_SUBTEXT}}}"
        )
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)

        self._test_status = QLabel("")
        self._test_status.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent")
        test_row.addWidget(self._test_status)
        test_row.addStretch()
        lo.addLayout(test_row)

        lo.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _on_nav_changed(self, row):
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    def _on_provider_changed(self, idx):
        if 0 <= idx < len(AI_PROVIDERS):
            _, url, model = AI_PROVIDERS[idx]
            self._ai_url.setText(url)
            self._ai_model.setText(model)

    def _update_preview(self):
        idx = self._font_combo.currentIndex()
        val = FONT_OPTIONS[idx][0]
        self._preview_label.setStyleSheet(
            f"color:{C_TEXT};font-size:{val + 1}px;background:transparent")

    # ──────────────────── Test Connection ────────────────────

    def _test_connection(self):
        url = self._ai_url.text().strip()
        key = self._ai_key.text().strip()
        model = self._ai_model.text().strip()

        if not url or not model:
            self._test_status.setText(u"\u26a0 \u8bf7\u5148\u586b\u5199 URL \u548c\u6a21\u578b")
            self._test_status.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent")
            return

        self._test_btn.setEnabled(False)
        self._test_status.setText(u"\u6d4b\u8bd5\u4e2d...")
        self._test_status.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent")

        from PyQt5.QtCore import QThread

        class _TestWorker(QThread):
            result_ok = pyqtSignal(str)
            result_fail = pyqtSignal(str)

            def __init__(self, url, key, model):
                super().__init__()
                self._url = url
                self._key = key
                self._model = model

            def run(self):
                try:
                    import openai
                    base = self._url.rstrip("/")
                    c = openai.OpenAI(
                        base_url=base if base.endswith("/v1") else base + "/v1",
                        api_key=self._key if self._key else "ollama",
                    )
                    resp = c.chat.completions.create(
                        model=self._model,
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=10,
                    )
                    self.result_ok.emit(resp.choices[0].message.content)
                except Exception as e:
                    self.result_fail.emit(str(e))

        self._test_worker = _TestWorker(url, key, model)
        self._test_worker.result_ok.connect(self._on_test_ok)
        self._test_worker.result_fail.connect(self._on_test_fail)
        self._test_worker.start()

    def _on_test_ok(self, text):
        self._test_status.setText(u"\u2705 \u8fde\u63a5\u6210\u529f")
        self._test_status.setStyleSheet(f"color:{C_GREEN};font-size:{fs(11)};background:transparent")
        self._test_btn.setEnabled(True)

    def _on_test_fail(self, err):
        short = err[:80] + ("..." if len(err) > 80 else "")
        self._test_status.setText(f"\u274c {short}")
        self._test_status.setStyleSheet(f"color:{C_RED};font-size:{fs(11)};background:transparent")
        self._test_btn.setEnabled(True)

    # ──────────────────── Apply / Cancel ────────────────────

    def _on_apply(self):
        idx = self._font_combo.currentIndex()
        new_font_size = FONT_OPTIONS[idx][0]
        self._settings["font_size"] = new_font_size

        self._settings["agent"] = {
            "api_base": self._ai_url.text().strip(),
            "api_key": self._ai_key.text().strip(),
            "model": self._ai_model.text().strip(),
        }

        save_settings(self._settings)

        new_style = build_style(new_font_size)
        if self._app:
            self._app.setStyleSheet(new_style)

        self.close()

    def _on_cancel(self):
        if self._original_font_size != self._settings.get("font_size", 13):
            build_style(self._original_font_size)
            if self._app:
                self._app.setStyleSheet(build_style(self._original_font_size))
        self.close()

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
