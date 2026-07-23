# -*- coding: utf-8 -*-
"""ChatWindow — floating AI chat dialog."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QTextEdit, QPushButton, QWidget, QSizePolicy, QScrollBar,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QKeyEvent

from .config import load_agent_config
from .llm_client import LLMClient
from .chat_worker import ChatWorker

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"


class _InputEdit(QTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.send_requested.emit()
        else:
            super().keyPressEvent(event)


class ChatBubble(QWidget):
    def __init__(self, text, is_user=True, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 4, 8, 4)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextFormat(Qt.RichText)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setMaximumWidth(400)

        if is_user:
            label.setStyleSheet(
                f"background:{C_ACCENT};color:#0D1117;border-radius:10px;padding:8px 12px;font-size:13px;"
            )
            lo.addStretch()
            lo.addWidget(label)
        else:
            label.setStyleSheet(
                f"background:{C_PANEL};color:{C_TEXT};border:1px solid {C_BORDER};"
                f"border-radius:10px;padding:8px 12px;font-size:13px;"
            )
            lo.addWidget(label)
            lo.addStretch()


class ChatWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages = []
        self._worker = None

        self.setWindowTitle(u"AI 助手")
        self.setMinimumSize(420, 520)
        self.resize(420, 560)
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet(f"background:{C_PANEL};border-bottom:1px solid {C_BORDER}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel(u"\u2b50 AI \u52a9\u624b")
        title.setStyleSheet(f"color:{C_TEXT};font-size:14px;font-weight:700;background:transparent")
        hl.addWidget(title)
        hl.addStretch()
        lo.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"QScrollArea{{background:{C_BG};border:none}}")

        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setAlignment(Qt.AlignTop)
        self._msg_layout.setSpacing(4)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)

        self._scroll.setWidget(self._msg_container)
        lo.addWidget(self._scroll)

        input_widget = QWidget()
        input_widget.setFixedHeight(56)
        input_widget.setStyleSheet(f"background:{C_PANEL};border-top:1px solid {C_BORDER}")
        il = QHBoxLayout(input_widget)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(8)

        self._input = _InputEdit()
        self._input.setPlaceholderText(u"输入消息... (Enter发送, Shift+Enter换行)")
        self._input.setFixedHeight(40)
        self._input.setAcceptRichText(False)
        self._input.setStyleSheet(
            f"QTextEdit{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:8px 10px;font-size:13px}}"
        )
        self._input.send_requested.connect(self._send)

        self._send_btn = QPushButton(u"发送")
        self._send_btn.setFixedSize(56, 36)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#0D1117;border:none;border-radius:6px;font-size:12px;font-weight:700}}"
            f"QPushButton:hover{{background:#E0B888}}"
            f"QPushButton:disabled{{background:{C_BORDER};color:{C_SUBTEXT}}}"
        )
        self._send_btn.clicked.connect(self._send)
        il.addWidget(self._input)
        il.addWidget(self._send_btn)
        lo.addWidget(input_widget)

    def _send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        cfg = load_agent_config()
        client = LLMClient(cfg["api_base"], cfg["api_key"], cfg["model"])

        self._add_bubble(text, is_user=True)
        self._messages.append({"role": "user", "content": text})
        self._input.clear()

        self._input.setEnabled(False)
        self._send_btn.setEnabled(False)

        full_messages = []
        if cfg.get("system_prompt"):
            full_messages.append({"role": "system", "content": cfg["system_prompt"]})
        full_messages.extend(self._messages)

        self._worker = ChatWorker(client, full_messages)
        self._worker.response.connect(self._on_response)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_response(self, text):
        self._add_bubble(text, is_user=False)
        self._messages.append({"role": "assistant", "content": text})

    def _on_error(self, error_text):
        self._add_bubble(u"\u274c \u9519\u8bef: " + error_text, is_user=False)

    def _on_finished(self):
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._worker = None

    def _add_bubble(self, text, is_user):
        display = text.replace("\n", "<br>")
        bubble = ChatBubble(display, is_user)
        self._msg_layout.addWidget(bubble)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))
