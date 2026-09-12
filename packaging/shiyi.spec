# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec:「拾遗」单 exe(onefile、无控制台)。

用法(在 packaging/ 目录下):
    pyinstaller shiyi.spec
产物:packaging/dist/拾遗.exe(若 icon.ico 已由 make_icon.ps1 生成则带图标)

PyInstaller 只是构建期工具,运行时仍是纯标准库。
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent          # packaging/ 的上级 = 项目根
ICON = Path(SPECPATH) / "icon.ico"

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "web" / "index.html"), "web")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_kw = dict(name="拾遗", debug=False, strip=False, upx=False,
              console=False)
if ICON.exists():
    exe_kw["icon"] = str(ICON)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    **exe_kw,
)
