# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/sfjdk/Desktop/StellaSoraGachaTool/新建文件夹/stellasora_gacha_ui/launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/sfjdk/Desktop/StellaSoraGachaTool/新建文件夹/stellasora_gacha_ui/assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StellaSoraGachaTool',
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
    icon=['C:/Users/sfjdk/Desktop/StellaSoraGachaTool/新建文件夹/stellasora_gacha_ui/assets/app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StellaSoraGachaTool',
)
