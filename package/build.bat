@echo off
chcp 65001 >nul
echo ========================================
echo  StockClassroom - PyInstaller Build
echo ========================================
echo.

set PYINST=C:\Users\Lenovo\AppData\Roaming\Python\Python314\Scripts\pyinstaller.exe
set BASE=%~dp0

cd /d "%BASE%"

"%PYINST%" ^
  --onedir ^
  --name StockClassroom ^
  --add-data "backend;backend" ^
  --add-data "frontend;frontend" ^
  --add-data "package\run.py;." ^
  --hidden-import flask ^
  --hidden-import flask_cors ^
  --hidden-import pandas ^
  --hidden-import numpy ^
  --hidden-import akshare ^
  --hidden-import werkzeug ^
  --hidden-import jinja2 ^
  --hidden-import markupsafe ^
  --hidden-import requests ^
  --hidden-import urllib3 ^
  --hidden-import http.client ^
  --hidden-import json ^
  --hidden-import sqlite3 ^
  --hidden-import concurrent.futures ^
  --collect-all akshare ^
  --collect-all pandas ^
  .\package\run.py

echo.
echo ========================================
echo  Build complete!
echo  Output: dist\StockClassroom\
echo ========================================
pause
