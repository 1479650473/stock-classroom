import sys, os
sys.path.insert(0, r"D:\小光工作区\projects\stock-classroom")
sys.path.insert(0, r"D:\小光工作区\projects\stock-classroom\backend")
os.chdir(r"D:\小光工作区\projects\stock-classroom")
import sys
sys.stdout.reconfigure(encoding="utf-8")
from PyQt5.QtWidgets import QApplication, QStyleFactory
from desktop_app import STYLE, DesktopApp
app = QApplication(sys.argv)
app.setStyle(QStyleFactory.create("fusion"))
app.setStyleSheet(STYLE)
w = DesktopApp()
w.show()
sys.exit(app.exec_())
