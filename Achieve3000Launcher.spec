# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Resource and asset bindings
datas = []
if os.path.exists('achieve3000.ico'):
    datas.append(('achieve3000.ico', '.'))
if os.path.exists('achieve3000.png'):
    datas.append(('achieve3000.png', '.'))
if os.path.exists('achieve3000.icns'):
    datas.append(('achieve3000.icns', '.'))
if os.path.exists('mac_launcher.py'):
    datas.append(('mac_launcher.py', '.'))

# Select native platform icon
icon_target = None
if sys.platform == 'win32' and os.path.exists('achieve3000.ico'):
    icon_target = 'achieve3000.ico'
elif sys.platform == 'darwin' and os.path.exists('achieve3000.icns'):
    icon_target = 'achieve3000.icns'

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['mac_launcher'],
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
    name='Achieve3000Launcher',
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
    icon=[icon_target] if icon_target else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Achieve3000Launcher',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Achieve3000Launcher.app',
        icon='achieve3000.icns' if os.path.exists('achieve3000.icns') else None,
        bundle_identifier='com.achieve3000.launcher',
        info_plist={
            'CFBundleName': 'Achieve3000 Launcher',
            'CFBundleDisplayName': 'Achieve3000 Launcher',
            'CFBundleIdentifier': 'com.achieve3000.launcher',
            'CFBundleVersion': '1.0.14',
            'CFBundleShortVersionString': '1.0.14',
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
            'LSMinimumSystemVersion': '10.13.0',
        },
    )
