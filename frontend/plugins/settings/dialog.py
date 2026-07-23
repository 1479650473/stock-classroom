# -*- coding: utf-8 -*-
"""Settings dialog — font size and display preferences."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QApplication,
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

FONT_OPTIONS = [
    (11, "\u5c0f (11px)"),
    (13, "\u4e2d (13px)"),
    (15, "\u5927 (15px)"),
    (17, "\u7279\u5927 (17px)"),
]


class SettingsWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = load_settings()
        self._original_font_size = self._settings.get("font_size", 13)
        self._app = QApplication.instance()

        self.setWindowTitle("\u8bbe\u7f6e")
        self.setFixedSize(340, 210)
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()
        self._update_preview()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 16, 20, 16)
        lo.setSpacing(14)

        # ── Header ──
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        icon = QLabel("\u2699")
        icon.setStyleSheet(f"font-size:{fs(18)};background:transparent;color:{C_ACCENT}")
        hdr.addWidget(icon)
        title = QLabel("\u663e\u793a\u8bbe\u7f6e")
        title.setStyleSheet(f"color:{C_TEXT};font-size:{fs(15)};font-weight:700;background:transparent")
        hdr.addWidget(title)
        hdr.addStretch()
        lo.addLayout(hdr)

        # ── Divider ──
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{C_BORDER}")
        lo.addWidget(div)

        # ── Font size row ──
        fs_row = QHBoxLayout()
        fs_row.setSpacing(12)
        fs_label = QLabel("\u5b57\u4f53\u5927\u5c0f")
        fs_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(12)};background:transparent")
        fs_row.addWidget(fs_label)

        self._font_combo = QComboBox()
        self._font_combo.setFixedWidth(120)
        current_idx = 1  # default to medium
        for i, (val, name) in enumerate(FONT_OPTIONS):
            self._font_combo.addItem(name, val)
            if val == self._settings.get("font_size", 13):
                current_idx = i
        self._font_combo.setCurrentIndex(current_idx)
        self._font_combo.currentIndexChanged.connect(self._update_preview)
        fs_row.addWidget(self._font_combo)
        fs_row.addStretch()
        lo.addLayout(fs_row)

        # ── Preview ──
        preview_frame = QFrame()
        preview_frame.setObjectName("preview")
        preview_frame.setStyleSheet(
            f"QFrame#preview{{background:{C_PANEL};border:1px solid {C_BORDER};border-radius:6px;padding:4px}}")
        pv = QHBoxLayout(preview_frame)
        pv.setContentsMargins(12, 8, 12, 8)

        self._preview_label = QLabel("123 ABC \u793a\u4f8b\u6587\u5b57 \u2709")
        self._preview_label.setStyleSheet(f"color:{C_TEXT};background:transparent")
        pv.addWidget(self._preview_label)
        pv.addStretch()
        lo.addWidget(preview_frame)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel = QPushButton("\u53d6\u6d88")
        cancel.setFixedSize(72, 32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C_PANEL};color:{C_SUBTEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;font-size:{fs(12)};padding:3px 12px}}"
            f"QPushButton:hover{{border-color:#484F58;color:{C_TEXT}}}")
        cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel)

        apply_btn = QPushButton("\u5e94\u7528")
        apply_btn.setFixedSize(72, 32)
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#0D1117;border:none;"
            f"border-radius:6px;font-size:{fs(12)};font-weight:700;padding:3px 12px}}"
            f"QPushButton:hover{{background:#E0B888}}")
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        lo.addLayout(btn_row)

    def _update_preview(self):
        idx = self._font_combo.currentIndex()
        val = FONT_OPTIONS[idx][0]
        self._preview_label.setStyleSheet(
            f"color:{C_TEXT};font-size:{val + 1}px;background:transparent")

    def _on_apply(self):
        idx = self._font_combo.currentIndex()
        new_font_size = FONT_OPTIONS[idx][0]
        self._settings["font_size"] = new_font_size
        save_settings(self._settings)

        # Rebuild and apply global stylesheet
        new_style = build_style(new_font_size)
        if self._app:
            self._app.setStyleSheet(new_style)

        self.close()

    def _on_cancel(self):
        # Restore original
        if self._original_font_size != self._settings.get("font_size", 13):
            build_style(self._original_font_size)
            if self._app:
                self._app.setStyleSheet(build_style(self._original_font_size))
        self.close()

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
