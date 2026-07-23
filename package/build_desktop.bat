@echo off
chcp 65001 >nul
echo ========================================
echo  stock-classroom v4.0 - PyInstaller Build
echo ========================================
echo.

set PYINST=C:\Users\Lenovo\AppData\Roaming\Python\Python314\Scripts\pyinstaller.exe
set PROJ=%~dp0..
set PACKAGE=%~dp0

cd /d "%PROJ%"

echo [1/3] Cleaning...
if exist dist\StockClassroom rmdir /s /q dist\StockClassroom
if exist build rmdir /s /q build

echo [2/3] Building (5-8 minutes)...
"%PYINST%" ^
  --onedir ^
  --name StockClassroom ^
  --windowed ^
  --noconfirm ^
  --paths "%PROJ%" ^
  --paths "%PROJ%\backend" ^
  --add-data "frontend\cyq_calculator.js;frontend" ^
  --add-data "frontend\plugins\plugins.json;frontend\plugins" ^
  --add-data "backend\configs;backend\configs" ^
  --collect-submodules frontend.plugins ^
  --collect-submodules frontend.platform ^
  --collect-all PyQt5 ^
  --collect-all py_mini_racer ^
  --collect-submodules akshare ^
  --collect-submodules pandas ^
  --hidden-import data_manager ^
  --hidden-import indicators ^
  --hidden-import akshare_source ^
  --hidden-import data_lhb ^
  --hidden-import factor_engine ^
  --hidden-import backend.factor_engine ^
  --hidden-import backend.factor_engine.calculator ^
  --hidden-import backend.factor_engine.scorer ^
  --hidden-import backend.factor_engine.config ^
  --hidden-import backend.factor_engine.models ^
  --hidden-import backend.factor_engine.dsl ^
  --hidden-import backend.factor_engine.filters ^
  --hidden-import backend.cache_modules ^
  --hidden-import backend.data_lhb ^
  --hidden-import openai ^
  --exclude-module matplotlib ^
  --exclude-module scipy ^
  --exclude-module backtesting ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module torchaudio ^
  --exclude-module numba ^
  --exclude-module llvmlite ^
  --exclude-module sklearn ^
  %PACKAGE%run_desktop.py

if errorlevel 1 (
  echo.
  echo ========================================
  echo  BUILD FAILED
  echo ========================================
  pause
  exit /b 1
)

echo [3/3] Creating data directory...
mkdir dist\StockClassroom\data 2>nul

echo.
echo ========================================
echo  Build complete! (~280 MB)
echo  Output: dist\StockClassroom\
echo.
echo  Usage: put kline.db + stock_cache.db in dist\StockClassroom\data\
echo  Launch: dist\StockClassroom\StockClassroom.exe
echo ========================================
pause
