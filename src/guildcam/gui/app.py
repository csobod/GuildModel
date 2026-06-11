"""GuildCAM main window — thin PySide6 shell over guildcam.core."""
from __future__ import annotations
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QStatusBar, QGroupBox, QTextEdit,
    QFrame, QSizePolicy, QMessageBox, QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QAction, QFont

from guildcam.gui.widgets.dxf_canvas import DxfCanvas
from guildcam.gui.widgets.params_panel import ParamsPanel
from guildcam.gui.widgets.preview_3d import Preview3D


# ------------------------------------------------------------------ DXF import worker

class ImportWorker(QObject):
    """Runs DXF import + boxing measurement off the GUI thread."""

    finished = Signal(dict, object, dict, list)  # layers, boxing|None, raw_summary, unrecognised
    error = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            import ezdxf as _ezdxf
            from collections import Counter as _Counter
            from guildcam.core.io_import.dxf import import_dxf
            from guildcam.core.layers import ALL_LAYERS as SUPPORTED_LAYERS
            from guildcam.core.io_import.normalize import points_to_polygon
            from guildcam.core.geometry.boxing import measure_from_polygon

            raw_doc = _ezdxf.readfile(str(self.path))
            raw_layers: dict[str, list[str]] = {}
            for e in raw_doc.modelspace():
                raw_layers.setdefault(e.dxf.layer, []).append(e.dxftype())
            raw_summary = {
                lyr: dict(_Counter(types))
                for lyr, types in raw_layers.items()
            }
            unrecognised = [
                lyr for lyr in raw_layers
                if lyr.upper() not in SUPPORTED_LAYERS
            ]

            layers = import_dxf(self.path)

            boxing = None
            lens_curves = layers.get("LENS", [])
            if len(lens_curves) >= 2:
                polys = [points_to_polygon(c) for c in lens_curves if len(c) >= 3]
                valid = [p for p in polys if p.is_valid and p.area > 1.0]
                if len(valid) >= 2:
                    boxing = measure_from_polygon(valid[0], valid[1])

            self.finished.emit(layers, boxing, raw_summary, unrecognised)
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ 3D mesh build worker

class MeshWorker(QObject):
    """Builds the relief mesh off the GUI thread."""

    finished = Signal(object)   # trimesh.Trimesh
    error = Signal(str)

    def __init__(self, outline, lens_od, lens_os, params) -> None:
        super().__init__()
        self.outline = outline
        self.lens_od = lens_od
        self.lens_os = lens_os
        self.params = params

    def run(self) -> None:
        try:
            from guildcam.core.relief.builder import build_preview_mesh
            mesh = build_preview_mesh(
                self.outline, self.lens_od, self.lens_os, self.params
            )
            self.finished.emit(mesh)
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ G-code generation worker

class GCodeWorker(QObject):
    """Builds back_relief.nc and front_profile.nc off the GUI thread."""

    finished = Signal(str)    # summary message with file paths
    progress = Signal(str)    # log line
    error = Signal(str)       # traceback

    def __init__(self, outline, scallop_enabled: bool, params: dict, out_dir: Path) -> None:
        super().__init__()
        self.outline = outline
        self.scallop_enabled = scallop_enabled
        self.params = params
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            self._generate()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _generate(self) -> None:
        import yaml
        import numpy as np
        from guildcam.core.cam.profile import profile_cut
        from guildcam.core.cam.dropcutter import drop_cutter_paths
        from guildcam.core.relief.scallop import back_scallop
        from guildcam.core.relief.heightfield import Heightfield
        from guildcam.core.post.grbl import GRBLPost

        p = self.params
        config_dir = Path(__file__).parent.parent / "config"

        with open(config_dir / "tools.yaml", encoding="utf-8") as f:
            tools_cfg = yaml.safe_load(f)
        with open(config_dir / "materials.yaml", encoding="utf-8") as f:
            mats_cfg = yaml.safe_load(f)

        relief_tool = tools_cfg.get(p["relief_tool_name"], tools_cfg["ball_2mm"])
        profile_tool = tools_cfg.get(p["profile_tool_name"], tools_cfg["flat_3mm"])

        mat_key = p["material_name"].split()[0].lower()
        mat = mats_cfg.get(mat_key, mats_cfg["acetate"])
        spindle_rpm = mat["spindle_rpm"]
        feed_rate = mat["feed_rate_mmpm"]
        plunge_rate = mat["plunge_rate_mmpm"]

        written: list[Path] = []

        # ---- back_relief.nc ----
        if self.scallop_enabled:
            self.progress.emit("[gcode] Building back-scallop heightfield…")
            scallop_hf = back_scallop(
                outline=self.outline,
                stock_thickness_mm=p["stock_thickness"],
                central_zone_mm=p["scallop_central"],
                slope_extent_mm=p["scallop_slope"],
                min_edge_thickness_mm=p["scallop_min"],
                resolution=0.5,
            )
            # Convert remaining-thickness field to cut-depth field:
            #   cut_z = scallop_z - stock_thickness  (negative = depth from back face)
            cut_z = scallop_hf.z - p["stock_thickness"]
            cut_hf = Heightfield(
                z=cut_z, origin=scallop_hf.origin, resolution=scallop_hf.resolution
            )

            self.progress.emit("[gcode] Computing back-relief raster paths…")
            back_paths = drop_cutter_paths(
                field=cut_hf,
                tool_type=relief_tool["type"],
                tool_radius_mm=relief_tool["radius_mm"],
                stepover_mm=p["stepover"],
            )
            self.progress.emit(f"[gcode] Back relief: {len(back_paths)} raster lines")

            post_back = GRBLPost(
                job_name="frame_back_relief",
                material=p["material_name"],
                tool_diameter_mm=relief_tool["diameter_mm"],
                spindle_rpm=spindle_rpm,
                feed_rate_mmpm=feed_rate,
                plunge_rate_mmpm=plunge_rate,
            )
            post_back.header("Back Relief")
            post_back.spindle_on()
            for line in back_paths:
                post_back.emit_polyline(line)
            post_back.end_program()

            back_file = self.out_dir / "back_relief.nc"
            post_back.write(back_file)
            written.append(back_file)
            self.progress.emit(
                f"[gcode] Wrote {back_file.name}  ({back_file.stat().st_size:,} bytes)"
            )
        else:
            self.progress.emit("[gcode] Back scallop disabled — skipping back_relief.nc")

        # ---- front_profile.nc ----
        self.progress.emit("[gcode] Computing front profile passes…")
        passes = profile_cut(
            outline=self.outline,
            tool_radius_mm=profile_tool["radius_mm"],
            stock_thickness_mm=p["stock_thickness"],
            stepdown_mm=p["stepdown_profile"],
            tab_count=p["tab_count"],
            tab_width_mm=p["tab_width"],
            tab_height_mm=p["tab_height"],
        )
        self.progress.emit(f"[gcode] Front profile: {len(passes)} depth passes")

        post_front = GRBLPost(
            job_name="frame_front_profile",
            material=p["material_name"],
            tool_diameter_mm=profile_tool["diameter_mm"],
            spindle_rpm=spindle_rpm,
            feed_rate_mmpm=feed_rate,
            plunge_rate_mmpm=plunge_rate,
        )
        post_front.header("Front Profile")
        post_front.spindle_on()
        for depth_pass in passes:
            for polyline in depth_pass:
                post_front.emit_polyline(polyline)
        post_front.end_program()

        front_file = self.out_dir / "front_profile.nc"
        post_front.write(front_file)
        written.append(front_file)
        self.progress.emit(
            f"[gcode] Wrote {front_file.name}  ({front_file.stat().st_size:,} bytes)"
        )

        summary = "Generated:\n" + "\n".join(f"  {f}" for f in written)
        self.finished.emit(summary)


# ------------------------------------------------------------------ action panel

class ActionPanel(QWidget):
    """Right-hand panel: file info, log, and primary action buttons."""

    generate_requested = Signal()
    export_requested = Signal()
    build3d_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # --- file info ---
        info_grp = QGroupBox("File")
        info_lay = QVBoxLayout(info_grp)
        self.filename_label = QLabel("None")
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("font-size: 11px;")
        self.layers_label = QLabel("Layers: —")
        self.layers_label.setStyleSheet("font-size: 11px; color: #555;")
        info_lay.addWidget(self.filename_label)
        info_lay.addWidget(self.layers_label)
        lay.addWidget(info_grp)

        # --- 3D preview ---
        preview_grp = QGroupBox("3D Preview")
        prev_lay = QVBoxLayout(preview_grp)

        self.build3d_btn = QPushButton("Build 3D Model")
        self.build3d_btn.setEnabled(False)
        self.build3d_btn.setMinimumHeight(32)
        font = self.build3d_btn.font()
        font.setBold(True)
        self.build3d_btn.setFont(font)
        self.build3d_btn.clicked.connect(self.build3d_requested)
        prev_lay.addWidget(self.build3d_btn)

        self.build_status = QLabel("Load a DXF first")
        self.build_status.setStyleSheet("font-size: 10px; color: #666;")
        self.build_status.setWordWrap(True)
        prev_lay.addWidget(self.build_status)
        lay.addWidget(preview_grp)

        # --- actions ---
        act_grp = QGroupBox("Generate")
        act_lay = QVBoxLayout(act_grp)

        self.generate_btn = QPushButton("Generate G-code")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setMinimumHeight(36)
        font2 = self.generate_btn.font()
        font2.setBold(True)
        self.generate_btn.setFont(font2)
        self.generate_btn.clicked.connect(self.generate_requested)
        act_lay.addWidget(self.generate_btn)

        note = QLabel("Generates two GRBL .nc files:\n  • back_relief.nc\n  • front_profile.nc")
        note.setStyleSheet("font-size: 10px; color: #666;")
        note.setWordWrap(True)
        act_lay.addWidget(note)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        act_lay.addWidget(sep)

        self.export_stl_btn = QPushButton("Export STL…")
        self.export_stl_btn.setEnabled(False)
        self.export_stl_btn.clicked.connect(self.export_requested)
        act_lay.addWidget(self.export_stl_btn)

        lay.addWidget(act_grp)

        # --- log ---
        log_grp = QGroupBox("Log")
        log_lay = QVBoxLayout(log_grp)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "background: #1a1a1a; color: #ffd580; font-family: Consolas, monospace;"
            " font-size: 11px; border: none;"
        )
        log_lay.addWidget(self.log)
        lay.addWidget(log_grp)

    def append_log(self, message: str) -> None:
        self.log.append(message)
        self.log.ensureCursorVisible()

    def set_file_loaded(self, name: str, layer_summary: str) -> None:
        self.filename_label.setText(name)
        self.layers_label.setText(layer_summary)
        self.generate_btn.setEnabled(True)
        self.export_stl_btn.setEnabled(True)
        self.build3d_btn.setEnabled(True)
        self.build_status.setText("Ready to build")


# ------------------------------------------------------------------ main window

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GuildCAM  —  Frame CAM")
        self.setMinimumSize(1200, 780)

        self._load_stylesheet()
        self._build_ui()
        self._build_menu()
        self._connect_signals()

        self._import_thread: Optional[QThread] = None
        self._import_worker: Optional[ImportWorker] = None
        self._mesh_thread: Optional[QThread] = None
        self._mesh_worker: Optional[MeshWorker] = None
        self._gcode_thread: Optional[QThread] = None
        self._gcode_worker: Optional[GCodeWorker] = None

        # Stored geometry from the last successful import
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None

    # ------------------------------------------------------------------ style

    def _load_stylesheet(self) -> None:
        qss_path = Path(__file__).parent / "style" / "guild.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        self.params = ParamsPanel()
        splitter.addWidget(self.params)

        # Center: toolbar + stacked canvas
        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        # Toolbar strip
        toolbar_strip = QWidget()
        toolbar_strip.setFixedHeight(36)
        toolbar_strip.setStyleSheet("background: #ffe8a8; border-bottom: 1px solid #c8a040;")
        ts_lay = QHBoxLayout(toolbar_strip)
        ts_lay.setContentsMargins(8, 4, 8, 4)

        lbl = QLabel("GuildCAM")
        font = QFont("League Spartan", 16)
        font.setBold(True)
        lbl.setFont(font)
        ts_lay.addWidget(lbl)
        ts_lay.addStretch()

        # 2D / 3D toggle buttons
        self.btn_2d = QPushButton("2D Outline")
        self.btn_3d = QPushButton("3D Preview")
        for btn in (self.btn_2d, self.btn_3d):
            btn.setFixedHeight(24)
            btn.setFixedWidth(84)
            btn.setCheckable(True)
        self.btn_2d.setChecked(True)
        self.btn_2d.clicked.connect(lambda: self._switch_view(0))
        self.btn_3d.clicked.connect(lambda: self._switch_view(1))
        ts_lay.addWidget(self.btn_2d)
        ts_lay.addWidget(self.btn_3d)
        ts_lay.addSpacing(8)

        self.zoom_label = QLabel("Zoom: —")
        self.zoom_label.setStyleSheet("font-size: 11px; color: #555;")
        ts_lay.addWidget(self.zoom_label)

        fit_btn = QPushButton("Fit")
        fit_btn.setFixedWidth(44)
        fit_btn.setFixedHeight(24)
        fit_btn.clicked.connect(self._on_fit)
        ts_lay.addWidget(fit_btn)

        center_lay.addWidget(toolbar_strip)

        # Stacked widget: page 0 = 2D canvas, page 1 = 3D preview
        self.stack = QStackedWidget()
        self.canvas = DxfCanvas()
        self.preview3d = Preview3D()
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.preview3d)
        center_lay.addWidget(self.stack)

        splitter.addWidget(center)

        self.action_panel = ActionPanel()
        splitter.addWidget(self.action_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

        sb = QStatusBar()
        sb.setStyleSheet("background: #ffe8a8; border-top: 1px solid #c8a040;")
        self.status_lbl = QLabel("Ready — open a DXF to begin")
        sb.addWidget(self.status_lbl)
        self.setStatusBar(sb)

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        open_act = QAction("&Open DXF…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._on_open)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = mb.addMenu("&View")
        fit_act = QAction("&Fit to view", self)
        fit_act.setShortcut("Ctrl+0")
        fit_act.triggered.connect(self._on_fit)
        view_menu.addAction(fit_act)
        view2d_act = QAction("2D Outline", self)
        view2d_act.triggered.connect(lambda: self._switch_view(0))
        view_menu.addAction(view2d_act)
        view3d_act = QAction("3D Preview", self)
        view3d_act.triggered.connect(lambda: self._switch_view(1))
        view_menu.addAction(view3d_act)

        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About GuildCAM", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ------------------------------------------------------------------ connections

    def _connect_signals(self) -> None:
        self.params.import_btn.clicked.connect(self._on_open)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)

        for layer, cb in self.params.layer_checks.items():
            cb.toggled.connect(
                lambda checked, lyr=layer: self.canvas.set_layer_visible(lyr, checked)
            )

        self.action_panel.generate_requested.connect(self._on_generate)
        self.action_panel.export_requested.connect(self._on_export_stl)
        self.action_panel.build3d_requested.connect(self._on_build_3d)

        # Live rebuild when relief params change (only if 3D view is active)
        self.params.relief_changed.connect(self._on_relief_params_changed)

    # ------------------------------------------------------------------ view switch

    def _switch_view(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.btn_2d.setChecked(index == 0)
        self.btn_3d.setChecked(index == 1)
        if index == 0:
            self.zoom_label.show()
        else:
            self.zoom_label.hide()

    # ------------------------------------------------------------------ DXF import

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open DXF file", "", "DXF files (*.dxf);;All files (*)",
        )
        if not path_str:
            return
        self._load_dxf(Path(path_str))

    def _load_dxf(self, path: Path) -> None:
        self.status_lbl.setText(f"Loading {path.name}…")
        self.action_panel.append_log(f"[import] {path.name}")

        self._import_worker = ImportWorker(path)
        self._import_thread = QThread()
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.error.connect(self._import_thread.quit)
        self._import_thread.start()

    def _on_import_finished(
        self, layers: dict, boxing, raw_summary: dict, unrecognised: list
    ) -> None:
        from guildcam.core.io_import.normalize import points_to_polygon

        self.canvas.set_layers(layers)

        fname = self._import_worker.path.name if self._import_worker else "?"
        non_empty = [k for k, v in layers.items() if v]

        self.action_panel.set_file_loaded(
            fname,
            "Layers: " + ", ".join(non_empty) if non_empty else "No recognised layers",
        )
        self.params.source_label.setText(fname)

        # raw DXF layer report
        self.action_panel.append_log(
            "[dxf]  Layers: "
            + ", ".join(
                f"{lyr}({','.join(t for t in types)})"
                for lyr, types in raw_summary.items()
            )
        )
        if unrecognised:
            self.action_panel.append_log(
                "[warn] Unrecognised layers (ignored): "
                + ", ".join(repr(l) for l in unrecognised)
                + "  (expected: " + " ".join(sorted(SUPPORTED_LAYERS)) + ")"
            )

        # Extract and cache polygons for 3D build
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None

        outline_curves = layers.get("OUTLINE", [])
        if outline_curves:
            self._outline_poly = points_to_polygon(outline_curves[0])

        lens_curves = layers.get("LENS", [])
        lens_polys = [
            points_to_polygon(c) for c in lens_curves if len(c) >= 3
        ]
        valid_lens = [p for p in lens_polys if p.is_valid and p.area > 1.0]
        if len(valid_lens) >= 2:
            sorted_lens = sorted(valid_lens, key=lambda p: p.centroid.x)
            self._lens_od = sorted_lens[1]   # right in DXF = OD
            self._lens_os = sorted_lens[0]   # left = OS

        # Boxing
        if boxing is not None:
            self.params.update_boxing(boxing.a, boxing.b, boxing.dbl, boxing.ed)
            self.action_panel.append_log(
                f"[boxing] A={boxing.a:.1f}  B={boxing.b:.1f}"
                f"  DBL={boxing.dbl:.1f}  ED={boxing.ed:.1f} mm"
            )
        else:
            lens_count = len(lens_curves)
            self.action_panel.append_log(
                f"[boxing] Skipped — {lens_count} LENS curve(s) found, need ≥2."
            )

        curve_counts = {k: len(v) for k, v in layers.items() if v}
        if curve_counts:
            self.action_panel.append_log(
                "[curves] " + "  ".join(f"{k}:{n}" for k, n in curve_counts.items())
            )

        self.status_lbl.setText(f"Loaded: {fname}")

    def _on_import_error(self, tb: str) -> None:
        self.action_panel.append_log("[ERROR] Import failed:\n" + tb)
        self.status_lbl.setText("Import failed — see log")
        QMessageBox.critical(self, "Import error", "DXF import failed.\n\nSee log for details.")

    # ------------------------------------------------------------------ 3D build

    def _on_build_3d(self) -> None:
        if self._outline_poly is None or self._lens_od is None or self._lens_os is None:
            self.action_panel.append_log(
                "[3D] Need OUTLINE + 2 LENS polygons. Load a valid frame DXF first."
            )
            return
        self._start_mesh_build()

    def _on_relief_params_changed(self) -> None:
        if self.stack.currentIndex() == 1 and self._outline_poly is not None:
            self._start_mesh_build()

    def _start_mesh_build(self) -> None:
        from guildcam.core.relief.builder import ReliefBuildParams

        p = self.params
        params = ReliefBuildParams(
            stock_thickness_mm=p.stock_thickness.value(),
            scallop_enabled=p.scallop_cb.isChecked(),
            scallop_central_zone_mm=p.scallop_central.value(),
            scallop_slope_extent_mm=p.scallop_slope.value(),
            scallop_min_edge_mm=p.scallop_min.value(),
            nosepad_enabled=p.nosepad_cb.isChecked(),
            nosepad_height_mm=p.nosepad_height.value(),
            nosepad_footprint_mm=p.nosepad_footprint.value(),
            nosepad_blend_radius_mm=4.0,
            groove_enabled=p.groove_cb.isChecked(),
            groove_depth_mm=p.groove_depth.value(),
            groove_width_mm=p.groove_width.value(),
        )

        self.action_panel.build_status.setText("Building…")
        self.action_panel.build3d_btn.setEnabled(False)
        self.action_panel.append_log("[3D] Building mesh…")
        self._switch_view(1)

        self._mesh_worker = MeshWorker(
            self._outline_poly, self._lens_od, self._lens_os, params
        )
        self._mesh_thread = QThread()
        self._mesh_worker.moveToThread(self._mesh_thread)
        self._mesh_thread.started.connect(self._mesh_worker.run)
        self._mesh_worker.finished.connect(self._on_mesh_finished)
        self._mesh_worker.error.connect(self._on_mesh_error)
        self._mesh_worker.finished.connect(self._mesh_thread.quit)
        self._mesh_worker.error.connect(self._mesh_thread.quit)
        self._mesh_thread.start()

    def _on_mesh_finished(self, mesh) -> None:
        self.preview3d.show_mesh(mesh)
        n_v = len(mesh.vertices)
        n_t = len(mesh.faces)
        self.action_panel.append_log(f"[3D] Done — {n_v:,} verts, {n_t:,} tris")
        self.action_panel.build_status.setText(f"{n_v:,} verts · {n_t:,} tris")
        self.action_panel.build3d_btn.setEnabled(True)
        self.status_lbl.setText("3D model ready")

    def _on_mesh_error(self, tb: str) -> None:
        self.action_panel.append_log("[3D ERROR]\n" + tb)
        self.action_panel.build_status.setText("Build failed — see log")
        self.action_panel.build3d_btn.setEnabled(True)

    # ------------------------------------------------------------------ other slots

    def _on_fit(self) -> None:
        if self.stack.currentIndex() == 0:
            self.canvas.fit_to_view()
        else:
            self.preview3d._cam_reset()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"Zoom: {scale:.1f} px/mm")

    def _on_generate(self) -> None:
        if self._outline_poly is None:
            QMessageBox.warning(
                self,
                "No frame outline",
                "Load a DXF with an OUTLINE layer before generating G-code.",
            )
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Choose output folder for .nc files"
        )
        if not out_dir:
            return

        params = self._collect_gcode_params()

        self.action_panel.generate_btn.setEnabled(False)
        self.action_panel.append_log(f"[gcode] Output folder: {out_dir}")

        self._gcode_worker = GCodeWorker(
            outline=self._outline_poly,
            scallop_enabled=params["scallop_enabled"],
            params=params,
            out_dir=Path(out_dir),
        )
        self._gcode_thread = QThread()
        self._gcode_worker.moveToThread(self._gcode_thread)
        self._gcode_thread.started.connect(self._gcode_worker.run)
        self._gcode_worker.progress.connect(self.action_panel.append_log)
        self._gcode_worker.finished.connect(self._on_gcode_finished)
        self._gcode_worker.error.connect(self._on_gcode_error)
        self._gcode_worker.finished.connect(self._gcode_thread.quit)
        self._gcode_worker.error.connect(self._gcode_thread.quit)
        self._gcode_thread.start()

    def _collect_gcode_params(self) -> dict:
        p = self.params
        return {
            "relief_tool_name":  p.tool_relief.currentText(),
            "profile_tool_name": p.tool_profile.currentText(),
            "material_name":     p.material.currentText(),
            "stock_thickness":   p.stock_thickness.value(),
            "stepover":          p.stepover.value(),
            "stepdown_relief":   p.stepdown_relief.value(),
            "stepdown_profile":  p.stepdown_profile.value(),
            "tab_count":         p.tab_count.value(),
            "tab_width":         p.tab_width.value(),
            "tab_height":        p.tab_height.value(),
            "scallop_enabled":   p.scallop_cb.isChecked(),
            "scallop_central":   p.scallop_central.value(),
            "scallop_slope":     p.scallop_slope.value(),
            "scallop_min":       p.scallop_min.value(),
        }

    def _on_gcode_finished(self, summary: str) -> None:
        self.action_panel.append_log("[gcode] Done.")
        self.action_panel.generate_btn.setEnabled(True)
        self.status_lbl.setText("G-code ready")
        QMessageBox.information(self, "G-code generated", summary)

    def _on_gcode_error(self, tb: str) -> None:
        self.action_panel.append_log("[gcode ERROR]\n" + tb)
        self.action_panel.generate_btn.setEnabled(True)
        self.status_lbl.setText("G-code generation failed — see log")

    def _on_export_stl(self) -> None:
        self.action_panel.append_log("[export] STL export not yet implemented.")
        QMessageBox.information(self, "Export STL", "STL export will be available in M3.")

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About GuildCAM",
            "<b>GuildCAM</b> v0.1 — pre-release demo<br><br>"
            "Free, open-source CAM tool for spectacle frame cutting on GRBL CNCs.<br>"
            "Companion to the Guild CNC and gSender fork.<br><br>"
            "GPLv3 — see LICENSE for details.",
        )


# ------------------------------------------------------------------ entry point

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GuildCAM")
    app.setOrganizationName("Guild")

    win = MainWindow()
    win.show()

    # Auto-load demo frame in dev mode
    project_root = Path(__file__).parents[3]
    for dev_name in ("frame_illustration.dxf", "hinge_th-23_front.dxf"):
        dev_dxf = project_root / dev_name
        if dev_dxf.exists():
            win._load_dxf(dev_dxf)
            break

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
