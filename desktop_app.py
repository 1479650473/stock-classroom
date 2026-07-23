# -*- coding: utf-8 -*-
"""stock-classroom v4.0 — Plugin-based desktop application entry point."""

import sys, os, traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))

from PyQt5.QtWidgets import QApplication, QStyleFactory
from frontend.platform.theme import STYLE
from frontend.platform.platform_shell import PlatformShell


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("stock-classroom v4.0")
        print("启动: python desktop_app.py")
        sys.exit(0)
    try:
        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("fusion"))
        app.setStyleSheet(STYLE)
        w = PlatformShell()
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        with open(os.path.join(PROJECT_DIR, "desktop_error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"启动失败，详见 desktop_error.log: {e}")
        sys.exit(1)
