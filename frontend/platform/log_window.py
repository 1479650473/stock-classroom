# -*- coding: utf-8 -*-
"""Log terminal: stdout/stderr redirect + floating log window."""

from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit


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
