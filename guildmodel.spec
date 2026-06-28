# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildModel — ONE-FOLDER build.
# Build:  python -m PyInstaller guildmodel.spec --clean --noconfirm
# Output: dist/GuildModel/GuildModel.exe  (one-folder, Windows)
#
# This is the build the Inno Setup installer (installer/GuildModel.iss) packages.
# Analysis inputs (hidden imports, bundled data, Qt excludes, VTK collection)
# live in build_common.py.
#
import os
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 — SPECPATH is injected by PyInstaller
from build_common import ICON_PATH, analysis_inputs

a = Analysis(
    ["main.py"],
    pathex=["src"],             # src-layout: import guildmodel from source
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    **analysis_inputs(),
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuildModel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX packing trips AV/EDR heuristics
    console=False,          # windowed — no terminal popup on Windows
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
    contents_directory=".", # flat layout: DLLs next to the exe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GuildModel",
)
