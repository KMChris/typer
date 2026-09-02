# PyInstaller spec for Typer (onedir build). Run: .venv\Scripts\python -m PyInstaller --noconfirm typer.spec
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "src" / "typer_app" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "src" / "typer_app" / "ui"), "typer_app/ui"),
        (str(ROOT / "src" / "typer_app" / "assets"), "typer_app/assets"),
    ],
    hiddenimports=[
        "clr",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "unittest", "pytest", "pydoc", "doctest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Typer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "src" / "typer_app" / "assets" / "typer.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Typer",
)
