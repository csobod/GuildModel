"""Shared PyInstaller analysis inputs for GuildModel.

Imported by ``guildmodel.spec`` (one-folder build). Keeps the hidden imports,
bundled data files, and excluded Qt modules in one place.

Unlike GuildDraw (2D, Qt-only), GuildModel renders 3D through PyVista/VTK, so the
VTK binaries + QtOpenGL(Widgets) must be COLLECTED, not excluded. The package
lives under ``src/`` (src-layout), so data is bundled to the ``guildmodel/...``
dest the frozen ``__file__`` resolution expects.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

# App icons, relative to the spec directory (repo root). The .ico is embedded
# in the Windows EXE; the .icns is embedded in the macOS .app BUNDLE. Both are
# regenerated from icon.svg by scripts/make_icon.py before each freeze.
ICON_PATH = "src/guildmodel/assets/icon.ico"
ICNS_PATH = "src/guildmodel/assets/icon.icns"

# Heavy third-party packages that ship DLLs / data files / dynamically-imported
# submodules PyInstaller's static analysis misses. collect_all bundles all three.
_COLLECT_ALL = [
    "vtkmodules",   # VTK core (the OpenGL render DLLs live here)
    "vtk",          # the thin vtk.py shim pyvista imports
    "pyvista",
    "pyvistaqt",
    "shapely",      # GEOS DLLs
    "ezdxf",
    "trimesh",      # bundled resource data
]

# Qt modules GuildModel never touches — excluded to keep the bundle lean.
# KEPT (do NOT exclude): QtOpenGL / QtOpenGLWidgets (VTK render surface),
# QtSvg / QtSvgWidgets (QSvgRenderer draws the toolbar + app icon).
_EXCLUDED_QT = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtAxContainer",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

# GuildModel package data, bundled to the dest the runtime expects (it locates
# these via ``Path(__file__).parents[...] / "config"`` etc., which under a frozen
# build resolves inside the recreated ``guildmodel/`` package tree).
_GUILDMODEL_DATAS = [
    ("src/guildmodel/config", "guildmodel/config"),
    ("src/guildmodel/gui/resources", "guildmodel/gui/resources"),
    ("src/guildmodel/assets", "guildmodel/assets"),
]


#: The B-Rep kernel's package, kept out of the freeze along with OCCT itself.
#:
#: `cadquery-ocp` has been an optional extra since M-N4 — not a dependency, not
#: the default kernel, and hidden from Preferences unless `GUILDMODEL_BREP` is
#: set — but none of that reached the installer. `collect_submodules` enumerates
#: **every** `guildmodel` submodule, which named all six `core.solid` modules as
#: hidden imports; each imports OCP at module level, unguarded; and the release
#: venv installs `.[dev,packaging]`, where `dev` pulls `guildmodel[brep]` in for
#: the parity gates. So the freeze bundled **264 MB** of OpenCASCADE (163 MB of
#: `OCP` plus 101 MB of `cadquery_ocp.libs`) into an app that cannot reach it.
#:
#: Dropping it is safe rather than merely smaller: `kernels.resolve_kernel` asks
#: `find_spec("OCP")` and answers "mesh" when it is absent, and both the GUI
#: (`_model_kernel`) and `zmap.castle_relief` route through it — so a project
#: saved with the B-Rep selected opens on the mesh here instead of failing.
#: `core.solid` stays in the repo: it is the third opinion the parity gates
#: measure the mesh against, and a developer install still gets it.
_BREP_PKG = "guildmodel.core.solid"
_EXCLUDED_BREP = ["OCP", "cadquery_ocp", "cadquery_ocp_proxy",
                  _BREP_PKG]


def analysis_inputs():
    """Return the kwargs shared by the spec's ``Analysis(...)`` call."""
    datas, binaries, hiddenimports = [], [], []
    for pkg in _COLLECT_ALL:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h

    # scipy / pydantic reach some submodules dynamically.
    hiddenimports += collect_submodules("scipy")
    hiddenimports += collect_submodules("pydantic")
    hiddenimports += [m for m in collect_submodules("guildmodel")
                      if not m.startswith(_BREP_PKG)]

    datas += _GUILDMODEL_DATAS

    return {
        "binaries": binaries,
        "datas": datas,
        "hiddenimports": hiddenimports,
        "excludes": _EXCLUDED_QT + _EXCLUDED_BREP,
    }
