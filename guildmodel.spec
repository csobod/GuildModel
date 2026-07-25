# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GuildModel.
# Build:  python -m PyInstaller guildmodel.spec --clean --noconfirm
# Output: dist/GuildModel/GuildModel.exe  (one-folder, Windows — packaged by
#                                           installer/GuildModel.iss)
#         dist/GuildModel.app             (bundle, macOS — see
#                                           scripts/build_release_macos.sh)
#
# Analysis inputs (hidden imports, bundled data, Qt excludes, VTK collection)
# live in build_common.py.
#
import os
import sys

sys.path.insert(0, SPECPATH)                       # noqa: F821 — SPECPATH is injected by PyInstaller
sys.path.insert(0, os.path.join(SPECPATH, "src"))  # noqa: F821 — src-layout: import guildmodel from source
from build_common import ICON_PATH, ICNS_PATH, analysis_inputs

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
    icon=(ICON_PATH if (sys.platform == "win32" and os.path.exists(ICON_PATH))
          else None),       # .ico is Windows-only; macOS gets .icns via BUNDLE
    # Flat layout (DLLs next to the exe) avoids _internal search failures on
    # Windows network drives. It CANNOT be flat on macOS: the exe "GuildModel"
    # and the bundled "guildmodel" package dir are the same name on the
    # case-insensitive filesystem, so COLLECT fails with ENOTDIR trying to
    # mkdir guildmodel/assets inside the GuildModel exe. Use the default
    # _internal/ there (also the standard layout for a macOS .app bundle).
    contents_directory="." if sys.platform == "win32" else "_internal",
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

if sys.platform == "darwin":
    # guildmodel/__init__.py is a bare version stamp — safe to import here.
    from guildmodel import __version__ as _app_version

    app = BUNDLE(
        coll,
        name="GuildModel.app",
        icon=ICNS_PATH if os.path.exists(ICNS_PATH) else None,
        bundle_identifier="org.spectaclemakers.guildmodel",
        version=_app_version,
        info_plist={
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "GuildModel Project",
                "CFBundleTypeExtensions": ["gmodel"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
