# -*- coding: utf-8 -*-
"""stock-classroom v4.0 — Plugin-based desktop application entry point."""

import sys, os, traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))

from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtGui import QFont
from frontend.platform.theme import build_style
from frontend.platform.platform_shell import PlatformShell
from frontend.plugins.settings.config import load_settings


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("stock-classroom v4.0")
        print("\u542f\u52a8: python desktop_app.py")
        sys.exit(0)
    try:
        settings = load_settings()
        font_size = settings.get("font_size", 13)

        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("fusion"))
        app.setStyleSheet(build_style(font_size))
        app.setFont(QFont("Microsoft YaHei", font_size))

        w = PlatformShell()
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        with open(os.path.join(PROJECT_DIR, "desktop_error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"\u542f\u52a8\u5931\u8d25\uff0c\u8be6\u89c1 desktop_error.log: {e}")
        sys.exit(1)
