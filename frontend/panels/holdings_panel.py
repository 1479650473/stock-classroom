"""Holdings Panel — Placeholder (暂不可用)"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_status = None
        self.setStyleSheet("background:#111111")
        lo = QVBoxLayout(self)
        lo.setAlignment(Qt.AlignCenter)
        lbl = QLabel("持仓功能暂不可用")
        lbl.setStyleSheet("color:#B4B4B4;font-size:14px")
        lo.addWidget(lbl)

    def load(self):
        if self.on_status: self.on_status("持仓功能暂不可用")
