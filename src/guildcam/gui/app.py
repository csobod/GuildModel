"""GuildCAM main window — thin PySide6 shell over guildcam.core.

Window architecture (BUILDPLAN M4.6 Part A): one right tabbed dock
(ParamsPanel: Frame / Castle / Stock / CAM), a top icon toolbar, and a
bottom log dock — GuildDraw's pattern. Long operations (Build 3D / Export
STL / Generate G-code) drive a determinate progress dialog with stage
labels and stage-boundary cancellation (Part B).
"""
from __future__ import annotations
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QStatusBar, QGroupBox, QTextEdit,
    QSizePolicy, QMessageBox, QStackedWidget,
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QCheckBox, QFormLayout,
    QDoubleSpinBox, QLineEdit, QScrollArea, QDockWidget,
    QToolBar, QProgressDialog,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QByteArray, QSize
from PySide6.QtGui import QAction, QKeySequence

from guildcam.core.layers import ALL_LAYERS as SUPPORTED_LAYERS
from guildcam.gui import prefs as prefs_mod
from guildcam.gui import icons as icons_mod
from guildcam.gui.style import theme
from guildcam.gui.widgets.dxf_canvas import DxfCanvas
from guildcam.gui.widgets.params_panel import ParamsPanel
from guildcam.gui.widgets.preview_3d import Preview3D
from guildcam.gui.widgets.cut_sim_view import CutSimView
from guildcam.gui.widgets import readiness_dot
from guildcam.gui.widgets.readiness_dot import ReadinessDot


class _Cancelled(Exception):
    """Raised inside a worker's progress callback to abort at a stage boundary."""


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


# ------------------------------------------------------------------ worker progress mixin

class _ProgressWorker(QObject):
    """Shared stage-progress + stage-boundary cancellation (M4.6 Part B).

    Subclasses call ``self._progress(label, frac)`` (passed as the ``progress=``
    hook to core); it relays to the ``stage`` signal and raises :class:`_Cancelled`
    if :meth:`cancel` was called between stages.
    """

    stage = Signal(str, int)   # human label, percent 0..100
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, label: str, frac: float) -> None:
        if self._cancel:
            raise _Cancelled()
        self.stage.emit(label, int(round(frac * 100)))


# ------------------------------------------------------------------ 3D mesh build worker

class MeshWorker(_ProgressWorker):
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
        self.stage_name = stage
        self.resolution = resolution

    def run(self) -> None:
        try:
            from guildcam.core.relief.castle import (
                build_castle_mesh, build_castle_stage,
            )
            relief = build_castle_stage(
                self.partition, self.castle, self.hinge_polys,
                stage=self.stage_name, resolution=self.resolution,
                progress=self._progress,
            )
            mesh = build_castle_mesh(relief, progress=self._progress)
            self.finished.emit(mesh, self.stage_name)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ STL export worker

class ExportWorker(_ProgressWorker):
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
                resolution=self.resolution, progress=self._progress,
            )
            mesh = build_castle_mesh(relief, progress=self._progress)
            self.progress.emit(
                f"[export] {len(mesh.vertices):,} verts, "
                f"{len(mesh.faces):,} tris, watertight={mesh.is_watertight}"
            )
            mesh.export(str(self.path))
            self.finished.emit(str(self.path))
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ G-code generation worker

class GCodeWorker(_ProgressWorker):
    """Builds posterior_cut.nc (castle) or front_profile.nc (fallback)
    off the GUI thread."""

    finished = Signal(str, object)   # summary message, op-summary rows | None
    progress = Signal(str)           # log line
    error = Signal(str)              # traceback

    def __init__(
        self, outline, castle, params: dict,
        partition=None, hinge_polys=(), cam_params=None,
    ) -> None:
        super().__init__()
        self.outline = outline
        self.castle = castle
        self.params = params
        self.cam_params = cam_params
        self.partition = partition
        self.hinge_polys = list(hinge_polys)
        # .gcam artifacts (filled by the castle path on success)
        self.programs: dict = {}
        self.machine_dump = None
        self.setup_dict = None

    def run(self) -> None:
        try:
            self._generate()
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _generate_castle(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Five-op posterior program: hinge pockets -> rough -> fine ->
        eyewires -> perimeter, single .nc, onion skin instead of tabs."""
        import yaml
        from guildcam.core.cam.castle_ops import (
            CastleCamParams, fixture_clearance_violations, generate_castle_program,
            op_summaries, write_castle_program,
        )
        from guildcam.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.post.machine import apply_machine_limits, lint_program, load_machine_profile
        from guildcam.core.relief.castle import build_castle_relief

        p = self.params
        castle = self.castle
        cam = self.cam_params or CastleCamParams()
        tool = tools_cfg.get(cam.tool_name, tools_cfg.get("flat_3175", next(iter(tools_cfg.values()))))
        mat_key = p["material_name"].split()[0].lower()
        mat = mats_cfg.get(mat_key, mats_cfg["acetate"])
        machine = load_machine_profile(cam.machine_name, config_dir)
        self.progress.emit(f"[gcode] Machine: {machine.display_name} · Tool: {cam.tool_name}")

        # Clamp requested feeds / spindle / depth-of-cut to the machine (the
        # material caps DOC too); choose arc vs. linearized output.
        clamp = apply_machine_limits(
            machine,
            feed_rate_mmpm=cam.feed_rate_mmpm or mat["feed_rate_mmpm"],
            plunge_rate_mmpm=cam.plunge_rate_mmpm or mat["plunge_rate_mmpm"],
            spindle_rpm=cam.spindle_rpm or mat["spindle_rpm"],
            contour_stepdown_mm=cam.contour_stepdown_mm,
            requested_arc_tol_mm=cam.arc_tolerance_mm,
            material_max_doc_mm=mat.get("max_doc_mm"),
        )
        for w in clamp.warnings:
            self.progress.emit(f"[gcode] machine: {w}")
        cam = cam.model_copy(update={"contour_stepdown_mm": clamp.contour_stepdown_mm})

        self.progress.emit("[gcode] Castle: building relief…")
        relief = build_castle_relief(
            self.partition, castle, self.hinge_polys, resolution=0.15,
            progress=self._progress,
        )
        self.progress.emit("[gcode] Castle: generating five operations…")
        ops = generate_castle_program(
            relief, castle, self.hinge_polys, tool, params=cam, progress=self._progress
        )
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
            spindle_rpm=clamp.spindle_rpm,
            feed_rate_mmpm=clamp.feed_rate_mmpm,
            plunge_rate_mmpm=clamp.plunge_rate_mmpm,
            safe_z_mm=castle.stock.total_pad_height_mm + cam.safe_z_clearance_mm,
        )
        self._progress("Writing program", 0.95)
        write_castle_program(
            ops, post, arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
        )
        # The program is kept in the project (.gcam) by default — no loose .nc
        # is written here; File ▸ Export G-code writes a standalone file on
        # demand (mirrors Export STL).
        text = post.to_string()
        self.progress.emit(f"[gcode] posterior_cut.nc generated ({len(text):,} bytes)")

        # Lint against the machine + estimate cut time (machine dynamics).
        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        report = estimate_program(text, MachineDynamics.from_profile(machine))
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))

        summary = ("Posterior program generated and stored in the project.\n"
                   "Save the project (Ctrl+S) to keep it in the .gcam, or "
                   "File ▸ Export G-code for a standalone .nc.")
        summary += (f"\n\nMachine: {machine.display_name}"
                    f"\nEstimated cycle: {report.cycle_seconds / 60:.1f} min "
                    f"(cut {report.cutting_only_seconds / 60:.1f} min)")
        if violations:
            summary += f"\n\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        if machine_warnings:
            summary += f"\n⚠ {len(machine_warnings)} machine compliance warning(s) — see log."
        rows = op_summaries(ops, feed_rate_mmpm=clamp.feed_rate_mmpm)

        # Stash artifacts for the .gcam container (M5.1); read on the GUI thread.
        self.programs = {"posterior_cut.nc": text}
        self.machine_dump = machine.model_dump()
        flip = (fixture.get("blank_zones", {}).get("front", {}).get("flip_axis_x_mm"))
        self.setup_dict = {
            "tool": tool.get("display_name", cam.tool_name),
            "tool_name": cam.tool_name,
            "material": p["material_name"],
            "machine": machine.display_name,
            "spindle_rpm": clamp.spindle_rpm,
            "feed_rate_mmpm": clamp.feed_rate_mmpm,
            "plunge_rate_mmpm": clamp.plunge_rate_mmpm,
            "contour_stepdown_mm": cam.contour_stepdown_mm,
            "onion_skin_mm": castle.onion_skin_mm,
            "hand_finishing_allowance_mm": castle.hand_finishing_allowance_mm,
            "flip_axis_x_mm": flip,
            "est_cut_min": round(report.cutting_only_seconds / 60, 2),
            "est_cycle_min": round(report.cycle_seconds / 60, 2),
            "ops": rows,
        }
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

        # Kept in the project by default; Export G-code writes a loose .nc.
        text = post_front.to_string()
        self.progress.emit(f"[gcode] front_profile.nc generated ({len(text):,} bytes)")
        self.programs = {"front_profile.nc": text}
        self.finished.emit(
            "Front profile program generated and stored in the project.\n"
            "Save the project (Ctrl+S) or File ▸ Export G-code for a standalone .nc.",
            None,
        )


# ------------------------------------------------------------------ cut simulation worker

class SimWorker(_ProgressWorker):
    """Simulates the machined result from the *posted* program (BUILDPLAN M5).

    Builds the relief and the five-op program, posts it (arcs + ramped lead-ins,
    exactly what runs), sweeps the tool along every cutting move to get the
    achieved floor, and verifies it against the target relief surface — so the
    simulation catches both strategy and post-processing defects before cutting.
    """

    finished = Signal(object, object)   # core.sim.CutReport, summary lines
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, partition, castle, cam_params, hinge_polys=(),
                 material_name="acetate", resolution: float = 0.3) -> None:
        super().__init__()
        self.partition = partition
        self.castle = castle
        self.cam_params = cam_params
        self.hinge_polys = list(hinge_polys)
        self.material_name = material_name
        self.resolution = resolution

    def run(self) -> None:
        try:
            import numpy as np
            import yaml
            from guildcam.core.relief.castle import build_castle_relief
            from guildcam.core.cam.castle_ops import (
                CastleCamParams, generate_castle_program, write_castle_program,
            )
            from guildcam.core.post.grbl import GRBLPost
            from guildcam.core.sim import (
                ToolProfile, achieved_floor, cutting_paths_from_program, verify,
            )

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = yaml.safe_load((config_dir / "tools.yaml").read_text(encoding="utf-8"))
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            tool = tools_cfg.get(cam.tool_name, tools_cfg.get("flat_3175"))
            mat = mats_cfg.get(self.material_name.split()[0].lower(), mats_cfg["acetate"])

            self.progress.emit(f"[sim] Building relief at {self.resolution} mm…")
            relief = build_castle_relief(
                self.partition, self.castle, self.hinge_polys,
                resolution=self.resolution, progress=self._progress,
            )
            self._progress("Generating program", 0.55)
            ops = generate_castle_program(
                relief, self.castle, self.hinge_polys, tool, params=cam)
            post = GRBLPost(
                job_name="sim", material=self.material_name,
                tool_diameter_mm=tool["diameter_mm"],
                spindle_rpm=mat["spindle_rpm"], feed_rate_mmpm=mat["feed_rate_mmpm"],
                plunge_rate_mmpm=mat["plunge_rate_mmpm"],
                safe_z_mm=self.castle.stock.total_pad_height_mm + cam.safe_z_clearance_mm,
            )
            write_castle_program(
                ops, post, arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg)

            self.progress.emit("[sim] Sweeping tool along the toolpaths…")
            f = relief.field
            paths = cutting_paths_from_program(post.to_string())
            init_z = self.castle.stock.total_pad_height_mm + 1.0
            floor = achieved_floor(
                paths, ToolProfile.from_tool(tool), f.origin, f.z.shape,
                f.resolution, init_z, progress=lambda p: self._progress("Simulating", 0.6 + 0.35 * p))
            report = verify(
                floor, np.where(relief.inside, f.z, np.nan), relief.inside,
                f.origin, f.resolution, partition=self.partition)
            self.finished.emit(report, report.summary_lines())
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ op summary dialog

class OpSummaryDialog(QDialog):
    """The in-app setup sheet (BUILDPLAN M4): one row per CAM operation."""

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
        ok_btn.clicked.connect(self._accept)
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
        self._log_check = QCheckBox("Show log panel on startup")
        self._log_check.setChecked(prefs["show_log_on_start"])
        self._log_check.setToolTip(
            "The toolbar button still toggles the log for the current session."
        )
        app_form.addRow(self._log_check)
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

        # ── Tab 1 — Materials ─────────────────────────────────────────────
        self._build_materials_tab(tabs)

    # ── Materials tab (feeds/speeds/stepover/stepdown defaults) ───────────

    _MAT_FIELDS = [
        ("spindle_rpm", "Spindle", 0, 60000, 500, 0, " RPM"),
        ("feed_rate_mmpm", "Feed", 0, 10000, 50, 0, " mm/min"),
        ("plunge_rate_mmpm", "Plunge", 0, 5000, 25, 0, " mm/min"),
        ("relief_stepover_mm", "Relief stepover", 0.05, 3.0, 0.05, 2, " mm"),
        ("contour_stepdown_mm", "Contour stepdown", 0.1, 6.0, 0.1, 2, " mm"),
        ("rough_axial_stock_mm", "Rough axial stock", 0.0, 5.0, 0.1, 2, " mm"),
    ]

    def _build_materials_tab(self, tabs) -> None:
        from guildcam.gui import material_store
        self._mat_widgets: dict = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 8)
        scroll.setWidget(inner)
        tabs.addTab(scroll, "Materials")

        eff = material_store.effective()
        for name, vals in eff.items():
            box = QGroupBox(vals.get("display_name", name))
            form = QFormLayout(box)
            self._mat_widgets[name] = {}
            for key, label, lo, hi, step, dec, suffix in self._MAT_FIELDS:
                if key not in vals:
                    continue
                sb = QDoubleSpinBox()
                sb.setRange(lo, hi); sb.setSingleStep(step); sb.setDecimals(dec)
                sb.setSuffix(suffix); sb.setValue(float(vals[key]))
                form.addRow(label + ":", sb)
                self._mat_widgets[name][key] = sb
            reset = QPushButton("Reset to shipped")
            reset.clicked.connect(lambda _=False, n=name: self._reset_material(n))
            form.addRow(reset)
            lay.addWidget(box)
        lay.addStretch()

    def _reset_material(self, name: str) -> None:
        from guildcam.gui import material_store
        material_store.reset_material(name)
        shipped = material_store.shipped_material(name)
        for key, sb in self._mat_widgets.get(name, {}).items():
            if key in shipped:
                sb.setValue(float(shipped[key]))

    def _save_materials(self) -> None:
        """Persist edited material values: store overrides that differ from
        shipped, drop overrides that now match shipped."""
        from guildcam.gui import material_store
        for name, widgets in getattr(self, "_mat_widgets", {}).items():
            shipped = material_store.shipped_material(name)
            values = {k: sb.value() for k, sb in widgets.items()}
            differs = any(abs(values[k] - float(shipped.get(k, values[k]))) > 1e-6
                          for k in values)
            if differs:
                material_store.save_override(name, values)
            else:
                material_store.reset_material(name)

    def _accept(self) -> None:
        self._save_materials()
        self.accept()

    def _browse_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Default output folder", self._out_dir.text()
        )
        if d:
            self._out_dir.setText(d)

    def to_prefs(self) -> dict:
        return {
            "dark_mode": self._dark_check.isChecked(),
            "show_log_on_start": self._log_check.isChecked(),
            "preview_resolution_mm": round(self._preview_res.value(), 2),
            "export_resolution_mm": round(self._export_res.value(), 2),
            "last_output_dir": self._out_dir.text(),
        }


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

        # Readiness traffic-light inputs (M5.2). The dot is a pure function of
        # these three flags (see _refresh_readiness): a DXF is loaded, a 3D
        # model has been built for the current design, and the current program
        # has been stored into the open .gcam. A design/CAM change that
        # invalidates the stored program clears _program_stored so green never
        # outlives the toolpaths it stood for. Initialised before _connect_signals,
        # which can emit cam_changed during startup restore.
        self._dxf_loaded = False
        self._mesh_built = False
        self._program_stored = False

        self._build_ui()
        self._build_toolbar()
        self._build_menu()
        self._connect_signals()

        # Apply the persisted theme to every surface (QSS is set app-wide
        # in main(); the painter/VTK surfaces + toolbar icons need the call).
        if self._dark_mode:
            self._act_dark.setChecked(True)
        self._apply_dark_mode(self._dark_mode)

        self._restore_window_state()
        # Dock visibility has explicit startup defaults (M4.6), independent of
        # the persisted state (which still supplies dock sizes + window
        # geometry): the params sidebar is always shown; the log is hidden
        # unless the user opts in via Preferences. Either can be toggled for
        # the session with its toolbar button.
        self._right_dock.setVisible(True)
        self._act_sidebar.setChecked(True)
        self._log_dock.setVisible(bool(self._prefs["show_log_on_start"]))
        self._act_log.setChecked(self._log_dock.isVisible())

        self._import_thread: Optional[QThread] = None
        self._import_worker: Optional[ImportWorker] = None
        self._mesh_thread: Optional[QThread] = None
        self._mesh_worker: Optional[MeshWorker] = None
        self._gcode_thread: Optional[QThread] = None
        self._gcode_worker: Optional[GCodeWorker] = None
        self._sim_thread: Optional[QThread] = None
        self._sim_worker: Optional[SimWorker] = None
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[ExportWorker] = None
        self._progress_dialog: Optional[QProgressDialog] = None

        # Stored geometry from the last successful import
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None
        self._partition = None
        self._hinge_polys = []

        # .gcam project state (M5.1): the source DXF bytes, the current project
        # file, and the artifacts that go into the container (the last generated
        # program, its setup sheet + machine snapshot, and the last cut report).
        self._source_dxf_bytes: Optional[bytes] = None
        self._source_name = ""
        self._project_path: Optional[Path] = None
        self._last_programs: dict = {}
        self._last_setup: Optional[dict] = None
        self._last_machine: Optional[dict] = None
        self._last_report: Optional[dict] = None

        # Castle preview state: current teaching stage + per-stage mesh cache
        # (cache invalidated whenever a castle parameter changes)
        self._stage = "pockets"
        self._stage_cache: dict[str, object] = {}

        # Debounce for live parametric rebuilds (every spinbox tick would
        # otherwise queue a ~2 s build)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(350)
        self._rebuild_timer.timeout.connect(
            lambda: self._start_mesh_build(show_progress=False)
        )

    # ------------------------------------------------------------------ theme

    def _apply_dark_mode(self, dark: bool) -> None:
        """Restyle every surface live (mirrors GuildDraw's _toggle_dark_mode)."""
        self._dark_mode = dark
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(dark))
        self.canvas.set_dark_mode(dark)
        self.preview3d.set_dark_mode(dark)
        self.cutsim.set_dark_mode(dark)
        self.params.set_dark_mode(dark)
        self.readiness.set_dark_mode(dark)
        icons_mod.apply_toolbar_icons(self._icon_actions, dark)

    def _on_toggle_dark_mode(self, dark: bool) -> None:
        self._apply_dark_mode(dark)
        self._prefs["dark_mode"] = dark
        prefs_mod.save(self._prefs)

    # -------------------------------------------------------------- readiness

    def _refresh_readiness(self) -> None:
        """Drive the status-bar dot from the three readiness flags (M5.2)."""
        self.readiness.set_state(readiness_dot.state_for(
            self._dxf_loaded, self._mesh_built, self._program_stored,
        ))

    def _invalidate_program(self) -> None:
        """A design/CAM change makes any stored program stale → drop to yellow."""
        if self._program_stored:
            self._program_stored = False
            self._refresh_readiness()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        # Center: just the stacked canvas/preview (the camera presets + stage
        # stepper live on Preview3D's own strip; the app-level strip is gone).
        self.stack = QStackedWidget()
        self.canvas = DxfCanvas()
        self.preview3d = Preview3D()
        self.cutsim = CutSimView()
        self.stack.addWidget(self.canvas)        # 0 — 2D outline
        self.stack.addWidget(self.preview3d)     # 1 — 3D model
        self.stack.addWidget(self.cutsim)        # 2 — cut simulation
        self.setCentralWidget(self.stack)

        # Right dock: the tabbed params panel (title bar hidden, GuildDraw look)
        self.params = ParamsPanel()
        self._right_dock = QDockWidget("Parameters", self)
        self._right_dock.setObjectName("paramsDock")
        self._right_dock.setWidget(self.params)
        self._right_dock.setTitleBarWidget(QWidget())   # hide the title bar
        self._right_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._right_dock)

        # Bottom dock: the log (amber-on-dark monospace in both themes)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("logView")
        self._log_dock = QDockWidget("Log", self)
        self._log_dock.setObjectName("logDock")
        self._log_dock.setWidget(self.log)
        self._log_dock.setMinimumHeight(120)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        # Status bar: transient message (left) + zoom read-out (permanent right)
        sb = QStatusBar()
        self.status_lbl = QLabel("Ready — open a DXF to begin")
        sb.addWidget(self.status_lbl)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("mutedSmallLabel")
        sb.addPermanentWidget(self.zoom_label)
        # Readiness traffic-light (M5.2): rightmost corner of the status bar.
        self.readiness = ReadinessDot()
        sb.addPermanentWidget(self.readiness)
        self.setStatusBar(sb)

    # ------------------------------------------------------------------ toolbar

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        # Left-anchored, icon-only with tooltips — GuildDraw's vertical icon
        # sidebar. Few enough buttons that they stack attractively; identity
        # lives in the tooltips.
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        self._toolbar = tb

        self._act_open = QAction("Open DXF", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.setToolTip("Open a GuildDraw DXF…  (Ctrl+O)")
        self._act_open.triggered.connect(self._on_open)

        self._act_open_project = QAction("Open Project…", self)
        self._act_open_project.setToolTip("Open a GuildCAM .gcam project")
        self._act_open_project.triggered.connect(self._on_open_project)
        self._act_save_project = QAction("Save Project…", self)
        self._act_save_project.setShortcut("Ctrl+S")
        self._act_save_project.setToolTip("Save the project as a .gcam container  (Ctrl+S)")
        self._act_save_project.triggered.connect(self._on_save_project)

        self._act_build = QAction("Build 3D Model", self)
        self._act_build.setShortcut("F5")
        self._act_build.setToolTip("Build the 3D castle model  (F5)")
        self._act_build.setEnabled(False)
        self._act_build.triggered.connect(self._on_build_3d)

        self._act_gcode = QAction("Generate G-code", self)
        self._act_gcode.setShortcut("Ctrl+G")
        self._act_gcode.setToolTip("Generate the posterior G-code program  (Ctrl+G)")
        self._act_gcode.setEnabled(False)
        self._act_gcode.triggered.connect(self._on_generate)

        self._act_export = QAction("Export STL", self)
        self._act_export.setShortcut("Ctrl+E")
        self._act_export.setToolTip("Export the watertight STL mesh…  (Ctrl+E)")
        self._act_export.setEnabled(False)
        self._act_export.triggered.connect(self._on_export_stl)

        self._act_export_nc = QAction("Export G-code", self)
        self._act_export_nc.setShortcut("Ctrl+Shift+G")
        self._act_export_nc.setToolTip(
            "Export the generated program to a standalone .nc file…  (Ctrl+Shift+G)")
        self._act_export_nc.setEnabled(False)
        self._act_export_nc.triggered.connect(self._on_export_nc)

        self._act_view2d = QAction("2D Outline", self, checkable=True)
        self._act_view2d.setChecked(True)
        self._act_view2d.setToolTip("2D outline view")
        self._act_view2d.triggered.connect(lambda: self._switch_view(0))
        self._act_view3d = QAction("3D Preview", self, checkable=True)
        self._act_view3d.setToolTip("3D preview view")
        self._act_view3d.triggered.connect(lambda: self._switch_view(1))

        self._act_simulate = QAction("Simulate Cut", self)
        self._act_simulate.setShortcut("Ctrl+Shift+S")
        self._act_simulate.setToolTip(
            "Simulate the machined result and verify completeness  (Ctrl+Shift+S)")
        self._act_simulate.setEnabled(False)
        self._act_simulate.triggered.connect(self._on_simulate)

        self._act_fit = QAction("Fit", self)
        self._act_fit.setShortcut("Ctrl+0")
        self._act_fit.setToolTip("Fit to view  (Ctrl+0)")
        self._act_fit.triggered.connect(self._on_fit)

        self._act_sidebar = QAction("Parameters", self, checkable=True)
        self._act_sidebar.setChecked(True)
        self._act_sidebar.setToolTip("Show/hide the parameters panel")
        self._act_sidebar.toggled.connect(self._right_dock.setVisible)
        self._right_dock.visibilityChanged.connect(self._act_sidebar.setChecked)

        self._act_log = QAction("Log", self, checkable=True)
        self._act_log.setChecked(True)
        self._act_log.setToolTip("Show/hide the log panel")
        self._act_log.toggled.connect(self._log_dock.setVisible)
        self._log_dock.visibilityChanged.connect(self._act_log.setChecked)

        tb.addAction(self._act_open)
        tb.addSeparator()
        tb.addAction(self._act_build)
        tb.addAction(self._act_gcode)
        tb.addAction(self._act_export_nc)
        tb.addAction(self._act_export)
        tb.addSeparator()
        tb.addAction(self._act_view2d)
        tb.addAction(self._act_view3d)
        tb.addAction(self._act_simulate)
        tb.addAction(self._act_fit)
        # push the dock toggles to the bottom of the vertical strip
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        tb.addWidget(spacer)
        tb.addAction(self._act_log)
        tb.addAction(self._act_sidebar)

        # (action, icon-name) for the runtime recolor hook (text fallback if
        # the SVG is missing). op-fit / view-sidebar are reused from GuildDraw.
        self._icon_actions = [
            (self._act_open, "op-open-dxf"),
            (self._act_build, "op-build-3d"),
            (self._act_gcode, "op-gcode"),
            (self._act_export_nc, "op-export-gcode"),
            (self._act_export, "op-export-stl"),
            (self._act_view2d, "view-2d"),
            (self._act_view3d, "view-3d"),
            (self._act_simulate, "sim-cut"),
            (self._act_fit, "op-fit"),
            (self._act_log, "toggle-log"),
            (self._act_sidebar, "view-sidebar"),
        ]

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        file_menu.addAction(self._act_open)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(self._act_open_project)
        file_menu.addAction(self._act_save_project)
        file_menu.addSeparator()
        file_menu.addAction(self._act_build)
        file_menu.addAction(self._act_gcode)
        file_menu.addAction(self._act_export_nc)
        file_menu.addAction(self._act_export)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._act_view2d)
        view_menu.addAction(self._act_view3d)
        view_menu.addAction(self._act_simulate)
        view_menu.addAction(self._act_fit)
        view_menu.addSeparator()
        view_menu.addAction(self._act_sidebar)
        view_menu.addAction(self._act_log)

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

    # ------------------------------------------------------------------ window state

    def _restore_window_state(self) -> None:
        geo = self._prefs.get("main_window_geometry", "")
        state = self._prefs.get("main_window_state", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        if state:
            # restoreState reinstates dock sizes + visibility; sync the toggles.
            self.restoreState(QByteArray.fromBase64(state.encode()))
            self._act_sidebar.setChecked(self._right_dock.isVisible())
            self._act_log.setChecked(self._log_dock.isVisible())

    def _save_window_state(self) -> None:
        self._prefs["main_window_geometry"] = bytes(
            self.saveGeometry().toBase64()
        ).decode()
        self._prefs["main_window_state"] = bytes(
            self.saveState().toBase64()
        ).decode()
        prefs_mod.save(self._prefs)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_window_state()
        super().closeEvent(event)

    # ------------------------------------------------------------------ log

    def append_log(self, message: str) -> None:
        self.log.append(message)
        self.log.ensureCursorVisible()

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
        if path.lower().endswith(".gcam"):
            self._open_project(Path(path))
        else:
            self._load_dxf(Path(path))

    # ------------------------------------------------------------------ .gcam project I/O (M5.1)

    def _build_project_schema(self):
        from guildcam.core.project.schema import MachineRef, MaterialRef, ProjectSchema
        cam = self.params.cam_params()
        job = self._source_name.rsplit(".", 1)[0] if self._source_name else "Untitled Frame"
        proj = ProjectSchema(
            job_name=job,
            source_file=self._source_name,
            castle=self.params.castle_params(),
            cam_params=cam,
            machine=MachineRef(name=cam.machine_name,
                               preset_file=f"machines/{cam.machine_name}.yaml"),
        )
        proj.cam.material = MaterialRef(name=self.params.material_name())
        return proj

    def _save_gcam_to(self, path: Path, announce: bool = True) -> bool:
        from guildcam.core.project.gcam import save_gcam
        from guildcam.core.post.machine import load_machine_profile
        if self._source_dxf_bytes is None:
            QMessageBox.warning(self, "No design", "Import a DXF before saving a project.")
            return False
        cam = self.params.cam_params()
        config_dir = Path(__file__).parent.parent / "config"
        machine = self._last_machine
        if machine is None:
            try:
                machine = load_machine_profile(cam.machine_name, config_dir).model_dump()
            except Exception:
                machine = None
        try:
            save_gcam(
                path, project=self._build_project_schema(),
                dxf_bytes=self._source_dxf_bytes,
                programs=self._last_programs or None,
                machine=machine, setup=self._last_setup, report=self._last_report,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._project_path = path
        self._add_recent(str(path))
        self.setWindowTitle(f"GuildCAM  —  {path.name}")
        # Green only once a program is actually stored in the .gcam (M5.2).
        self._program_stored = bool(self._last_programs)
        self._refresh_readiness()
        if announce:
            self.append_log(f"[project] Saved {path.name}")
            self.status_lbl.setText(f"Project saved — {path.name}")
        return True

    def _on_save_project(self) -> None:
        if self._source_dxf_bytes is None:
            QMessageBox.warning(self, "No design", "Import a DXF before saving a project.")
            return
        default = self._project_path or (
            Path(self._prefs["last_output_dir"] or ".")
            / ((self._source_name.rsplit(".", 1)[0] if self._source_name else "frame") + ".gcam"))
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save GuildCAM project", str(default), "GuildCAM project (*.gcam)")
        if not path_str:
            return
        if not path_str.lower().endswith(".gcam"):
            path_str += ".gcam"
        if self._save_gcam_to(Path(path_str)):
            self._prefs["last_output_dir"] = str(Path(path_str).parent)
            prefs_mod.save(self._prefs)

    def _on_open_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open GuildCAM project", self._prefs["last_output_dir"],
            "GuildCAM project (*.gcam);;All files (*)")
        if path_str:
            self._open_project(Path(path_str))

    def _open_project(self, path: Path) -> None:
        from guildcam.core.project.gcam import GcamError, load_gcam
        try:
            bundle = load_gcam(path)
        except GcamError as exc:
            QMessageBox.critical(self, "Open failed", f"{path.name}:\n{exc}")
            return
        proj = bundle.project
        # Restore params first so the post-import rebuild uses them.
        self.params.set_material(proj.cam.material.name)
        self.params.set_castle_params(proj.castle)
        self.params.set_cam_params(proj.cam_params)
        self._last_programs = dict(bundle.programs)
        self._last_setup = bundle.setup
        self._last_machine = bundle.machine
        self._last_report = bundle.report
        self._project_path = path
        # Readiness: a stored program means the reopened job is transmittable
        # (green) as soon as its DXF finishes importing below; otherwise the
        # import drops it to red. The model is rebuilt lazily from the DXF.
        self._mesh_built = False
        self._program_stored = bundle.has_program()
        self._act_export_nc.setEnabled(bundle.has_program())
        self._add_recent(str(path))
        self.setWindowTitle(f"GuildCAM  —  {path.name}")
        self.append_log(
            f"[project] Opened {path.name} "
            f"({'with program' if bundle.has_program() else 'no program yet'})")
        if bundle.dxf_bytes:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"gcam_{path.stem}.dxf"
            tmp.write_bytes(bundle.dxf_bytes)
            self._load_dxf(tmp, from_project=True)
            self._source_dxf_bytes = bundle.dxf_bytes
            self._source_name = proj.source_file or tmp.name
        else:
            QMessageBox.warning(self, "No DXF",
                                "This project has no embedded DXF; parameters restored only.")

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
        self.canvas.zoom_changed.connect(self._on_zoom_changed)

        for layer, cb in self.params.layer_checks.items():
            cb.toggled.connect(
                lambda checked, lyr=layer: self.canvas.set_layer_visible(lyr, checked)
            )

        # Live parametric rebuild (debounced; only while the 3D view is up)
        self.params.castle_changed.connect(self._on_castle_params_changed)
        self.params.stock_changed.connect(self._on_stock_changed)
        self.params.zone_hovered.connect(self._on_zone_hover)
        self.params.cam_changed.connect(self._on_cam_changed)
        self.preview3d.stage_changed.connect(self._on_stage_changed)

        # Restore persisted material + CAM params (machine / tool / strategy /
        # feeds). Set the material first (without repopulating), then apply the
        # persisted CAM values so the user's last edits survive the restart.
        self.params.set_material(self._prefs.get("material_name") or "acetate")
        saved_cam = self._prefs.get("cam_params") or {}
        if saved_cam:
            from guildcam.core.project.schema import CastleCamParams
            try:
                self.params.set_cam_params(CastleCamParams(**saved_cam))
            except Exception:
                pass

    # ------------------------------------------------------------------ view switch

    def _switch_view(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._act_view2d.setChecked(index == 0)
        self._act_view3d.setChecked(index == 1)
        self.zoom_label.setVisible(index == 0)

    # ------------------------------------------------------------------ DXF import

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open DXF file", "", "DXF files (*.dxf);;All files (*)",
        )
        if not path_str:
            return
        self._load_dxf(Path(path_str))

    def _load_dxf(self, path: Path, *, from_project: bool = False) -> None:
        self.status_lbl.setText(f"Loading {path.name}…")
        self.append_log(f"[import] {path.name}")

        # Retain the source DXF bytes so a .gcam is self-contained (M5.1).
        try:
            self._source_dxf_bytes = Path(path).read_bytes()
            self._source_name = path.name
        except Exception:
            self._source_dxf_bytes = None
        if not from_project:
            # A fresh DXF starts a new (unsaved) project; drop stale artifacts.
            self._project_path = None
            self._last_programs = {}
            self._last_setup = self._last_machine = self._last_report = None
            # Readiness restarts at red once the import lands (no model/program).
            self._mesh_built = False
            self._program_stored = False
            # No program for the fresh design yet — disable loose export.
            self._act_export_nc.setEnabled(False)

        self._import_worker = ImportWorker(path)
        self._import_thread = QThread()
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.error.connect(self._import_thread.quit)
        self._import_thread.start()

    def _set_file_loaded(self, name: str, layer_summary: str) -> None:
        self.params.set_file(name, layer_summary)
        self._act_gcode.setEnabled(True)
        self._act_export.setEnabled(True)
        self._act_build.setEnabled(True)

    def _on_import_finished(
        self, layers: dict, boxing, raw_summary: dict, unrecognised: list
    ) -> None:
        from guildcam.core.io_import.normalize import points_to_polygon

        self.canvas.set_layers(layers)

        fname = self._import_worker.path.name if self._import_worker else "?"
        non_empty = [k for k, v in layers.items() if v]

        self._set_file_loaded(
            fname,
            "Layers: " + ", ".join(non_empty) if non_empty else "No recognised layers",
        )

        # raw DXF layer report
        self.append_log(
            "[dxf]  Layers: "
            + ", ".join(
                f"{lyr}({','.join(t for t in types)})"
                for lyr, types in raw_summary.items()
            )
        )
        if unrecognised:
            self.append_log(
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
            self.append_log(
                f"[castle] {len(self._partition.zones)} zones from "
                f"{len(sculpt_curves)} SCULPT cuts ({kind})"
            )

        # Castle UI state: zone inspector, stage stepper, stock ghost, cache
        self.params.set_zones(self._partition)
        matched = self._partition is not None and self._partition.matched
        self.preview3d.set_stage_enabled(matched)
        self._act_simulate.setEnabled(matched)
        self._stage = "pockets"
        self.preview3d.set_stage(self._stage)
        self._stage_cache.clear()
        self._update_stock_canvas()

        # Boxing
        if boxing is not None:
            self.params.update_boxing(boxing.a, boxing.b, boxing.dbl, boxing.ed)
            self.append_log(
                f"[boxing] A={boxing.a:.1f}  B={boxing.b:.1f}"
                f"  DBL={boxing.dbl:.1f}  ED={boxing.ed:.1f} mm"
            )
        else:
            lens_count = len(lens_curves)
            self.append_log(
                f"[boxing] Skipped — {lens_count} LENS curve(s) found, need ≥2."
            )

        curve_counts = {k: len(v) for k, v in layers.items() if v}
        if curve_counts:
            self.append_log(
                "[curves] " + "  ".join(f"{k}:{n}" for k, n in curve_counts.items())
            )

        self.status_lbl.setText(f"Loaded: {fname}")
        self._dxf_loaded = True
        self._refresh_readiness()
        if self._import_worker is not None:
            self._add_recent(str(self._import_worker.path))

    def _on_import_error(self, tb: str) -> None:
        self.append_log("[ERROR] Import failed:\n" + tb)
        self.status_lbl.setText("Import failed — see log")
        QMessageBox.critical(self, "Import error", "DXF import failed.\n\nSee log for details.")

    # ------------------------------------------------------------------ progress dialog

    def _open_progress(self, title: str) -> QProgressDialog:
        dlg = QProgressDialog(title, "Cancel", 0, 100, self)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        self._progress_dialog = dlg
        return dlg

    def _on_stage(self, label: str, pct: int) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.setLabelText(label)
            self._progress_dialog.setValue(pct)

    def _close_progress(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.reset()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    # ------------------------------------------------------------------ 3D build

    def _castle_ready(self) -> bool:
        return self._partition is not None and self._partition.matched

    def _on_build_3d(self) -> None:
        if not self._castle_ready():
            self.append_log(
                "[3D] Castle relief needs the standard SCULPT zone layout "
                "(5 section cuts per side). Draw them in GuildDraw and re-export."
            )
            return
        self._start_mesh_build(show_progress=True)

    def _on_castle_params_changed(self) -> None:
        # Parameters changed: every cached stage is stale, and so is any stored
        # program (the relief it rode just changed) — drop green back to yellow.
        self._stage_cache.clear()
        self._invalidate_program()
        if self.stack.currentIndex() == 1 and self._castle_ready():
            self._rebuild_timer.start()

    def _on_stage_changed(self, stage: str) -> None:
        self._stage = stage
        cached = self._stage_cache.get(stage)
        if cached is not None:
            self._show_stage_mesh(cached)
        elif self._castle_ready():
            self._start_mesh_build(show_progress=False)

    def _on_stock_changed(self) -> None:
        self._invalidate_program()
        self._update_stock_canvas()
        # Re-draw the stock ghost around the currently shown stage, if any.
        cached = self._stage_cache.get(self._stage)
        if cached is not None and self.stack.currentIndex() == 1:
            self._show_stage_mesh(cached)

    def _on_cam_changed(self) -> None:
        """Persist the CAM tab (material / machine / tool / strategy / feeds).
        CAM params do not affect the 3D preview, so no rebuild is triggered."""
        # Feeds/tool/strategy changes invalidate any stored program (M5.2).
        self._invalidate_program()
        try:
            self._prefs["cam_params"] = self.params.cam_params().model_dump()
            self._prefs["material_name"] = self.params.material_name()
            prefs_mod.save(self._prefs)
        except Exception:
            pass

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

    def _start_mesh_build(self, show_progress: bool = False) -> None:
        if not self._castle_ready():
            return
        self.status_lbl.setText("Building 3D model…")
        self._act_build.setEnabled(False)
        self.append_log(f"[3D] Building castle ({self._stage})…")
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
        self._mesh_worker.cancelled.connect(self._on_mesh_cancelled)
        self._mesh_worker.finished.connect(self._mesh_thread.quit)
        self._mesh_worker.error.connect(self._mesh_thread.quit)
        self._mesh_worker.cancelled.connect(self._mesh_thread.quit)

        if show_progress:
            dlg = self._open_progress("Building 3D model")
            self._mesh_worker.stage.connect(self._on_stage)
            dlg.canceled.connect(self._mesh_worker.cancel)
        self._mesh_thread.start()

    def _show_stage_mesh(self, mesh) -> None:
        self.preview3d.show_mesh(mesh, stock=self.params.castle_params().stock)
        n_v = len(mesh.vertices)
        n_t = len(mesh.faces)
        self.status_lbl.setText(f"3D model ready — {n_v:,} verts · {n_t:,} tris")

    def _on_mesh_finished(self, mesh, stage: str) -> None:
        self._close_progress()
        self._stage_cache[stage] = mesh
        if stage == self._stage:
            self._show_stage_mesh(mesh)
        self.append_log(
            f"[3D] Done ({stage}) — {len(mesh.vertices):,} verts, "
            f"{len(mesh.faces):,} tris"
        )
        self._act_build.setEnabled(True)
        self._mesh_built = True
        self._refresh_readiness()

    def _on_mesh_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[3D ERROR]\n" + tb)
        self.status_lbl.setText("Build failed — see log")
        self._act_build.setEnabled(True)

    def _on_mesh_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[3D] Build cancelled.")
        self.status_lbl.setText("Build cancelled")
        self._act_build.setEnabled(True)

    # ------------------------------------------------------------------ other slots

    def _on_fit(self) -> None:
        idx = self.stack.currentIndex()
        if idx == 0:
            self.canvas.fit_to_view()
        elif idx == 1:
            self.preview3d._cam_reset()
        else:
            self.cutsim._cam_reset()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"Zoom: {scale:.1f} px/mm")

    # ------------------------------------------------------------------ cut simulation

    def _on_simulate(self) -> None:
        if not self._castle_ready():
            QMessageBox.warning(
                self, "No castle",
                "Load a DXF with matched SCULPT zones to simulate the cut.")
            return
        self.status_lbl.setText("Simulating cut…")
        self._act_simulate.setEnabled(False)
        self.append_log("[sim] Simulating the machined result…")
        self._switch_view(2)

        self._sim_worker = SimWorker(
            self._partition, self.params.castle_params(),
            cam_params=self.params.cam_params(),
            hinge_polys=self._hinge_polys,
            material_name=self.params.material_name(),
            resolution=self._prefs["preview_resolution_mm"],
        )
        self._sim_thread = QThread()
        self._sim_worker.moveToThread(self._sim_thread)
        self._sim_thread.started.connect(self._sim_worker.run)
        self._sim_worker.progress.connect(self.append_log)
        self._sim_worker.finished.connect(self._on_sim_finished)
        self._sim_worker.error.connect(self._on_sim_error)
        self._sim_worker.cancelled.connect(self._on_sim_cancelled)
        self._sim_worker.finished.connect(self._sim_thread.quit)
        self._sim_worker.error.connect(self._sim_thread.quit)
        self._sim_worker.cancelled.connect(self._sim_thread.quit)

        dlg = self._open_progress("Simulating cut")
        self._sim_worker.stage.connect(self._on_stage)
        dlg.canceled.connect(self._sim_worker.cancel)
        self._sim_thread.start()

    def _on_sim_finished(self, report, lines) -> None:
        self._close_progress()
        self.cutsim.show_report(report)
        for line in lines:
            self.append_log("[sim] " + line)
        self.status_lbl.setText({
            "ok": "Cut verified — surface fully reached",
            "warn": "Cut simulated — review the flagged regions",
            "fail": "Cut incomplete — see the flagged regions",
        }.get(report.status(), "Cut simulated"))
        # Keep a serialisable summary for the .gcam (no numpy masks).
        c, g = report.completeness, report.gouge
        self._last_report = {
            "status": report.status(),
            "uncut_fraction": round(c.uncut_fraction, 5),
            "max_excess_mm": round(c.max_excess_mm, 3),
            "gouge_cells": g.gouge_cells,
            "gouge_max_mm": round(g.max_depth_mm, 3),
            "summary": lines,
        }
        if self._project_path is not None:
            self._save_gcam_to(self._project_path, announce=False)
        self._act_simulate.setEnabled(True)

    def _on_sim_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[sim ERROR]\n" + tb)
        self.status_lbl.setText("Simulation failed — see log")
        self._act_simulate.setEnabled(True)

    def _on_sim_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[sim] Cancelled.")
        self.status_lbl.setText("Simulation cancelled")
        self._act_simulate.setEnabled(True)

    def _on_generate(self) -> None:
        if self._outline_poly is None:
            QMessageBox.warning(
                self,
                "No frame outline",
                "Load a DXF with an OUTLINE layer before generating G-code.",
            )
            return

        params = self._collect_gcode_params()
        self._maybe_write_back_material()

        self._act_gcode.setEnabled(False)
        self.append_log("[gcode] Generating — the program is stored in the project.")

        self._gcode_worker = GCodeWorker(
            outline=self._outline_poly,
            castle=self.params.castle_params(),
            params=params,
            partition=self._partition,
            hinge_polys=self._hinge_polys,
            cam_params=self.params.cam_params(),
        )
        self._gcode_thread = QThread()
        self._gcode_worker.moveToThread(self._gcode_thread)
        self._gcode_thread.started.connect(self._gcode_worker.run)
        self._gcode_worker.progress.connect(self.append_log)
        self._gcode_worker.finished.connect(self._on_gcode_finished)
        self._gcode_worker.error.connect(self._on_gcode_error)
        self._gcode_worker.cancelled.connect(self._on_gcode_cancelled)
        self._gcode_worker.finished.connect(self._gcode_thread.quit)
        self._gcode_worker.error.connect(self._gcode_thread.quit)
        self._gcode_worker.cancelled.connect(self._gcode_thread.quit)

        dlg = self._open_progress("Generating G-code")
        self._gcode_worker.stage.connect(self._on_stage)
        dlg.canceled.connect(self._gcode_worker.cancel)
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

    def _maybe_write_back_material(self) -> None:
        """If the CAM tab's feeds/speeds/stepover/stepdown differ from the
        selected material's stored defaults, offer to save them back."""
        from guildcam.gui import material_store
        name = self.params.material_name()
        values = self.params.current_material_values()
        changed = material_store.changed_keys(name, values)
        if not changed:
            return
        labels = {
            "spindle_rpm": "spindle", "feed_rate_mmpm": "feed",
            "plunge_rate_mmpm": "plunge", "relief_stepover_mm": "stepover",
            "contour_stepdown_mm": "stepdown", "rough_axial_stock_mm": "rough stock",
        }
        what = ", ".join(labels.get(k, k) for k in changed)
        resp = QMessageBox.question(
            self, "Update material defaults?",
            f"You changed {what} from the “{name}” defaults.\n\n"
            f"Save these as the new defaults for {name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            material_store.save_override(name, values)
            self.append_log(f"[material] Saved new {name} defaults: {what}.")

    def _on_gcode_finished(self, summary: str, rows) -> None:
        self._close_progress()
        self.append_log("[gcode] Done.")
        self._act_gcode.setEnabled(True)
        self.status_lbl.setText("G-code ready")
        # Capture the program + setup for the .gcam container (M5.1). A new
        # program supersedes any stale cut report.
        w = self._gcode_worker
        if w is not None and getattr(w, "programs", None):
            self._last_programs = w.programs
            self._last_setup = w.setup_dict
            self._last_machine = w.machine_dump
            self._last_report = None
            self._act_export_nc.setEnabled(True)
            # If a project file is open, fold the new program straight into it.
            if self._project_path is not None:
                self._save_gcam_to(self._project_path, announce=False)
                self.append_log(f"[project] Updated {self._project_path.name} with the new program.")
        if rows:
            OpSummaryDialog(rows, summary, self).exec()
        else:
            QMessageBox.information(self, "G-code generated", summary)

    def _on_gcode_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[gcode ERROR]\n" + tb)
        self._act_gcode.setEnabled(True)
        self.status_lbl.setText("G-code generation failed — see log")

    def _on_gcode_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[gcode] Cancelled.")
        self._act_gcode.setEnabled(True)
        self.status_lbl.setText("G-code cancelled")

    def _on_export_nc(self) -> None:
        """Write the generated program(s) to standalone .nc file(s) on demand
        (the program lives in the project by default; this is the opt-in loose
        export, mirroring Export STL)."""
        if not self._last_programs:
            QMessageBox.information(
                self, "Export G-code",
                "Generate G-code first (Ctrl+G) — then export it to a .nc file.",
            )
            return
        base = Path(self._prefs["last_output_dir"] or ".")
        if len(self._last_programs) == 1:
            name, text = next(iter(self._last_programs.items()))
            path_str, _ = QFileDialog.getSaveFileName(
                self, "Export G-code", str(base / name), "G-code (*.nc);;All files (*)"
            )
            if not path_str:
                return
            out = Path(path_str)
            try:
                out.write_text(text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
                return
            self._prefs["last_output_dir"] = str(out.parent)
            written = [out]
        else:
            # Multiple programs (e.g. a future back-side cut): pick a folder.
            d = QFileDialog.getExistingDirectory(
                self, "Export G-code — choose folder", str(base)
            )
            if not d:
                return
            written = []
            try:
                for name, text in self._last_programs.items():
                    p = Path(d) / name
                    p.write_text(text, encoding="utf-8")
                    written.append(p)
            except OSError as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
                return
            self._prefs["last_output_dir"] = d
        prefs_mod.save(self._prefs)
        for p in written:
            self.append_log(f"[export] Wrote {p}")
        self.status_lbl.setText(
            f"G-code exported — {written[0].name}"
            + (f" (+{len(written) - 1} more)" if len(written) > 1 else "")
        )

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
        self._act_export.setEnabled(False)
        self.status_lbl.setText("Exporting STL…")
        self._export_worker = ExportWorker(
            self._partition, self.params.castle_params(), self._hinge_polys,
            resolution=self._prefs["export_resolution_mm"], path=Path(path_str),
        )
        self._export_thread = QThread()
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self.append_log)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.cancelled.connect(self._on_export_cancelled)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_worker.error.connect(self._export_thread.quit)
        self._export_worker.cancelled.connect(self._export_thread.quit)

        dlg = self._open_progress("Exporting STL")
        self._export_worker.stage.connect(self._on_stage)
        dlg.canceled.connect(self._export_worker.cancel)
        self._export_thread.start()

    def _on_export_finished(self, path: str) -> None:
        self._close_progress()
        self.append_log(f"[export] Wrote {path}")
        self._act_export.setEnabled(True)
        self.status_lbl.setText("STL exported")

    def _on_export_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[export ERROR]\n" + tb)
        self._act_export.setEnabled(True)
        self.status_lbl.setText("STL export failed — see log")

    def _on_export_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[export] Cancelled.")
        self._act_export.setEnabled(True)
        self.status_lbl.setText("STL export cancelled")

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About GuildCAM",
            "<b>GuildCAM</b> v0.5.1 — pre-release<br><br>"
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
