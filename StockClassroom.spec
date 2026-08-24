# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('frontend\\cyq_calculator.js', 'frontend'), ('frontend\\plugins\\plugins.json', 'frontend\\plugins'), ('backend\\configs', 'backend\\configs')]
binaries = []
hiddenimports = ['data_manager', 'indicators', 'akshare_source', 'data_lhb', 'factor_engine', 'backend.factor_engine', 'backend.factor_engine.calculator', 'backend.factor_engine.scorer', 'backend.factor_engine.config', 'backend.factor_engine.models', 'backend.factor_engine.dsl', 'backend.factor_engine.filters', 'backend.cache_modules', 'backend.data_lhb', 'openai']
hiddenimports += collect_submodules('frontend.plugins')
hiddenimports += collect_submodules('frontend.platform')
hiddenimports += collect_submodules('akshare')
hiddenimports += collect_submodules('pandas')
tmp_ret = collect_all('PyQt5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('py_mini_racer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:\\小光工作区\\projects\\stock-classroom\\package\\run_desktop.py'],
    pathex=['D:\\小光工作区\\projects\\stock-classroom\\package\\..', 'D:\\小光工作区\\projects\\stock-classroom\\package\\..\\backend'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'backtesting', 'torch', 'torchvision', 'torchaudio', 'numba', 'llvmlite', 'sklearn'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StockClassroom',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StockClassroom',
)
