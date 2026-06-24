"""Shared PyInstaller analysis inputs for GuildCAM.

Imported by ``guildcam.spec`` (one-folder build). Keeps the hidden imports,
bundled data files, and excluded Qt modules in one place.

Unlike GuildDraw (2D, Qt-only), GuildCAM renders 3D through PyVista/VTK, so the
VTK binaries + QtOpenGL(Widgets) must be COLLECTED, not excluded. The package
lives under ``src/`` (src-layout), so data is bundled to the ``guildcam/...``
dest the frozen ``__file__`` resolution expects.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# App icon, relative to the spec directory (repo root).
ICON_PATH = "src/guildcam/assets/icon.ico"

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

# Qt modules GuildCAM never touches — excluded to keep the bundle lean.
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

# GuildCAM package data, bundled to the dest the runtime expects (it locates
# these via ``Path(__file__).parents[...] / "config"`` etc., which under a frozen
# build resolves inside the recreated ``guildcam/`` package tree).
_GUILDCAM_DATAS = [
    ("src/guildcam/config", "guildcam/config"),
    ("src/guildcam/gui/resources", "guildcam/gui/resources"),
    ("src/guildcam/assets", "guildcam/assets"),
]


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
    hiddenimports += collect_submodules("guildcam")
    # pyclipper / svgelements are small pure/binary extensions — make sure their
    # data (if any) rides along.
    datas += collect_data_files("svgelements")

    datas += _GUILDCAM_DATAS

    return {
        "binaries": binaries,
        "datas": datas,
        "hiddenimports": hiddenimports,
        "excludes": _EXCLUDED_QT,
    }
