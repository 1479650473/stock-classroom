# -*- coding: utf-8 -*-
"""
PyInstaller entry point for stock-classroom desktop app.
Handles frozen path setup before launching PlatformShell.
"""

import sys, os, traceback

# ── Path setup for frozen mode ──
if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
    EXE_DIR = os.path.dirname(sys.executable)
    if BASE not in sys.path:
        sys.path.insert(0, BASE)
    be = os.path.join(BASE, "backend")
    if be not in sys.path:
        sys.path.insert(0, be)
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    EXE_DIR = BASE
    sys.path.insert(0, os.path.join(BASE, "backend"))
    sys.path.insert(0, BASE)

LOG_PATH = os.path.join(EXE_DIR, "error.log")


if __name__ == "__main__":
    try:
        from PyQt5.QtWidgets import QApplication, QStyleFactory
        from frontend.platform.theme import STYLE
        from frontend.platform.platform_shell import PlatformShell

        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("fusion"))
        app.setStyleSheet(STYLE)
        w = PlatformShell()
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"stock-classroom startup error:\n")
            traceback.print_exc(file=f)
        sys.exit(1)
