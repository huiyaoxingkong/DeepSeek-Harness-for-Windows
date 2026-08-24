# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the DeepSeek Harness desktop launcher.

import os

APP_NAME = "DeepSeek Harness"
ROOT = os.path.dirname(os.path.abspath(SPEC))

datas = [
    (os.path.join(ROOT, "ui"), "ui"),
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "dsh.ico"),
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
