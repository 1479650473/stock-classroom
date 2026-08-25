# -*- coding: utf-8 -*-
"""Trainer placeholder panel."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from .styles import C_BG, C_TEXT, C_SUBTEXT
from frontend.platform.theme import fs


class TrainerPlaceholder(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:%s" % C_BG)
        lo = QVBoxLayout(self)
        lo.setAlignment(Qt.AlignCenter)
        lo.setSpacing(8)

        icon = QLabel("\U0001f4ca")
        icon.setStyleSheet("font-size:%s;color:%s;background:transparent" % (fs(18), C_SUBTEXT))
        icon.setAlignment(Qt.AlignCenter)
        lo.addWidget(icon)

        title = QLabel("\u56de\u6d4b\u8bad\u7ec3")
        title.setStyleSheet("color:%s;font-size:%s;font-weight:700;background:transparent" % (C_TEXT, fs(15)))
        title.setAlignment(Qt.AlignCenter)
        lo.addWidget(title)

        hint = QLabel("\u529f\u80fd\u6b63\u5728\u72ec\u7acb\u5f00\u53d1\u4e2d\uff0c\u5c06\u5728\u540e\u7eed\u7248\u672c\u96c6\u6210\u3002")
        hint.setStyleSheet("color:%s;font-size:%s;background:transparent" % (C_SUBTEXT, fs(11)))
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        lo.addWidget(hint)
