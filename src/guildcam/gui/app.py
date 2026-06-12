"""GuildCAM main window — thin PySide6 shell over guildcam.core."""
from __future__ import annotations
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QStatusBar, QGroupBox, QTextEdit,
    QFrame, QSizePolicy, QMessageBox, QStackedWidget,
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QCheckBox, QFormLayout,
    QDoubleSpinBox, QLineEdit, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject
from PySide6.QtGui import QAction

from guildcam.core.layers import ALL_LAYERS as SUPPORTED_LAYERS
from guildcam.gui import prefs as prefs_mod
from guildcam.gui.style import theme
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
    """Builds the castle relief mesh off the GUI thread (matched SCULPT
    zone layouts only — the spike's distance-based fallback is retired)."""

    finished = Signal(object, str)   # trimesh.Trimesh, stage
    error = Signal(str)

    def __init__(
        self, partition, castle, hinge_polys=(), stage: str = "pockets",
        resolution: float = 0.3,
    ) -> None:
        super().__init__()
        self.partition = partition
        self.castle = castle
        self.hinge_polys = list(hinge_polys)
        self.stage = stage
        self.resolution = resolution

    def run(self) -> None:
        try:
            from guildcam.core.relief.castle import (
                build_castle_mesh, build_castle_stage,
            )
            relief = build_castle_stage(
                self.partition, self.castle, self.hinge_polys,
                stage=self.stage, resolution=self.resolution,
            )
            self.finished.emit(build_castle_mesh(relief), self.stage)
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ STL export worker

class ExportWorker(QObject):
    """Rebuilds the full castle at export resolution and writes the STL.

    Never the preview cache (M4.5 Part B): export quality is controlled by
    the export_resolution_mm preference, independent of the 3D view.
    """

    finished = Signal(str)   # written path
    progress = Signal(str)   # log line
    error = Signal(str)

    def __init__(
        self, partition, castle, hinge_polys, resolution: float, path: Path,
    ) -> None:
        super().__init__()
        self.partition = partition
        self.castle = castle
        self.hinge_polys = list(hinge_polys)
        self.resolution = resolution
        self.path = Path(path)

    def run(self) -> None:
        try:
            from guildcam.core.relief.castle import (
                build_castle_mesh, build_castle_relief,
            )
            self.progress.emit(
                f"[export] Building castle at {self.resolution} mm…"
            )
            relief = build_castle_relief(
                self.partition, self.castle, self.hinge_polys,
                resolution=self.resolution,
            )
            mesh = build_castle_mesh(relief)
            self.progress.emit(
                f"[export] {len(mesh.vertices):,} verts, "
                f"{len(mesh.faces):,} tris, watertight={mesh.is_watertight}"
            )
            mesh.export(str(self.path))
            self.finished.emit(str(self.path))
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ G-code generation worker

class GCodeWorker(QObject):
    """Builds posterior_cut.nc (castle) or front_profile.nc (fallback)
    off the GUI thread."""

    finished = Signal(str, object)   # summary message, op-summary rows | None
    progress = Signal(str)           # log line
    error = Signal(str)              # traceback

    def __init__(
        self, outline, castle, params: dict, out_dir: Path,
        partition=None, hinge_polys=(),
    ) -> None:
        super().__init__()
        self.outline = outline
        self.castle = castle
        self.params = params
        self.out_dir = out_dir
        self.partition = partition
        self.hinge_polys = list(hinge_polys)

    def run(self) -> None:
        try:
            self._generate()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _generate_castle(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Five-op posterior program: hinge pockets -> rough -> fine ->
        eyewires -> perimeter, single .nc, onion skin instead of tabs."""
        import yaml
        from guildcam.core.cam.castle_ops import (
            fixture_clearance_violations, generate_castle_program,
            op_summaries, write_castle_program,
        )
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.relief.castle import build_castle_relief

        p = self.params
        castle = self.castle
        tool = tools_cfg.get("flat_3175", next(iter(tools_cfg.values())))
        mat_key = p["material_name"].split()[0].lower()
        mat = mats_cfg.get(mat_key, mats_cfg["acetate"])

        self.progress.emit("[gcode] Castle: building relief…")
        relief = build_castle_relief(
            self.partition, castle, self.hinge_polys, resolution=0.15
        )
        self.progress.emit("[gcode] Castle: generating five operations…")
        ops = generate_castle_program(relief, castle, self.hinge_polys, tool)
        for op in ops:
            zmin, zmax = op.z_range()
            self.progress.emit(
                f"[gcode]   {op.name}: {len(op.paths)} paths, Z {zmin:.2f}..{zmax:.2f}"
            )

        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        violations = fixture_clearance_violations(ops, fixture, tool["radius_mm"])
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        post = GRBLPost(
            job_name="posterior_cut",
            material=p["material_name"],
            tool_diameter_mm=tool["diameter_mm"],
            spindle_rpm=mat["spindle_rpm"],
            feed_rate_mmpm=mat["feed_rate_mmpm"],
            plunge_rate_mmpm=mat["plunge_rate_mmpm"],
            safe_z_mm=castle.stock.total_pad_height_mm + 5.0,
        )
        write_castle_program(ops, post)
        out_file = self.out_dir / "posterior_cut.nc"
        post.write(out_file)
        self.progress.emit(
            f"[gcode] Wrote {out_file.name}  ({out_file.stat().st_size:,} bytes)"
        )
        summary = f"Posterior program written:\n  {out_file}"
        if violations:
            summary += f"\n\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        rows = op_summaries(ops, feed_rate_mmpm=mat["feed_rate_mmpm"])
        self.finished.emit(summary, rows)

    def _generate(self) -> None:
        import yaml
        from guildcam.core.cam.profile import profile_cut
        from guildcam.core.post.grbl import GRBLPost

        p = self.params
        config_dir = Path(__file__).parent.parent / "config"

        with open(config_dir / "tools.yaml", encoding="utf-8") as f:
            tools_cfg = yaml.safe_load(f)
        with open(config_dir / "materials.yaml", encoding="utf-8") as f:
            mats_cfg = yaml.safe_load(f)

        # ---- Castle path: the five-operation posterior program (M3) ----
        if self.partition is not None and self.partition.matched:
            self._generate_castle(tools_cfg, mats_cfg, config_dir)
            return

        # ---- Fallback for DXFs without SCULPT zones: profile cut only ----
        profile_tool = tools_cfg.get(p["profile_tool_name"], tools_cfg["flat_3mm"])

        mat_key = p["material_name"].split()[0].lower()
        mat = mats_cfg.get(mat_key, mats_cfg["acetate"])
        spindle_rpm = mat["spindle_rpm"]
        feed_rate = mat["feed_rate_mmpm"]
        plunge_rate = mat["plunge_rate_mmpm"]

        self.progress.emit(
            "[gcode] No matched SCULPT zones — emitting profile cut only "
            "(draw 5 section cuts per side on the SCULPT layer in GuildDraw "
            "for the five-op castle program)."
        )
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
        self.progress.emit(
            f"[gcode] Wrote {front_file.name}  ({front_file.stat().st_size:,} bytes)"
        )

        self.finished.emit(f"Generated:\n  {front_file}", None)


# ------------------------------------------------------------------ op summary dialog

class OpSummaryDialog(QDialog):
    """The in-app setup sheet (BUILDPLAN M4.6): one row per CAM operation."""

    def __init__(self, rows: list[dict], summary: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Posterior program — operation summary")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)

        head = QLabel(summary.replace("\n", "<br>"))
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        lay.addWidget(head)

        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(
            ["Operation", "Strategy", "Z floor", "Cut length", "Est. time*"]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        for r, row in enumerate(rows):
            cells = [
                row["name"],
                row["strategy"],
                f"{row['floor_z_mm']:.2f} mm",
                f"{row['cut_length_mm'] / 1000.0:.2f} m",
                f"{row['est_minutes']:.1f} min" if "est_minutes" in row else "—",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.setFixedHeight(
            table.horizontalHeader().height()
            + sum(table.rowHeight(r) for r in range(len(rows))) + 8
        )
        lay.addWidget(table)

        foot = QLabel("* cutting moves at the material feed rate; rapids excluded.")
        foot.setObjectName("hintLabel")
        lay.addWidget(foot)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


# ------------------------------------------------------------------ preferences dialog

class PrefsDialog(QDialog):
    """Application preferences (M4.5 Part A) — patterned on GuildDraw's
    SettingsDialog: tabbed with OK/Cancel.  General tab only for now; the
    structure leaves room for more tabs as GuildCAM grows."""

    def __init__(self, prefs: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tabs = QTabWidget()
        root_layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 8, 16, 16)
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root_layout.addLayout(btn_row)

        # ── Tab 0 — General ───────────────────────────────────────────────
        gen_scroll = QScrollArea()
        gen_scroll.setWidgetResizable(True)
        gen_scroll.setFrameShape(gen_scroll.Shape.NoFrame)
        gen_inner = QWidget()
        gen_lay = QVBoxLayout(gen_inner)
        gen_lay.setSpacing(12)
        gen_lay.setContentsMargins(16, 16, 16, 8)
        gen_scroll.setWidget(gen_inner)
        tabs.addTab(gen_scroll, "General")

        # Appearance
        app_box = QGroupBox("Appearance")
        app_form = QFormLayout(app_box)
        self._dark_check = QCheckBox("Enable dark mode")
        self._dark_check.setChecked(prefs["dark_mode"])
        app_form.addRow(self._dark_check)
        gen_lay.addWidget(app_box)

        # Preview / export mesh resolution
        def _res_spin(value: float) -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(0.05, 1.0)
            s.setSingleStep(0.05)
            s.setDecimals(2)
            s.setSuffix(" mm")
            s.setValue(value)
            return s

        prev_box = QGroupBox("Preview")
        prev_form = QFormLayout(prev_box)
        self._preview_res = _res_spin(prefs["preview_resolution_mm"])
        self._preview_res.setToolTip(
            "Grid resolution of the live 3D preview (coarser = faster rebuilds)."
        )
        self._export_res = _res_spin(prefs["export_resolution_mm"])
        self._export_res.setToolTip(
            "Grid resolution used when exporting STL (finer = smoother file)."
        )
        prev_form.addRow("Preview resolution:", self._preview_res)
        prev_form.addRow("Export resolution:", self._export_res)
        gen_lay.addWidget(prev_box)

        # Paths
        path_box = QGroupBox("Paths")
        path_form = QFormLayout(path_box)
        path_row = QHBoxLayout()
        self._out_dir = QLineEdit(prefs["last_output_dir"])
        self._out_dir.setPlaceholderText("(ask every time)")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_out_dir)
        path_row.addWidget(self._out_dir)
        path_row.addWidget(browse_btn)
        path_form.addRow("Output folder:", path_row)
        gen_lay.addWidget(path_box)

        gen_lay.addStretch()

    def _browse_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Default output folder", self._out_dir.text()
        )
        if d:
            self._out_dir.setText(d)

    def to_prefs(self) -> dict:
        return {
            "dark_mode": self._dark_check.isChecked(),
            "preview_resolution_mm": round(self._preview_res.value(), 2),
            "export_resolution_mm": round(self._export_res.value(), 2),
            "last_output_dir": self._out_dir.text(),
        }


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
        self.filename_label.setObjectName("smallLabel")
        self.layers_label = QLabel("Layers: —")
        self.layers_label.setObjectName("mutedSmallLabel")
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
        self.build_status.setObjectName("hintLabel")
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

        note = QLabel(
            "SCULPT castle: posterior_cut.nc\n(five ops, onion skin)\n"
            "No SCULPT: front_profile.nc"
        )
        note.setObjectName("hintLabel")
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
        self.log.setObjectName("logView")   # amber-on-dark in both themes
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

        # Persistent preferences (~/.guildcam/prefs.json — GuildDraw pattern)
        self._prefs = prefs_mod.load()
        self._dark_mode = bool(self._prefs["dark_mode"])
        self._recent_files: list[str] = [
            p for p in self._prefs.get("recent_files", []) if isinstance(p, str)
        ]

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        # Apply the persisted theme to every surface (QSS is set app-wide
        # in main(); the painter/VTK surfaces need the explicit call).
        if self._dark_mode:
            self._act_dark.setChecked(True)
        self._apply_dark_mode(self._dark_mode)

        self._import_thread: Optional[QThread] = None
        self._import_worker: Optional[ImportWorker] = None
        self._mesh_thread: Optional[QThread] = None
        self._mesh_worker: Optional[MeshWorker] = None
        self._gcode_thread: Optional[QThread] = None
        self._gcode_worker: Optional[GCodeWorker] = None
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[ExportWorker] = None

        # Stored geometry from the last successful import
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None
        self._partition = None
        self._hinge_polys = []

        # Castle preview state: current teaching stage + per-stage mesh cache
        # (cache invalidated whenever a castle parameter changes)
        self._stage = "pockets"
        self._stage_cache: dict[str, object] = {}

        # Debounce for live parametric rebuilds (every spinbox tick would
        # otherwise queue a ~2 s build)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(350)
        self._rebuild_timer.timeout.connect(self._start_mesh_build)

    # ------------------------------------------------------------------ theme

    def _apply_dark_mode(self, dark: bool) -> None:
        """Restyle every surface live (mirrors GuildDraw's _toggle_dark_mode)."""
        self._dark_mode = dark
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(dark))
        self.canvas.set_dark_mode(dark)
        self.preview3d.set_dark_mode(dark)
        self.params.set_dark_mode(dark)

    def _on_toggle_dark_mode(self, dark: bool) -> None:
        self._apply_dark_mode(dark)
        self._prefs["dark_mode"] = dark
        prefs_mod.save(self._prefs)

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

        # Toolbar strip (styled by the theme via #toolbarStrip)
        toolbar_strip = QWidget()
        toolbar_strip.setObjectName("toolbarStrip")
        toolbar_strip.setFixedHeight(36)
        ts_lay = QHBoxLayout(toolbar_strip)
        ts_lay.setContentsMargins(8, 4, 8, 4)

        lbl = QLabel("GuildCAM")
        lbl.setObjectName("appTitle")
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
        self.zoom_label.setObjectName("mutedSmallLabel")
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
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
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

        # Settings menu mirrors GuildDraw: Dark Mode toggle + Preferences…
        settings_menu = mb.addMenu("&Settings")
        self._act_dark = QAction("Dark Mode", self, checkable=True, checked=False)
        self._act_dark.triggered.connect(self._on_toggle_dark_mode)
        settings_menu.addAction(self._act_dark)
        settings_menu.addSeparator()
        settings_menu.addAction("Preferences…", self._open_preferences)

        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About GuildCAM", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ------------------------------------------------------------------ recent files

    _MAX_RECENT = 8

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self._recent_files = ([path]
                              + [p for p in self._recent_files if p != path])
        del self._recent_files[self._MAX_RECENT:]
        self._prefs["recent_files"] = list(self._recent_files)
        prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        m = self._recent_menu
        m.clear()
        if not self._recent_files:
            empty = m.addAction("(empty)")
            empty.setEnabled(False)
            return
        for p in self._recent_files:
            act = m.addAction(os.path.basename(p),
                              lambda checked=False, p=p: self._open_recent(p))
            act.setToolTip(p)
        m.addSeparator()
        m.addAction("Clear Recent", self._clear_recent)

    def _clear_recent(self) -> None:
        self._recent_files = []
        self._prefs["recent_files"] = []
        prefs_mod.save(self._prefs)
        self._rebuild_recent_menu()

    def _open_recent(self, path: str) -> None:
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File not found",
                                f"{path}\n\nno longer exists.")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._prefs["recent_files"] = list(self._recent_files)
            prefs_mod.save(self._prefs)
            self._rebuild_recent_menu()
            return
        self._load_dxf(Path(path))

    # ------------------------------------------------------------------ preferences

    def _open_preferences(self) -> None:
        current = {**self._prefs, "dark_mode": self._dark_mode}
        dlg = PrefsDialog(current, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p = dlg.to_prefs()
        old_preview_res = self._prefs["preview_resolution_mm"]
        self._prefs.update(p)
        prefs_mod.save(self._prefs)

        if p["dark_mode"] != self._dark_mode:
            self._act_dark.setChecked(p["dark_mode"])
            self._apply_dark_mode(p["dark_mode"])
        if p["preview_resolution_mm"] != old_preview_res:
            # Cached stage meshes were built at the old resolution.
            self._stage_cache.clear()
            if self.stack.currentIndex() == 1 and self._castle_ready():
                self._rebuild_timer.start()

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

        # Live parametric rebuild (debounced; only while the 3D view is up)
        self.params.castle_changed.connect(self._on_castle_params_changed)
        self.params.stock_changed.connect(self._on_stock_changed)
        self.params.zone_hovered.connect(self._on_zone_hover)
        self.preview3d.stage_changed.connect(self._on_stage_changed)

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
        self._partition = None
        self._hinge_polys = []

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
            self._lens_od = sorted_lens[1]   # posterior coords: OD on +x
            self._lens_os = sorted_lens[0]

        self._hinge_polys = [
            p for p in (points_to_polygon(c) for c in layers.get("HINGE", []) if len(c) >= 3)
            if p.is_valid and p.area > 0.5
        ]

        # Castle zone partition from the SCULPT section cuts
        sculpt_curves = layers.get("SCULPT", [])
        if self._outline_poly is not None and len(valid_lens) >= 2 and sculpt_curves:
            from guildcam.core.geometry.regions import partition_zones
            self._partition = partition_zones(
                self._outline_poly, valid_lens[:2] if len(valid_lens) == 2 else valid_lens,
                sculpt_curves,
            )
            kind = ("standard castle layout" if self._partition.matched
                    else "generic zones — castle relief needs the 5-cuts-per-side layout")
            self.action_panel.append_log(
                f"[castle] {len(self._partition.zones)} zones from "
                f"{len(sculpt_curves)} SCULPT cuts ({kind})"
            )

        # Castle UI state: zone inspector, stage stepper, stock ghost, cache
        self.params.set_zones(self._partition)
        matched = self._partition is not None and self._partition.matched
        self.preview3d.set_stage_enabled(matched)
        self._stage = "pockets"
        self.preview3d.set_stage(self._stage)
        self._stage_cache.clear()
        self._update_stock_canvas()

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
        if self._import_worker is not None:
            self._add_recent(str(self._import_worker.path))

    def _on_import_error(self, tb: str) -> None:
        self.action_panel.append_log("[ERROR] Import failed:\n" + tb)
        self.status_lbl.setText("Import failed — see log")
        QMessageBox.critical(self, "Import error", "DXF import failed.\n\nSee log for details.")

    # ------------------------------------------------------------------ 3D build

    def _castle_ready(self) -> bool:
        return self._partition is not None and self._partition.matched

    def _on_build_3d(self) -> None:
        if not self._castle_ready():
            self.action_panel.append_log(
                "[3D] Castle relief needs the standard SCULPT zone layout "
                "(5 section cuts per side). Draw them in GuildDraw and re-export."
            )
            return
        self._start_mesh_build()

    def _on_castle_params_changed(self) -> None:
        # Parameters changed: every cached stage is stale.
        self._stage_cache.clear()
        if self.stack.currentIndex() == 1 and self._castle_ready():
            self._rebuild_timer.start()

    def _on_stage_changed(self, stage: str) -> None:
        self._stage = stage
        cached = self._stage_cache.get(stage)
        if cached is not None:
            self._show_stage_mesh(cached)
        elif self._castle_ready():
            self._start_mesh_build()

    def _on_stock_changed(self) -> None:
        self._update_stock_canvas()
        # Re-draw the stock ghost around the currently shown stage, if any.
        cached = self._stage_cache.get(self._stage)
        if cached is not None and self.stack.currentIndex() == 1:
            self._show_stage_mesh(cached)

    def _update_stock_canvas(self) -> None:
        if self._outline_poly is None:
            return
        s = self.params.castle_params().stock
        self.canvas.set_stock([
            (-s.blank_length_mm / 2.0, -s.blank_width_mm / 2.0,
             s.blank_length_mm / 2.0, s.blank_width_mm / 2.0),
            (s.pad_block_dx_mm - s.pad_block_length_mm / 2.0,
             s.pad_block_dy_mm - s.pad_block_width_mm / 2.0,
             s.pad_block_dx_mm + s.pad_block_length_mm / 2.0,
             s.pad_block_dy_mm + s.pad_block_width_mm / 2.0),
        ])

    def _on_zone_hover(self, name: str) -> None:
        if not name or self._partition is None:
            self.canvas.set_zone_highlight(None)
            return
        try:
            poly = self._partition.zone(name).polygon
        except KeyError:
            self.canvas.set_zone_highlight(None)
            return
        rings = [list(poly.exterior.coords)]
        rings += [list(r.coords) for r in poly.interiors]
        self.canvas.set_zone_highlight(rings)

    def _start_mesh_build(self) -> None:
        if not self._castle_ready():
            return
        self.action_panel.build_status.setText("Building…")
        self.action_panel.build3d_btn.setEnabled(False)
        self.action_panel.append_log(f"[3D] Building castle ({self._stage})…")
        self._switch_view(1)

        self._mesh_worker = MeshWorker(
            self._partition, self.params.castle_params(),
            hinge_polys=self._hinge_polys, stage=self._stage,
            resolution=self._prefs["preview_resolution_mm"],
        )
        self._mesh_thread = QThread()
        self._mesh_worker.moveToThread(self._mesh_thread)
        self._mesh_thread.started.connect(self._mesh_worker.run)
        self._mesh_worker.finished.connect(self._on_mesh_finished)
        self._mesh_worker.error.connect(self._on_mesh_error)
        self._mesh_worker.finished.connect(self._mesh_thread.quit)
        self._mesh_worker.error.connect(self._mesh_thread.quit)
        self._mesh_thread.start()

    def _show_stage_mesh(self, mesh) -> None:
        self.preview3d.show_mesh(mesh, stock=self.params.castle_params().stock)
        n_v = len(mesh.vertices)
        n_t = len(mesh.faces)
        self.action_panel.build_status.setText(f"{n_v:,} verts · {n_t:,} tris")

    def _on_mesh_finished(self, mesh, stage: str) -> None:
        self._stage_cache[stage] = mesh
        if stage == self._stage:
            self._show_stage_mesh(mesh)
        self.action_panel.append_log(
            f"[3D] Done ({stage}) — {len(mesh.vertices):,} verts, "
            f"{len(mesh.faces):,} tris"
        )
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
            self, "Choose output folder for .nc files",
            self._prefs["last_output_dir"],
        )
        if not out_dir:
            return
        self._prefs["last_output_dir"] = out_dir
        prefs_mod.save(self._prefs)

        params = self._collect_gcode_params()

        self.action_panel.generate_btn.setEnabled(False)
        self.action_panel.append_log(f"[gcode] Output folder: {out_dir}")

        self._gcode_worker = GCodeWorker(
            outline=self._outline_poly,
            castle=self.params.castle_params(),
            params=params,
            out_dir=Path(out_dir),
            partition=self._partition,
            hinge_polys=self._hinge_polys,
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
            "profile_tool_name": p.tool_profile.currentText(),
            "material_name":     p.material.currentText(),
            "stock_thickness":   p.blank_thickness.value(),
            "stepdown_profile":  p.stepdown_profile.value(),
            "tab_count":         p.tab_count.value(),
            "tab_width":         p.tab_width.value(),
            "tab_height":        p.tab_height.value(),
        }

    def _on_gcode_finished(self, summary: str, rows) -> None:
        self.action_panel.append_log("[gcode] Done.")
        self.action_panel.generate_btn.setEnabled(True)
        self.status_lbl.setText("G-code ready")
        if rows:
            OpSummaryDialog(rows, summary, self).exec()
        else:
            QMessageBox.information(self, "G-code generated", summary)

    def _on_gcode_error(self, tb: str) -> None:
        self.action_panel.append_log("[gcode ERROR]\n" + tb)
        self.action_panel.generate_btn.setEnabled(True)
        self.status_lbl.setText("G-code generation failed — see log")

    def _on_export_stl(self) -> None:
        if not self._castle_ready():
            QMessageBox.information(
                self, "Export STL",
                "STL export needs the standard SCULPT zone layout "
                "(5 section cuts per side). Draw them in GuildDraw and "
                "re-export the DXF.",
            )
            return
        start = str(
            Path(self._prefs["last_output_dir"] or ".") / "frame_front.stl"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export STL", start, "STL files (*.stl)"
        )
        if not path_str:
            return
        self._prefs["last_output_dir"] = str(Path(path_str).parent)
        prefs_mod.save(self._prefs)

        # Always a fresh build at export resolution — never the preview cache.
        self.action_panel.export_stl_btn.setEnabled(False)
        self.status_lbl.setText("Exporting STL…")
        self._export_worker = ExportWorker(
            self._partition, self.params.castle_params(), self._hinge_polys,
            resolution=self._prefs["export_resolution_mm"], path=Path(path_str),
        )
        self._export_thread = QThread()
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self.action_panel.append_log)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_worker.error.connect(self._export_thread.quit)
        self._export_thread.start()

    def _on_export_finished(self, path: str) -> None:
        self.action_panel.append_log(f"[export] Wrote {path}")
        self.action_panel.export_stl_btn.setEnabled(True)
        self.status_lbl.setText("STL exported")

    def _on_export_error(self, tb: str) -> None:
        self.action_panel.append_log("[export ERROR]\n" + tb)
        self.action_panel.export_stl_btn.setEnabled(True)
        self.status_lbl.setText("STL export failed — see log")

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About GuildCAM",
            "<b>GuildCAM</b> v0.4.5 — pre-release<br><br>"
            "Free, open-source CAM tool for spectacle frame cutting on GRBL CNCs.<br>"
            "Companion to the Guild CNC and gSender fork.<br><br>"
            "GPLv3 — see LICENSE for details.",
        )


# ------------------------------------------------------------------ entry point

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GuildCAM")
    app.setOrganizationName("Guild")
    app.setStyleSheet(theme.stylesheet(prefs_mod.load()["dark_mode"]))

    win = MainWindow()
    win.show()

    # Auto-load demo frame in dev mode (the Demo Project DXF exercises the
    # full castle pipeline; the illustrations have no SCULPT layer)
    project_root = Path(__file__).parents[3]
    for dev_name in (
        "Demo Project/GuildDraw DXF Export.dxf",
        "frame_illustration.dxf",
        "hinge_th-23_front.dxf",
    ):
        dev_dxf = project_root / dev_name
        if dev_dxf.exists():
            win._load_dxf(dev_dxf)
            break

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
