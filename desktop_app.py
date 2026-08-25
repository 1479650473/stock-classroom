# -*- coding: utf-8 -*-
"""stock-classroom v4.0 — Plugin-based desktop application entry point."""

import sys, os, traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))

from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
from frontend.platform.theme import build_style
from frontend.platform.platform_shell import PlatformShell
from frontend.plugins.settings.config import load_settings

# QWebEngineView(指挥舱插件) 需在 QApplication 创建前设该属性, 否则无法创建 Web 视图
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("stock-classroom v4.0")
        print("\u542f\u52a8: python desktop_app.py")
        sys.exit(0)
    try:
        settings = load_settings()
        font_size = settings.get("font_size", 13)
        theme_key = settings.get("theme", "graphite")

        from frontend.platform import theme as _th
        _th.set_theme(theme_key)

        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create("fusion"))
        app.setStyleSheet(build_style(font_size))
        app.setFont(QFont("Microsoft YaHei", font_size))

        w = PlatformShell()
        w.show()
        # 全局 excepthook: 捕捉 Qt 事件循环内(Qt 槽/回调)的未捕获异常, 写入桌面错误日志便于定位
        def _global_excepthook(etype, value, tb):
            try:
                with open(os.path.join(PROJECT_DIR, "desktop_error.log"), "a", encoding="utf-8") as f:
                    f.write("=== UNCAUGHT (Qt event loop) ===\n")
                    traceback.print_exception(etype, value, tb, file=f)
            except Exception:
                pass
            sys.__excepthook__(etype, value, tb)
        sys.excepthook = _global_excepthook
        sys.exit(app.exec_())
    except Exception as e:
        with open(os.path.join(PROJECT_DIR, "desktop_error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"\u542f\u52a8\u5931\u8d25\uff0c\u8be6\u89c1 desktop_error.log: {e}")
        sys.exit(1)
