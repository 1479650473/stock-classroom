# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — stock-api 单文件 sidecar (Web 后端, 无 PyQt5)."""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

root = r"D:\小光工作区\projects\stock-classroom"

# akshare 自带 CSV/JSON 数据文件(file_fold 等), 必须打包为 data
datas = []
datas += collect_data_files('akshare')
datas += collect_data_files('pandas')
binaries = []
hiddenimports = [
    'backend.api.server', 'backend.api.settings_store', 'backend.api.paths',
    'backend.api.envelope', 'backend.api.jobman',
    'data_manager', 'indicators', 'akshare_source', 'data_lhb',
    'frontend.plugins.research.worker', 'frontend.plugins.trainer.engine',
    'backend.strategy.metrics', 'backend.strategy.describe',
    'backend.strategy.portfolio_rebalance', 'backend.strategy.regime',
    'backend.strategy.sell_rules', 'backend.strategy.position_guard',
    'backend.trade_engine.engine', 'backend.trade_engine.schema',
    'backend.agent.llm_client', 'backend.agent.toolkit', 'backend.agent.research_loop',
    'backend.agent.gateway', 'backend.agent.jobs', 'backend.agent.services',
    'openai',
]
hiddenimports += collect_submodules('akshare')
hiddenimports += collect_submodules('backend.factor_engine')

a = Analysis(
    [r'D:\小光工作区\projects\stock-classroom\package\run_web_api.py'],
    pathex=[root, r'D:\小光工作区\projects\stock-classroom\backend'],
    # 注意: 不要把 frontend 加入 pathex —— frontend/platform 会被当成顶层 platform 包,
    # 遮蔽 stdlib platform, 导致 pandas 等报 "module 'platform' has no attribute ..."
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'matplotlib', 'PyQt6', 'scipy', 'torch',
              'torchvision', 'sklearn', 'tensorflow',
              'frontend.platform', 'frontend.plugins.agent', 'frontend.plugins.research.panel',
              'frontend.plugins.research.companion', 'frontend.plugins.trainer.panel'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='stock-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
