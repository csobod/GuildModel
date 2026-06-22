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
    QToolBar, QProgressDialog, QTabBar, QComboBox,
    QListWidget, QListWidgetItem, QSpinBox, QSplitter,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QByteArray, QSize
from PySide6.QtGui import QAction, QKeySequence, QColor

from guildcam.core.layers import ALL_LAYERS as SUPPORTED_LAYERS
from guildcam.gui import prefs as prefs_mod
from guildcam.gui import icons as icons_mod
from guildcam.gui.style import theme
from guildcam.gui.widgets.dxf_canvas import DxfCanvas
from guildcam.gui.widgets.params_panel import ParamsPanel
from guildcam.gui.widgets.viewer_3d import Viewer3D
from guildcam.gui.widgets import readiness_dot
from guildcam.gui.widgets.readiness_dot import ReadinessDot
from guildcam.gui.component_workspace import (
    ComponentWorkspace, build_workspaces_from_gdraw, derive_workspace,
)


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


class FlatMeshWorker(_ProgressWorker):
    """Builds a flat-part solid (temple or base-curve block) off the GUI thread.

    Reuses the castle mesher on a flat-extrusion relief (core/relief/flat.py): a
    temple is the outline extruded with HINGE pockets + ENGRAVING grooves (snapped
    to the blank end when asked), a block is the blank box with the lens scribed on
    top and the M4 holes as through-holes. Emits the mesh + the temple core-guide
    bounds (a 3D visual reference, or None for a block).
    """

    finished = Signal(object, object)   # trimesh.Trimesh, core_guide bounds | None
    error = Signal(str)

    def __init__(self, mode: str, *, outline=None, temple=None, hinge_polys=(),
                 engraving=(), lens=None, block=None, resolution: float = 0.3) -> None:
        super().__init__()
        self.mode = mode
        self.outline = outline
        self.temple = temple
        self.hinge_polys = list(hinge_polys)
        self.engraving = list(engraving)
        self.lens = lens
        self.block = block
        self.resolution = resolution

    def run(self) -> None:
        try:
            from shapely.affinity import translate
            from guildcam.core.relief.castle import build_castle_mesh
            from guildcam.core.relief.flat import (
                build_block_relief, build_temple_relief, temple_core_guide,
                temple_snap_offset,
            )
            if self.mode == "temple":
                outline, hinge = self.outline, list(self.hinge_polys)
                eng = [list(c) for c in self.engraving]
                if self.temple.snap_to_blank_end:
                    dx, dy = temple_snap_offset(outline, hinge, self.temple.blank_length_mm)
                    outline = translate(outline, dx, dy)
                    hinge = [translate(h, dx, dy) for h in hinge]
                    eng = [[(x + dx, y + dy) for x, y in c] for c in eng]
                relief = build_temple_relief(
                    outline, self.temple, hinge, eng,
                    resolution=self.resolution, progress=self._progress)
                guide = temple_core_guide(outline, hinge, self.temple).bounds
                mesh = build_castle_mesh(relief, progress=self._progress)
                self.finished.emit(mesh, guide)
            else:
                relief = build_block_relief(
                    self.lens, self.block, resolution=self.resolution,
                    progress=self._progress)
                mesh = build_castle_mesh(relief, progress=self._progress)
                self.finished.emit(mesh, None)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


class MultiMeshWorker(_ProgressWorker):
    """Builds **every** loaded component's mesh in a *single* thread (BUILDPLAN M7
    UX: Build 3D builds all components). One worker / one thread for the whole run —
    never reassigned mid-flight — so there is no "QThread destroyed while running"
    crash. Emits ``built(index, mesh, core_guide|None)`` as each finishes, then
    ``finished``. ``specs`` are plain build descriptions (see _build_spec)."""

    built = Signal(int, object, object)   # ws index, trimesh.Trimesh, core_guide|None
    finished = Signal()
    error = Signal(str)

    def __init__(self, specs: list[dict], resolution: float) -> None:
        super().__init__()
        self.specs = specs
        self.resolution = resolution

    def run(self) -> None:
        try:
            from shapely.affinity import translate
            from guildcam.core.relief.castle import build_castle_mesh, build_castle_stage
            from guildcam.core.relief.flat import (
                build_block_relief, build_temple_relief, temple_core_guide,
                temple_snap_offset,
            )
            n = max(1, len(self.specs))
            for k, spec in enumerate(self.specs):
                label = spec["label"]

                def sub(lbl, frac, _k=k):
                    self._progress(f"{label}: {lbl}", (_k + frac) / n)

                sub("starting", 0.0)
                mode = spec["mode"]
                if mode == "castle":
                    relief = build_castle_stage(
                        spec["partition"], spec["castle"], spec["hinge"],
                        stage=spec["stage"], resolution=self.resolution, progress=sub)
                    mesh = build_castle_mesh(relief, progress=sub)
                    self.built.emit(spec["index"], mesh, None)
                elif mode == "temple":
                    outline, hinge = spec["outline"], list(spec["hinge"])
                    eng = [list(c) for c in spec["engraving"]]
                    temple = spec["temple"]
                    if temple.snap_to_blank_end:
                        dx, dy = temple_snap_offset(outline, hinge, temple.blank_length_mm)
                        outline = translate(outline, dx, dy)
                        hinge = [translate(h, dx, dy) for h in hinge]
                        eng = [[(x + dx, y + dy) for x, y in c] for c in eng]
                    relief = build_temple_relief(
                        outline, temple, hinge, eng, resolution=self.resolution, progress=sub)
                    guide = temple_core_guide(outline, hinge, temple).bounds
                    mesh = build_castle_mesh(relief, progress=sub)
                    self.built.emit(spec["index"], mesh, guide)
                else:  # block
                    relief = build_block_relief(
                        spec["lens"], spec["block"], resolution=self.resolution, progress=sub)
                    mesh = build_castle_mesh(relief, progress=sub)
                    self.built.emit(spec["index"], mesh, None)
            self.finished.emit()
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


# ------------------------------------------------------------------ tool library

def _tools_cfg() -> dict:
    """The effective tool table: shipped ``config/tools.yaml`` merged with the
    user's library (``~/.guildcam/tools.yaml``) — the single tool source for the
    CAM combos, generation, the post, and the sim (BUILDPLAN M7.8)."""
    from guildcam.gui import tool_store
    return tool_store.effective()


# Distinct overlay colours cycled across a program's operations (M7.11).
_TOOLPATH_COLORS = ["#e0563b", "#3b86e0", "#3aa33a", "#c79a2b",
                    "#9b59b6", "#16a085", "#e08c3b", "#d6477f"]


def _op_overlay(ops) -> list[dict]:
    """Per-op cutting paths (design mm) for the 2D toolpath overlay (M7.11)."""
    return [{"name": op.name, "tool": op.tool_name or "",
             "paths": [[(float(p[0]), float(p[1])) for p in path] for path in op.paths]}
            for op in ops]


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
        engraving=(), temple=None, is_temple=False,
    ) -> None:
        super().__init__()
        self.outline = outline
        self.castle = castle
        self.params = params
        self.cam_params = cam_params
        self.partition = partition
        self.hinge_polys = list(hinge_polys)
        self.engraving = list(engraving)     # ENGRAVING curves (M6.3 temples)
        self.temple = temple                 # TempleParams | None
        self.is_temple = is_temple
        self.block_lens = None               # a LENS interior (M6.4 base-curve block)
        self.block = None                    # BaseCurveBlockParams | None
        self.is_block = False
        self.is_worktable = False            # combined multi-part bed (M6.5)
        self.op_overlay = None               # per-op toolpaths for the 2D overlay (M7.11)
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
            relief, castle, self.hinge_polys, tool, params=cam,
            progress=self._progress, tools_cfg=tools_cfg,
        )
        for op in ops:
            zmin, zmax = op.z_range()
            tag = f" · {op.tool_name}" if (cam.is_multi_tool() and op.tool_name) else ""
            self.progress.emit(
                f"[gcode]   {op.name}: {len(op.paths)} paths, Z {zmin:.2f}..{zmax:.2f}{tag}"
            )

        # Tool-reach gating (BUILDPLAN M6.1 task 3): warn when an op's tool can't
        # reach its feature, suggesting a fitting tool.
        from guildcam.core.cam.castle_ops import (
            analyze_program_reach, build_tool_settings, count_tool_changes,
            depth_reach_warnings,
        )
        reach = analyze_program_reach(ops, self.hinge_polys, tools_cfg)
        reach = list(reach) + depth_reach_warnings(ops, self.castle.stock.total_pad_height_mm)
        for r in reach:
            self.progress.emit(f"[gcode] ⚠ reach: {r.message()}")

        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        violations = fixture_clearance_violations(ops, fixture, tool["radius_mm"])
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        # Multi-tool jobs (BUILDPLAN M6.1): assemble per-tool feeds (tool override
        # or material, clamped to the machine) and the Tn map; single-tool jobs
        # leave tool_settings None and post exactly as before.
        tool_settings = None
        if cam.is_multi_tool():
            tool_settings, ts_warns = build_tool_settings(
                ops, tools_cfg,
                default_feed=clamp.feed_rate_mmpm,
                default_plunge=clamp.plunge_rate_mmpm,
                default_spindle=clamp.spindle_rpm,
                machine=machine,
            )
            for w in ts_warns:
                self.progress.emit(f"[gcode] tool: {w}")
            n_changes = count_tool_changes(ops)
            tools_list = ", ".join(f"T{s.number} {n}" for n, s in tool_settings.items())
            self.progress.emit(
                f"[gcode] Multi-tool: {tools_list} · {n_changes} tool change(s) "
                f"({machine.tool_change_mode.upper()})"
            )
            first_ts = tool_settings[ops[0].tool_name]
            post_dia = first_ts.diameter_mm
            post_spindle = first_ts.spindle_rpm
            post_feed = first_ts.feed_rate_mmpm
            post_plunge = first_ts.plunge_rate_mmpm
        else:
            post_dia = tool["diameter_mm"]
            post_spindle = clamp.spindle_rpm
            post_feed = clamp.feed_rate_mmpm
            post_plunge = clamp.plunge_rate_mmpm

        # Program zero / G54 datum (BUILDPLAN M6.2): a post-time offset so the
        # chosen stock-box datum lands at work zero; geometry/sim stay in the
        # design frame. Fixture mode = identity.
        work_offset = cam.program_zero.work_offset(castle.stock)
        datum = cam.program_zero.datum_world(castle.stock)
        self.progress.emit(
            f"[gcode] Program zero: {cam.program_zero.label()} · "
            f"offset ({work_offset[0]:+.2f}, {work_offset[1]:+.2f}, {work_offset[2]:+.2f}) mm"
        )

        post = GRBLPost(
            job_name="posterior_cut",
            material=p["material_name"],
            tool_diameter_mm=post_dia,
            spindle_rpm=post_spindle,
            feed_rate_mmpm=post_feed,
            plunge_rate_mmpm=post_plunge,
            safe_z_mm=castle.stock.total_pad_height_mm + cam.safe_z_clearance_mm,
            work_offset=work_offset,
        )
        self._progress("Writing program", 0.95)
        write_castle_program(
            ops, post, arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            tool_settings=tool_settings,
            tool_change_mode=machine.tool_change_mode,
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
        report = estimate_program(
            text, MachineDynamics.from_profile(machine),
            tool_change_seconds=machine.tool_change_seconds,
        )
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))

        summary = ("Posterior program generated and stored in the project.\n"
                   "Save the project (Ctrl+S) to keep it in the .gcam, or "
                   "File ▸ Export G-code for a standalone .nc.")
        summary += (f"\n\nMachine: {machine.display_name}"
                    f"\nProgram zero: {cam.program_zero.label()}"
                    f"\nEstimated cycle: {report.cycle_seconds / 60:.1f} min "
                    f"(cut {report.cutting_only_seconds / 60:.1f} min)")
        if tool_settings:
            summary += (f"\nMulti-tool: {len(tool_settings)} tools, "
                        f"{report.n_tool_changes} change(s) — "
                        f"{report.total_seconds / 60:.1f} min incl. changes")
        if reach:
            summary += f"\n\n⚠ {len(reach)} tool-reach warning(s) — see log."
        if violations:
            summary += f"\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        if machine_warnings:
            summary += f"\n⚠ {len(machine_warnings)} machine compliance warning(s) — see log."
        rows = op_summaries(ops, feed_rate_mmpm=clamp.feed_rate_mmpm)
        self.op_overlay = _op_overlay(ops)

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
            "program_zero": cam.program_zero.label(),
            "program_zero_mode": cam.program_zero.mode,
            "work_offset_mm": [round(v, 3) for v in work_offset],
            "datum_world_mm": [round(v, 3) for v in datum],
            "est_cut_min": round(report.cutting_only_seconds / 60, 2),
            "est_cycle_min": round(report.cycle_seconds / 60, 2),
            "ops": rows,
        }
        if tool_settings:
            self.setup_dict.update({
                "op_tools": {op.name: op.tool_name for op in ops},
                "tools": [
                    {"number": s.number, "name": n, "diameter_mm": s.diameter_mm,
                     "spindle_rpm": s.spindle_rpm, "feed_rate_mmpm": s.feed_rate_mmpm,
                     "plunge_rate_mmpm": s.plunge_rate_mmpm}
                    for n, s in tool_settings.items()
                ],
                "tool_change_mode": machine.tool_change_mode,
                "n_tool_changes": report.n_tool_changes,
                "est_total_min": round(report.total_seconds / 60, 2),
            })
        self.finished.emit(summary, rows)

    def _generate_temple(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Temple program (BUILDPLAN M6.3): engrave the ENGRAVING curves at depth
        with a small tool, then profile-cut the outline with the bulk tool — one
        tool change between them, posted through the same multi-tool machinery and
        program-zero offset as the frame front."""
        import yaml
        from guildcam.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, count_tool_changes,
            fixture_clearance_violations, op_summaries, resolve_tool, write_castle_program,
        )
        from guildcam.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildcam.core.cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.post.machine import lint_program, load_machine_profile
        from guildcam.core.project.schema import TempleParams

        p = self.params
        cam = self.cam_params or CastleCamParams()
        temple = self.temple or TempleParams()
        machine = load_machine_profile(cam.machine_name, config_dir)
        mat_key = p["material_name"].split()[0].lower()
        mat = mats_cfg.get(mat_key, mats_cfg["acetate"])
        self.progress.emit(
            f"[gcode] Temple · Machine: {machine.display_name} · "
            f"engrave {temple.engrave_tool} → profile {temple.profile_tool}"
        )

        ops = generate_temple_program(self.outline, self.engraving, temple, tools_cfg, cam,
                                      hinge_polys=self.hinge_polys)
        for op in ops:
            zmin, zmax = op.z_range()
            self.progress.emit(
                f"[gcode]   {op.name}: {len(op.paths)} paths, "
                f"Z {zmin:.2f}..{zmax:.2f} · {op.tool_name}"
            )

        tool_settings, ts_warns = build_tool_settings(
            ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
            default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"],
            machine=machine)
        for w in ts_warns:
            self.progress.emit(f"[gcode] tool: {w}")
        n_changes = count_tool_changes(ops)
        self.progress.emit(
            f"[gcode] {', '.join(f'T{s.number} {n}' for n, s in tool_settings.items())} "
            f"· {n_changes} tool change(s) ({machine.tool_change_mode.upper()})"
        )

        # program zero from the temple blank box
        tstock = temple.stock()
        work_offset = cam.program_zero.work_offset(tstock)
        datum = cam.program_zero.datum_world(tstock)
        self.progress.emit(
            f"[gcode] Program zero: {cam.program_zero.label()} · "
            f"offset ({work_offset[0]:+.2f}, {work_offset[1]:+.2f}, {work_offset[2]:+.2f}) mm"
        )

        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        zone = temple.fixture_zone if temple.fixture_zone in fixture.get("blank_zones", {}) else "temple_right"
        profile_r = resolve_tool(temple.profile_tool, tools_cfg)["radius_mm"]
        violations = fixture_clearance_violations(ops, fixture, profile_r, blank=zone)
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        first_ts = tool_settings[ops[0].tool_name]
        post = GRBLPost(
            job_name="temple_cut", material=p["material_name"],
            tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
            feed_rate_mmpm=first_ts.feed_rate_mmpm, plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
            safe_z_mm=temple.blank_thickness_mm + cam.safe_z_clearance_mm,
            work_offset=work_offset,
        )
        self._progress("Writing temple program", 0.9)
        write_castle_program(
            ops, post, side="Temple", arc_tol_mm=cam.arc_tolerance_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=TEMPLE_CONTOUR_OPS)
        text = post.to_string()
        self.progress.emit(f"[gcode] temple_cut.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        report = estimate_program(text, MachineDynamics.from_profile(machine),
                                  tool_change_seconds=machine.tool_change_seconds)
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))
        rows = op_summaries(ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)
        self.op_overlay = _op_overlay(ops)

        summary = ("Temple program (engrave + profile) generated and stored in the "
                   "project.\nSave the project (Ctrl+S) or File ▸ Export G-code for a "
                   "standalone .nc.")
        summary += (f"\n\nMachine: {machine.display_name}"
                    f"\nProgram zero: {cam.program_zero.label()}"
                    f"\nTools: {len(tool_settings)} ({n_changes} change) — "
                    f"{report.total_seconds / 60:.1f} min incl. changes")
        if violations:
            summary += f"\n\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        if machine_warnings:
            summary += f"\n⚠ {len(machine_warnings)} machine compliance warning(s) — see log."

        self.programs = {"temple_cut.nc": text}
        self.machine_dump = machine.model_dump()
        self.setup_dict = {
            "component": "temple",
            "material": p["material_name"],
            "machine": machine.display_name,
            "engrave_tool": temple.engrave_tool,
            "profile_tool": temple.profile_tool,
            "engrave_depth_mm": temple.engrave_depth_mm,
            "onion_skin_mm": temple.onion_skin_mm,
            "program_zero": cam.program_zero.label(),
            "work_offset_mm": [round(v, 3) for v in work_offset],
            "datum_world_mm": [round(v, 3) for v in datum],
            "tools": [
                {"number": s.number, "name": n, "diameter_mm": s.diameter_mm,
                 "spindle_rpm": s.spindle_rpm, "feed_rate_mmpm": s.feed_rate_mmpm}
                for n, s in tool_settings.items()
            ],
            "n_tool_changes": n_changes,
            "est_cut_min": round(report.cutting_only_seconds / 60, 2),
            "est_total_min": round(report.total_seconds / 60, 2),
            "ops": rows,
        }
        self.finished.emit(summary, rows)

    def _generate_block(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Base-curve forming block (BUILDPLAN M6.4): peck-drill 3 mounting holes,
        scribe the lens-interior footprint, profile-cut the acetal blank — one
        tool change (drill → bulk), posted through the shared multi-tool machinery
        and program-zero offset."""
        import yaml
        from guildcam.core.cam.block_ops import (
            BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
        )
        from guildcam.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, count_tool_changes,
            fixture_clearance_violations, op_summaries, resolve_tool, write_castle_program,
        )
        from guildcam.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.post.machine import lint_program, load_machine_profile
        from guildcam.core.project.schema import BaseCurveBlockParams

        cam = self.cam_params or CastleCamParams()
        block = self.block or BaseCurveBlockParams()
        machine = load_machine_profile(cam.machine_name, config_dir)
        mat = mats_cfg.get(block.material, mats_cfg.get("acetate"))
        self.progress.emit(
            f"[gcode] Base-curve block · Machine: {machine.display_name} · "
            f"material {block.material} · drill {block.drill_tool}"
        )

        ops = generate_block_program(self.block_lens, block, tools_cfg, cam)
        for op in ops:
            zmin, zmax = op.z_range()
            self.progress.emit(
                f"[gcode]   {op.name}: {len(op.paths)} paths, "
                f"Z {zmin:.2f}..{zmax:.2f} · {op.tool_name}"
            )

        tool_settings, ts_warns = build_tool_settings(
            ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
            default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"],
            machine=machine)
        for w in ts_warns:
            self.progress.emit(f"[gcode] tool: {w}")
        n_changes = count_tool_changes(ops)
        self.progress.emit(
            f"[gcode] {', '.join(f'T{s.number} {n}' for n, s in tool_settings.items())} "
            f"· {n_changes} tool change(s) ({machine.tool_change_mode.upper()})"
        )

        # contour stepdown clamped to the acetal / machine depth-of-cut
        stepdown = min(cam.contour_stepdown_mm, machine.max_doc_mm,
                       mat.get("max_doc_mm", cam.contour_stepdown_mm))

        bstock = block.stock()
        work_offset = cam.program_zero.work_offset(bstock)
        datum = cam.program_zero.datum_world(bstock)
        self.progress.emit(
            f"[gcode] Program zero: {cam.program_zero.label()} · "
            f"offset ({work_offset[0]:+.2f}, {work_offset[1]:+.2f}, {work_offset[2]:+.2f}) mm"
        )

        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        zone = block.fixture_zone if block.fixture_zone in fixture.get("blank_zones", {}) else "bc_template_right"
        profile_r = resolve_tool(block.profile_tool, tools_cfg)["radius_mm"]
        violations = fixture_clearance_violations(ops, fixture, profile_r, blank=zone)
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        first_ts = tool_settings[ops[0].tool_name]
        post = GRBLPost(
            job_name="base_curve_block", material=block.material,
            tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
            feed_rate_mmpm=first_ts.feed_rate_mmpm, plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
            safe_z_mm=block.blank_thickness_mm + cam.safe_z_clearance_mm,
            work_offset=work_offset,
        )
        self._progress("Writing block program", 0.9)
        write_castle_program(
            ops, post, side="Base-Curve Block", arc_tol_mm=cam.arc_tolerance_mm,
            contour_stepdown_mm=stepdown, contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=BLOCK_CONTOUR_OPS, drill_op_names=BLOCK_DRILL_OPS,
            peck_depth_mm=block.peck_depth_mm)
        text = post.to_string()
        self.progress.emit(f"[gcode] base_curve_block.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        report = estimate_program(text, MachineDynamics.from_profile(machine),
                                  tool_change_seconds=machine.tool_change_seconds)
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))
        rows = op_summaries(ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)
        self.op_overlay = _op_overlay(ops)

        summary = ("Base-curve forming block (drill + forming scribe + profile) "
                   "generated and stored in the project.\nSave the project (Ctrl+S) "
                   "or File ▸ Export G-code for a standalone .nc.")
        summary += (f"\n\nMachine: {machine.display_name} · {block.material}"
                    f"\nProgram zero: {cam.program_zero.label()}"
                    f"\n{block.hole_count} × M4 holes ({block.hole_arrangement}, "
                    f"{block.hole_spacing_mm:.0f} mm, Ø{block.hole_diameter_mm:.1f}); "
                    f"{n_changes} tool change — {report.total_seconds / 60:.1f} min")
        if violations:
            summary += f"\n\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        if machine_warnings:
            summary += f"\n⚠ {len(machine_warnings)} machine compliance warning(s) — see log."

        self.programs = {"base_curve_block.nc": text}
        self.machine_dump = machine.model_dump()
        self.setup_dict = {
            "component": "base_curve_block",
            "material": block.material,
            "machine": machine.display_name,
            "blank_mm": [block.blank_length_mm, block.blank_width_mm, block.blank_thickness_mm],
            "drill_tool": block.drill_tool,
            "hole_count": block.hole_count,
            "hole_arrangement": block.hole_arrangement,
            "hole_spacing_mm": block.hole_spacing_mm,
            "hole_diameter_mm": block.hole_diameter_mm,
            "program_zero": cam.program_zero.label(),
            "work_offset_mm": [round(v, 3) for v in work_offset],
            "datum_world_mm": [round(v, 3) for v in datum],
            "tools": [
                {"number": s.number, "name": n, "diameter_mm": s.diameter_mm,
                 "spindle_rpm": s.spindle_rpm, "feed_rate_mmpm": s.feed_rate_mmpm}
                for n, s in tool_settings.items()
            ],
            "n_tool_changes": n_changes,
            "est_cut_min": round(report.cutting_only_seconds / 60, 2),
            "est_total_min": round(report.total_seconds / 60, 2),
            "ops": rows,
        }
        self.finished.emit(summary, rows)

    def _generate_worktable(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Combined worktable program (BUILDPLAN M6.5): the frame front + its
        base-curve block, auto-packed onto their fixture zones and cut in **one**
        program, scheduled to minimise tool changes across the whole bed."""
        import yaml
        from guildcam.core.cam.block_ops import (
            BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
        )
        from guildcam.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, generate_castle_program,
            op_summaries, write_castle_program,
        )
        from guildcam.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildcam.core.cam.layout import BedPart, bed_clearance_violations, build_bed_program
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.post.machine import lint_program, load_machine_profile
        from guildcam.core.project.schema import BaseCurveBlockParams
        from guildcam.core.relief.castle import build_castle_relief

        cam = self.cam_params or CastleCamParams()
        castle = self.castle
        block = self.block or BaseCurveBlockParams()
        machine = load_machine_profile(cam.machine_name, config_dir)
        mat_name = self.params["material_name"]
        mat = mats_cfg.get(mat_name.split()[0].lower(), mats_cfg["acetate"])
        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        self.progress.emit(f"[gcode] Worktable · Machine: {machine.display_name}")

        # part 1 — the frame front (posterior cut)
        self.progress.emit("[gcode] Worktable: building the frame relief…")
        relief = build_castle_relief(self.partition, castle, self.hinge_polys,
                                     resolution=0.15, progress=self._progress)
        frame_ops = generate_castle_program(
            relief, castle, self.hinge_polys, tools_cfg.get(cam.tool_name, tools_cfg["flat_3175"]),
            params=cam, tools_cfg=tools_cfg)

        # part 2 — the base-curve forming block from the OD lens
        self.progress.emit("[gcode] Worktable: generating the base-curve block…")
        block_ops = generate_block_program(self.block_lens, block, tools_cfg, cam)

        parts = [
            BedPart("frame_front", "Frame", "front", frame_ops, {"Eyewires", "Perimeter"}, set()),
            BedPart("base_curve_block", "Block", "bc_template_right", block_ops,
                    BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS),
        ]
        bed = build_bed_program(parts, fixture)
        self.progress.emit(
            f"[gcode] Bed: {len(parts)} parts, {len(bed.ops)} ops, "
            f"{bed.n_tool_changes} tool change(s) (grouped by tool):"
        )
        for p in bed.placements:
            self.progress.emit(
                f"[gcode]   {p.label} ({p.kind}) → {p.fixture_zone} "
                f"@ ({p.x_mm:.1f}, {p.y_mm:.1f}) mm")

        tool_settings, ts_warns = build_tool_settings(
            bed.ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
            default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"],
            machine=machine)
        for w in ts_warns:
            self.progress.emit(f"[gcode] tool: {w}")

        # parts are placed in absolute machine coordinates → touch off machine zero
        violations = bed_clearance_violations(bed.ops, fixture, skip_op_names=bed.drill_op_names)
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        first_ts = tool_settings[bed.ops[0].tool_name]
        safe_z = max(castle.stock.total_pad_height_mm, block.blank_thickness_mm) + cam.safe_z_clearance_mm
        post = GRBLPost(
            job_name="worktable", material=mat_name,
            tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
            feed_rate_mmpm=first_ts.feed_rate_mmpm, plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
            safe_z_mm=safe_z,
        )
        self._progress("Writing worktable program", 0.92)
        write_castle_program(
            bed.ops, post, side="Worktable", arc_tol_mm=cam.arc_tolerance_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=bed.contour_op_names, drill_op_names=bed.drill_op_names,
            peck_depth_mm=block.peck_depth_mm)
        text = post.to_string()
        self.progress.emit(f"[gcode] worktable.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        report = estimate_program(text, MachineDynamics.from_profile(machine),
                                  tool_change_seconds=machine.tool_change_seconds)
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))
        rows = op_summaries(bed.ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)

        summary = ("Worktable program (frame front + base-curve block) generated "
                   "and stored in the project.\nSave the project (Ctrl+S) or File ▸ "
                   "Export G-code for a standalone .nc.")
        summary += (f"\n\nMachine: {machine.display_name} · zero at machine origin"
                    f"\n{len(parts)} parts, {len(tool_settings)} tools, "
                    f"{report.n_tool_changes} change(s) — "
                    f"{report.total_seconds / 60:.1f} min incl. changes")
        if violations:
            summary += f"\n\n⚠ {len(violations)} fixture clearance warning(s) — see log."
        if machine_warnings:
            summary += f"\n⚠ {len(machine_warnings)} machine compliance warning(s) — see log."

        self.programs = {"worktable.nc": text}
        self.machine_dump = machine.model_dump()
        self.setup_dict = {
            "component": "worktable",
            "material": mat_name,
            "machine": machine.display_name,
            "parts": [
                {"label": p.label, "kind": p.kind, "fixture_zone": p.fixture_zone,
                 "x_mm": p.x_mm, "y_mm": p.y_mm, "rotation_deg": p.rotation_deg}
                for p in bed.placements
            ],
            "tools": [
                {"number": s.number, "name": n, "diameter_mm": s.diameter_mm,
                 "spindle_rpm": s.spindle_rpm, "feed_rate_mmpm": s.feed_rate_mmpm}
                for n, s in tool_settings.items()
            ],
            "n_tool_changes": report.n_tool_changes,
            "est_cut_min": round(report.cutting_only_seconds / 60, 2),
            "est_total_min": round(report.total_seconds / 60, 2),
            "ops": rows,
        }
        self.finished.emit(summary, rows)

    def _generate(self) -> None:
        import yaml
        from guildcam.core.cam.profile import profile_cut
        from guildcam.core.post.grbl import GRBLPost

        p = self.params
        config_dir = Path(__file__).parent.parent / "config"

        tools_cfg = _tools_cfg()
        with open(config_dir / "materials.yaml", encoding="utf-8") as f:
            mats_cfg = yaml.safe_load(f)

        # ---- Worktable path: several components in one program (M6.5) ----
        if self.is_worktable:
            self._generate_worktable(tools_cfg, mats_cfg, config_dir)
            return

        # ---- Base-curve block path: drill + forming scribe + profile (M6.4) ----
        if self.is_block:
            self._generate_block(tools_cfg, mats_cfg, config_dir)
            return

        # ---- Temple path: engrave + profile (M6.3) ----
        if self.is_temple:
            self._generate_temple(tools_cfg, mats_cfg, config_dir)
            return

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

    finished = Signal(object, object, object)   # CutReport, summary lines, FloorSnapshot[]
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
                CastleCamParams, build_tool_settings, generate_castle_program,
                write_castle_program,
            )
            from guildcam.core.post.grbl import GRBLPost
            from guildcam.core.sim import (
                ToolProfile, achieved_floor, achieved_floor_grouped,
                cutting_paths_from_program, cutting_paths_from_program_grouped, verify,
                simulate_steps, steps_from_ops,
            )

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
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
                relief, self.castle, self.hinge_polys, tool, params=cam,
                tools_cfg=tools_cfg)

            # Multi-tool jobs (M6.1): post with per-tool change blocks and sweep
            # each move with its own tool profile, so the sim matches the real cut.
            tool_settings = None
            if cam.is_multi_tool():
                tool_settings, _ = build_tool_settings(
                    ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
                    default_plunge=mat["plunge_rate_mmpm"],
                    default_spindle=mat["spindle_rpm"])
            first = tool_settings[ops[0].tool_name] if tool_settings else None
            post = GRBLPost(
                job_name="sim", material=self.material_name,
                tool_diameter_mm=(first.diameter_mm if first else tool["diameter_mm"]),
                spindle_rpm=(first.spindle_rpm if first else mat["spindle_rpm"]),
                feed_rate_mmpm=(first.feed_rate_mmpm if first else mat["feed_rate_mmpm"]),
                plunge_rate_mmpm=(first.plunge_rate_mmpm if first else mat["plunge_rate_mmpm"]),
                safe_z_mm=self.castle.stock.total_pad_height_mm + cam.safe_z_clearance_mm,
            )
            write_castle_program(
                ops, post, arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                tool_settings=tool_settings)

            self.progress.emit("[sim] Sweeping tool along the toolpaths…")
            f = relief.field
            init_z = self.castle.stock.total_pad_height_mm + 1.0
            _swp = lambda p: self._progress("Simulating", 0.6 + 0.35 * p)
            if tool_settings:
                groups = cutting_paths_from_program_grouped(post.to_string())
                profiles = {n: ToolProfile.from_tool(tools_cfg[n])
                            for n in {t for _, t in groups if t and t in tools_cfg}}
                floor = achieved_floor_grouped(
                    groups, profiles, ToolProfile.from_tool(tool),
                    f.origin, f.z.shape, f.resolution, init_z, progress=_swp)
            else:
                paths = cutting_paths_from_program(post.to_string())
                floor = achieved_floor(
                    paths, ToolProfile.from_tool(tool), f.origin, f.z.shape,
                    f.resolution, init_z, progress=_swp)
            report = verify(
                floor, np.where(relief.inside, f.z, np.nan), relief.inside,
                f.origin, f.resolution, partition=self.partition)

            # Per-op snapshots for the playback scrubber (M7.12): re-sweep the ops
            # one at a time (each op carries its own tool), capturing the cumulative
            # floor after each. Monotonic; the last frame matches the full sweep.
            self._progress("Building playback", 0.96)
            snaps = simulate_steps(
                steps_from_ops(ops, ToolProfile.from_tool(tool)),
                f.origin, f.z.shape, f.resolution, init_z)
            self.finished.emit(report, report.summary_lines(), snaps)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


class FlatSimWorker(_ProgressWorker):
    """Simulates the machined result of a flat part — a temple or a base-curve
    block (BUILDPLAN M7: machine simulation on every component). Builds the flat
    relief as the target surface, generates + posts the same program the tab cuts,
    sweeps each tool along the cutting moves, and verifies the achieved floor
    against the target — reusing the castle sim's `achieved_floor`/`verify`.
    """

    finished = Signal(object, object, object)   # CutReport, summary lines, FloorSnapshot[]
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, mode: str, *, outline=None, temple=None, hinge_polys=(),
                 engraving=(), lens=None, block=None, cam_params=None,
                 material_name: str = "acetate", resolution: float = 0.3) -> None:
        super().__init__()
        self.mode = mode
        self.outline = outline
        self.temple = temple
        self.hinge_polys = list(hinge_polys)
        self.engraving = list(engraving)
        self.lens = lens
        self.block = block
        self.cam_params = cam_params
        self.material_name = material_name
        self.resolution = resolution

    def run(self) -> None:
        try:
            import numpy as np
            import yaml
            from guildcam.core.cam.block_ops import (
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
            )
            from guildcam.core.cam.castle_ops import (
                CastleCamParams, build_tool_settings, resolve_tool, write_castle_program,
            )
            from guildcam.core.cam.temple_ops import (
                TEMPLE_CONTOUR_OPS, generate_temple_program,
            )
            from guildcam.core.post.grbl import GRBLPost
            from guildcam.core.relief.flat import build_block_relief, build_temple_relief
            from guildcam.core.sim import (
                ToolProfile, achieved_floor_grouped,
                cutting_paths_from_program_grouped, verify,
                simulate_steps, steps_from_ops,
            )

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            mat_key = self.material_name.split()[0].lower()
            mat = mats_cfg.get(mat_key, mats_cfg["acetate"])

            self.progress.emit(f"[sim] Building the {self.mode} relief at {self.resolution} mm…")
            if self.mode == "temple":
                t = self.temple
                # The sim target matches what the PROGRAM cuts: the temple program
                # now mills the HINGE pockets (BUILDPLAN M7), so the relief carves
                # them too — model, sim, and posted G-code agree on the recess.
                relief = build_temple_relief(
                    self.outline, t, self.hinge_polys, self.engraving,
                    resolution=self.resolution, progress=self._progress)
                ops = generate_temple_program(self.outline, self.engraving, t, tools_cfg, cam,
                                              hinge_polys=self.hinge_polys)
                contour_names, drill_names = TEMPLE_CONTOUR_OPS, set()
                top_z, peck = t.blank_thickness_mm, 1.5
                fallback_tool = resolve_tool(t.profile_tool, tools_cfg)
            else:
                b = self.block
                relief = build_block_relief(
                    self.lens, b, resolution=self.resolution, progress=self._progress)
                ops = generate_block_program(self.lens, b, tools_cfg, cam)
                contour_names, drill_names = BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS
                top_z, peck = b.blank_thickness_mm, b.peck_depth_mm
                fallback_tool = resolve_tool(b.profile_tool, tools_cfg)

            self._progress("Posting the program", 0.55)
            tool_settings, _ = build_tool_settings(
                ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
                default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"])
            first = tool_settings[ops[0].tool_name]
            post = GRBLPost(
                job_name="sim", material=self.material_name,
                tool_diameter_mm=first.diameter_mm, spindle_rpm=first.spindle_rpm,
                feed_rate_mmpm=first.feed_rate_mmpm, plunge_rate_mmpm=first.plunge_rate_mmpm,
                safe_z_mm=top_z + cam.safe_z_clearance_mm)        # work_offset (0,0,0): sim stays in the design frame
            write_castle_program(
                ops, post, arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                tool_settings=tool_settings, contour_op_names=contour_names,
                drill_op_names=drill_names, peck_depth_mm=peck)

            self.progress.emit("[sim] Sweeping the tools along the toolpaths…")
            f = relief.field
            init_z = top_z                                        # the uncut flat top = the target top
            _swp = lambda p: self._progress("Simulating", 0.6 + 0.35 * p)
            groups = cutting_paths_from_program_grouped(post.to_string())
            profiles = {n: ToolProfile.from_tool(tools_cfg[n])
                        for n in {t for _, t in groups if t and t in tools_cfg}}
            floor = achieved_floor_grouped(
                groups, profiles, ToolProfile.from_tool(fallback_tool),
                f.origin, f.z.shape, f.resolution, init_z, progress=_swp)
            report = verify(
                floor, np.where(relief.inside, f.z, np.nan), relief.inside,
                f.origin, f.resolution, partition=None)

            # Per-op snapshots for the playback scrubber (M7.12).
            self._progress("Building playback", 0.96)
            snaps = simulate_steps(
                steps_from_ops(ops, ToolProfile.from_tool(fallback_tool)),
                f.origin, f.z.shape, f.resolution, init_z)
            self.finished.emit(report, report.summary_lines(), snaps)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


# ------------------------------------------------------------------ worktable nest worker

class NestWorker(_ProgressWorker):
    """Generate each built component's program and nest them onto the tagged
    worktable by role (BUILDPLAN M7.6). Off-thread because the frame relief build is
    the slow part; the resulting `BedNest` drives the bed render + clearance badge.
    Clearance itself is recomputed on the GUI thread (cheap) so a nudge can re-check
    without regenerating any program.
    """

    finished = Signal(object)    # core.cam.layout.BedNest
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, specs, worktable, *, cam_params=None,
                 resolution: float = 0.4) -> None:
        super().__init__()
        self.specs = specs
        self.worktable = worktable
        self.cam_params = cam_params
        self.resolution = resolution

    def run(self) -> None:
        try:
            import yaml
            from guildcam.core.cam.block_ops import (
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
            )
            from guildcam.core.cam.castle_ops import (
                CastleCamParams, generate_castle_program,
            )
            from guildcam.core.cam.temple_ops import (
                TEMPLE_CONTOUR_OPS, generate_temple_program,
            )
            from guildcam.core.cam.layout import BedPart, nest_components_on_worktable
            from guildcam.core.relief.castle import build_castle_relief

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools = _tools_cfg()
            default_tool = tools.get(cam.tool_name, tools["flat_3175"])
            n = max(len(self.specs), 1)
            parts: list = []
            for k, spec in enumerate(self.specs):
                base = k / n
                self.progress.emit(f"[nest] {spec['label']}: generating program…")
                mode = spec["mode"]
                if mode == "castle":
                    relief = build_castle_relief(
                        spec["partition"], spec["castle"], spec["hinge"],
                        resolution=self.resolution,
                        progress=lambda lbl, f, b=base: self._progress(lbl, b + f / n))
                    ops = generate_castle_program(
                        relief, spec["castle"], spec["hinge"], default_tool,
                        params=cam, tools_cfg=tools)
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         {"Eyewires", "Perimeter"}, set()))
                elif mode == "temple":
                    ops = generate_temple_program(
                        spec["outline"], spec["engraving"], spec["temple"], tools, cam,
                        hinge_polys=spec["hinge"])
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         set(TEMPLE_CONTOUR_OPS), set()))
                else:  # block
                    ops = generate_block_program(spec["lens"], spec["block"], tools, cam)
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         set(BLOCK_CONTOUR_OPS), set(BLOCK_DRILL_OPS)))
            self._progress("Nesting onto the bed", 0.95)
            self.finished.emit(nest_components_on_worktable(parts, self.worktable))
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


class BedSimWorker(_ProgressWorker):
    """Simulate the whole nested bed (BUILDPLAN M7.7): build each placed component's
    cut sim and composite them onto one machine-coords bed grid → a `CutReport` for
    the whole worktable. Off-thread because each component rebuilds its relief; the
    report drives the shared 3D viewer's sim mode (Uncut / Gouge overlays)."""

    finished = Signal(object, object)   # core.sim.CutReport, summary lines
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, specs, placements, work_area, *, cam_params=None,
                 material_name: str = "acetate", resolution: float = 0.4) -> None:
        super().__init__()
        self.specs = specs
        self.placements = placements          # list[BedPlacement] (label → dx/dy/kind)
        self.work_area = work_area
        self.cam_params = cam_params
        self.material_name = material_name
        self.resolution = resolution

    def run(self) -> None:
        try:
            import yaml
            from guildcam.core.cam.castle_ops import CastleCamParams
            from guildcam.core.sim import (
                ComponentSim, composite_bed_report, simulate_component,
            )

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            place = {pl.label: pl for pl in self.placements}
            specs = [s for s in self.specs if s["label"] in place]
            comps: list = []
            n = max(len(specs), 1)
            for k, spec in enumerate(specs):
                base = k / n
                self.progress.emit(f"[bed-sim] {spec['label']}: simulating…")
                floor, target, inside, origin, res = simulate_component(
                    spec, cam=cam, tools_cfg=tools_cfg, mats_cfg=mats_cfg,
                    material_name=self.material_name, resolution=self.resolution,
                    progress=lambda lbl, fr, b=base: self._progress(lbl, b + fr / n))
                pl = place[spec["label"]]
                comps.append(ComponentSim(floor, target, inside, origin, res,
                                          dx=pl.dx, dy=pl.dy, label=pl.label, kind=pl.kind))
            self._progress("Compositing the bed", 0.96)
            report = composite_bed_report(comps, self.work_area, resolution=self.resolution)
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

        # ── Tab 2 — Tools (the editable tool library, BUILDPLAN M7.8) ──────
        self._build_tools_tab(tabs)

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

    # ── Tools tab (the editable tool library, BUILDPLAN M7.8) ─────────────

    # (field, label, kind, lo, hi, step, dec, suffix); kind: int | float | feed
    _TOOL_FIELDS = [
        ("diameter_mm", "Diameter", "float", 0.05, 25.0, 0.05, 3, " mm"),
        ("corner_radius_mm", "Corner radius (toroid)", "float", 0.0, 12.0, 0.05, 3, " mm"),
        ("included_angle_deg", "Included angle (V-bit)", "float", 0.0, 180.0, 1.0, 1, "°"),
        ("flutes", "Flutes", "int", 1, 8, 1, 0, ""),
        ("flute_length_mm", "Flute length", "float", 0.0, 80.0, 0.5, 2, " mm"),
        ("shank_diameter_mm", "Shank diameter", "float", 0.0, 12.0, 0.5, 2, " mm"),
        ("number", "Tool number (0 = auto)", "int", 0, 99, 1, 0, ""),
        ("feed_rate_mmpm", "Feed (0 = material)", "feed", 0.0, 10000.0, 50.0, 0, " mm/min"),
        ("plunge_rate_mmpm", "Plunge (0 = material)", "feed", 0.0, 5000.0, 25.0, 0, " mm/min"),
        ("spindle_rpm", "Spindle (0 = material)", "feed", 0.0, 60000.0, 500.0, 0, " RPM"),
        ("max_doc_mm", "Max DOC (0 = material)", "feed", 0.0, 10.0, 0.1, 2, " mm"),
    ]
    _TOOL_FEED_KEYS = ("feed_rate_mmpm", "plunge_rate_mmpm", "spindle_rpm", "max_doc_mm")

    def _build_tools_tab(self, tabs) -> None:
        from guildcam.gui import tool_store
        from guildcam.core.cam.tooling import TOOL_TYPES
        # staged working copy (name → ToolSpec); committed to the user library on OK.
        self._tool_working = {n: tool_store.spec(n) for n in tool_store.names()}

        outer = QWidget()
        col = QVBoxLayout(outer)
        col.setContentsMargins(16, 16, 16, 8)
        col.setSpacing(8)
        tabs.addTab(outer, "Tools")

        hint = QLabel("Your tool library. Add, edit, or remove tools here — no file "
                      "editing needed. Shipped tools can be reset; share a set with "
                      "Import / Export.")
        hint.setWordWrap(True)
        hint.setObjectName("mutedSmallLabel")
        col.addWidget(hint)

        split = QSplitter()
        col.addWidget(split, 1)

        self._tool_list = QListWidget()
        self._tool_list.setMinimumWidth(170)
        self._tool_list.currentRowChanged.connect(self._on_tool_selected)
        split.addWidget(self._tool_list)

        form_host = QWidget()
        fl = QFormLayout(form_host)
        self._tw: dict = {}
        self._tw_name = QLabel("—")
        fl.addRow("Id:", self._tw_name)
        self._tw_display = QLineEdit()
        self._tw_display.textEdited.connect(self._on_tool_field_changed)
        fl.addRow("Name:", self._tw_display)
        self._tw_type = QComboBox()
        self._tw_type.addItems(TOOL_TYPES)
        self._tw_type.currentIndexChanged.connect(self._on_tool_field_changed)
        fl.addRow("Type:", self._tw_type)
        for key, label, kind, lo, hi, step, dec, suffix in self._TOOL_FIELDS:
            if kind == "int":
                sb = QSpinBox()
                sb.setRange(int(lo), int(hi))
                sb.setSingleStep(int(step))
            else:
                sb = QDoubleSpinBox()
                sb.setRange(lo, hi)
                sb.setSingleStep(step)
                sb.setDecimals(dec)
            if suffix:
                sb.setSuffix(suffix)
            sb.valueChanged.connect(self._on_tool_field_changed)
            fl.addRow(label + ":", sb)
            self._tw[key] = sb
        self._tw_notes = QLineEdit()
        self._tw_notes.textEdited.connect(self._on_tool_field_changed)
        fl.addRow("Notes:", self._tw_notes)
        split.addWidget(form_host)
        split.setStretchFactor(1, 1)

        from guildcam.gui.widgets.tool_view import ToolView
        self._tool_view = ToolView()
        self._tool_view.set_dark_mode(self._dark_check.isChecked())
        split.addWidget(self._tool_view)

        row = QHBoxLayout()
        for label, slot in (("Add", self._on_tool_add),
                            ("Duplicate", self._on_tool_duplicate),
                            ("Delete", self._on_tool_delete),
                            ("Reset to shipped", self._on_tool_reset)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        col.addLayout(row)
        row2 = QHBoxLayout()
        imp = QPushButton("Import…")
        imp.clicked.connect(self._on_tool_import)
        exp = QPushButton("Export…")
        exp.clicked.connect(self._on_tool_export)
        row2.addWidget(imp)
        row2.addWidget(exp)
        row2.addStretch()
        col.addLayout(row2)

        self._refresh_tool_list()

    def _current_tool_name(self):
        it = self._tool_list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _refresh_tool_list(self, select: str | None = None) -> None:
        from guildcam.gui import tool_store
        target = select or self._current_tool_name()
        self._tool_list.blockSignals(True)
        self._tool_list.clear()
        for name, spec in self._tool_working.items():
            tag = "" if tool_store.is_shipped(name) else "  (custom)"
            it = QListWidgetItem((spec.display_name or name) + tag)
            it.setData(Qt.ItemDataRole.UserRole, name)
            self._tool_list.addItem(it)
        self._tool_list.blockSignals(False)
        rows = {self._tool_list.item(i).data(Qt.ItemDataRole.UserRole): i
                for i in range(self._tool_list.count())}
        self._tool_list.setCurrentRow(rows.get(target, 0) if rows else -1)

    def _on_tool_selected(self, _row: int) -> None:
        name = self._current_tool_name()
        if name is None:
            return
        spec = self._tool_working[name]
        block = [self._tw_display, self._tw_type, self._tw_notes, *self._tw.values()]
        for w in block:
            w.blockSignals(True)
        self._tw_name.setText(name)
        self._tw_display.setText(spec.display_name)
        self._tw_type.setCurrentText(spec.type)
        for key, sb in self._tw.items():
            val = getattr(spec, key)
            sb.setValue(float(val) if val is not None else 0.0)
        self._tw_notes.setText(spec.notes)
        for w in block:
            w.blockSignals(False)
        self._tool_view.set_spec(spec)

    def _on_tool_field_changed(self, *_a) -> None:
        from guildcam.core.cam.tooling import ToolSpec
        from guildcam.gui import tool_store
        name = self._current_tool_name()
        if name is None:
            return
        d = {"display_name": self._tw_display.text(),
             "type": self._tw_type.currentText(),
             "notes": self._tw_notes.text()}
        for key, sb in self._tw.items():
            d[key] = sb.value()
        for f in self._TOOL_FEED_KEYS:
            if not d.get(f):
                d[f] = None
        d["flutes"], d["number"] = int(d["flutes"]), int(d["number"])
        spec = ToolSpec.from_dict(d)
        self._tool_working[name] = spec
        self._tool_view.set_spec(spec)
        it = self._tool_list.currentItem()
        if it is not None:
            tag = "" if tool_store.is_shipped(name) else "  (custom)"
            it.setText((d["display_name"] or name) + tag)

    def _unique_tool_key(self, base: str) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "tool"
        key, i = slug, 2
        while key in self._tool_working:
            key, i = f"{slug}_{i}", i + 1
        return key

    def _on_tool_add(self) -> None:
        from guildcam.core.cam.tooling import ToolSpec
        key = self._unique_tool_key("new tool")
        self._tool_working[key] = ToolSpec(display_name="New Tool", type="flat",
                                           diameter_mm=3.0, flutes=2)
        self._refresh_tool_list(select=key)

    def _on_tool_duplicate(self) -> None:
        name = self._current_tool_name()
        if name is None:
            return
        src = self._tool_working[name]
        label = src.display_name or name
        key = self._unique_tool_key(label + " copy")
        self._tool_working[key] = src.model_copy(
            update={"display_name": label + " (copy)", "number": 0})
        self._refresh_tool_list(select=key)

    def _on_tool_delete(self) -> None:
        name = self._current_tool_name()
        if name is None:
            return
        del self._tool_working[name]
        self._refresh_tool_list()

    def _on_tool_reset(self) -> None:
        from guildcam.core.cam.tooling import ToolSpec
        from guildcam.gui import tool_store
        name = self._current_tool_name()
        if name is None or not tool_store.is_shipped(name):
            return
        self._tool_working[name] = ToolSpec.from_dict(tool_store.shipped_tool(name))
        self._refresh_tool_list(select=name)
        self._on_tool_selected(self._tool_list.currentRow())

    def _on_tool_export(self) -> None:
        import yaml
        path, _ = QFileDialog.getSaveFileName(
            self, "Export tool library", "tools.tools",
            "Tool library (*.tools *.yaml);;All files (*)")
        if not path:
            return
        data = {n: s.to_yaml() for n, s in self._tool_working.items()}
        try:
            Path(path).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        except Exception:
            QMessageBox.warning(self, "Export failed", "Could not write the library file.")

    def _on_tool_import(self) -> None:
        import yaml
        from guildcam.core.cam.tooling import ToolSpec
        path, _ = QFileDialog.getOpenFileName(
            self, "Import tool library", "",
            "Tool library (*.tools *.yaml);;All files (*)")
        if not path:
            return
        try:
            incoming = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except Exception:
            QMessageBox.warning(self, "Import failed", "Could not read the library file.")
            return
        n = 0
        for name, vals in (incoming.items() if isinstance(incoming, dict) else ()):
            if not isinstance(vals, dict) or vals.get("_deleted"):
                continue
            self._tool_working[name] = ToolSpec.from_dict(vals)
            n += 1
        self._refresh_tool_list()
        QMessageBox.information(self, "Import tools",
                               f"Imported {n} tool(s). Click OK to keep them.")

    def _save_tools(self) -> None:
        """Commit the staged tool library to the user overrides (BUILDPLAN M7.8):
        write entries that differ from shipped, drop those that match (reset),
        tombstone shipped tools the user removed, omit deleted custom tools."""
        from guildcam.gui import tool_store
        from guildcam.core.cam.tooling import ToolSpec
        shipped = tool_store.shipped()
        new_user: dict = {}
        for name, spec in getattr(self, "_tool_working", {}).items():
            target = spec.to_yaml()
            if name in shipped:
                if target != ToolSpec.from_dict(shipped[name]).to_yaml():
                    new_user[name] = target
            else:
                new_user[name] = target
        for name in shipped:
            if name not in self._tool_working:
                new_user[name] = {"_deleted": True}
        tool_store.replace_user(new_user)

    def _accept(self) -> None:
        self._save_materials()
        self._save_tools()
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

        # The component notebook (BUILDPLAN M7.3): a project is N role-typed
        # components, one active at a time. The `self._*` geometry/artifacts below
        # mirror `self._workspaces[self._active_ws]`; a component-tab switch swaps
        # them, so the build/generate/simulate code operates on the active
        # component transparently. A plain DXF import is a one-component project.
        self._workspaces: list[ComponentWorkspace] = []
        self._active_ws = -1

        # The interactive worktable bed (BUILDPLAN M7.4): a peer tab after the
        # components. `None` until first shown, then the default Guild fixture or
        # an imported bed DXF; persisted with the project.
        self._worktable = None
        self._worktable_tab_index = -1
        self._nest = None                 # core.cam.layout.BedNest (M7.6) once nested
        self._nest_specs = None           # build specs behind the nest (M7.7 bed sim)
        self._nest_thread = None
        self._nest_worker = None

        # Active component's geometry (mirrors the active workspace)
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None
        self._partition = None
        self._hinge_polys = []
        self._engraving_curves = []      # ENGRAVING layer polylines (M6.3 temples)
        self._is_temple = False          # outline + no lenses => temple component

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

        # The last component view (0 = 2D, 1 = 3D, 2 = Sim) — persisted across
        # component-tab switches so the chosen view follows you between components
        # (the Worktable page is excluded). Build 3D builds *every* loaded component
        # in one background worker (MultiMeshWorker).
        self._last_component_view = 0
        self._active_core_guide = None

        # Debounce for live parametric rebuilds (every spinbox tick would
        # otherwise queue a ~2 s build)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(350)
        self._rebuild_timer.timeout.connect(
            lambda: self._start_mesh_build(show_progress=False)
        )

        # Connect signals LAST: _connect_signals() restores the persisted material /
        # CAM params, which fires cam_changed → handlers that read the geometry state
        # above. Connecting earlier crashed at startup ('_is_temple' not yet set).
        self._connect_signals()

    # ------------------------------------------------------------------ theme

    def _apply_dark_mode(self, dark: bool) -> None:
        """Restyle every surface live (mirrors GuildDraw's _toggle_dark_mode)."""
        self._dark_mode = dark
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(dark))
        self.canvas.set_dark_mode(dark)
        self.view3d.set_dark_mode(dark)
        self.bed_canvas.set_dark_mode(dark)
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
        # The drawn toolpaths no longer match the design — clear the overlay (M7.11).
        if getattr(self, "_toolpath_table", None) is not None:
            self._clear_toolpath_overlay()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        # Center: a stacked 2D canvas / unified 3D viewer / worktable. The 3D model
        # preview and the cut sim share ONE VTK window (Viewer3D, model|sim modes)
        # so toggling between them never hides a render window — the dual-context
        # corruption is gone (BUILDPLAN M7 VTK-context fix). Camera presets + stage
        # stepper live on the viewer's own strip.
        self.stack = QStackedWidget()
        self.canvas = DxfCanvas()
        self.view3d = Viewer3D()
        self.stack.addWidget(self.canvas)        # 0 — 2D outline
        self.stack.addWidget(self.view3d)        # 1 — 3D model + cut sim (one VTK window)
        # 2 — the interactive worktable bed (BUILDPLAN M7.4)
        self._worktable_page_index = self.stack.addWidget(self._build_worktable_page())

        # Component notebook (M7.3): a tab bar over the shared view stack — one tab
        # per component (Frame Front / Temple R / Temple L / Base Curve R / L).
        # Hidden until a component is loaded; a plain DXF shows a single tab.
        self.component_tabs = QTabBar()
        self.component_tabs.setObjectName("componentTabs")
        self.component_tabs.setExpanding(False)
        self.component_tabs.setDrawBase(True)
        self.component_tabs.setVisible(False)
        self.component_tabs.currentChanged.connect(self._on_component_tab_changed)

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.component_tabs)
        cv.addWidget(self.stack, 1)
        self.setCentralWidget(central)

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

        # Bottom dock: per-op toolpath inspector (M7.11), tabbed with the log.
        self._toolpath_table = QTableWidget(0, 5)
        self._toolpath_table.setHorizontalHeaderLabels(
            ["Op", "Tool", "Z floor", "Length", "Est. time"])
        self._toolpath_table.verticalHeader().setVisible(False)
        self._toolpath_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._toolpath_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._toolpath_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._toolpath_table.itemChanged.connect(self._on_toolpath_item_changed)
        self._toolpath_table.itemSelectionChanged.connect(self._on_toolpath_selection)
        self._toolpath_dock = QDockWidget("Toolpaths", self)
        self._toolpath_dock.setObjectName("toolpathDock")
        self._toolpath_dock.setWidget(self._toolpath_table)
        self._toolpath_dock.setMinimumHeight(120)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._toolpath_dock)
        self.tabifyDockWidget(self._log_dock, self._toolpath_dock)
        self._toolpath_dock.setVisible(False)

        # Status bar: transient message (left) + zoom read-out (permanent right)
        sb = QStatusBar()
        self.status_lbl = QLabel("Ready — open a GuildDraw drawing (.gdraw) or a DXF to begin")
        sb.addWidget(self.status_lbl)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("mutedSmallLabel")
        sb.addPermanentWidget(self.zoom_label)
        # Readiness traffic-light (M5.2): rightmost corner of the status bar.
        self.readiness = ReadinessDot()
        sb.addPermanentWidget(self.readiness)
        self.setStatusBar(sb)

    # -------------------------------------------------------- worktable (M7.4)

    def _build_worktable_page(self) -> QWidget:
        """The Worktable bed page: a machine-coords canvas + a tagging panel.

        Import a bed DXF (or load the Guild fixture), click each region, and tag
        its role — frame-front / temple R-L / base-curve R-L / keep-out. The bed
        is the `Worktable` model that supersedes the named fixture (BUILDPLAN M7.4).
        """
        from guildcam.gui.widgets.bed_canvas import BedCanvas
        from guildcam.core.project.schema import BedRole, bed_role_label

        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.bed_canvas = BedCanvas()
        self.bed_canvas.region_clicked.connect(self._on_bed_region_clicked)
        self.bed_canvas.component_nudged.connect(self._on_component_nudged)
        h.addWidget(self.bed_canvas, 1)

        panel = QWidget()
        panel.setObjectName("worktablePanel")
        panel.setFixedWidth(252)
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        title = QLabel("Worktable")
        title.setObjectName("sectionTitle")
        v.addWidget(title)
        desc = QLabel("Import a bed DXF, then click each region and tag its role. "
                      "Keep-outs are hold-downs the cutter must avoid.")
        desc.setWordWrap(True)
        desc.setObjectName("mutedSmallLabel")
        v.addWidget(desc)

        self._bed_import_btn = QPushButton("Import Bed DXF…")
        self._bed_import_btn.clicked.connect(self._on_import_bed)
        self._bed_default_btn = QPushButton("Load Guild Bed")
        self._bed_default_btn.clicked.connect(self._on_load_default_bed)
        self._bed_save_btn = QPushButton("Save Bed…")
        self._bed_save_btn.clicked.connect(self._on_save_bed)
        v.addWidget(self._bed_import_btn)
        v.addWidget(self._bed_default_btn)
        v.addWidget(self._bed_save_btn)

        v.addSpacing(6)
        v.addWidget(QLabel("Selected region role:"))
        self._bed_role_combo = QComboBox()
        for role in BedRole:
            self._bed_role_combo.addItem(bed_role_label(role), role.value)
        self._bed_role_combo.setEnabled(False)
        self._bed_role_combo.currentIndexChanged.connect(self._on_bed_role_changed)
        v.addWidget(self._bed_role_combo)

        self._bed_region_list = QListWidget()
        self._bed_region_list.currentRowChanged.connect(self._on_bed_list_row)
        v.addWidget(self._bed_region_list, 1)

        self._bed_counts = QLabel("No bed loaded")
        self._bed_counts.setObjectName("mutedSmallLabel")
        self._bed_counts.setWordWrap(True)
        v.addWidget(self._bed_counts)

        v.addSpacing(6)
        self._bed_nest_btn = QPushButton("Nest Components")
        self._bed_nest_btn.setToolTip(
            "Auto-place every built component on a zone whose role matches its kind, "
            "then drag a footprint to nudge it. Keep-out collisions flag in red.")
        self._bed_nest_btn.clicked.connect(self._on_nest_components)
        v.addWidget(self._bed_nest_btn)
        self._bed_nest_status = QLabel("")
        self._bed_nest_status.setObjectName("mutedSmallLabel")
        self._bed_nest_status.setWordWrap(True)
        v.addWidget(self._bed_nest_status)

        self._bed_gen_btn = QPushButton("Generate Worktable Program")
        self._bed_gen_btn.setToolTip(
            "Post the whole nested bed as one worktable.nc — every placed component, "
            "scheduled to minimise tool changes, linted and clearance-checked. "
            "Stored in the project (Save / Ctrl+S); per-component tabs still Generate "
            "each part on its own.")
        self._bed_gen_btn.setEnabled(False)
        self._bed_gen_btn.clicked.connect(self._on_generate_worktable_nest)
        v.addWidget(self._bed_gen_btn)

        self._bed_sim_btn = QPushButton("Simulate Bed")
        self._bed_sim_btn.setToolTip(
            "Simulate the whole nested bed's machined result and flag uncut / gouged "
            "regions across every component (shown in the 3D cut-sim view).")
        self._bed_sim_btn.setEnabled(False)
        self._bed_sim_btn.clicked.connect(self._on_simulate_bed)
        v.addWidget(self._bed_sim_btn)

        h.addWidget(panel)
        return page

    def _ensure_worktable(self):
        """The active bed, defaulting to the built-in Guild fixture (M7.4)."""
        if self._worktable is None:
            from guildcam.core.cam.worktable import default_worktable
            try:
                self._worktable = default_worktable()
            except Exception:
                self.append_log("[worktable] could not load the default Guild bed:\n"
                                + traceback.format_exc())
                from guildcam.core.project.schema import Worktable
                self._worktable = Worktable()
        return self._worktable

    def _activate_worktable_tab(self) -> None:
        """Show the bed page (stack index 3) and the worktable controls."""
        if 0 <= self._active_ws < len(self._workspaces):
            self._sync_active_workspace()        # persist the component we leave
        self._ensure_worktable()
        self.bed_canvas.set_worktable(self._worktable)
        self._refresh_worktable_panel()
        if self._nest is not None:                 # re-show a prior nest (M7.6)
            self._refresh_nest_render()
        self.stack.setCurrentIndex(self._worktable_page_index)
        self._right_dock.setVisible(False)        # the bed has its own side panel
        self.zoom_label.setVisible(False)
        self._act_view2d.setChecked(False)
        self._act_view3d.setChecked(False)
        self.status_lbl.setText(f"Worktable — {self._worktable.display_name}")

    def _on_show_worktable(self) -> None:
        """Jump to the Worktable tab (toolbar / View menu)."""
        if self._worktable_tab_index < 0 or self.component_tabs.count() == 0:
            self._populate_component_tabs()        # a bar with just the Worktable tab
        self.component_tabs.blockSignals(True)
        self.component_tabs.setCurrentIndex(self._worktable_tab_index)
        self.component_tabs.blockSignals(False)
        self._activate_worktable_tab()

    # ---- bed loading -------------------------------------------------------

    def _on_import_bed(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import bed DXF", self._prefs.get("last_output_dir") or "",
            "DXF files (*.dxf);;All files (*)")
        if not path_str:
            return
        from guildcam.core.cam.worktable import WorktableError, build_worktable_from_dxf
        try:
            wt = build_worktable_from_dxf(Path(path_str))
        except WorktableError as exc:
            QMessageBox.warning(self, "Import bed failed", str(exc))
            return
        except Exception:
            self.append_log("[worktable] import failed:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Import bed failed", "See the log for details.")
            return
        self._worktable = wt
        self._clear_nest()                 # a new bed invalidates any prior nest
        self.bed_canvas.set_worktable(wt)
        self._refresh_worktable_panel()
        self.append_log(
            f"[worktable] {Path(path_str).name}: {len(wt.zones)} regions — "
            "click each and tag its role.")
        self.status_lbl.setText(
            f"Imported bed: {Path(path_str).name}  ({len(wt.zones)} regions)")

    def _on_load_default_bed(self) -> None:
        from guildcam.core.cam.worktable import default_worktable
        try:
            self._worktable = default_worktable()
        except Exception:
            self.append_log("[worktable] could not load the Guild bed:\n"
                            + traceback.format_exc())
            return
        self._clear_nest()
        self.bed_canvas.set_worktable(self._worktable)
        self._refresh_worktable_panel()
        self.status_lbl.setText("Loaded the Guild standard bed")

    # ---- nesting (BUILDPLAN M7.6) ------------------------------------------

    def _clear_nest(self) -> None:
        self._nest = None
        self._nest_specs = None
        if hasattr(self, "_bed_nest_status"):
            self._bed_nest_status.setText("")
        if hasattr(self, "_bed_gen_btn"):
            self._bed_gen_btn.setEnabled(False)
        if hasattr(self, "_bed_sim_btn"):
            self._bed_sim_btn.setEnabled(False)
        self.bed_canvas.clear_nest()

    def _on_nest_components(self) -> None:
        """Generate each built component's program and auto-place it on a role-
        matched zone of the tagged worktable (BUILDPLAN M7.6)."""
        self._ensure_worktable()
        if not self._worktable.placement_zones():
            QMessageBox.information(
                self, "No placement zones",
                "Tag at least one zone with a component role (frame-front, temple, "
                "base-curve) before nesting. Keep-outs alone hold nothing.")
            return
        targets = self._buildable_workspaces()
        if not targets:
            QMessageBox.information(
                self, "Nothing to nest",
                "Open a drawing (or a matched frame) so there are built components "
                "to place on the bed.")
            return
        if self._nest_thread is not None and self._nest_thread.isRunning():
            return
        self._sync_active_workspace()        # capture the active component's dock edits
        specs = [self._build_spec(i) for i in targets]
        self._nest_specs = specs             # kept for the whole-bed sim (M7.7)
        self._bed_nest_btn.setEnabled(False)
        self._bed_nest_status.setText("Nesting…")
        self.append_log(f"[nest] Nesting {len(specs)} component(s) onto "
                        f"{self._worktable.display_name}…")

        res = max(0.4, self._prefs["preview_resolution_mm"])
        self._nest_worker = NestWorker(
            specs, self._worktable,
            cam_params=self.params.cam_params(), resolution=res)
        self._nest_thread = QThread()
        self._nest_worker.moveToThread(self._nest_thread)
        self._nest_thread.started.connect(self._nest_worker.run)
        self._nest_worker.progress.connect(self.append_log)
        self._nest_worker.finished.connect(self._on_nest_finished)
        self._nest_worker.error.connect(self._on_nest_error)
        self._nest_worker.cancelled.connect(self._on_nest_cancelled)
        self._nest_worker.finished.connect(self._nest_thread.quit)
        self._nest_worker.error.connect(self._nest_thread.quit)
        self._nest_worker.cancelled.connect(self._nest_thread.quit)
        dlg = self._open_progress("Nesting components")
        self._nest_worker.stage.connect(self._on_stage)
        dlg.canceled.connect(self._nest_worker.cancel)
        self._nest_thread.start()

    def _on_nest_finished(self, nest) -> None:
        self._close_progress()
        self._nest = nest
        self._bed_nest_btn.setEnabled(True)
        if nest.unplaced:
            for p in nest.unplaced:
                self.append_log(f"[nest]   {p.label}: no free {p.kind} zone — unplaced")
        self._refresh_nest_render()

    def _on_nest_error(self, tb: str) -> None:
        self._close_progress()
        self._bed_nest_btn.setEnabled(True)
        self._bed_nest_status.setText("Nesting failed — see log")
        self.append_log("[nest ERROR]\n" + tb)

    def _on_nest_cancelled(self) -> None:
        self._close_progress()
        self._bed_nest_btn.setEnabled(True)
        self._bed_nest_status.setText("Nesting cancelled")
        self.append_log("[nest] Cancelled.")

    def _refresh_nest_render(self) -> None:
        """Build the bed-canvas footprints from the current nest, flag keep-out
        collisions per placement (live after a nudge), and update the badge."""
        from guildcam.core.cam.layout import worktable_clearance_violations
        if self._nest is None:
            return
        dicts: list[dict] = []
        all_viol: list[str] = []
        for pl in self._nest.placements:
            viol = worktable_clearance_violations(
                pl.ops, self._worktable, skip_op_names=pl.drill_names)
            all_viol += viol
            names = pl.contour_names | pl.drill_names
            paths = [[(x, y) for x, y, *_ in path]
                     for op in pl.ops if op.name in names for path in op.paths]
            dicts.append({"zone_id": pl.zone_id, "role": pl.role, "label": pl.label,
                          "paths": paths, "violated": bool(viol)})
        self.bed_canvas.set_nest(dicts)
        for v in all_viol:
            self.append_log(f"[nest] ⚠ {v}")
        n = len(self._nest.placements)
        bits = [f"{n} placed"]
        if self._nest.unplaced:
            bits.append(f"{len(self._nest.unplaced)} unplaced")
        bits.append("clear" if not all_viol else f"{len(all_viol)} collision(s)")
        self._bed_nest_status.setText("Nested: " + " · ".join(bits)
                                      + ".  Drag a footprint to nudge it.")
        self._bed_gen_btn.setEnabled(bool(self._nest.placements))
        self._bed_sim_btn.setEnabled(bool(self._nest.placements))
        self.status_lbl.setText(
            "Bed nested — " + ("all clear" if not all_viol
                               else f"{len(all_viol)} keep-out collision(s)"))

    def _on_component_nudged(self, zone_id: str, dx: float, dy: float) -> None:
        """A footprint was dragged on the bed — shift its placement and re-check
        clearance without regenerating any program (BUILDPLAN M7.6)."""
        if self._nest is None:
            return
        for pl in self._nest.placements:
            if pl.zone_id == zone_id:
                pl.nudge(dx, dy)
                break
        self._refresh_nest_render()

    def _bed_safe_z(self, cam) -> float:
        """Safe rapid height above the tallest stock on the bed."""
        tops: list[float] = []
        for pl in self._nest.placements:
            z = self._worktable.zone(pl.zone_id) if self._worktable else None
            if z is not None and z.stock_thickness_mm:
                tops.append(float(z.stock_thickness_mm))
        return (max(tops) if tops else 12.0) + cam.safe_z_clearance_mm

    def _on_generate_worktable_nest(self) -> None:
        """Post the whole nested bed as one ``worktable.nc`` (BUILDPLAN M7.7).

        Generalises the M6.5 fixture worktable onto the user-tagged ``Worktable`` +
        the multi-component nest (M7.6): one combined, tool-change-minimised program,
        linted + keep-out-clearance-checked + cut-timed over the whole bed, stored in
        the project. The component programs were already generated by Nest Components,
        so this is a fast post (no relief rebuild). Per-component tabs still Generate
        each part on its own — this is the bed-wide output."""
        if self._nest is None or not self._nest.placements:
            QMessageBox.information(
                self, "Nest first",
                "Click Nest Components to place the model on the bed, then generate "
                "the worktable program.")
            return
        import yaml
        from guildcam.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, op_summaries, write_castle_program,
        )
        from guildcam.core.cam.cuttime import (
            MachineDynamics, estimate_program, format_report,
        )
        from guildcam.core.cam.layout import (
            build_nest_program, worktable_clearance_violations,
        )
        from guildcam.core.post.grbl import GRBLPost
        from guildcam.core.post.machine import lint_program, load_machine_profile

        try:
            cam = self.params.cam_params() or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            machine = load_machine_profile(cam.machine_name, config_dir)
            mat_name = self.params.material_name()
            mat = mats_cfg.get(mat_name.split()[0].lower(), mats_cfg["acetate"])

            bed = build_nest_program(self._nest)
            if not bed.ops:
                QMessageBox.information(self, "Nothing to cut",
                                       "The nested components produced no toolpaths.")
                return
            self.append_log(
                f"[gcode] Worktable: {len(bed.placements)} part(s), {len(bed.ops)} ops, "
                f"{bed.n_tool_changes} tool change(s) (grouped by tool).")

            tool_settings, ts_warns = build_tool_settings(
                bed.ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
                default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"],
                machine=machine)
            for w in ts_warns:
                self.append_log(f"[gcode] tool: {w}")

            violations = worktable_clearance_violations(
                bed.ops, self._worktable, skip_op_names=bed.drill_op_names)
            for vmsg in violations:
                self.append_log(f"[gcode] WARNING: {vmsg}")

            first_ts = tool_settings[bed.ops[0].tool_name]
            post = GRBLPost(
                job_name="worktable", material=mat_name,
                tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
                feed_rate_mmpm=first_ts.feed_rate_mmpm,
                plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
                safe_z_mm=self._bed_safe_z(cam))
            write_castle_program(
                bed.ops, post, side="Worktable", arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
                contour_op_names=bed.contour_op_names, drill_op_names=bed.drill_op_names)
            text = post.to_string()

            machine_warnings = lint_program(text, machine)
            for w in machine_warnings:
                self.append_log(f"[gcode] ⚠ machine: {w}")
            report = estimate_program(text, MachineDynamics.from_profile(machine),
                                      tool_change_seconds=machine.tool_change_seconds)
            self.append_log("[gcode] Estimated cut time —\n" + format_report(report))
            rows = op_summaries(bed.ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)
        except Exception:
            self.append_log("[gcode ERROR]\n" + traceback.format_exc())
            QMessageBox.critical(self, "Worktable program failed",
                                 "Could not post the worktable program — see the log.")
            return

        self._last_programs = {"worktable.nc": text}
        self._last_machine = machine.model_dump()
        self._last_report = None
        self._last_setup = {
            "component": "worktable",
            "material": mat_name,
            "machine": machine.display_name,
            "parts": [
                {"label": pl.label, "kind": pl.kind, "zone": pl.zone_id,
                 "x_mm": pl.dx, "y_mm": pl.dy, "rotation_deg": pl.rotation_deg}
                for pl in bed.placements],
            "tools": [
                {"number": s.number, "name": n, "diameter_mm": s.diameter_mm,
                 "spindle_rpm": s.spindle_rpm, "feed_rate_mmpm": s.feed_rate_mmpm}
                for n, s in tool_settings.items()],
            "n_tool_changes": report.n_tool_changes,
            "est_total_min": round(report.total_seconds / 60, 2),
            "ops": rows,
        }
        self._act_export_nc.setEnabled(True)
        self.append_log(f"[gcode] worktable.nc generated ({len(text):,} bytes).")

        summary = (f"Worktable program generated — {len(bed.placements)} part(s), "
                   f"{len(tool_settings)} tool(s), {report.n_tool_changes} change(s), "
                   f"{report.total_seconds / 60:.1f} min incl. changes.\n\n"
                   "Stored in the project (Ctrl+S to save) or File ▸ Export G-code "
                   "for a standalone .nc.")
        warn_bits = []
        if self._nest.unplaced:
            warn_bits.append(f"{len(self._nest.unplaced)} component(s) unplaced")
        if violations:
            warn_bits.append(f"{len(violations)} clearance warning(s)")
        if machine_warnings:
            warn_bits.append(f"{len(machine_warnings)} machine warning(s)")
        if warn_bits:
            summary += "\n\n⚠ " + " · ".join(warn_bits) + " — see log."

        # Fold straight into an open single-DXF project; a full multi-component
        # model has no embedded source DXF yet (M7.x .gcam tree), so it is kept in
        # memory and exported / saved explicitly.
        if self._project_path is not None and self._source_dxf_bytes is not None:
            self._save_gcam_to(self._project_path, announce=False)
            self.append_log(
                f"[project] Updated {self._project_path.name} with the worktable program.")
        self.status_lbl.setText("Worktable G-code ready")
        QMessageBox.information(self, "Worktable program", summary)

    def _on_simulate_bed(self) -> None:
        """Simulate the whole nested bed and show the cut result in the 3D cut-sim
        view (BUILDPLAN M7.7). Reuses the per-component sim per placement, composited
        onto one machine-coords bed grid."""
        if self._nest is None or not self._nest.placements or not self._nest_specs:
            QMessageBox.information(
                self, "Nest first",
                "Click Nest Components to place the model on the bed, then simulate it.")
            return
        if self._sim_thread is not None and self._sim_thread.isRunning():
            return
        self.status_lbl.setText("Simulating bed…")
        self._bed_sim_btn.setEnabled(False)
        self.append_log("[bed-sim] Simulating the whole nested bed…")
        self._switch_view(2)                 # show the 3D cut-sim viewer

        res = max(0.4, self._prefs["preview_resolution_mm"])
        self._sim_worker = BedSimWorker(
            self._nest_specs, self._nest.placements,
            (self._worktable.work_area_width_mm, self._worktable.work_area_height_mm),
            cam_params=self.params.cam_params(), material_name=self.params.material_name(),
            resolution=res)
        self._sim_thread = QThread()
        self._sim_worker.moveToThread(self._sim_thread)
        self._sim_thread.started.connect(self._sim_worker.run)
        self._sim_worker.progress.connect(self.append_log)
        self._sim_worker.finished.connect(self._on_sim_bed_finished)
        self._sim_worker.error.connect(self._on_sim_bed_error)
        self._sim_worker.cancelled.connect(self._on_sim_bed_cancelled)
        self._sim_worker.finished.connect(self._sim_thread.quit)
        self._sim_worker.error.connect(self._sim_thread.quit)
        self._sim_worker.cancelled.connect(self._sim_thread.quit)
        dlg = self._open_progress("Simulating bed")
        self._sim_worker.stage.connect(self._on_stage)
        dlg.canceled.connect(self._sim_worker.cancel)
        self._sim_thread.start()

    def _on_sim_bed_finished(self, report, lines) -> None:
        self._close_progress()
        self.view3d.show_report(report)
        self._switch_view(2)
        for line in lines:
            self.append_log("[bed-sim] " + line)
        self.status_lbl.setText({
            "ok": "Bed verified — every component reached",
            "warn": "Bed simulated — review the flagged regions",
            "fail": "Bed incomplete — see the flagged regions",
        }.get(report.status(), "Bed simulated"))
        self._bed_sim_btn.setEnabled(True)

    def _on_sim_bed_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[bed-sim ERROR]\n" + tb)
        self.status_lbl.setText("Bed simulation failed — see log")
        self._bed_sim_btn.setEnabled(True)

    def _on_sim_bed_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[bed-sim] Cancelled.")
        self.status_lbl.setText("Bed simulation cancelled")
        self._bed_sim_btn.setEnabled(True)

    def _on_save_bed(self) -> None:
        if self._worktable is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save worktable", "worktable.bed",
            "Bed files (*.bed);;All files (*)")
        if not path_str:
            return
        from guildcam.core.cam.worktable import save_bed
        try:
            save_bed(self._worktable, Path(path_str))
        except Exception:
            self.append_log("[worktable] save failed:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Save bed failed", "See the log for details.")
            return
        self.append_log(f"[worktable] saved {Path(path_str).name}")
        self.status_lbl.setText(f"Saved bed: {Path(path_str).name}")

    # ---- tagging -----------------------------------------------------------

    def _on_bed_region_clicked(self, zone_id: str) -> None:
        self._select_bed_region(zone_id or None)

    def _on_bed_list_row(self, row: int) -> None:
        if row < 0:
            return
        item = self._bed_region_list.item(row)
        if item is not None:
            self._select_bed_region(item.data(Qt.ItemDataRole.UserRole))

    def _select_bed_region(self, zone_id) -> None:
        from guildcam.core.project.schema import BedRole, bed_role_label
        self.bed_canvas.set_selected(zone_id)
        self._bed_region_list.blockSignals(True)
        matched = False
        for i in range(self._bed_region_list.count()):
            it = self._bed_region_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == zone_id:
                self._bed_region_list.setCurrentRow(i)
                matched = True
                break
        if not matched:
            self._bed_region_list.clearSelection()
        self._bed_region_list.blockSignals(False)

        self._bed_role_combo.setEnabled(zone_id is not None)
        if zone_id is not None and self._worktable is not None:
            z = self._worktable.zone(zone_id)
            self._bed_role_combo.blockSignals(True)
            idx = self._bed_role_combo.findData(BedRole(z.role).value)
            if idx >= 0:
                self._bed_role_combo.setCurrentIndex(idx)
            self._bed_role_combo.blockSignals(False)
            self.status_lbl.setText(f"Region {zone_id}: {bed_role_label(z.role)}")

    def _on_bed_role_changed(self, idx: int) -> None:
        from guildcam.core.project.schema import BedRole, bed_role_label
        zid = self.bed_canvas.selected_id()
        if zid is None or self._worktable is None or idx < 0:
            return
        role = self._bed_role_combo.itemData(idx)
        z = self._worktable.set_role(zid, BedRole(role))
        self.bed_canvas.refresh(self._worktable)
        self._refresh_worktable_panel(keep_selection=zid)
        self.append_log(f"[worktable] {zid} → {bed_role_label(z.role)}")

    def _refresh_worktable_panel(self, keep_selection=None) -> None:
        from guildcam.core.project.schema import bed_role_label
        wt = self._worktable
        self._bed_region_list.blockSignals(True)
        self._bed_region_list.clear()
        if wt is not None:
            for z in wt.zones:
                it = QListWidgetItem(f"{z.label or z.id}  ·  {bed_role_label(z.role)}")
                it.setData(Qt.ItemDataRole.UserRole, z.id)
                self._bed_region_list.addItem(it)
        self._bed_region_list.blockSignals(False)

        for btn in (self._bed_save_btn,):
            btn.setEnabled(wt is not None)
        if wt is not None:
            self._bed_counts.setText(
                f"{len(wt.zones)} regions · {len(wt.placement_zones())} tagged · "
                f"{len(wt.keep_outs())} keep-out · {len(wt.untagged())} untagged")
        else:
            self._bed_counts.setText("No bed loaded")

        sel = keep_selection or self.bed_canvas.selected_id()
        if wt is not None and sel and sel in {z.id for z in wt.zones}:
            self._select_bed_region(sel)

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

        self._act_open_model = QAction("Open Drawing…", self)
        self._act_open_model.setShortcut("Ctrl+Shift+O")
        self._act_open_model.setToolTip(
            "Open a GuildDraw drawing (.gdraw) — frame front + temples + base-curve "
            "templates load as separate component tabs  (Ctrl+Shift+O)")
        self._act_open_model.triggered.connect(self._on_open_model)

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

        self._act_block = QAction("Generate Base-Curve Block", self)
        self._act_block.setToolTip(
            "Generate the heat-forming block from the frame's lens interior "
            "(acetal blank + 3 M4 mounting holes)")
        self._act_block.setEnabled(False)
        self._act_block.triggered.connect(self._on_generate_block)

        self._act_worktable = QAction("Generate Worktable Program", self)
        self._act_worktable.setToolTip(
            "Cut the frame front and its base-curve block in one program, "
            "auto-packed onto the bed and grouped to minimise tool changes")
        self._act_worktable.setEnabled(False)
        self._act_worktable.triggered.connect(self._on_generate_worktable)

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

        self._act_show_worktable = QAction("Worktable", self)
        self._act_show_worktable.setShortcut("Ctrl+B")
        self._act_show_worktable.setToolTip(
            "Open the worktable bed — import a bed DXF and tag role zones + "
            "keep-outs  (Ctrl+B)")
        self._act_show_worktable.triggered.connect(self._on_show_worktable)

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

        self._act_toolpaths = QAction("Toolpaths", self, checkable=True)
        self._act_toolpaths.setToolTip(
            "Show/hide the toolpath inspector (per-op list + 2D overlay, M7.11)")
        self._act_toolpaths.toggled.connect(self._toolpath_dock.setVisible)
        self._toolpath_dock.visibilityChanged.connect(self._act_toolpaths.setChecked)

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
        tb.addAction(self._act_show_worktable)
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
            (self._act_show_worktable, "op-fit"),
            (self._act_fit, "op-fit"),
            (self._act_log, "toggle-log"),
            (self._act_sidebar, "view-sidebar"),
        ]

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        file_menu.addAction(self._act_open)
        file_menu.addAction(self._act_open_model)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(self._act_open_project)
        file_menu.addAction(self._act_save_project)
        file_menu.addSeparator()
        file_menu.addAction(self._act_build)
        file_menu.addAction(self._act_gcode)
        file_menu.addAction(self._act_block)
        file_menu.addAction(self._act_worktable)
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
        view_menu.addAction(self._act_show_worktable)
        view_menu.addAction(self._act_fit)
        view_menu.addSeparator()
        view_menu.addAction(self._act_sidebar)
        view_menu.addAction(self._act_log)
        view_menu.addAction(self._act_toolpaths)

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
        lower = path.lower()
        if lower.endswith(".gcam"):
            self._open_project(Path(path))
        elif lower.endswith((".gdraw", ".svg")):
            self._load_model(Path(path))
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
        proj.worktable = self._worktable          # the tagged bed, if any (M7.4)
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
        self._worktable = proj.worktable          # restore the tagged bed (M7.4)
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

        # The tool library may have changed (Preferences ▸ Tools) — refresh every
        # tool combo so new/edited tools appear without a restart (M7.8).
        self.params.refresh_tool_lists()

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
        self.view3d.stage_changed.connect(self._on_stage_changed)
        self.view3d.playback_step_changed.connect(self._on_playback_step)

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

    def _switch_view(self, view: int) -> None:
        """Show a component view: 0 = 2D outline, 1 = 3D model, 2 = cut sim.

        Views 1 and 2 are two MODES of the single Viewer3D (stack page 1) — one VTK
        window, never hidden when toggling between them (BUILDPLAN M7 VTK-context
        fix). The Worktable bed is shown separately via `_activate_worktable_tab`."""
        if view == 0:
            self.stack.setCurrentIndex(0)
        elif view == 1:
            self.stack.setCurrentIndex(1)
            self.view3d.set_mode("model")
        elif view == 2:
            self.stack.setCurrentIndex(1)
            self.view3d.set_mode("sim")
        else:
            return
        self._act_view2d.setChecked(view == 0)
        self._act_view3d.setChecked(view == 1)
        self.zoom_label.setVisible(view == 0)
        # Remember the component view so it follows tab switches.
        self._last_component_view = view

    # -------------------------------------------------------- active 3D preview

    def _active_is_flat(self) -> bool:
        """The active component is a flat part (temple / base-curve block)."""
        return self._is_temple or (self._outline_poly is None and self._lens_od is not None)

    def _active_mesh_key(self) -> str:
        """The active component's mesh cache key (its teaching stage, or 'flat')."""
        return "flat" if self._active_is_flat() else self._stage

    def _has_active_3d(self) -> bool:
        """True if the active component already has a built mesh to show."""
        return self._stage_cache.get(self._active_mesh_key()) is not None

    def _active_program_zero_3d(self):
        """(datum_xyz, stock) for the active part's G54 work-zero in the design
        frame — drives the 3D axis-triad marker — or (None, None)."""
        pz = self.params.cam_params().program_zero
        if self._active_is_flat():
            stock = self._flat_stock()
        elif self._outline_poly is not None:
            stock = self.params.castle_params().stock
        else:
            return None, None
        return pz.datum_world(stock), stock

    def _show_active_3d(self) -> None:
        """Show the active component's built mesh in the 3D preview (cached). Clears
        the view if nothing is built yet, so the 3D always reflects the active tab."""
        mesh = self._stage_cache.get(self._active_mesh_key())
        if mesh is None:
            self.view3d.clear()
            return
        zero, _ = self._active_program_zero_3d()
        if self._active_is_flat():
            self.view3d.show_mesh(mesh, stock=self._flat_stock(),
                                  core_guide=self._active_core_guide, program_zero=zero)
        else:
            self.view3d.show_mesh(mesh, stock=self.params.castle_params().stock,
                                  program_zero=zero)

    # -------------------------------------------------------- component notebook

    def _populate_component_tabs(self) -> None:
        """Rebuild the component tab bar from ``self._workspaces`` (M7.3), with a
        trailing **Worktable** tab — the interactive bed, a peer of the components
        (BUILDPLAN M7.4)."""
        tb = self.component_tabs
        tb.blockSignals(True)
        while tb.count():
            tb.removeTab(0)
        for ws in self._workspaces:
            idx = tb.addTab(ws.label)
            tb.setTabEnabled(idx, ws.enabled)
            if not ws.enabled:
                tb.setTabToolTip(idx, f"{ws.label}: not in this model")
        self._worktable_tab_index = tb.addTab("Worktable")
        tb.setTabToolTip(self._worktable_tab_index,
                         "The cutting bed — import a bed DXF, tag role zones + keep-outs")
        tb.blockSignals(False)
        tb.setVisible(True)

    def _on_component_tab_changed(self, index: int) -> None:
        if index == self._worktable_tab_index:
            self._activate_worktable_tab()
        elif 0 <= index < len(self._workspaces):
            self._activate_workspace(index)

    def _sync_active_workspace(self) -> None:
        """Persist the active component's mutable artifacts (mesh / programs /
        readiness — written by the workers onto ``self._*``) back into its
        workspace before switching away."""
        i = self._active_ws
        if not (0 <= i < len(self._workspaces)):
            return
        from guildcam.core.project.schema import ComponentKind
        ws = self._workspaces[i]
        ws.stage = self._stage
        ws.stage_cache = self._stage_cache
        ws.mesh_built = self._mesh_built
        ws.core_guide = self._active_core_guide
        ws.last_programs = self._last_programs
        ws.last_setup = self._last_setup
        ws.last_machine = self._last_machine
        ws.last_report = self._last_report
        ws.program_stored = self._program_stored
        # Capture this component's editable params from the kind-aware dock (M7.3).
        if ws.kind == ComponentKind.FRAME_FRONT:
            ws.castle_params = self.params.castle_params()
        elif ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
            ws.temple_params = self.params.temple_params()
        elif ws.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            ws.block_params = self.params.block_params()

    def _load_active_geometry(self, ws: ComponentWorkspace) -> None:
        """Point the active ``self._*`` working set at ``ws``."""
        self._outline_poly = ws.outline_poly
        self._lens_od = ws.lens_od
        self._lens_os = ws.lens_os
        self._partition = ws.partition
        self._hinge_polys = ws.hinge_polys
        self._engraving_curves = ws.engraving_curves
        self._is_temple = ws.is_temple
        self._stage = ws.stage
        self._stage_cache = ws.stage_cache
        self._mesh_built = ws.mesh_built
        self._active_core_guide = ws.core_guide
        self._last_programs = ws.last_programs
        self._last_setup = ws.last_setup
        self._last_machine = ws.last_machine
        self._last_report = ws.last_report
        self._program_stored = ws.program_stored

    def _apply_workspace_to_ui(self, ws: ComponentWorkspace) -> None:
        """Re-render the shared views + dock + actions for the active component."""
        from guildcam.core.project.schema import ComponentKind

        self._clear_toolpath_overlay()       # the overlay belonged to the old tab (M7.11)
        self.canvas.set_layers(ws.layers)
        non_empty = [k for k, v in ws.layers.items() if v]
        self.params.set_file(
            ws.label,
            "Layers: " + ", ".join(non_empty) if non_empty else "No recognised layers")
        self.params.set_zones(ws.partition)

        # Kind-aware param dock (M7.3): show this component's tabs and push its
        # stored params in (signals blocked so activation never triggers a
        # rebuild; a plain-DXF frame has None params → the dock is left as-is).
        self.params.set_component_kind(ws.kind)
        self.params.blockSignals(True)
        try:
            if ws.kind == ComponentKind.FRAME_FRONT and ws.castle_params is not None:
                self.params.set_castle_params(ws.castle_params)
            elif (ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)
                  and ws.temple_params is not None):
                self.params.set_temple_params(ws.temple_params)
            elif (ws.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT)
                  and ws.block_params is not None):
                self.params.set_block_params(ws.block_params)
        finally:
            self.params.blockSignals(False)
        self.view3d.set_stage_enabled(ws.matched)
        self.view3d.set_stage(ws.stage)

        has_outline = ws.outline_poly is not None
        # Build 3D: a matched frame castle, or a flat part — a temple (outline) or
        # a base-curve block (its lens) — via the flat-extrusion mesher (M7).
        flat_buildable = ws.is_temple or (ws.outline_poly is None and ws.lens_od is not None)
        self._act_build.setEnabled(ws.matched or flat_buildable)
        self._act_export.setEnabled(ws.matched)
        # Cut simulation now runs on every component — a matched frame, a temple, or
        # a base-curve block (BUILDPLAN M7: machine sim on multiple components).
        self._act_simulate.setEnabled(ws.matched or flat_buildable)
        self._act_gcode.setEnabled(has_outline)          # frame castle or temple profile
        self._act_block.setEnabled(ws.lens_od is not None)
        self._act_worktable.setEnabled(ws.matched and ws.lens_od is not None)
        self._act_export_nc.setEnabled(bool(ws.last_programs))

        if ws.boxing is not None:
            b = ws.boxing
            self.params.update_boxing(b.a, b.b, b.dbl, b.ed)
        self._update_stock_canvas()
        # Persist the active view across the tab switch (M7 UX): keep the same
        # 2D/3D view and reflect THIS component in it. Fall back to 2D when the
        # chosen view has nothing to show for this component yet (its 3D not built;
        # the cut sim is run per-component on demand, not cached across tabs).
        view = self._last_component_view
        if view == 1 and not self._has_active_3d():
            view = 0
        elif view == 2:
            view = 0
        # Switch the view FIRST so the 3D widget is the current (sized, visible)
        # stack page before VTK renders into it — otherwise the framebuffer is
        # zero-size and the render fails ("FRAMEBUFFER_INCOMPLETE_ATTACHMENT").
        self._switch_view(view)
        if view == 1:
            self._show_active_3d()

    def _activate_workspace(self, index: int) -> None:
        """Make component ``index`` active: persist the current one, swap the
        working set, and re-render the shared views/dock/actions (M7.3)."""
        if not (0 <= index < len(self._workspaces)):
            return
        if 0 <= self._active_ws < len(self._workspaces) and self._active_ws != index:
            self._sync_active_workspace()
        self._active_ws = index
        ws = self._workspaces[index]
        self._load_active_geometry(ws)
        self._apply_workspace_to_ui(ws)
        # Leaving the Worktable tab → restore the params dock to the sidebar toggle.
        self._right_dock.setVisible(self._act_sidebar.isChecked())
        if self.component_tabs.currentIndex() != index:
            self.component_tabs.blockSignals(True)
            self.component_tabs.setCurrentIndex(index)
            self.component_tabs.blockSignals(False)
        self._refresh_readiness()

    # ------------------------------------------------------------------ DXF import

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open DXF file", "", "DXF files (*.dxf);;All files (*)",
        )
        if not path_str:
            return
        self._load_dxf(Path(path_str))

    def _on_open_model(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open GuildDraw drawing", self._prefs.get("last_output_dir") or "",
            "GuildDraw drawing (*.gdraw);;GuildDraw SVG (*.svg);;All files (*)")
        if path_str:
            self._load_model(Path(path_str))

    def _load_model(self, path: Path) -> None:
        """Import a GuildDraw ``.gdraw`` as a multi-component project (M7.3): one
        workspace tab per component (frame front + temples + base-curve templates)."""
        from guildcam.core.io_import.gdraw import GdrawError
        self.status_lbl.setText(f"Loading {path.name}…")
        self.append_log(f"[model] {path.name}")
        try:
            workspaces, _active = build_workspaces_from_gdraw(path)
        except GdrawError as exc:
            self.append_log("[ERROR] Drawing import failed:\n" + str(exc))
            QMessageBox.critical(self, "Open Drawing failed", f"{path.name}:\n{exc}")
            return
        except Exception:
            self.append_log("[ERROR] Drawing import failed:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Open Drawing failed", "See log for details.")
            return
        if not workspaces:
            QMessageBox.warning(self, "Empty model", "No components found in this model.")
            return

        self._source_name = path.name
        # A whole-model .gcam (the components/<id>/ tree) is M7.6; for now per-
        # component Generate works in each tab, but Save Project stays frame-bound.
        self._source_dxf_bytes = None
        self._project_path = None
        self._workspaces = workspaces
        self._active_ws = -1
        self._populate_component_tabs()

        populated = [w.label for w in workspaces if w.enabled]
        self.append_log(
            f"[model] {len(workspaces)} components, {len(populated)} populated: "
            + ", ".join(populated))
        self._dxf_loaded = True
        self._activate_workspace(0)
        self.setWindowTitle(f"GuildCAM  —  {path.name}")
        self.status_lbl.setText(
            f"Loaded drawing: {path.name}  ({len(populated)} of {len(workspaces)} "
            f"components) — Build 3D to model them all")
        self._add_recent(str(path))

    def _load_dxf(self, path: Path, *, from_project: bool = False) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            return                            # an import is already in flight
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

    def _on_import_finished(
        self, layers: dict, boxing, raw_summary: dict, unrecognised: list
    ) -> None:
        from guildcam.core.project.schema import ComponentKind, component_label

        fname = self._import_worker.path.name if self._import_worker else "?"

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

        # A plain DXF is a one-component project: a frame front, or a temple when
        # it is an outline with no lenses (M6.3). The derived geometry + actions
        # are applied by _activate_workspace below (M7.3).
        ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="", layers=layers)
        derive_workspace(ws, boxing=boxing)
        if ws.is_temple:
            ws.kind = ComponentKind.TEMPLE_RIGHT
        ws.label = component_label(ws.kind)
        self._workspaces = [ws]
        self._active_ws = -1
        self._populate_component_tabs()

        if ws.is_temple:
            self.append_log(
                f"[temple] Temple component: outline + "
                f"{len(ws.engraving_curves)} engraving curve(s) — "
                f"engrave + profile program on Generate G-code."
            )
        if ws.partition is not None:
            layout = ("standard castle layout" if ws.matched
                      else "generic zones — castle relief needs the 5-cuts-per-side layout")
            self.append_log(
                f"[castle] {len(ws.partition.zones)} zones from "
                f"{len(layers.get('SCULPT', []))} SCULPT cuts ({layout})"
            )

        if boxing is not None:
            self.append_log(
                f"[boxing] A={boxing.a:.1f}  B={boxing.b:.1f}"
                f"  DBL={boxing.dbl:.1f}  ED={boxing.ed:.1f} mm"
            )
        else:
            self.append_log(
                f"[boxing] Skipped — {len(layers.get('LENS', []))} LENS curve(s) found, need ≥2."
            )

        curve_counts = {k: len(v) for k, v in layers.items() if v}
        if curve_counts:
            self.append_log(
                "[curves] " + "  ".join(f"{k}:{n}" for k, n in curve_counts.items())
            )

        self._dxf_loaded = True
        self._activate_workspace(0)
        self.status_lbl.setText(f"Loaded: {fname}")
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

    def _flat_build_mode(self) -> str | None:
        """Which flat-part 3D to build for the active component, or None for a
        castle frame front (BUILDPLAN M7 per-component 3D)."""
        if self._is_temple and self._outline_poly is not None:
            return "temple"
        if self._outline_poly is None and self._lens_od is not None:
            return "block"
        return None

    def _buildable_workspaces(self) -> list[int]:
        """Indices of every enabled component whose 3D can be built — a matched
        frame, a temple, or a base-curve block (BUILDPLAN M7 UX: Build 3D builds
        *all* loaded components, not just the active one)."""
        out: list[int] = []
        for i, ws in enumerate(self._workspaces):
            if not ws.enabled:
                continue
            if ws.matched or ws.is_temple or (ws.outline_poly is None and ws.lens_od is not None):
                out.append(i)
        return out

    def _on_build_3d(self) -> None:
        targets = self._buildable_workspaces()
        if not targets:
            self.append_log(
                "[3D] Nothing to build yet — a frame needs its SCULPT zone layout "
                "(5 section cuts per side); a drawing also builds its temples and "
                "base-curve blocks. Draw the zones in GuildDraw and re-export."
            )
            return
        self._build_all(targets)

    # ---- build every component (ONE worker, ONE thread) --------------------

    def _build_spec(self, i: int) -> dict:
        """A plain build description for component *i* (geometry + params), so the
        single MultiMeshWorker can build any component off-thread without touching
        the active working set."""
        ws = self._workspaces[i]
        kind = ws.kind.value
        if ws.matched:
            return {"index": i, "mode": "castle", "kind": kind, "label": ws.label,
                    "partition": ws.partition,
                    "castle": ws.castle_params or self.params.castle_params(),
                    "hinge": list(ws.hinge_polys), "stage": ws.stage}
        if ws.is_temple:
            return {"index": i, "mode": "temple", "kind": kind, "label": ws.label,
                    "outline": ws.outline_poly,
                    "temple": ws.temple_params or self.params.temple_params(),
                    "hinge": list(ws.hinge_polys),
                    "engraving": list(ws.engraving_curves)}
        return {"index": i, "mode": "block", "kind": kind, "label": ws.label,
                "lens": ws.lens_od,
                "block": ws.block_params or self.params.block_params()}

    def _build_all(self, targets: list[int]) -> None:
        """Build every target component's mesh in a single background thread."""
        if self._mesh_thread is not None and self._mesh_thread.isRunning():
            return                            # a build is already in flight
        self._sync_active_workspace()        # capture the active component's dock edits
        specs = [self._build_spec(i) for i in targets]
        n = len(specs)
        self._act_build.setEnabled(False)
        self._switch_view(1)
        self.append_log(f"[3D] Building {n} component model{'s' if n != 1 else ''}…")

        self._mesh_worker = MultiMeshWorker(specs, self._prefs["preview_resolution_mm"])
        self._mesh_thread = QThread()
        self._mesh_worker.moveToThread(self._mesh_thread)
        self._mesh_thread.started.connect(self._mesh_worker.run)
        self._mesh_worker.built.connect(self._on_multi_mesh_built)
        self._mesh_worker.finished.connect(self._on_multi_mesh_finished)
        self._mesh_worker.error.connect(self._on_multi_mesh_error)
        self._mesh_worker.cancelled.connect(self._on_multi_mesh_cancelled)
        self._mesh_worker.finished.connect(self._mesh_thread.quit)
        self._mesh_worker.error.connect(self._mesh_thread.quit)
        self._mesh_worker.cancelled.connect(self._mesh_thread.quit)
        self._mesh_worker.stage.connect(self._on_stage)
        dlg = self._open_progress("Building 3D models")
        dlg.canceled.connect(self._mesh_worker.cancel)
        self._mesh_thread.start()

    def _on_multi_mesh_built(self, i: int, mesh, core_guide) -> None:
        """One component's mesh is ready — cache it into that component (M7 UX)."""
        ws = self._workspaces[i]
        if ws.matched:
            ws.stage_cache[ws.stage] = mesh       # shared with self._stage_cache iff active
        else:
            ws.stage_cache["flat"] = mesh
            ws.core_guide = core_guide
            if i == self._active_ws:
                self._active_core_guide = core_guide
        ws.mesh_built = True
        self.append_log(f"[3D]   {ws.label}: {len(mesh.vertices):,} verts")

    def _on_multi_mesh_finished(self) -> None:
        self._close_progress()
        self._act_build.setEnabled(True)
        self._mesh_built = True
        self._show_active_3d()                    # show whichever component is active
        self._refresh_readiness()
        self.append_log("[3D] All component models built.")

    def _on_multi_mesh_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[3D ERROR]\n" + tb)
        self._act_build.setEnabled(True)
        self.status_lbl.setText("Build failed — see log")

    def _on_multi_mesh_cancelled(self) -> None:
        self._close_progress()
        self._act_build.setEnabled(True)
        self._show_active_3d()
        self.append_log("[3D] Build cancelled.")

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
        self._update_program_zero_marker()   # 2D datum marker may have moved
        # Live-update the 3D datum triad too (no camera reset) when viewing 3D.
        if self.stack.currentIndex() == 1:
            zero, stock_z = self._active_program_zero_3d()
            self.view3d.set_program_zero(zero, stock_z)
        try:
            self._prefs["cam_params"] = self.params.cam_params().model_dump()
            self._prefs["material_name"] = self.params.material_name()
            prefs_mod.save(self._prefs)
        except Exception:
            pass

    def _update_stock_canvas(self) -> None:
        # Flat parts (temple / base-curve block): a single-level blank framed around
        # the part (the temple's 170×30 blank, the block's 70×70 blank) — not the
        # frame's two-level stock (BUILDPLAN M7 UX fix).
        if self._active_is_flat():
            if self._is_temple:
                s = self.params.temple_params().stock()
                geom = self._outline_poly
            else:
                s = self.params.block_params().stock()
                geom = self._lens_od
            cx, cy = 0.0, 0.0
            if geom is not None:
                x0, y0, x1, y1 = geom.bounds
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            hl, hw = s.blank_length_mm / 2.0, s.blank_width_mm / 2.0
            self.canvas.set_stock([(cx - hl, cy - hw, cx + hl, cy + hw)])
            self._update_program_zero_marker()
            return
        if self._outline_poly is None:
            self.canvas.set_stock([])
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
        self._update_program_zero_marker()

    def _update_program_zero_marker(self) -> None:
        """Draw the G54 datum where posted (0,0) lands in the design frame
        (= -work_offset): the stock-box datum, or the design origin in fixture
        mode (BUILDPLAN M6.2). The marker is a frame concern — cleared for flat parts."""
        if self._active_is_flat() or self._outline_poly is None:
            self.canvas.set_program_zero(None)
            return
        s = self.params.castle_params().stock
        pz = self.params.cam_params().program_zero
        ox, oy, _ = pz.work_offset(s)
        label = "G54" if pz.mode == "stock_box" else "G54 (fixture)"
        self.canvas.set_program_zero((-ox, -oy), label)

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
        if self._mesh_thread is not None and self._mesh_thread.isRunning():
            return                            # don't spawn a second mesh thread
        mode = self._flat_build_mode()
        if mode is not None:
            self._start_flat_build(mode, show_progress)
            return
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

    def _flat_stock(self):
        """The single-level stock for the active flat part (temple / block)."""
        if self._is_temple:
            return self.params.temple_params().stock()
        return self.params.block_params().stock()

    def _start_flat_build(self, mode: str, show_progress: bool = False) -> None:
        """Build a temple / base-curve-block solid (BUILDPLAN M7 per-component 3D)."""
        self.status_lbl.setText("Building 3D model…")
        self._act_build.setEnabled(False)
        self.append_log(f"[3D] Building {mode}…")
        self._switch_view(1)
        res = self._prefs["preview_resolution_mm"]

        if mode == "temple":
            self._mesh_worker = FlatMeshWorker(
                "temple", outline=self._outline_poly,
                temple=self.params.temple_params(), hinge_polys=self._hinge_polys,
                engraving=self._engraving_curves, resolution=res)
        else:
            self._mesh_worker = FlatMeshWorker(
                "block", lens=self._lens_od, block=self.params.block_params(),
                resolution=res)

        self._mesh_thread = QThread()
        self._mesh_worker.moveToThread(self._mesh_thread)
        self._mesh_thread.started.connect(self._mesh_worker.run)
        self._mesh_worker.finished.connect(self._on_flat_mesh_finished)
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

    def _on_flat_mesh_finished(self, mesh, core_guide) -> None:
        self._close_progress()
        self._stage_cache["flat"] = mesh
        self._active_core_guide = core_guide
        zero, _ = self._active_program_zero_3d()
        self.view3d.show_mesh(mesh, stock=self._flat_stock(),
                              core_guide=core_guide, program_zero=zero)
        n_v, n_t = len(mesh.vertices), len(mesh.faces)
        self.status_lbl.setText(f"3D model ready — {n_v:,} verts · {n_t:,} tris")
        self.append_log(f"[3D] Done — {n_v:,} verts, {n_t:,} tris")
        self._act_build.setEnabled(True)
        self._mesh_built = True
        self._refresh_readiness()

    def _show_stage_mesh(self, mesh) -> None:
        zero, _ = self._active_program_zero_3d()
        self.view3d.show_mesh(mesh, stock=self.params.castle_params().stock,
                              program_zero=zero)
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
        if idx == self._worktable_page_index:
            self.bed_canvas.fit_to_view()
        elif idx == 0:
            self.canvas.fit_to_view()
        else:                                  # the unified 3D viewer (model or sim)
            self.view3d._cam_reset()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"Zoom: {scale:.1f} px/mm")

    # ------------------------------------------------------------------ cut simulation

    def _on_simulate(self) -> None:
        mode = self._flat_build_mode()
        if mode is None and not self._castle_ready():
            QMessageBox.warning(
                self, "Nothing to simulate",
                "Open a frame with matched SCULPT zones, a temple, or a base-curve "
                "block to simulate its cut.")
            return
        if self._sim_thread is not None and self._sim_thread.isRunning():
            return
        self.status_lbl.setText("Simulating cut…")
        self._act_simulate.setEnabled(False)
        self.append_log(f"[sim] Simulating the machined result ({mode or 'frame'})…")
        self._switch_view(2)

        res = self._prefs["preview_resolution_mm"]
        cam, mat = self.params.cam_params(), self.params.material_name()
        if mode == "temple":
            self._sim_worker = FlatSimWorker(
                "temple", outline=self._outline_poly, temple=self.params.temple_params(),
                hinge_polys=self._hinge_polys, engraving=self._engraving_curves,
                cam_params=cam, material_name=mat, resolution=res)
        elif mode == "block":
            self._sim_worker = FlatSimWorker(
                "block", lens=self._lens_od, block=self.params.block_params(),
                cam_params=cam, material_name=mat, resolution=res)
        else:
            self._sim_worker = SimWorker(
                self._partition, self.params.castle_params(), cam_params=cam,
                hinge_polys=self._hinge_polys, material_name=mat, resolution=res)
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

    def _on_sim_finished(self, report, lines, snaps=None) -> None:
        self._close_progress()
        self.view3d.show_report(report)
        self.view3d.set_playback(snaps or [])     # per-op scrubber (M7.12)
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
        if self._gcode_thread is not None and self._gcode_thread.isRunning():
            return                            # a G-code job is already in flight
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
            engraving=self._engraving_curves,
            temple=self.params.temple_params(),
            is_temple=self._is_temple,
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

    def _on_generate_block(self) -> None:
        """Generate the base-curve forming block from the loaded frame's lens
        interior (BUILDPLAN M6.4) — its own program, folded into the .gcam."""
        if self._gcode_thread is not None and self._gcode_thread.isRunning():
            return                            # a G-code job is already in flight
        if self._lens_od is None:
            QMessageBox.warning(
                self, "No lens",
                "Load a frame DXF with a LENS layer before generating a "
                "base-curve forming block.")
            return
        self._act_block.setEnabled(False)
        self.append_log("[gcode] Generating the base-curve forming block from the lens interior.")

        worker = GCodeWorker(
            outline=self._outline_poly, castle=self.params.castle_params(),
            params=self._collect_gcode_params(), cam_params=self.params.cam_params())
        worker.block_lens = self._lens_od
        worker.block = self.params.block_params()
        worker.is_block = True
        self._gcode_worker = worker

        self._gcode_thread = QThread()
        worker.moveToThread(self._gcode_thread)
        self._gcode_thread.started.connect(worker.run)
        worker.progress.connect(self.append_log)
        worker.finished.connect(self._on_gcode_finished)
        worker.error.connect(self._on_gcode_error)
        worker.cancelled.connect(self._on_gcode_cancelled)
        worker.finished.connect(self._gcode_thread.quit)
        worker.error.connect(self._gcode_thread.quit)
        worker.cancelled.connect(self._gcode_thread.quit)

        dlg = self._open_progress("Generating base-curve block")
        worker.stage.connect(self._on_stage)
        dlg.canceled.connect(worker.cancel)
        self._gcode_thread.start()

    def _on_generate_worktable(self) -> None:
        """Cut the frame front + its base-curve block in one bed program (M6.5)."""
        if self._gcode_thread is not None and self._gcode_thread.isRunning():
            return                            # a G-code job is already in flight
        if not (self._partition is not None and self._partition.matched
                and self._lens_od is not None):
            QMessageBox.warning(
                self, "Worktable needs a full frame",
                "Load a frame DXF with SCULPT zones and lenses — the worktable "
                "cuts the frame front and its base-curve block together.")
            return
        self._act_worktable.setEnabled(False)
        self._act_gcode.setEnabled(False)
        self.append_log("[gcode] Generating the worktable program (frame + base-curve block).")

        worker = GCodeWorker(
            outline=self._outline_poly, castle=self.params.castle_params(),
            params=self._collect_gcode_params(), partition=self._partition,
            hinge_polys=self._hinge_polys, cam_params=self.params.cam_params())
        worker.block_lens = self._lens_od
        worker.block = self.params.block_params()
        worker.is_worktable = True
        self._gcode_worker = worker

        self._gcode_thread = QThread()
        worker.moveToThread(self._gcode_thread)
        self._gcode_thread.started.connect(worker.run)
        worker.progress.connect(self.append_log)
        worker.finished.connect(self._on_gcode_finished)
        worker.error.connect(self._on_gcode_error)
        worker.cancelled.connect(self._on_gcode_cancelled)
        worker.finished.connect(self._gcode_thread.quit)
        worker.error.connect(self._gcode_thread.quit)
        worker.cancelled.connect(self._gcode_thread.quit)

        dlg = self._open_progress("Generating worktable program")
        worker.stage.connect(self._on_stage)
        dlg.canceled.connect(worker.cancel)
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

    # -------------------------------------------------- toolpath overlay (M7.11)

    def _show_toolpath_overlay(self, overlay: list, rows: list) -> None:
        """Colour the program's ops, draw them over the 2D design, and fill the
        toolpath inspector (BUILDPLAN M7.11)."""
        for i, op in enumerate(overlay):
            op["color"] = _TOOLPATH_COLORS[i % len(_TOOLPATH_COLORS)]
        self.canvas.set_toolpaths(overlay)
        self._populate_toolpath_inspector(rows, overlay)
        self._toolpath_dock.setVisible(True)
        if self._act_toolpaths is not None:
            self._act_toolpaths.setChecked(True)
        self._switch_view(0)                       # 2D outline so the paths show

    def _populate_toolpath_inspector(self, rows: list, overlay: list) -> None:
        tool_by = {op["name"]: op.get("tool", "") for op in overlay}
        color_by = {op["name"]: op.get("color", "") for op in overlay}
        t = self._toolpath_table
        t.blockSignals(True)
        t.setRowCount(len(rows))
        total_len = total_min = 0.0
        for r, row in enumerate(rows):
            name = row["name"]
            op_item = QTableWidgetItem(name)
            op_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                             | Qt.ItemFlag.ItemIsSelectable)
            op_item.setCheckState(Qt.CheckState.Checked)
            op_item.setData(Qt.ItemDataRole.UserRole, name)
            if color_by.get(name):
                op_item.setForeground(QColor(color_by[name]))
            t.setItem(r, 0, op_item)
            t.setItem(r, 1, QTableWidgetItem(tool_by.get(name) or "—"))
            t.setItem(r, 2, QTableWidgetItem(f"{row['floor_z_mm']:.2f} mm"))
            total_len += row["cut_length_mm"]
            t.setItem(r, 3, QTableWidgetItem(f"{row['cut_length_mm'] / 1000.0:.2f} m"))
            if "est_minutes" in row:
                total_min += row["est_minutes"]
                t.setItem(r, 4, QTableWidgetItem(f"{row['est_minutes']:.1f} min"))
            else:
                t.setItem(r, 4, QTableWidgetItem("—"))
            for c in (2, 3, 4):
                t.item(r, c).setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        t.blockSignals(False)
        t.resizeColumnsToContents()
        self._toolpath_dock.setWindowTitle(
            f"Toolpaths — {len(rows)} ops · {total_len / 1000.0:.2f} m · "
            f"{total_min:.1f} min")

    def _on_toolpath_item_changed(self, item) -> None:
        if item.column() != 0:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name is not None:
            self.canvas.set_toolpath_visible(
                name, item.checkState() == Qt.CheckState.Checked)

    def _on_toolpath_selection(self) -> None:
        items = self._toolpath_table.selectedItems()
        name = None
        if items:
            cell = self._toolpath_table.item(items[0].row(), 0)
            name = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        self.canvas.set_toolpath_highlight(name)

    def _on_playback_step(self, op_index: int, label: str) -> None:
        """Sync the M7.11 toolpath inspector to the scrubber cursor (M7.12): when
        the Toolpaths table lists the op now being cut, select its row (which
        highlights it on the 2D overlay). Best-effort — the table is only populated
        after Generate, so a sim-only session simply shows the viewer's step label."""
        t = getattr(self, "_toolpath_table", None)
        if t is None or t.rowCount() == 0:
            return
        selected_rows = {i.row() for i in t.selectedItems()}
        for r in range(t.rowCount()):
            cell = t.item(r, 0)
            if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == label:
                if r not in selected_rows:
                    t.selectRow(r)
                return

    def _clear_toolpath_overlay(self) -> None:
        """Drop the 2D toolpath overlay + inspector (a new component or a stale
        program)."""
        self.canvas.clear_toolpaths()
        self._toolpath_table.blockSignals(True)
        self._toolpath_table.setRowCount(0)
        self._toolpath_table.blockSignals(False)
        self._toolpath_dock.setWindowTitle("Toolpaths")

    def _on_gcode_finished(self, summary: str, rows) -> None:
        self._close_progress()
        self.append_log("[gcode] Done.")
        self._act_gcode.setEnabled(True)
        self._act_block.setEnabled(self._lens_od is not None)
        self._act_worktable.setEnabled(
            self._partition is not None and self._partition.matched
            and self._lens_od is not None)
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
        # Draw the toolpaths over the 2D design + fill the inspector (M7.11); the
        # worktable bed has its own render, so only per-component programs overlay.
        overlay = getattr(w, "op_overlay", None) if w is not None else None
        if overlay:
            self._show_toolpath_overlay(overlay, rows)
        if rows:
            OpSummaryDialog(rows, summary, self).exec()
        else:
            QMessageBox.information(self, "G-code generated", summary)

    def _on_gcode_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[gcode ERROR]\n" + tb)
        self._act_gcode.setEnabled(True)
        self._act_block.setEnabled(self._lens_od is not None)
        self._act_worktable.setEnabled(
            self._partition is not None and self._partition.matched
            and self._lens_od is not None)
        self.status_lbl.setText("G-code generation failed — see log")

    def _on_gcode_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[gcode] Cancelled.")
        self._act_gcode.setEnabled(True)
        self._act_block.setEnabled(self._lens_od is not None)
        self._act_worktable.setEnabled(
            self._partition is not None and self._partition.matched
            and self._lens_od is not None)
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
            "<b>GuildCAM</b> v0.7.11 — pre-release<br><br>"
            "Free, open-source CAM tool for spectacle frame cutting on GRBL CNCs.<br>"
            "Companion to the Guild CNC and gSender fork.<br><br>"
            "GPLv3 — see LICENSE for details.",
        )


# ------------------------------------------------------------------ entry point

def main() -> None:
    # Share one OpenGL context across the 3D-preview + cut-sim render windows
    # (must be set before the QApplication exists). Qt+VTK best practice for apps
    # embedding multiple QtInteractors — reduces wglMakeCurrent / context-loss
    # failures on Windows when switching views or after the display sleeps.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("GuildCAM")
    app.setOrganizationName("Guild")
    app.setStyleSheet(theme.stylesheet(prefs_mod.load()["dark_mode"]))

    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
