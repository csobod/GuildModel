"""GuildModel main window — thin PySide6 shell over guildmodel.core.

Window architecture (BUILDPLAN M4.6 Part A): one right tabbed dock
(ParamsPanel: Frame / Castle / Stock / CAM), a top icon toolbar, and a
bottom log dock — GuildDraw's pattern. Long operations (Build 3D / Export
STL / Generate G-code) drive a determinate progress dialog with stage
labels and stage-boundary cancellation (Part B).
"""
from __future__ import annotations
import datetime
import json
import logging
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
    QDoubleSpinBox, QLineEdit, QScrollArea, QDockWidget, QFrame,
    QToolBar, QProgressDialog, QTabBar, QComboBox,
    QListWidget, QListWidgetItem, QSpinBox, QSplitter,
    QSlider, QColorDialog,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QByteArray, QSize, QPointF
from PySide6.QtGui import QAction, QKeySequence, QColor, QPainter, QPen, QPixmap, QIcon

from guildmodel.core.layers import ALL_LAYERS as SUPPORTED_LAYERS
from guildmodel.gui import prefs as prefs_mod
from guildmodel.gui import icons as icons_mod
from guildmodel.gui import hidpi
from guildmodel.gui.mesh_build import build_component_mesh
from guildmodel.gui.style import theme
from guildmodel.gui.widgets.dxf_canvas import DxfCanvas
from guildmodel.gui.widgets.params_panel import ParamsPanel
from guildmodel.gui.widgets.viewer_3d import Viewer3D
from guildmodel.gui.widgets import readiness_dot
from guildmodel.gui.widgets.readiness_dot import ReadinessDot
from guildmodel.gui.component_workspace import (
    ComponentWorkspace, build_workspaces_from_gdraw, derive_workspace,
)


class _Cancelled(Exception):
    """Raised inside a worker's progress callback to abort at a stage boundary."""


# Saved dock/toolbar layout version (QMainWindow.save/restoreState). Bump whenever
# the default dock arrangement changes so a stale saved layout is dropped rather than
# overriding the new default. v2 (M11): the inspector is split beside the toolpaths.
_DOCK_STATE_VERSION = 3   # 3: bottom-row split re-established (rc2 dock fix)


class ToolSep(QWidget):
    """A crisp, uniform toolbar group divider (BUILDPLAN M7.12 UI).

    A stylesheet ``QToolBar::separator`` with a 1 px width rounds inconsistently on
    fractional-DPI displays — each separator lands at a different sub-pixel position
    and rasterises to 0/1/2 device px, so they look mismatched. This paints the line
    itself with a *cosmetic* pen (width is transform-independent → exactly one device
    pixel everywhere), giving identical, hairline-crisp dividers at any scale, and
    flips its axis with the toolbar's orientation."""

    def __init__(self, toolbar: QToolBar):
        super().__init__(toolbar)
        self._tb = toolbar
        self._color = QColor("#383838")
        self._pad = 4          # logical-px inset at the line's ends
        self._cell = 13        # logical-px thickness of the spacing cell
        self._apply_policy()

    def _apply_policy(self) -> None:
        # Fixed along the toolbar axis (the spacing cell); stretch across it so the
        # line spans the button height.
        if self._tb.orientation() == Qt.Orientation.Horizontal:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_color(self, color) -> None:
        self._color = QColor(color)
        self.update()

    def refresh(self) -> None:
        self._apply_policy()
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        cross = 24             # span most of the button height even if not stretched
        if self._tb.orientation() == Qt.Orientation.Horizontal:
            return QSize(self._cell, cross)
        return QSize(cross, self._cell)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(self._color)
        pen.setCosmetic(True)              # 1 device px regardless of DPI / position
        p.setPen(pen)
        r = self.rect()
        if self._tb.orientation() == Qt.Orientation.Horizontal:
            x = r.center().x() + 0.5       # pixel-centre for a crisp vertical line
            p.drawLine(QPointF(x, r.top() + self._pad), QPointF(x, r.bottom() - self._pad))
        else:
            y = r.center().y() + 0.5
            p.drawLine(QPointF(r.left() + self._pad, y), QPointF(r.right() - self._pad, y))


# ------------------------------------------------------------------ DXF import worker

class ImportWorker(QObject):
    """Runs DXF import + boxing measurement off the GUI thread."""

    # layers, boxing|None, raw_summary, unrecognised, curves
    finished = Signal(dict, object, dict, list, dict)
    error = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            import ezdxf as _ezdxf
            from collections import Counter as _Counter
            from guildmodel.core.io_import.dxf import import_curves
            from guildmodel.core.io_import.normalize import points_to_polygon
            from guildmodel.core.geometry.boxing import measure_from_polygon

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

            # `import_curves`, not `import_dxf`: same points, plus the exact
            # SPLINE definitions behind them for the B-Rep path.
            layers, curves = import_curves(self.path)

            boxing = None
            lens_curves = layers.get("LENS", [])
            if len(lens_curves) >= 2:
                polys = [points_to_polygon(c) for c in lens_curves if len(c) >= 3]
                valid = [p for p in polys if p.is_valid and p.area > 1.0]
                if len(valid) >= 2:
                    boxing = measure_from_polygon(valid[0], valid[1])

            self.finished.emit(layers, boxing, raw_summary, unrecognised, curves)
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
    """Builds one castle relief mesh off the GUI thread (matched SCULPT
    zone layouts only — the spike's distance-based fallback is retired)."""

    finished = Signal(object, str, object)   # trimesh.Trimesh, stage, edges|None
    error = Signal(str)

    def __init__(
        self, partition, castle, hinge_polys=(), stage: str = "pockets",
        resolution: float = 0.3, solid: bool = False,
    ) -> None:
        super().__init__()
        self.spec = {"mode": "castle", "partition": partition, "castle": castle,
                     "hinge": list(hinge_polys), "stage": stage}
        self.stage_name = stage
        self.resolution = resolution
        self.solid = solid

    def run(self) -> None:
        try:
            mesh, edges, _guide = build_component_mesh(
                self.spec, resolution=self.resolution, solid=self.solid,
                progress=self._progress)
            self.finished.emit(mesh, self.stage_name, edges)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


class FlatMeshWorker(_ProgressWorker):
    """Builds a flat-part solid (temple or base-curve block) off the GUI thread.

    A temple is the outline extruded with HINGE pockets + ENGRAVING grooves
    (snapped to the blank end when asked), a block is the blank box with the lens
    scribed on top and the M4 holes as through-holes. Emits the mesh + the temple
    core-guide bounds (a 3D visual reference, or None for a block).
    """

    finished = Signal(object, object)   # trimesh.Trimesh, core_guide bounds | None
    error = Signal(str)

    def __init__(self, mode: str, *, outline=None, temple=None, hinge_polys=(),
                 engraving=(), lens=None, block=None, resolution: float = 0.3) -> None:
        super().__init__()
        self.spec = {"mode": mode, "outline": outline, "temple": temple,
                     "hinge": list(hinge_polys), "engraving": list(engraving),
                     "lens": lens, "block": block}
        self.resolution = resolution

    def run(self) -> None:
        try:
            mesh, _edges, guide = build_component_mesh(
                self.spec, resolution=self.resolution, progress=self._progress)
            self.finished.emit(mesh, guide)
        except _Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())


class MultiMeshWorker(_ProgressWorker):
    """Builds **every** loaded component's mesh in a *single* thread (BUILDPLAN M7
    UX: Build 3D builds all components). One worker / one thread for the whole run —
    never reassigned mid-flight — so there is no "QThread destroyed while running"
    crash. Emits ``built(index, mesh, edges|None, core_guide|None)`` as each
    finishes, then ``finished``. ``specs`` are plain build descriptions (see
    _build_spec).

    `solid` reaches this worker too. It did not used to, and that was the whole
    of the 2026-08-07 finding 2: Build 3D came through here and so always
    produced raster meshes with no edges, which left the display-mode combo
    correctly disabled and apparently dead, while changing a parameter went
    through `MeshWorker` and did build a solid.
    """

    built = Signal(int, object, object, object)   # index, mesh, edges|None, guide|None
    finished = Signal()
    error = Signal(str)

    def __init__(self, specs: list[dict], resolution: float,
                 solid: bool = False) -> None:
        super().__init__()
        self.specs = specs
        self.resolution = resolution
        self.solid = solid

    def run(self) -> None:
        try:
            n = max(1, len(self.specs))
            for k, spec in enumerate(self.specs):
                label = spec["label"]

                def sub(lbl, frac, _k=k, _label=label):
                    self._progress(f"{_label}: {lbl}", (_k + frac) / n)

                sub("starting", 0.0)
                mesh, edges, guide = build_component_mesh(
                    spec, resolution=self.resolution, solid=self.solid,
                    progress=sub)
                self.built.emit(spec["index"], mesh, edges, guide)
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
            from guildmodel.core.relief.castle import (
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
    user's library (``~/.guildmodel/tools.yaml``) — the single tool source for the
    CAM combos, generation, the post, and the sim (BUILDPLAN M7.8)."""
    from guildmodel.gui import tool_store
    return tool_store.effective()


def _apply_appearance_prefs(prefs: dict) -> None:
    """Push the persisted Appearance prefs into the theme module (startup and
    Preferences-OK): viewport preset, 3D light rig, model surface color, and
    the toolpath-overlay palette. Surfaces re-pull on their next refresh."""
    vp = prefs.get("viewport") or {}
    theme.apply_viewport(vp.get("preset", "auto"), vp.get("custom_bg"))
    r3 = prefs.get("render3d") or {}
    theme.set_lighting(r3)
    theme.set_mesh_color(r3.get("model_color") or None)
    theme.set_toolpath_palette(prefs.get("toolpath_palette"))
    theme.set_layer_overrides(prefs.get("layer_colors"))
    theme.set_grid(prefs.get("grid"))


def _op_overlay(ops) -> list[dict]:
    """Per-op cutting paths (design mm) for the 2D toolpath overlay (M7.11)."""
    return [{"name": op.name, "tool": op.tool_name or "",
             "paths": [[(float(p[0]), float(p[1])) for p in path] for path in op.paths]}
            for op in ops]


def _op_tool_geom(ops, default_tool: dict | None) -> dict:
    """Per-op tool geometry for the moving-tool render (BUILDPLAN M7.12.2): the
    cutting shape (type / radius / V-angle) plus shank & flute length from the op's
    tools.yaml entry (or the global default), keyed by op name to match
    ``RemovalPlayback.frame_labels``."""
    out: dict = {}
    for op in ops:
        t = op.tool or default_tool or {}
        r = t.get("radius_mm")
        if r is None:
            d = t.get("diameter_mm")
            r = (d / 2.0) if d else 1.5875
        out[op.name] = {
            "type": t.get("type", "flat"),
            "radius_mm": float(r),
            "included_angle_deg": float(t.get("included_angle_deg", 0.0) or 0.0),
            "flute_length_mm": float(t.get("flute_length_mm", 0.0) or 0.0),
            "shank_diameter_mm": float(t.get("shank_diameter_mm", 0.0) or 0.0),
        }
    return out


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
        # inspector inputs (M7.14): captured by the finish handler into the dock
        self.reach_warnings: list = []
        self.clearance_violations: list = []
        self.machine_warnings: list = []
        # .gmodel artifacts (filled by the castle path on success)
        self.programs: dict = {}
        self.machine_dump = None
        self.setup_dict = None

    def run(self) -> None:
        try:
            self._generate()
        except _Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            # "Every operation is switched off" is the maker's own setting, not a
            # crash — report the sentence, not a traceback (M16 per-op enable).
            from guildmodel.core.cam.castle_ops import NoOperationsError
            self.error.emit(str(exc) if isinstance(exc, NoOperationsError)
                            else traceback.format_exc())

    def _generate_castle(self, tools_cfg: dict, mats_cfg: dict, config_dir: Path) -> None:
        """Five-op posterior program: hinge pockets -> rough -> fine ->
        eyewires -> perimeter, single .nc, onion skin instead of tabs."""
        import yaml
        from guildmodel.core.cam.castle_ops import (
            CastleCamParams, fixture_clearance_violations, generate_castle_program,
            op_summaries, require_ops, write_castle_program,
        )
        from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildmodel.core.post.grbl import GRBLPost
        from guildmodel.core.post.machine import (
            clamp_cam_to_machine, lint_program, load_machine_profile,
        )
        from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

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
        cam, clamp = clamp_cam_to_machine(cam, machine, mat)
        for w in clamp.warnings:
            self.progress.emit(f"[gcode] machine: {w}")

        self.progress.emit("[gcode] Castle: building relief…")
        relief = build_castle_relief(
            self.partition, castle, self.hinge_polys, resolution=CUT_RES_MM,
            progress=self._progress,
        )
        self.progress.emit("[gcode] Castle: generating five operations…")
        ops = require_ops(generate_castle_program(
            relief, castle, self.hinge_polys, tool, params=cam,
            progress=self._progress, tools_cfg=tools_cfg,
        ), "The frame front")
        for op in ops:
            zmin, zmax = op.z_range()
            tag = f" · {op.tool_name}" if (cam.is_multi_tool() and op.tool_name) else ""
            self.progress.emit(
                f"[gcode]   {op.name}: {len(op.paths)} paths, Z {zmin:.2f}..{zmax:.2f}{tag}"
            )

        # Tool-reach gating (BUILDPLAN M6.1 task 3): warn when an op's tool can't
        # reach its feature, suggesting a fitting tool.
        from guildmodel.core.cam.castle_ops import (
            analyze_program_reach, build_tool_settings, count_tool_changes,
            depth_reach_warnings, feature_reach_warnings,
        )
        reach = analyze_program_reach(ops, self.hinge_polys, tools_cfg)
        reach = list(reach) + depth_reach_warnings(ops, self.castle.stock.total_pad_height_mm)
        reach += feature_reach_warnings(self.castle, ops, tools_cfg)
        for r in reach:
            self.progress.emit(f"[gcode] ⚠ reach: {r.message()}")

        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        violations = fixture_clearance_violations(ops, fixture, tool["radius_mm"])
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        # Lens bevel groove (V1): soft checks — form-tool mismatch, flanks
        # breaking the wall top / anterior face.
        if getattr(relief, "groove", None) is not None:
            from guildmodel.core.cam.castle_ops import groove_warnings
            g_tool = next((op.tool for op in ops if op.name == "Lens Groove"),
                          None) or tool
            heights = [castle.zones.for_kind(z.kind)
                       for z in relief.partition.zones]
            for w in groove_warnings(relief.groove, g_tool,
                                     min(heights) if heights else 0.0):
                self.progress.emit(f"[gcode] WARNING groove: {w}")

        # Multi-tool jobs (BUILDPLAN M6.1): assemble per-tool feeds (tool override
        # or material, clamped to the machine) and the Tn map; single-tool jobs
        # leave tool_settings None and post exactly as before. A lens-groove job
        # is ALWAYS multi-tool: the drageoir op is not in POSTERIOR_OPS, so
        # is_multi_tool() alone can't see it (V1).
        tool_settings = None
        if cam.is_multi_tool() or getattr(relief, "groove", None) is not None:
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
            safe_z_mm=cam.safe_z_for(castle.stock.total_pad_height_mm),
            feed_plane_mm=castle.stock.total_pad_height_mm + 1.0,   # rapid-descent floor
            work_offset=work_offset,
        )
        if cam.link_retracts:
            from guildmodel.core.cam.castle_ops import work_holding_keepouts
            post.link_clearance_z_mm = castle.stock.total_pad_height_mm + cam.link_clearance_mm
            post.link_keepouts = tuple(work_holding_keepouts(
                relief.partition.body, castle.stock, post_dia / 2.0,
                screw_head_diameter_mm=cam.screw_head_diameter_mm,
                margin_mm=cam.screw_keepout_margin_mm,
                is_hole=relief.partition.is_hole))
        self._progress("Writing program", 0.95)
        write_castle_program(
            ops, post, arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            contour_lead_in=cam.contour_lead_in,
            tool_settings=tool_settings,
            tool_change_mode=machine.tool_change_mode,
        )
        # The program is kept in the project (.gmodel) by default — no loose .nc
        # is written here; File ▸ Export G-code writes a standalone file on
        # demand (mirrors Export STL).
        text = post.to_string()
        self.progress.emit(f"[gcode] posterior_cut.nc generated ({len(text):,} bytes)")

        # Lint against the machine + estimate cut time (machine dynamics).
        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        self.reach_warnings = list(reach)                 # M7.14 inspector inputs
        self.clearance_violations = list(violations)
        self.machine_warnings = list(machine_warnings)
        report = estimate_program(
            text, MachineDynamics.from_profile(machine),
            tool_change_seconds=machine.tool_change_seconds,
        )
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))

        summary = ("Posterior program generated and stored in the project.\n"
                   "Save the project (Ctrl+S) to keep it in the .gmodel, or "
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

        # Stash artifacts for the .gmodel container (M5.1); read on the GUI thread.
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
        from guildmodel.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, count_tool_changes,
            fixture_clearance_violations, op_summaries, require_ops, resolve_tool,
            write_castle_program,
        )
        from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildmodel.core.cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
        from guildmodel.core.post.grbl import GRBLPost
        from guildmodel.core.post.machine import (
            clamp_cam_to_machine, lint_program, load_machine_profile,
        )
        from guildmodel.core.project.schema import TempleParams

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

        # The temple posts through the SAME machine/material clamp as the frame and
        # the bed. It was the last single-component path that did not: its ops were
        # generated from an unclamped stepdown, and its post was handed
        # cam.arc_tolerance_mm rather than the clamped tolerance, so a controller
        # declared to have no reliable G2/G3 still got arcs (the other half of
        # INCIDENT-2026-07-29).
        cam, clamp = clamp_cam_to_machine(cam, machine, mat)
        for w in clamp.warnings:
            self.progress.emit(f"[gcode] machine: {w}")

        from guildmodel.core.relief.flat import place_temple_on_blank
        outline, hinge_polys, engraving = place_temple_on_blank(
            self.outline, self.hinge_polys, self.engraving, temple.blank_length_mm,
            stock_side=temple.stock_side, snap=temple.snap_to_blank_end)
        ops = require_ops(
            generate_temple_program(outline, engraving, temple, tools_cfg, cam,
                                    hinge_polys=hinge_polys), "This temple")
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
            safe_z_mm=cam.safe_z_for(temple.blank_thickness_mm),
            feed_plane_mm=temple.blank_thickness_mm + 1.0,
            work_offset=work_offset,
        )
        self._progress("Writing temple program", 0.9)
        write_castle_program(
            ops, post, side="Temple", arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            contour_lead_in=cam.contour_lead_in,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=TEMPLE_CONTOUR_OPS)
        text = post.to_string()
        self.progress.emit(f"[gcode] temple_cut.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        self.clearance_violations = list(violations)      # M7.14 inspector inputs
        self.machine_warnings = list(machine_warnings)
        report = estimate_program(text, MachineDynamics.from_profile(machine),
                                  tool_change_seconds=machine.tool_change_seconds)
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))
        rows = op_summaries(ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)
        # The ops live in the BLANK frame (snapped); back-project the overlay into
        # the design frame so it draws on the part in the 2D view (2026-07-09).
        self.op_overlay = _op_overlay(ops)
        if temple.snap_to_blank_end:
            from guildmodel.core.relief.flat import temple_snap_transform
            flipped, sdx, sdy = temple_snap_transform(
                self.outline, self.hinge_polys, temple.blank_length_mm,
                stock_side=temple.stock_side, snap=True)
            sgn = -1.0 if flipped else 1.0
            for entry in self.op_overlay:
                entry["paths"] = [[(sgn * (x - sdx), sgn * (y - sdy)) for x, y in path]
                                  for path in entry["paths"]]

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
        from guildmodel.core.cam.block_ops import (
            BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
        )
        from guildmodel.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, count_tool_changes,
            fixture_clearance_violations, op_summaries, require_ops, resolve_tool,
            write_castle_program,
        )
        from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildmodel.core.post.grbl import GRBLPost
        from guildmodel.core.post.machine import (
            clamp_cam_to_machine, lint_program, load_machine_profile,
        )
        from guildmodel.core.project.schema import BaseCurveBlockParams

        cam = self.cam_params or CastleCamParams()
        block = self.block or BaseCurveBlockParams()
        machine = load_machine_profile(cam.machine_name, config_dir)
        mat = mats_cfg.get(block.material, mats_cfg.get("acetate"))
        self.progress.emit(
            f"[gcode] Base-curve block · Machine: {machine.display_name} · "
            f"material {block.material} · drill {block.drill_tool}"
        )

        # Clamp BEFORE generating the ops. This path used to compute a clamped
        # stepdown and hand it only to write_castle_program, which sets the lead-in
        # ramp depth — the contour passes themselves were already cut from the
        # unclamped value, so the clamp was cosmetic. The block's material (acetal,
        # max_doc 2.0) is usually stricter than the frame's, which is exactly when
        # that mattered.
        cam, clamp = clamp_cam_to_machine(cam, machine, mat)
        for w in clamp.warnings:
            self.progress.emit(f"[gcode] machine: {w}")

        ops = require_ops(
            generate_block_program(self.block_lens, block, tools_cfg, cam),
            "This base-curve block")
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
            safe_z_mm=cam.safe_z_for(block.blank_thickness_mm),
            feed_plane_mm=block.blank_thickness_mm + 1.0,
            work_offset=work_offset,
        )
        self._progress("Writing block program", 0.9)
        write_castle_program(
            ops, post, side="Base-Curve Block", arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            contour_lead_in=cam.contour_lead_in,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=BLOCK_CONTOUR_OPS, drill_op_names=BLOCK_DRILL_OPS,
            peck_depth_mm=block.peck_depth_mm)
        text = post.to_string()
        self.progress.emit(f"[gcode] base_curve_block.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        self.clearance_violations = list(violations)      # M7.14 inspector inputs
        self.machine_warnings = list(machine_warnings)
        report = estimate_program(text, MachineDynamics.from_profile(machine),
                                  tool_change_seconds=machine.tool_change_seconds)
        self.progress.emit("[gcode] Estimated cut time —\n" + format_report(report))
        rows = op_summaries(ops, feed_rate_mmpm=first_ts.feed_rate_mmpm)
        # Block ops are centred on the origin (center_on_origin); shift the overlay
        # back onto the lens as drawn so it lands on the part in the 2D view.
        self.op_overlay = _op_overlay(ops)
        if self.block_lens is not None:
            bx0, by0, bx1, by1 = self.block_lens.bounds
            bcx, bcy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            for entry in self.op_overlay:
                entry["paths"] = [[(x + bcx, y + bcy) for x, y in path]
                                  for path in entry["paths"]]

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
        from guildmodel.core.cam.block_ops import (
            BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
        )
        from guildmodel.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, generate_castle_program,
            op_summaries, write_castle_program,
        )
        from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
        from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program, format_report
        from guildmodel.core.cam.layout import BedPart, bed_clearance_violations, build_bed_program
        from guildmodel.core.post.grbl import GRBLPost
        from guildmodel.core.post.machine import (
            clamp_cam_to_machine, lint_program, load_machine_profile,
        )
        from guildmodel.core.project.schema import BaseCurveBlockParams
        from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

        cam = self.cam_params or CastleCamParams()
        castle = self.castle
        block = self.block or BaseCurveBlockParams()
        machine = load_machine_profile(cam.machine_name, config_dir)
        mat_name = self.params["material_name"]
        mat = mats_cfg.get(mat_name.split()[0].lower(), mats_cfg["acetate"])
        with open(config_dir / "fixtures" / "guild_cnc.yaml", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        self.progress.emit(f"[gcode] Worktable · Machine: {machine.display_name}")

        # The bed posts through the SAME machine/material clamp as the single-
        # component program — otherwise stepdown, feeds, spindle and the arc /
        # linearize decision reach the post unchecked (INCIDENT-2026-07-29).
        cam, clamp = clamp_cam_to_machine(cam, machine, mat)
        for w in clamp.warnings:
            self.progress.emit(f"[gcode] machine: {w}")

        # part 1 — the frame front (posterior cut)
        self.progress.emit("[gcode] Worktable: building the frame relief…")
        relief = build_castle_relief(self.partition, castle, self.hinge_polys,
                                     resolution=CUT_RES_MM, progress=self._progress)
        frame_ops = generate_castle_program(
            relief, castle, self.hinge_polys, tools_cfg.get(cam.tool_name, tools_cfg["flat_3175"]),
            params=cam, tools_cfg=tools_cfg)

        # part 2 — the base-curve forming block from the OD lens
        self.progress.emit("[gcode] Worktable: generating the base-curve block…")
        block_ops = generate_block_program(self.block_lens, block, tools_cfg, cam)

        parts = [
            BedPart("frame_front", "Frame", "front", frame_ops, set(CASTLE_CONTOUR_OPS), set()),
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
            bed.ops, tools_cfg, default_feed=clamp.feed_rate_mmpm,
            default_plunge=clamp.plunge_rate_mmpm, default_spindle=clamp.spindle_rpm,
            machine=machine)
        for w in ts_warns:
            self.progress.emit(f"[gcode] tool: {w}")

        # parts are placed in absolute machine coordinates → touch off machine zero
        violations = bed_clearance_violations(bed.ops, fixture, skip_op_names=bed.drill_op_names)
        for v in violations:
            self.progress.emit(f"[gcode] WARNING: {v}")

        first_ts = tool_settings[bed.ops[0].tool_name]
        safe_z = cam.safe_z_for(max(castle.stock.total_pad_height_mm, block.blank_thickness_mm))
        post = GRBLPost(
            job_name="worktable", material=mat_name,
            tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
            feed_rate_mmpm=first_ts.feed_rate_mmpm, plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
            safe_z_mm=safe_z,
        )
        self._progress("Writing worktable program", 0.92)
        write_castle_program(
            bed.ops, post, side="Worktable", arc_tol_mm=clamp.arc_tol_mm,
            contour_stepdown_mm=cam.contour_stepdown_mm,
            contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
            contour_lead_in=cam.contour_lead_in,
            tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
            contour_op_names=bed.contour_op_names, drill_op_names=bed.drill_op_names,
            peck_depth_mm=block.peck_depth_mm)
        text = post.to_string()
        self.progress.emit(f"[gcode] worktable.nc generated ({len(text):,} bytes)")

        machine_warnings = lint_program(text, machine)
        for w in machine_warnings:
            self.progress.emit(f"[gcode] ⚠ machine: {w}")
        self.clearance_violations = list(violations)      # M7.14 inspector inputs
        self.machine_warnings = list(machine_warnings)
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
        from guildmodel.core.cam.profile import profile_cut
        from guildmodel.core.post.grbl import GRBLPost

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
        if self.partition is not None and self.partition.classified:
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
            from guildmodel.core.relief.castle import (
                build_castle_relief, stock_top_heightfield,
            )
            from guildmodel.core.cam.castle_ops import (
                CastleCamParams, build_tool_settings, generate_castle_program,
                write_castle_program,
            )
            from guildmodel.core.post.grbl import GRBLPost
            from guildmodel.core.sim import (
                ToolProfile, achieved_floor, achieved_floor_grouped,
                cutting_paths_from_program, cutting_paths_from_program_grouped, verify,
                build_removal_plan, motion_steps_from_program,
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
            # each move with its own tool profile, so the sim matches the real
            # cut. A lens-groove job is ALWAYS multi-tool (see GCodeWorker).
            tool_settings = None
            if cam.is_multi_tool() or getattr(relief, "groove", None) is not None:
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
                safe_z_mm=cam.safe_z_for(self.castle.stock.total_pad_height_mm),
            )
            if cam.link_retracts:
                from guildmodel.core.cam.castle_ops import work_holding_keepouts
                post.link_clearance_z_mm = self.castle.stock.total_pad_height_mm + cam.link_clearance_mm
                post.link_keepouts = tuple(work_holding_keepouts(
                    relief.partition.body, self.castle.stock,
                    (first.diameter_mm if first else tool["diameter_mm"]) / 2.0,
                    screw_head_diameter_mm=cam.screw_head_diameter_mm,
                    margin_mm=cam.screw_keepout_margin_mm,
                    is_hole=relief.partition.is_hole))
            write_castle_program(
                ops, post, arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                contour_lead_in=cam.contour_lead_in,
                tool_settings=tool_settings)

            self.progress.emit("[sim] Sweeping tool along the toolpaths…")
            f = relief.field
            init_z = self.castle.stock.total_pad_height_mm + 1.0
            _swp = lambda p: self._progress("Simulating", 0.6 + 0.35 * p)
            if tool_settings:
                groups = cutting_paths_from_program_grouped(post.to_string())
                # The lens-groove drageoir cuts SIDEWAYS: a top-down Z-buffer
                # sweep of its loop would falsely carve the rim lip from above.
                # Drop groove-tool moves — the channel it rides in is verified
                # by the eyewire sweep; the V itself is geometry (V1).
                groups = [
                    (p, t) for p, t in groups
                    if not (t and tools_cfg.get(t, {}).get("type") == "groove")]
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

            # Position-based removal plan (M7.12): the full toolpath + sparse
            # keyframes — the 3D block carves along the path in sync with the tool.
            self._progress("Building playback", 0.96)
            stock_hf = stock_top_heightfield(
                self.castle.stock, resolution=f.resolution,
                origin=f.origin, shape=f.z.shape)
            plan = build_removal_plan(
                motion_steps_from_program(
                    post.to_string(), ToolProfile.from_tool(tool),
                    profiles={n: ToolProfile.from_tool(c) for n, c in tools_cfg.items()},
                    rapid_mmpm=3000.0, feed_mmpm=post.feed_rate_mmpm,
                    base_spacing=f.resolution),
                stock_hf.z, f.origin, f.resolution)
            plan.op_tool_geom = _op_tool_geom(ops, tool)

            # Lens groove (V1): the side-cut op is outside the Z-buffer sweep
            # (its ToolProfile kernel stamps nothing) — verify it geometrically
            # instead and hand the viewer its true rings to mark in the scene.
            lines = report.summary_lines()
            g_op = next((o for o in ops if o.name == "Lens Groove"), None)
            if g_op is not None and getattr(relief, "groove", None) is not None:
                from guildmodel.core.cam.castle_ops import verify_groove_op
                issues = verify_groove_op(
                    g_op, relief.groove_lens_polys, relief.groove,
                    g_op.tool or tool)
                if issues:
                    lines += [f"⚠ {w}" for w in issues]
                else:
                    lines.append(
                        "Lens Groove: side-cut op verified geometrically "
                        "(apex on the lens contour; outside the top-down sweep)")
                z_apex = float(relief.groove.anterior_offset_mm)
                plan.groove_rings = [
                    [(float(x), float(y), z_apex)
                     for x, y in lens.exterior.coords]
                    for lens in relief.groove_lens_polys]

            self.finished.emit(report, lines, plan)
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
            from guildmodel.core.cam.block_ops import (
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
            )
            from guildmodel.core.cam.castle_ops import (
                CastleCamParams, build_tool_settings, resolve_tool, write_castle_program,
            )
            from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
            from guildmodel.core.cam.temple_ops import (
                TEMPLE_CONTOUR_OPS, generate_temple_program,
            )
            from guildmodel.core.post.grbl import GRBLPost
            from guildmodel.core.relief.flat import build_block_relief, build_temple_relief
            from guildmodel.core.sim import (
                ToolProfile, achieved_floor_grouped,
                cutting_paths_from_program_grouped, verify,
                build_removal_plan, motion_steps_from_program,
            )

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            mat_key = self.material_name.split()[0].lower()
            mat = mats_cfg.get(mat_key, mats_cfg["acetate"])
            # Simulate the program the tab actually posts — same clamp, so the pass
            # structure the maker watches is the pass structure they cut.
            try:
                from guildmodel.core.post.machine import (
                    clamp_cam_to_machine, load_machine_profile,
                )
                cam, _clamp = clamp_cam_to_machine(
                    cam, load_machine_profile(cam.machine_name, config_dir), mat)
            except Exception:
                pass                     # unknown machine: simulate unclamped, as before

            self.progress.emit(f"[sim] Building the {self.mode} relief at {self.resolution} mm…")
            if self.mode == "temple":
                t = self.temple
                # The sim target matches what the PROGRAM cuts: the temple program
                # now mills the HINGE pockets (BUILDPLAN M7), so the relief carves
                # them too — model, sim, and posted G-code agree on the recess. Place
                # the temple on its blank (M11 stock-side) first so all three agree.
                from guildmodel.core.relief.flat import place_temple_on_blank
                outline, hinge_polys, engraving = place_temple_on_blank(
                    self.outline, self.hinge_polys, self.engraving, t.blank_length_mm,
                    stock_side=t.stock_side, snap=t.snap_to_blank_end)
                relief = build_temple_relief(
                    outline, t, hinge_polys, engraving,
                    resolution=self.resolution, progress=self._progress)
                ops = generate_temple_program(outline, engraving, t, tools_cfg, cam,
                                              hinge_polys=hinge_polys)
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
                safe_z_mm=cam.safe_z_for(top_z))                 # work_offset (0,0,0): sim stays in the design frame
            write_castle_program(
                ops, post, arc_tol_mm=cam.arc_tolerance_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                contour_lead_in=cam.contour_lead_in,
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

            # Position-based removal plan (M7.12): single-level blank (temple /
            # base-curve block) carved along the toolpath in sync with the tool.
            self._progress("Building playback", 0.96)
            stock_top = np.full(f.z.shape, float(top_z), dtype=float)
            plan = build_removal_plan(
                motion_steps_from_program(
                    post.to_string(), ToolProfile.from_tool(fallback_tool),
                    profiles={n: ToolProfile.from_tool(c) for n, c in tools_cfg.items()},
                    rapid_mmpm=3000.0, feed_mmpm=post.feed_rate_mmpm,
                    base_spacing=f.resolution),
                stock_top, f.origin, f.resolution)
            plan.op_tool_geom = _op_tool_geom(ops, fallback_tool)
            self.finished.emit(report, report.summary_lines(), plan)
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

    These ops are **posted verbatim** as `worktable.nc` (`build_nest_program`), so
    they are built at `CUT_RES_MM` and against machine-clamped CAM params — the
    same grid and the same limits as the single-component posting. This worker used
    to take its grid from the 3D-preview preference, floored at 0.4 mm, which put a
    preview-grade toolpath on real hardware (INCIDENT-2026-07-29). There is
    deliberately no `resolution` parameter: nothing that ends in a `.nc` gets to
    choose its own grid.
    """

    finished = Signal(object)    # core.cam.layout.BedNest
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, specs, worktable, *, cam_params=None,
                 machine=None, material: dict | None = None) -> None:
        super().__init__()
        self.specs = specs
        self.worktable = worktable
        self.cam_params = cam_params
        self.machine = machine
        self.material = material

    def run(self) -> None:
        try:
            from guildmodel.core.cam.block_ops import (
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
            )
            from guildmodel.core.cam.castle_ops import (
                CastleCamParams, generate_castle_program,
            )
            from guildmodel.core.cam.temple_ops import (
                TEMPLE_CONTOUR_OPS, generate_temple_program,
            )
            from guildmodel.core.cam.layout import (
                BedPart, default_nest_rotation, nest_components_on_worktable,
            )
            from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
            from guildmodel.core.post.machine import clamp_cam_to_machine
            from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

            cam = self.cam_params or CastleCamParams()
            if self.machine is not None:
                cam, clamp = clamp_cam_to_machine(cam, self.machine, self.material)
                for w in clamp.warnings:
                    self.progress.emit(f"[nest] machine: {w}")
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
                        resolution=CUT_RES_MM,
                        progress=lambda lbl, f, b=base: self._progress(lbl, b + f / n))
                    ops = generate_castle_program(
                        relief, spec["castle"], spec["hinge"], default_tool,
                        params=cam, tools_cfg=tools)
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         set(CASTLE_CONTOUR_OPS), set()))
                elif mode == "temple":
                    from guildmodel.core.relief.flat import place_temple_on_blank
                    t = spec["temple"]
                    t_outline, t_hinge, t_eng = place_temple_on_blank(
                        spec["outline"], spec["hinge"], spec["engraving"],
                        t.blank_length_mm, stock_side=t.stock_side,
                        snap=t.snap_to_blank_end)
                    ops = generate_temple_program(
                        t_outline, t_eng, t, tools, cam, hinge_polys=t_hinge)
                    # A snapped temple's ops live in its blank frame: place blank
                    # centre → zone centre so the core end stays registered against
                    # the zone end, matching how the blank slides into its slot.
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         set(TEMPLE_CONTOUR_OPS), set(),
                                         place_by_origin=t.snap_to_blank_end))
                else:  # block
                    ops = generate_block_program(spec["lens"], spec["block"], tools, cam)
                    parts.append(BedPart(spec["kind"], spec["label"], "", ops,
                                         set(BLOCK_CONTOUR_OPS), set(BLOCK_DRILL_OPS)))
            # Seed each part's bed orientation (an UN-snapped temple_left flips 180°
            # to face the right temple); the maker then rotates any placement freely
            # (M-UX). A snapped temple's orientation is authoritative — stock_side
            # already faced its core end, and a default spin would break the
            # core-aligned loading the snap exists for.
            for part in parts:
                if not part.place_by_origin:
                    part.rotation_deg = default_nest_rotation(part.kind)
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
    report drives the shared 3D viewer's sim mode (Uncut / Gouge overlays).

    `simulate_component` re-derives each part's relief *and* its program from the
    spec, so the sim only verifies the posted bed when it rebuilds on the posting
    grid — at any other resolution it is checking a program that will never run
    (INCIDENT-2026-07-29). Hence `CUT_RES_MM` and no `resolution` parameter."""

    finished = Signal(object, object, object)   # CutReport, summary lines, RemovalPlayback
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, specs, placements, work_area, *, cam_params=None,
                 material_name: str = "acetate") -> None:
        super().__init__()
        self.specs = specs
        self.placements = placements          # list[BedPlacement] (label → dx/dy/kind)
        self.work_area = work_area
        self.cam_params = cam_params
        self.material_name = material_name

    def run(self) -> None:
        try:
            import numpy as np
            import yaml
            from guildmodel.core.cam.castle_ops import CastleCamParams
            from guildmodel.core.sim import (
                BedRemovalPart, ComponentSim, ToolProfile, build_bed_removal_plan,
                composite_bed_report, simulate_component, steps_from_ops,
            )

            from guildmodel.core.relief.castle import CUT_RES_MM

            cam = self.cam_params or CastleCamParams()
            config_dir = Path(__file__).parent.parent / "config"
            tools_cfg = _tools_cfg()
            mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
            # Same clamp the bed program posts under (NestWorker / Generate Worktable),
            # so the bed sim shows the passes the bed will actually cut.
            try:
                from guildmodel.core.post.machine import (
                    clamp_cam_to_machine, load_machine_profile,
                )
                _key = (self.material_name.split() or ["acetate"])[0].lower()
                cam, _clamp = clamp_cam_to_machine(
                    cam, load_machine_profile(cam.machine_name, config_dir),
                    mats_cfg.get(_key, mats_cfg["acetate"]))
            except Exception:
                pass                     # unknown machine: simulate unclamped, as before
            place = {pl.label: pl for pl in self.placements}
            specs = [s for s in self.specs if s["label"] in place]
            comps: list = []
            bed_parts: list = []          # volumetric bed removal (M7.12.3)
            geom: dict = {}
            n = max(len(specs), 1)
            for k, spec in enumerate(specs):
                base = k / n
                self.progress.emit(f"[bed-sim] {spec['label']}: simulating…")
                floor, target, inside, origin, res = simulate_component(
                    spec, cam=cam, tools_cfg=tools_cfg, mats_cfg=mats_cfg,
                    material_name=self.material_name, resolution=CUT_RES_MM,
                    progress=lambda lbl, fr, b=base: self._progress(lbl, b + fr / n))
                pl = place[spec["label"]]
                comps.append(ComponentSim(floor, target, inside, origin, res,
                                          dx=pl.dx, dy=pl.dy, label=pl.label, kind=pl.kind))

                # bed removal part: this part's stock heightfield + machine-coord steps
                mode = spec["mode"]
                if mode == "castle":
                    from guildmodel.core.relief.castle import stock_top_heightfield
                    stock_hf = stock_top_heightfield(
                        spec["castle"].stock, resolution=res, origin=origin,
                        shape=floor.shape).z
                elif mode == "temple":
                    stock_hf = np.full(floor.shape, float(spec["temple"].blank_thickness_mm))
                else:
                    stock_hf = np.full(floor.shape, float(spec["block"].blank_thickness_mm))
                part_steps = [(f"{pl.label} · {lbl}", prof, paths)
                              for (lbl, prof, paths) in steps_from_ops(pl.ops, ToolProfile())]
                for op_lbl, gv in _op_tool_geom(pl.ops, None).items():
                    geom[f"{pl.label} · {op_lbl}"] = gv
                bed_parts.append(BedRemovalPart(part_steps, stock_hf, origin, pl.dx, pl.dy))

            self._progress("Compositing the bed", 0.96)
            report = composite_bed_report(comps, self.work_area, resolution=CUT_RES_MM)
            plan = build_bed_removal_plan(bed_parts, resolution=CUT_RES_MM)
            plan.op_tool_geom = geom
            self.finished.emit(report, report.summary_lines(), plan)
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
    structure leaves room for more tabs as GuildModel grows."""

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

        # Startup (dark mode + the rest of the look moved to the Appearance tab)
        app_box = QGroupBox("Startup")
        app_form = QFormLayout(app_box)
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

        # BUILDPLAN Stage 2. The solid is the master representation; the raster
        # stays available so the two can be compared (report §3.5).
        self._solid_model = QCheckBox("Build the model as a B-Rep solid")
        self._solid_model.setChecked(bool(prefs.get("use_solid_model", False)))
        self._solid_model.setToolTip(
            "Model with the OpenCASCADE solid kernel instead of the raster\n"
            "heightfield. Cuts get exact edges, the solid is watertight by\n"
            "construction, and the viewer's wireframe / hidden-edge display\n"
            "modes become available — they draw the part's real edges, which a\n"
            "heightfield mesh does not have.\n\n"
            "Slower to rebuild, and the resolution settings above no longer\n"
            "apply to the preview: a solid has no grid.")
        prev_form.addRow("", self._solid_model)
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

        # ── Tab 1 — Appearance (mode / viewport / 3D render / toolpaths) ───
        # Must precede the Tools tab: its ToolView preview reads _dark_check.
        self._build_appearance_tab(tabs, prefs)

        # ── Tab 2 — Layers (per-layer colour overrides, GuildDraw parity) ──
        self._build_layers_tab(tabs, prefs)

        # ── Tab 3 — Materials ─────────────────────────────────────────────
        self._build_materials_tab(tabs)

        # ── Tab 3 — Tools (the editable tool library, BUILDPLAN M7.8) ──────
        self._build_tools_tab(tabs)

        # ── Tabs 4–5 — Hotkeys + Toolbar (customization, BUILDPLAN M7.15) ──
        self._action_specs = list(getattr(parent, "_action_specs", []))
        self._hotkey_overrides = dict(prefs.get("hotkeys", {}))
        self._saved_toolbar = list(prefs.get("toolbar", []) or [])
        self._hotkey_rows = []
        self._toolbar_list = None
        if self._action_specs:
            self._build_hotkeys_tab(tabs)
            self._build_toolbar_tab(tabs)

    # ── Appearance tab (viewport preset / 3D light rig / overlays) ────────

    def _build_appearance_tab(self, tabs, prefs: dict) -> None:
        ap_scroll = QScrollArea()
        ap_scroll.setWidgetResizable(True)
        ap_scroll.setFrameShape(ap_scroll.Shape.NoFrame)
        ap_inner = QWidget()
        ap_lay = QVBoxLayout(ap_inner)
        ap_lay.setSpacing(12)
        ap_lay.setContentsMargins(16, 16, 16, 8)
        ap_scroll.setWidget(ap_inner)
        tabs.addTab(ap_scroll, "Appearance")

        mode_box = QGroupBox("Mode")
        mode_form = QFormLayout(mode_box)
        self._dark_check = QCheckBox("Enable dark mode")
        self._dark_check.setChecked(prefs["dark_mode"])
        mode_form.addRow(self._dark_check)

        # UI scale (BUILDPLAN-NEW UI-0). The escape hatch that keeps any future
        # scaling bug from stranding the maker in an unusable UI: Auto follows
        # the desktop's own convention (see gui/hidpi._decide), a number pins
        # it. The sample label previews the chosen size live.
        self._scale_choices = [
            ("auto", "Auto (follow the desktop)"),
            ("1.0", "100%"), ("1.1", "110%"), ("1.25", "125%"),
            ("1.5", "150%"), ("1.75", "175%"), ("2.0", "200%"),
        ]
        self._scale_combo = QComboBox()
        for _k, label in self._scale_choices:
            self._scale_combo.addItem(label)
        cur_scale = str(prefs.get("ui_scale", "auto"))
        self._scale_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._scale_choices)
             if k == cur_scale), 0))
        self._scale_combo.setToolTip(
            "Size of the whole interface (fonts and controls).\n"
            "Auto follows your desktop's scaling setting; pick a number to\n"
            "override just this app. Takes effect immediately on OK.")
        self._scale_sample = QLabel("Sample — Aa 12.5 mm")
        self._scale_sample.setToolTip("Preview of interface text at the chosen scale.")
        self._scale_base_pt = self.font().pointSizeF() or 10.0
        self._scale_combo.currentIndexChanged.connect(self._on_scale_preview)
        self._on_scale_preview(self._scale_combo.currentIndex())
        mode_form.addRow("UI scale:", self._scale_combo)
        mode_form.addRow("", self._scale_sample)
        ap_lay.addWidget(mode_box)

        # Viewport preset — GuildDraw's canvas themes, shared verbatim so the
        # two apps feel like one product (theme.VIEWPORT_PRESETS).
        vp = prefs.get("viewport") or {}
        vp_box = QGroupBox("Viewport")
        vp_form = QFormLayout(vp_box)
        self._vp_choices = [
            ("auto",      "Follow UI theme"),
            ("parchment", "Parchment"),
            ("dimmed",    "Dimmed"),
            ("blueprint", "Blueprint"),
            ("matte",     "Matte Dark"),
            ("white",     "Plain White"),
            ("custom",    "Custom…"),
        ]
        self._vp_combo = QComboBox()
        for _key, label in self._vp_choices:
            self._vp_combo.addItem(label)
        cur_preset = vp.get("preset", "auto")
        self._vp_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._vp_choices) if k == cur_preset),
            0))
        self._vp_combo.setToolTip(
            "Backdrop + drawing ink for the 2D canvases and the 3D viewport,\n"
            "independent of the UI mode. Follow UI theme = parchment in light\n"
            "mode, matte in dark mode.")
        self._vp_combo.currentIndexChanged.connect(self._on_vp_preset_changed)
        vp_form.addRow("Canvas preset:", self._vp_combo)

        self._vp_custom_color = vp.get("custom_bg") or "#faf6ee"
        self._vp_color_btn = QPushButton("Canvas colour…")
        self._vp_color_btn.setToolTip(
            "Custom canvas colour; drawing ink is derived automatically.")
        self._vp_color_btn.clicked.connect(self._pick_vp_color)
        self._vp_color_btn.setEnabled(cur_preset == "custom")
        self._update_vp_swatch()
        vp_form.addRow("Custom:", self._vp_color_btn)
        ap_lay.addWidget(vp_box)

        # 3D render — light rig + key-light direction/strength + part colour.
        r3 = prefs.get("render3d") or {}
        r3_box = QGroupBox("3D render")
        r3_form = QFormLayout(r3_box)
        self._rig_choices = [
            ("studio",      "Studio (soft, default)"),
            ("directional", "Directional (dramatic)"),
            ("flat",        "Flat (no shading)"),
        ]
        self._rig_combo = QComboBox()
        for _key, label in self._rig_choices:
            self._rig_combo.addItem(label)
        cur_rig = r3.get("rig", "studio")
        self._rig_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._rig_choices) if k == cur_rig),
            0))
        self._rig_combo.setToolTip(
            "Studio adds a movable key light over VTK's soft light kit;\n"
            "Directional keeps only the key light, for strong relief-reading\n"
            "shadows; Flat renders unshaded silhouettes.")
        self._rig_combo.currentIndexChanged.connect(self._on_rig_changed)
        r3_form.addRow("Light rig:", self._rig_combo)

        def _slider(lo: int, hi: int, val: float, fmt, tip: str):
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(int(round(val)))
            s.setToolTip(tip)
            lbl = QLabel(fmt(s.value()))
            lbl.setMinimumWidth(44)
            s.valueChanged.connect(lambda v, f=fmt, l=lbl: l.setText(f(v)))
            lay.addWidget(s, 1)
            lay.addWidget(lbl)
            return row, s

        az_row, self._light_az = _slider(
            -180, 180, float(r3.get("azimuth_deg", -27.0)),
            lambda v: f"{v}°",
            "Where the key light stands around the part\n"
            "(0° = from the right, +X; 90° = from the back).")
        el_row, self._light_el = _slider(
            5, 90, float(r3.get("elevation_deg", 61.0)),
            lambda v: f"{v}°",
            "How high the key light sits above the table (90° = overhead).")
        in_row, self._light_in = _slider(
            0, 200, float(r3.get("intensity", 0.8)) * 100.0,
            lambda v: f"{v}%",
            "Key-light strength (the shipped default is 80%).")
        r3_form.addRow("Light direction:", az_row)
        r3_form.addRow("Light height:", el_row)
        r3_form.addRow("Light intensity:", in_row)

        self._model_color = str(r3.get("model_color") or "")
        self._model_color_btn = QPushButton("Model colour…")
        self._model_color_btn.setToolTip(
            "Surface colour of the 3D part (default: the theme's amber\n"
            "acetate look).")
        self._model_color_btn.clicked.connect(self._pick_model_color)
        mc_reset = QPushButton("Default")
        mc_reset.setToolTip("Back to the theme's amber part colour.")
        mc_reset.clicked.connect(self._reset_model_color)
        mc_row = QWidget()
        mc_lay = QHBoxLayout(mc_row)
        mc_lay.setContentsMargins(0, 0, 0, 0)
        mc_lay.setSpacing(8)
        mc_lay.addWidget(self._model_color_btn, 1)
        mc_lay.addWidget(mc_reset)
        self._update_model_swatch()
        r3_form.addRow("Model colour:", mc_row)
        ap_lay.addWidget(r3_box)
        self._on_rig_changed(self._rig_combo.currentIndex())

        # Toolpath overlay palette (M7.11 overlay colours)
        tp_box = QGroupBox("Toolpath overlay")
        tp_form = QFormLayout(tp_box)
        self._tp_choices = [
            ("vivid", "Vivid (default)"),
            ("soft",  "Soft"),
            ("bold",  "Bold"),
            ("mono",  "Monochrome blue"),
        ]
        self._tp_combo = QComboBox()
        self._tp_combo.setIconSize(QSize(64, 12))
        for key, label in self._tp_choices:
            self._tp_combo.addItem(
                self._palette_icon(theme.TOOLPATH_PALETTES[key]), label)
        cur_tp = prefs.get("toolpath_palette", "vivid")
        self._tp_combo.setCurrentIndex(next(
            (i for i, (k, _l) in enumerate(self._tp_choices) if k == cur_tp),
            0))
        self._tp_combo.setToolTip(
            "Colour set cycled across a program's operations on the 2D\n"
            "toolpath overlay.")
        tp_form.addRow("Path colours:", self._tp_combo)
        ap_lay.addWidget(tp_box)

        # 2D-canvas grid (GuildDraw parity). Shipped values = the historical
        # 10 mm dotted grid, plus a heavier major line every 5th.
        gr = prefs.get("grid") or {}
        grid_box = QGroupBox("Grid  (2D canvas)")
        grid_form = QFormLayout(grid_box)
        self._grid_visible = QCheckBox("Show grid")
        self._grid_visible.setChecked(bool(gr.get("visible", True)))
        grid_form.addRow(self._grid_visible)
        self._grid_spacing = QDoubleSpinBox()
        self._grid_spacing.setRange(0.5, 100.0)
        self._grid_spacing.setSingleStep(0.5)
        self._grid_spacing.setDecimals(1)
        self._grid_spacing.setSuffix(" mm")
        self._grid_spacing.setValue(float(gr.get("spacing_mm", 10.0)))
        self._grid_spacing.setToolTip("Grid line spacing on the design canvas.")
        grid_form.addRow("Spacing:", self._grid_spacing)
        self._grid_major = QSpinBox()
        self._grid_major.setRange(1, 20)
        self._grid_major.setValue(int(gr.get("major_every", 5)))
        self._grid_major.setToolTip(
            "Every Nth line is drawn heavier (a major division).\n"
            "1 = a uniform grid with no major lines.")
        grid_form.addRow("Major every:", self._grid_major)
        self._grid_width = QDoubleSpinBox()
        self._grid_width.setRange(0.5, 4.0)
        self._grid_width.setSingleStep(0.5)
        self._grid_width.setDecimals(1)
        self._grid_width.setSuffix(" px")
        self._grid_width.setValue(float(gr.get("major_width_px", 1.0)))
        self._grid_width.setToolTip("Line weight of the major grid lines (screen pixels).")
        grid_form.addRow("Major width:", self._grid_width)
        # Grid line colours: "" = follow the theme (mirrors the model-colour swatch).
        self._grid_minor_color = str(gr.get("minor_color") or "")
        self._grid_major_color = str(gr.get("major_color") or "")
        self._grid_minor_btn = QPushButton("Minor colour…")
        self._grid_minor_btn.clicked.connect(lambda: self._pick_grid_color("minor"))
        self._grid_major_btn = QPushButton("Major colour…")
        self._grid_major_btn.clicked.connect(lambda: self._pick_grid_color("major"))
        grid_reset = QPushButton("Theme default")
        grid_reset.setToolTip("Clear both grid colour overrides — the grid "
                              "follows the theme again.")
        grid_reset.clicked.connect(self._reset_grid_colors)
        grid_colors_row = QWidget()
        gc_lay = QHBoxLayout(grid_colors_row)
        gc_lay.setContentsMargins(0, 0, 0, 0)
        gc_lay.setSpacing(6)
        gc_lay.addWidget(self._grid_minor_btn)
        gc_lay.addWidget(self._grid_major_btn)
        gc_lay.addWidget(grid_reset)
        gc_lay.addStretch()
        grid_form.addRow("Colours:", grid_colors_row)
        self._update_grid_swatches()
        ap_lay.addWidget(grid_box)

        ap_lay.addStretch()

    @staticmethod
    def _palette_icon(colors: list[str]) -> QIcon:
        pm = QPixmap(64, 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        w = 64 // len(colors)
        for i, c in enumerate(colors):
            p.fillRect(i * w, 0, w, 12, QColor(c))
        p.end()
        return QIcon(pm)

    def _on_vp_preset_changed(self, idx: int) -> None:
        self._vp_color_btn.setEnabled(self._vp_choices[idx][0] == "custom")

    def _pick_vp_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._vp_custom_color), self,
                                  "Canvas colour")
        if c.isValid():
            self._vp_custom_color = c.name()
            self._update_vp_swatch()

    def _update_vp_swatch(self) -> None:
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._vp_custom_color))
        self._vp_color_btn.setIcon(QIcon(pm))

    def _on_rig_changed(self, idx: int) -> None:
        lit = self._rig_choices[idx][0] != "flat"
        for s in (self._light_az, self._light_el, self._light_in):
            s.setEnabled(lit)

    def _pick_model_color(self) -> None:
        current = self._model_color or theme.LIGHT.mesh_surface
        c = QColorDialog.getColor(QColor(current), self, "Model surface colour")
        if c.isValid():
            self._model_color = c.name()
            self._update_model_swatch()

    def _reset_model_color(self) -> None:
        self._model_color = ""
        self._update_model_swatch()

    def _update_model_swatch(self) -> None:
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._model_color or theme.LIGHT.mesh_surface))
        self._model_color_btn.setIcon(QIcon(pm))

    # ── Grid colours (Appearance ▸ Grid) ──────────────────────────────────

    def _pick_grid_color(self, which: str) -> None:
        current = (self._grid_minor_color if which == "minor"
                   else self._grid_major_color) or theme.LIGHT.grid
        c = QColorDialog.getColor(QColor(current), self,
                                  f"Grid {which} colour")
        if not c.isValid():
            return
        if which == "minor":
            self._grid_minor_color = c.name()
        else:
            self._grid_major_color = c.name()
        self._update_grid_swatches()

    def _reset_grid_colors(self) -> None:
        self._grid_minor_color = ""
        self._grid_major_color = ""
        self._update_grid_swatches()

    def _update_grid_swatches(self) -> None:
        for color, btn in ((self._grid_minor_color, self._grid_minor_btn),
                           (self._grid_major_color, self._grid_major_btn)):
            pm = QPixmap(16, 16)
            pm.fill(QColor(color or theme.LIGHT.grid))
            btn.setIcon(QIcon(pm))

    # ── Layers tab (per-layer colour overrides — GuildDraw parity) ────────

    def _build_layers_tab(self, tabs, prefs: dict) -> None:
        from guildmodel.core.layers import LAYER_STYLES
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 8)
        scroll.setWidget(inner)
        tabs.addTab(scroll, "Layers")

        note = QLabel(
            "Drawing colour per design layer, for each UI mode. Reset returns "
            "a layer to the shipped colour. With a pinned viewport preset the "
            "override matching the backdrop's brightness applies.")
        note.setWordWrap(True)
        lay.addWidget(note)

        # {layer: {"light": "#rrggbb"|"", "dark": ...}} — only real overrides
        # survive into to_prefs().
        self._layer_colors: dict[str, dict] = {}
        for layer, cfg in (prefs.get("layer_colors") or {}).items():
            if isinstance(cfg, dict) and (cfg.get("light") or cfg.get("dark")):
                self._layer_colors[layer] = {"light": cfg.get("light") or "",
                                             "dark": cfg.get("dark") or ""}

        grp = QGroupBox("Layer colours")
        form = QFormLayout(grp)
        self._layer_btns: dict[tuple[str, str], QPushButton] = {}
        for layer in LAYER_STYLES:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            for mode, label in (("light", "Light…"), ("dark", "Dark…")):
                btn = QPushButton(label)
                btn.clicked.connect(
                    lambda _=False, l=layer, m=mode: self._pick_layer_color(l, m))
                self._layer_btns[(layer, mode)] = btn
                h.addWidget(btn)
            reset = QPushButton("Reset")
            reset.setToolTip("Back to the shipped colour in both modes.")
            reset.clicked.connect(
                lambda _=False, l=layer: self._reset_layer_color(l))
            h.addWidget(reset)
            h.addStretch()
            form.addRow(f"{layer}:", row)
            self._update_layer_swatches(layer)
        lay.addWidget(grp)
        lay.addStretch()

    def _layer_swatch_color(self, layer: str, mode: str) -> str:
        """The colour the swatch shows: the pending override for that mode, or
        the shipped per-mode colour (raw — the dialog edits per-mode values)."""
        ov = (self._layer_colors.get(layer) or {}).get(mode) or ""
        if ov:
            return ov
        from guildmodel.core.layers import LAYER_STYLES
        return theme.layer_color(LAYER_STYLES[layer][0], mode == "dark")

    def _pick_layer_color(self, layer: str, mode: str) -> None:
        c = QColorDialog.getColor(
            QColor(self._layer_swatch_color(layer, mode)), self,
            f"{layer} colour ({mode} mode)")
        if not c.isValid():
            return
        self._layer_colors.setdefault(layer, {"light": "", "dark": ""})[mode] = c.name()
        self._update_layer_swatches(layer)

    def _reset_layer_color(self, layer: str) -> None:
        self._layer_colors.pop(layer, None)
        self._update_layer_swatches(layer)

    def _update_layer_swatches(self, layer: str) -> None:
        for mode in ("light", "dark"):
            pm = QPixmap(16, 16)
            pm.fill(QColor(self._layer_swatch_color(layer, mode)))
            self._layer_btns[(layer, mode)].setIcon(QIcon(pm))

    # ── Hotkeys tab (rebindable shortcuts, M7.15) ─────────────────────────

    def _build_hotkeys_tab(self, tabs) -> None:
        from PySide6.QtWidgets import QKeySequenceEdit
        from PySide6.QtGui import QKeySequence
        from guildmodel.gui.shortcuts import effective_shortcuts

        outer = QWidget()
        col = QVBoxLayout(outer)
        col.setContentsMargins(16, 16, 16, 8)
        col.setSpacing(8)
        col.addWidget(QLabel(
            "Rebind keyboard shortcuts. Click a cell and press the new combination; "
            "↺ resets one binding."))

        eff = effective_shortcuts(self._action_specs, self._hotkey_overrides)
        table = QTableWidget(len(self._action_specs), 3)
        table.setHorizontalHeaderLabels(["Action", "Shortcut", ""])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(False)
        table.setColumnWidth(0, 220)
        table.setColumnWidth(1, 160)
        table.setColumnWidth(2, 36)

        for i, spec in enumerate(self._action_specs):
            name = QTableWidgetItem(spec.label)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            table.setItem(i, 0, name)
            edit = QKeySequenceEdit(QKeySequence(eff[spec.key]))
            try:
                edit.setMaximumSequenceLength(1)      # single shortcut, not a chord chain
            except AttributeError:
                pass
            edit.keySequenceChanged.connect(self._check_hotkey_conflicts)
            table.setCellWidget(i, 1, edit)
            rb = QPushButton("↺")
            rb.setToolTip(f"Reset to default ({spec.default_shortcut or 'none'})")
            rb.setFixedWidth(30)
            rb.clicked.connect(
                lambda _=False, e=edit, d=spec.default_shortcut: (
                    e.setKeySequence(QKeySequence(d)), self._check_hotkey_conflicts()))
            table.setCellWidget(i, 2, rb)
            self._hotkey_rows.append((spec.key, spec.default_shortcut, edit))
        col.addWidget(table, 1)

        self._hotkey_conflict_lbl = QLabel("")
        self._hotkey_conflict_lbl.setWordWrap(True)
        col.addWidget(self._hotkey_conflict_lbl)

        reset_all = QPushButton("Reset all shortcuts to defaults")
        reset_all.clicked.connect(self._reset_all_hotkeys)
        col.addWidget(reset_all, 0, Qt.AlignmentFlag.AlignLeft)

        tabs.addTab(outer, "Hotkeys")
        self._check_hotkey_conflicts()

    def _check_hotkey_conflicts(self) -> None:
        from PySide6.QtGui import QKeySequence
        from guildmodel.gui.shortcuts import find_conflicts
        bindings = {
            key: e.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            for key, _d, e in self._hotkey_rows}
        labels = {s.key: s.label for s in self._action_specs}
        conflicts = find_conflicts(bindings)
        if conflicts:
            parts = [f"{sc} — {', '.join(labels.get(k, k) for k in keys)}"
                     for sc, keys in conflicts.items()]
            self._hotkey_conflict_lbl.setText("⚠ Duplicate shortcuts: " + "; ".join(parts))
            self._hotkey_conflict_lbl.setStyleSheet("color: #c0392b; font-weight: 600;")
        else:
            self._hotkey_conflict_lbl.setText("")

    def _reset_all_hotkeys(self) -> None:
        from PySide6.QtGui import QKeySequence
        for (_key, default, edit) in self._hotkey_rows:
            edit.setKeySequence(QKeySequence(default))
        self._check_hotkey_conflicts()

    def hotkey_overrides(self) -> dict:
        """Collect only genuine overrides (a binding that differs from its default)."""
        from PySide6.QtGui import QKeySequence
        out: dict = {}
        for (key, default, edit) in self._hotkey_rows:
            cur = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            if cur != default:
                out[key] = cur
        return out

    # ── Toolbar tab (which buttons show + their order, M7.15) ─────────────

    def _build_toolbar_tab(self, tabs) -> None:
        from guildmodel.gui.shortcuts import effective_toolbar
        spec_by_key = {s.key: s for s in self._action_specs}
        shown = effective_toolbar(self._action_specs, self._saved_toolbar)
        shown_set = set(shown)
        # checked (toolbar) items first in their order, then the rest in registry order
        ordered = shown + [s.key for s in self._action_specs if s.key not in shown_set]

        outer = QWidget()
        col = QVBoxLayout(outer)
        col.setContentsMargins(16, 16, 16, 8)
        col.setSpacing(8)
        col.addWidget(QLabel(
            "Choose which buttons appear on the toolbar and their order. Check to show; "
            "use ▲ / ▼ to reorder. Dividers between groups are added automatically."))

        self._toolbar_list = QListWidget()
        for key in ordered:
            spec = spec_by_key[key]
            item = QListWidgetItem(f"{spec.label}   ·   {spec.group}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in shown_set
                               else Qt.CheckState.Unchecked)
            self._toolbar_list.addItem(item)
        col.addWidget(self._toolbar_list, 1)

        row = QHBoxLayout()
        up = QPushButton("▲ Up")
        down = QPushButton("▼ Down")
        up.clicked.connect(lambda: self._move_toolbar_item(-1))
        down.clicked.connect(lambda: self._move_toolbar_item(1))
        reset = QPushButton("Reset toolbar to default")
        reset.clicked.connect(self._reset_toolbar)
        row.addWidget(up)
        row.addWidget(down)
        row.addStretch()
        row.addWidget(reset)
        col.addLayout(row)

        tabs.addTab(outer, "Toolbar")

    def _move_toolbar_item(self, delta: int) -> None:
        lw = self._toolbar_list
        row = lw.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < lw.count()):
            return
        item = lw.takeItem(row)
        lw.insertItem(new, item)
        lw.setCurrentRow(new)

    def _reset_toolbar(self) -> None:
        lw = self._toolbar_list
        lw.clear()
        # default order: toolbar_default specs (in registry order), then the rest
        defaults = [s for s in self._action_specs if s.toolbar_default]
        rest = [s for s in self._action_specs if not s.toolbar_default]
        for spec in defaults + rest:
            item = QListWidgetItem(f"{spec.label}   ·   {spec.group}")
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if spec.toolbar_default
                               else Qt.CheckState.Unchecked)
            lw.addItem(item)

    def toolbar_order(self) -> list:
        """The checked action keys in list order; [] when it equals the shipped
        default (so a future default change still reaches unchanged users)."""
        lw = self._toolbar_list
        out = []
        for i in range(lw.count()):
            item = lw.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        default = [s.key for s in self._action_specs if s.toolbar_default]
        return [] if out == default else out

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
        from guildmodel.gui import material_store
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
        from guildmodel.gui import material_store
        material_store.reset_material(name)
        shipped = material_store.shipped_material(name)
        for key, sb in self._mat_widgets.get(name, {}).items():
            if key in shipped:
                sb.setValue(float(shipped[key]))

    def _save_materials(self) -> None:
        """Persist edited material values: store overrides that differ from
        shipped, drop overrides that now match shipped."""
        from guildmodel.gui import material_store
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
        from guildmodel.gui import tool_store
        from guildmodel.core.cam.tooling import TOOL_TYPES
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

        from guildmodel.gui.widgets.tool_view import ToolView
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
        from guildmodel.gui import tool_store
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
        from guildmodel.core.cam.tooling import ToolSpec
        from guildmodel.gui import tool_store
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
        from guildmodel.core.cam.tooling import ToolSpec
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
        from guildmodel.core.cam.tooling import ToolSpec
        from guildmodel.gui import tool_store
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
        from guildmodel.core.cam.tooling import ToolSpec
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
        from guildmodel.gui import tool_store
        from guildmodel.core.cam.tooling import ToolSpec
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

    def _on_scale_preview(self, index: int) -> None:
        """Resize the sample label to the chosen scale — live, dialog-local."""
        from guildmodel.gui import hidpi
        key = self._scale_choices[index][0]
        if key == "auto":
            app = QApplication.instance()
            scale = hidpi.ui_scale(app.primaryScreen() if app else None, {})
        else:
            scale = float(key)
        font = self._scale_sample.font()
        font.setPointSizeF(self._scale_base_pt * scale)
        self._scale_sample.setFont(font)

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
        scale_key = self._scale_choices[self._scale_combo.currentIndex()][0]
        out = {
            "dark_mode": self._dark_check.isChecked(),
            "ui_scale": scale_key if scale_key == "auto" else float(scale_key),
            "show_log_on_start": self._log_check.isChecked(),
            "use_solid_model": self._solid_model.isChecked(),
            "preview_resolution_mm": round(self._preview_res.value(), 2),
            "export_resolution_mm": round(self._export_res.value(), 2),
            "last_output_dir": self._out_dir.text(),
            # Appearance tab (viewport preset / 3D light rig / path palette)
            "viewport": {
                "preset": self._vp_choices[self._vp_combo.currentIndex()][0],
                "custom_bg": self._vp_custom_color,
            },
            "render3d": {
                "rig": self._rig_choices[self._rig_combo.currentIndex()][0],
                "azimuth_deg": float(self._light_az.value()),
                "elevation_deg": float(self._light_el.value()),
                "intensity": round(self._light_in.value() / 100.0, 2),
                "model_color": self._model_color,
            },
            "toolpath_palette": self._tp_choices[self._tp_combo.currentIndex()][0],
            "grid": {
                "visible": self._grid_visible.isChecked(),
                "spacing_mm": round(self._grid_spacing.value(), 1),
                "major_every": int(self._grid_major.value()),
                "minor_color": self._grid_minor_color,
                "major_color": self._grid_major_color,
                "major_width_px": round(self._grid_width.value(), 1),
            },
            # Only genuine overrides persist (an all-"" entry is a reset).
            "layer_colors": {k: dict(v) for k, v in self._layer_colors.items()
                             if (v.get("light") or v.get("dark"))},
        }
        if self._hotkey_rows:                     # M7.15 — only genuine overrides
            out["hotkeys"] = self.hotkey_overrides()
        if self._toolbar_list is not None:        # M7.15 — [] = default toolbar
            out["toolbar"] = self.toolbar_order()
        return out


# ------------------------------------------------------------------ main window

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GuildModel  —  Frame CAM")
        self.setMinimumSize(1200, 780)

        # Unsaved-changes tracking (GuildDraw pattern): _dirty drives the title
        # star, the close/open guards, and the autosave timer. _restoring > 0
        # suppresses _mark_dirty during programmatic restores (startup prefs,
        # project open, component-tab activation) so only real user edits count.
        self._dirty = False
        self._restoring = 1          # released at the end of __init__
        self._baseline_dirty_once = False   # recovery: next load baselines dirty

        # Persistent preferences (~/.guildmodel/prefs.json — GuildDraw pattern)
        self._prefs = prefs_mod.load()
        self._dark_mode = bool(self._prefs["dark_mode"])
        # Appearance prefs go into the theme module before any surface is
        # built, so the first paint already honors them.
        _apply_appearance_prefs(self._prefs)
        self._recent_files: list[str] = [
            p for p in self._prefs.get("recent_files", []) if isinstance(p, str)
        ]

        # Readiness traffic-light inputs (M5.2). The dot is a pure function of
        # these three flags (see _refresh_readiness): a DXF is loaded, a 3D
        # model has been built for the current design, and the current program
        # has been stored into the open .gmodel. A design/CAM change that
        # invalidates the stored program clears _program_stored so green never
        # outlives the toolpaths it stood for. Initialised before _connect_signals,
        # which can emit cam_changed during startup restore.
        self._dxf_loaded = False
        self._mesh_built = False
        self._program_stored = False
        # The tessellation's verdict on the current model (BUILDPLAN-NEW UI-0).
        # None = nothing built yet; set by `_set_mesh_verdict` on every build.
        self._mesh_verdict = None

        self._build_ui()
        self._build_toolbar()                     # builds the action registry + toolbar
        self._build_menu()
        self._apply_hotkeys()                     # M7.15 customizable hotkeys

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
        # Worktable undo/redo (M7.4 UX): snapshots of the Worktable taken before a
        # structural edit (remove region / re-tag / load a different bed).
        self._wt_undo: list = []
        self._wt_redo: list = []
        # Set once the maker has answered the "make this the default bed?" prompt for
        # the current bed state; reset on any bed change so a genuinely new bed re-asks.
        self._bed_prompt_answered = False
        self._nest = None                 # core.cam.layout.BedNest (M7.6) once nested
        self._nest_specs = None           # build specs behind the nest (M7.7 bed sim)
        self._nest_thread = None
        self._nest_worker = None
        self._selected_placement_zone = None   # zone id of the footprint being rotated (M-UX)

        # Active component's geometry (mirrors the active workspace)
        self._outline_poly = None
        self._lens_od = None
        self._lens_os = None
        self._partition = None
        self._hinge_polys = []
        self._engraving_curves = []      # ENGRAVING layer polylines (M6.3 temples)
        self._is_temple = False          # outline + no lenses => temple component

        # .gmodel project state (M5.1): the source DXF bytes, the current project
        # file, and the artifacts that go into the container (the last generated
        # program, its setup sheet + machine snapshot, and the last cut report).
        self._source_dxf_bytes: Optional[bytes] = None
        # A whole-model .gdraw is the source for a multi-component project (it has no
        # single DXF); embedding its bytes lets a .gmodel round-trip the whole session.
        self._source_gdraw_bytes: Optional[bytes] = None
        self._source_name = ""
        self._project_path: Optional[Path] = None
        self._last_programs: dict = {}
        self._last_setup: Optional[dict] = None
        self._last_machine: Optional[dict] = None
        self._last_report: Optional[dict] = None

        # Inspector inputs (M7.14): the latest generate warnings + the cut-report
        # object, folded into severity-tagged issues for the Inspector dock. Component
        # diag (per workspace) vs the worktable's own bed diag (clearance + collisions).
        self._diag_reach: list = []
        self._diag_clearance: list = []
        self._diag_lint: list = []
        self._diag_cut_report = None
        self._diag_bed_clearance: list = []
        self._diag_bed_lint: list = []
        self._diag_bed_collisions: list = []

        # Castle preview state: current teaching stage + per-stage mesh cache
        # (cache invalidated whenever a castle parameter changes)
        self._stage = "pockets"
        self._stage_cache: dict[str, object] = {}
        # Real topological edges per stage, from the solid path (Stage 2).
        # None on the raster path — a heightfield mesh has no edges to draw.
        self._edge_cache: dict[str, object] = {}

        # The active view (0 = 2D, 1 = 3D, 2 = Sim) — the single axis the toolbar
        # toggles drive, persisted across tab switches so the chosen view follows you
        # (BUILDPLAN M7.12 unified tab/view model). Each tab maps the three views to
        # its own content: a component → outline / mesh / cut-sim; the Worktable →
        # bed canvas / (no 3D) / bed cut-sim. `_switch_view` is the single source of
        # truth and always re-renders, so a (tab, view) combination is never stale.
        self._current_view = 0
        # Cached cut-sim results so toggling back to Sim is instant; re-run only when
        # the design/CAM (component) or the nest (bed) changes. Active-component cache
        # is cleared on a tab switch (it belonged to the part we left).
        self._active_sim_removal = None
        self._active_sim_report = None
        self._bed_removal = None
        self._bed_report = None
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
        self._restoring = 0          # startup restore done — edits now mark dirty

        # Autosave + crash recovery (GuildDraw pattern): snapshot dirty work to
        # a recovery slot every few minutes; offer to restore it on startup.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self._AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start()
        QTimer.singleShot(400, self._offer_recovery)

        # Diagnostic only (BUILDPLAN known issue): snapshot window state when
        # VTK logs its once-per-session 0×0-framebuffer error.
        self._fbo_probe = _FboProbe(self)
        logging.getLogger().addHandler(self._fbo_probe)

        # The scale decision boot made, into the log pane (BUILDPLAN-NEW UI-0):
        # any wrong-size report becomes diagnosable from a log paste.
        _decision = QApplication.instance().property("guildmodel_scale_decision")
        if _decision:
            self.append_log(f"[ui] {_decision}")

    # ------------------------------------------------------------------ theme

    def _apply_dark_mode(self, dark: bool) -> None:
        """Restyle every surface live (mirrors GuildDraw's _toggle_dark_mode)."""
        self._dark_mode = dark
        app = QApplication.instance()
        if app is not None:
            # Re-derive the scale rather than defaulting it: the stylesheet
            # carries the scaled font sizes, so restyling without it would snap
            # the whole UI back to the design baseline on a theme toggle.
            app.setStyleSheet(theme.stylesheet(
                dark, hidpi.stylesheet_scale(app, self._prefs)))
        self.canvas.set_dark_mode(dark)
        self.view3d.set_dark_mode(dark)
        self.bed_canvas.set_dark_mode(dark)
        self.params.set_dark_mode(dark)
        self.readiness.set_dark_mode(dark)
        self._inspector.set_dark_mode(dark)
        icons_mod.apply_toolbar_icons(self._icon_actions, dark)
        self._fit_toolbar_button_styles()         # icons now set → icon-only vs text
        self._style_toolbar_separators()          # re-tint for the new theme

    def _on_toggle_dark_mode(self, dark: bool) -> None:
        self._apply_dark_mode(dark)
        self._prefs["dark_mode"] = dark
        prefs_mod.save(self._prefs)

    # -------------------------------------------------------------- readiness

    def _refresh_readiness(self) -> None:
        """Drive the status-bar dot from the three readiness flags (M5.2).

        A model the tessellation rejects does not count as built, however
        cheerfully the kernel reported it (BUILDPLAN-NEW UI-0) — the dot is the
        one thing a maker glances at before cutting metal.
        """
        verdict = getattr(self, "_mesh_verdict", None)
        built = self._mesh_built and (verdict is None or verdict.ok)
        self.readiness.set_state(readiness_dot.state_for(
            self._dxf_loaded, built, self._program_stored,
        ))

    def _invalidate_program(self) -> None:
        """A design/CAM change makes any stored program stale → drop to yellow."""
        if self._program_stored:
            self._program_stored = False
            self._refresh_readiness()
        # The drawn toolpaths no longer match the design — clear the overlay (M7.11).
        if getattr(self, "_toolpath_table", None) is not None:
            self._clear_toolpath_overlay()
        # The cached cut sim no longer matches the design/CAM — drop it so the Sim
        # view re-runs (M7.12).
        self._active_sim_removal = None
        self._active_sim_report = None
        if getattr(self, "_act_simulate", None) is not None:
            self._update_view_toggles()

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
        # Context-aware sidebar (BUILDPLAN M7.12 + UX pass): the dock follows both the
        # active tab AND the active view. Component params on a component tab, the
        # worktable controls on the Worktable tab, and a read-only cut verdict while
        # the Simulation view is up — `_sync_dock_page` is the single authority.
        self._dock_stack = QStackedWidget()
        self._dock_stack.addWidget(self.params)              # 0 — component params
        # The worktable panel is tall (file ops, size, region list, nest, rotate,
        # generate) — wrap it in a scroll area so it never forces the right dock's
        # minimum height up (which starved the bottom docks, glitching them over the
        # status bar). The params panel scrolls per-tab for the same reason.
        _wt_scroll = QScrollArea()
        _wt_scroll.setWidgetResizable(True)
        _wt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _wt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _wt_scroll.setWidget(self._worktable_panel)
        self._dock_stack.addWidget(_wt_scroll)               # 1 — worktable controls
        self._dock_stack.addWidget(self._build_sim_panel())  # 2 — simulation verdict
        self._right_dock.setWidget(self._dock_stack)
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

        # Bottom-area docks (M11): Log + Toolpaths tabbed together on the LEFT, the
        # Inspector split BESIDE them on the RIGHT so toolpaths and inspector can be
        # open at once. ORDER MATTERS: establish the log|inspector split FIRST, then
        # tab the toolpaths onto the log — splitting into an already-full tab group
        # only re-tabs (Qt gives the group the whole area, no room to split).
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
        # Fit beside the Inspector: wrap text and let the op column absorb the
        # width instead of forcing a wide fixed table (rc2 dock fix).
        self._toolpath_table.setWordWrap(True)
        tp_hh = self._toolpath_table.horizontalHeader()
        tp_hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tp_hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        from guildmodel.gui.widgets.inspector import InspectorPanel
        self._inspector = InspectorPanel()
        self._inspector.issue_activated.connect(self._on_issue_activated)
        self._inspector_dock = QDockWidget("Inspector", self)
        self._inspector_dock.setObjectName("inspectorDock")
        self._inspector_dock.setWidget(self._inspector)
        self._inspector_dock.setMinimumHeight(120)
        self.splitDockWidget(self._log_dock, self._inspector_dock,
                             Qt.Orientation.Horizontal)        # log | inspector

        self._toolpath_dock = QDockWidget("Toolpaths", self)
        self._toolpath_dock.setObjectName("toolpathDock")
        self._toolpath_dock.setWidget(self._toolpath_table)
        self._toolpath_dock.setMinimumHeight(120)
        self.tabifyDockWidget(self._log_dock, self._toolpath_dock)  # tab onto the log

        self._toolpath_dock.setVisible(False)
        self._inspector_dock.setVisible(False)
        self._log_dock.raise_()                  # keep the log as the front tab by default

        # Status bar: transient message (left) + zoom read-out (permanent right)
        sb = QStatusBar()
        self.status_lbl = QLabel("Ready — open a GuildDraw drawing (.gdraw) or a DXF to begin")
        sb.addWidget(self.status_lbl)
        # measure-tool read-out (M7.13): distance / angle, shown only while measuring
        self._measure_lbl = QLabel("")
        self._measure_lbl.setObjectName("measureLabel")
        self._measure_lbl.setVisible(False)
        sb.addPermanentWidget(self._measure_lbl)
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
        from guildmodel.gui.widgets.bed_canvas import BedCanvas
        from guildmodel.core.project.schema import BedRole, bed_role_label

        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.bed_canvas = BedCanvas()
        self.bed_canvas.region_clicked.connect(self._on_bed_region_clicked)
        self.bed_canvas.component_nudged.connect(self._on_component_nudged)
        self.bed_canvas.component_selected.connect(self._on_bed_placement_selected)
        self.bed_canvas.perimeter_clicked.connect(self._on_perimeter_selected)
        h.addWidget(self.bed_canvas, 1)

        # The worktable controls live in the right dock (the sidebar), so they're
        # available across the bed's 2D + Simulation views — a context-aware sidebar
        # (BUILDPLAN M7.12). The central page is just the bed canvas.
        self._worktable_panel = QWidget()
        self._worktable_panel.setObjectName("worktablePanel")
        v = QVBoxLayout(self._worktable_panel)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        title = QLabel("Worktable")
        title.setObjectName("sectionTitle")
        v.addWidget(title)
        desc = QLabel("Import a bed DXF (or load a saved .bed / the Guild fixture), "
                      "then click each region and tag its role. An outer outline "
                      "around the regions is the bed's work envelope. Keep-outs are "
                      "hold-downs the cutter must avoid.")
        desc.setWordWrap(True)
        desc.setObjectName("mutedSmallLabel")
        v.addWidget(desc)

        # File ops, two per row (Load DXF/BED combines the DXF-import and .bed-load
        # paths — the open dialog dispatches on the file's extension).
        self._bed_load_btn = QPushButton("Load DXF/BED…")
        self._bed_load_btn.setToolTip("Import a bed DXF or open a saved .bed file.")
        self._bed_load_btn.clicked.connect(self._on_load_bed_or_dxf)
        self._bed_default_btn = QPushButton("Load Guild Bed")
        self._bed_default_btn.setToolTip("Load the shipped Guild CNC fixture.")
        self._bed_default_btn.clicked.connect(self._on_load_default_bed)
        self._bed_save_btn = QPushButton("Save Bed…")
        self._bed_save_btn.setToolTip("Save this worktable to a .bed file.")
        self._bed_save_btn.clicked.connect(self._on_save_bed)
        self._bed_setdefault_btn = QPushButton("Set as Default")
        self._bed_setdefault_btn.setToolTip(
            "Make this bed the default that loads with every new session.")
        self._bed_setdefault_btn.clicked.connect(self._on_set_default_bed)
        load_row = QHBoxLayout()
        load_row.addWidget(self._bed_load_btn)
        load_row.addWidget(self._bed_default_btn)
        v.addLayout(load_row)
        save_row = QHBoxLayout()
        save_row.addWidget(self._bed_save_btn)
        save_row.addWidget(self._bed_setdefault_btn)
        v.addLayout(save_row)

        # Bed size = the work envelope (BUILDPLAN M7.4). Click the bed perimeter to
        # select it; edit W × H here. A DXF's outer outline seeds this on import.
        v.addSpacing(6)
        size_title = QLabel("Bed size (work envelope):")
        v.addWidget(size_title)
        size_row = QHBoxLayout()
        self._bed_width_spin = QDoubleSpinBox()
        self._bed_height_spin = QDoubleSpinBox()
        for sp, suffix in ((self._bed_width_spin, " mm W"), (self._bed_height_spin, " mm H")):
            sp.setRange(1.0, 5000.0)
            sp.setDecimals(1)
            sp.setSingleStep(1.0)
            sp.setSuffix(suffix)
            sp.setEnabled(False)
            sp.valueChanged.connect(self._on_bed_size_changed)
        size_row.addWidget(self._bed_width_spin)
        size_row.addWidget(self._bed_height_spin)
        v.addLayout(size_row)

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

        self._bed_remove_btn = QPushButton("Remove Region")
        self._bed_remove_btn.setToolTip(
            "Delete the selected region (e.g. a polygonize sliver or a leftover face).")
        self._bed_remove_btn.setEnabled(False)
        self._bed_remove_btn.clicked.connect(self._on_remove_region)
        v.addWidget(self._bed_remove_btn)

        undo_row = QHBoxLayout()
        self._bed_undo_btn = QPushButton("↶ Undo")
        self._bed_undo_btn.setToolTip("Undo the last bed edit (remove / tag / load).")
        self._bed_undo_btn.setEnabled(False)
        self._bed_undo_btn.clicked.connect(self._on_wt_undo)
        self._bed_redo_btn = QPushButton("↷ Redo")
        self._bed_redo_btn.setToolTip("Redo the last undone bed edit.")
        self._bed_redo_btn.setEnabled(False)
        self._bed_redo_btn.clicked.connect(self._on_wt_redo)
        undo_row.addWidget(self._bed_undo_btn)
        undo_row.addWidget(self._bed_redo_btn)
        v.addLayout(undo_row)

        self._bed_counts = QLabel("No bed loaded")
        self._bed_counts.setObjectName("mutedSmallLabel")
        self._bed_counts.setWordWrap(True)
        v.addWidget(self._bed_counts)

        v.addSpacing(6)
        hd_row = QHBoxLayout()
        hd_row.addWidget(QLabel("Hold-down height:"))
        self._bed_holddown_spin = QDoubleSpinBox()
        self._bed_holddown_spin.setRange(0.0, 80.0)
        self._bed_holddown_spin.setSingleStep(0.5)
        self._bed_holddown_spin.setDecimals(1)
        self._bed_holddown_spin.setSuffix(" mm")
        self._bed_holddown_spin.setValue(8.0)
        self._bed_holddown_spin.setToolTip(
            "Height of the hold-downs (screw heads / clamps) above the bed.")
        self._bed_holddown_spin.valueChanged.connect(self._on_holddown_height_changed)
        hd_row.addWidget(self._bed_holddown_spin)
        v.addLayout(hd_row)

        bz_row = QHBoxLayout()
        bz_row.addWidget(QLabel("Bed zero:"))
        self._bed_zero_combo = QComboBox()
        for label, data in (
            ("Lower-left (bed origin)", ("stock_box", "left", "bottom")),
            ("Lower-right", ("stock_box", "right", "bottom")),
            ("Upper-left", ("stock_box", "left", "top")),
            ("Upper-right", ("stock_box", "right", "top")),
            ("Center", ("stock_box", "center", "center")),
            ("Raw bed coordinates", ("fixture", "left", "bottom")),
        ):
            self._bed_zero_combo.addItem(label, data)
        self._bed_zero_combo.setToolTip(
            "Where the whole-bed worktable.nc touches off G54.")
        self._bed_zero_combo.currentIndexChanged.connect(self._on_bed_zero_changed)
        bz_row.addWidget(self._bed_zero_combo)
        v.addLayout(bz_row)

        v.addSpacing(6)
        self._bed_nest_btn = QPushButton("Nest Components")
        self._bed_nest_btn.setToolTip(
            "Auto-place every component on a role-matched zone (drag to nudge).")
        self._bed_nest_btn.clicked.connect(self._on_nest_components)
        v.addWidget(self._bed_nest_btn)
        self._bed_nest_status = QLabel("")
        self._bed_nest_status.setObjectName("mutedSmallLabel")
        self._bed_nest_status.setWordWrap(True)
        v.addWidget(self._bed_nest_status)

        # Rotate a placed component (M-UX): click a footprint on the bed to select it,
        # then spin it — e.g. face the left temple to the right, or orient both temples
        # for slotted loading. The rotated part posts directly into the worktable.nc.
        v.addSpacing(8)
        rot_title = QLabel("Rotate placement")
        rot_title.setObjectName("sectionTitle")
        v.addWidget(rot_title)
        self._bed_sel_label = QLabel("Click a component footprint on the bed to select it.")
        self._bed_sel_label.setObjectName("mutedSmallLabel")
        self._bed_sel_label.setWordWrap(True)
        v.addWidget(self._bed_sel_label)

        rot_row = QHBoxLayout()
        self._bed_rot_ccw = QPushButton("⟲ 90°")
        self._bed_rot_cw = QPushButton("⟳ 90°")
        self._bed_rot_180 = QPushButton("180°")
        self._bed_rot_ccw.setToolTip("Rotate the selected component 90° counter-clockwise.")
        self._bed_rot_cw.setToolTip("Rotate the selected component 90° clockwise.")
        self._bed_rot_180.setToolTip("Flip the selected component 180°.")
        self._bed_rot_ccw.clicked.connect(lambda: self._rotate_selected_placement(-90.0))
        self._bed_rot_cw.clicked.connect(lambda: self._rotate_selected_placement(90.0))
        self._bed_rot_180.clicked.connect(lambda: self._rotate_selected_placement(180.0))
        for b in (self._bed_rot_ccw, self._bed_rot_cw, self._bed_rot_180):
            rot_row.addWidget(b)
        v.addLayout(rot_row)

        ang_row = QHBoxLayout()
        ang_row.addWidget(QLabel("Angle:"))
        self._bed_rot_spin = QDoubleSpinBox()
        self._bed_rot_spin.setRange(0.0, 359.9)
        self._bed_rot_spin.setDecimals(1)
        self._bed_rot_spin.setSingleStep(5.0)
        self._bed_rot_spin.setWrapping(True)
        self._bed_rot_spin.setSuffix(" °")
        self._bed_rot_spin.setToolTip(
            "Set the selected component's absolute rotation on the bed.")
        self._bed_rot_spin.editingFinished.connect(self._on_bed_rot_spin)
        ang_row.addWidget(self._bed_rot_spin)
        v.addLayout(ang_row)
        self._set_rotation_controls_enabled(False)

        self._bed_gen_btn = QPushButton("Generate Worktable Program")
        self._bed_gen_btn.setToolTip(
            "Post the whole nested bed as one worktable.nc.")
        self._bed_gen_btn.setEnabled(False)
        self._bed_gen_btn.clicked.connect(self._on_generate_worktable_nest)
        v.addWidget(self._bed_gen_btn)

        # The bed cut-sim is driven by the Simulation view toggle (M7.12 unified
        # tab/view model) — no separate button. A hint points the maker there; the
        # Sim toggle enables once the bed is nested.
        self._bed_sim_hint = QLabel(
            "To simulate the bed, switch to the Simulation view "
            "(enabled once components are nested).")
        self._bed_sim_hint.setObjectName("mutedSmallLabel")
        self._bed_sim_hint.setWordWrap(True)
        v.addWidget(self._bed_sim_hint)
        v.addStretch(0)
        return page

    def _ensure_worktable(self):
        """The active bed, defaulting to the user's saved default bed if any, else the
        built-in Guild fixture (M7.4)."""
        if self._worktable is None:
            from guildmodel.core.cam.worktable import startup_worktable as default_worktable
            try:
                self._worktable = default_worktable()
            except Exception:
                self.append_log("[worktable] could not load the default Guild bed:\n"
                                + traceback.format_exc())
                from guildmodel.core.project.schema import Worktable
                self._worktable = Worktable()
        return self._worktable

    def _activate_worktable_tab(self) -> None:
        """Show the Worktable bed. Its views map 2D → bed canvas, Sim → bed cut-sim
        (3D is N/A); the unified `_switch_view` routes to the active view."""
        if 0 <= self._active_ws < len(self._workspaces):
            self._sync_active_workspace()        # persist the component we leave
        self._ensure_worktable()
        self.bed_canvas.set_worktable(self._worktable)
        self._bed_holddown_spin.blockSignals(True)
        self._bed_holddown_spin.setValue(self._worktable.hold_down_height_mm)
        self._bed_holddown_spin.blockSignals(False)
        self._refresh_worktable_panel()
        if self._nest is not None:                 # re-show a prior nest (M7.6)
            self._refresh_nest_render()
        self._right_dock.setVisible(self._act_sidebar.isChecked())
        # The dock page (→ worktable controls) is set by _switch_view / _sync_dock_page.
        self._switch_view(self._current_view)     # bed canvas, or the bed sim if cached
        self._refresh_inspector()                 # show the bed's diagnostics (M7.14)
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

    def _apply_new_worktable(self, wt, *, log_msg: str = "", status_msg: str = "") -> None:
        """Replace the active bed (import / load / default), snapshotting the old bed
        for undo and re-arming the default-bed prompt for this new bed (M7.4)."""
        self._wt_snapshot()                # remember the outgoing bed for Undo
        self._worktable = wt
        self._clear_nest()                 # a new bed invalidates any prior nest
        self.bed_canvas.set_worktable(wt)
        self._refresh_worktable_panel()
        self._bed_prompt_answered = False
        self._mark_dirty()
        if log_msg:
            self.append_log(log_msg)
        if status_msg:
            self.status_lbl.setText(status_msg)

    def _import_bed_dxf(self, path: Path) -> None:
        from guildmodel.core.cam.worktable import WorktableError, build_worktable_from_dxf
        try:
            wt = build_worktable_from_dxf(path)
        except WorktableError as exc:
            QMessageBox.warning(self, "Import bed failed", str(exc))
            return
        except Exception:
            self.append_log("[worktable] import failed:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Import bed failed", "See the log for details.")
            return
        self._apply_new_worktable(
            wt,
            log_msg=f"[worktable] {path.name}: {len(wt.zones)} regions — "
                    "click each and tag its role.",
            status_msg=f"Imported bed: {path.name}  ({len(wt.zones)} regions)")

    def _load_bed_file(self, path: Path) -> None:
        from guildmodel.core.cam.worktable import load_bed
        try:
            wt = load_bed(path)
        except Exception:
            self.append_log("[worktable] load failed:\n" + traceback.format_exc())
            QMessageBox.critical(
                self, "Load bed failed",
                f"Could not read {path.name}. See the log for details.")
            return
        self._apply_new_worktable(
            wt,
            log_msg=f"[worktable] loaded {path.name}: {len(wt.zones)} regions",
            status_msg=f"Loaded bed: {path.name}  ({len(wt.zones)} regions)")

    def _on_load_bed_or_dxf(self) -> None:
        """Load a bed from either a DXF (polygonized) or a saved `.bed`; the dialog
        dispatches on the chosen file's extension (M7.4 UX consolidation)."""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Load bed (DXF or .bed)", self._prefs.get("last_output_dir") or "",
            "Bed files (*.dxf *.bed);;DXF files (*.dxf);;Bed files (*.bed);;All files (*)")
        if not path_str:
            return
        p = Path(path_str)
        if p.suffix.lower() == ".bed":
            self._load_bed_file(p)
        else:
            self._import_bed_dxf(p)

    def _on_import_bed(self) -> None:
        """Import a bed DXF (kept for the menu / tests; the toolbar uses the combined
        Load DXF/BED button)."""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import bed DXF", self._prefs.get("last_output_dir") or "",
            "DXF files (*.dxf);;All files (*)")
        if path_str:
            self._import_bed_dxf(Path(path_str))

    def _on_load_bed(self) -> None:
        """Open a saved `.bed` worktable file (kept for the menu / tests)."""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Load bed", self._prefs.get("last_output_dir") or "",
            "Bed files (*.bed);;All files (*)")
        if path_str:
            self._load_bed_file(Path(path_str))

    def _on_load_default_bed(self) -> None:
        """Load the shipped Guild fixture (always the built-in bed, not the user
        default — this is the explicit 'reset to Guild' action)."""
        from guildmodel.core.cam.worktable import default_worktable
        try:
            wt = default_worktable()
        except Exception:
            self.append_log("[worktable] could not load the Guild bed:\n"
                            + traceback.format_exc())
            return
        self._apply_new_worktable(wt, status_msg="Loaded the Guild standard bed")

    def _on_set_default_bed(self) -> None:
        """Make the current bed the user's default (loads in every new session)."""
        if self._worktable is None:
            return
        from guildmodel.core.cam.worktable import save_user_default_bed
        try:
            save_user_default_bed(self._worktable)
        except Exception:
            self.append_log("[worktable] set-default failed:\n" + traceback.format_exc())
            QMessageBox.critical(self, "Set default failed", "See the log for details.")
            return
        self._bed_prompt_answered = True      # current == default; the save prompt is moot
        self.append_log("[worktable] saved as the default bed")
        self.status_lbl.setText("This bed is now the default")

    # ---- worktable undo / redo (M7.4 UX) -----------------------------------

    def _wt_snapshot(self) -> None:
        """Push the current bed onto the undo stack before a structural edit; clears
        the redo stack and caps the history."""
        if self._worktable is None:
            return
        self._wt_undo.append(self._worktable.model_copy(deep=True))
        del self._wt_undo[:-30]               # keep the last 30 edits
        self._wt_redo.clear()
        self._refresh_wt_undo_buttons()

    def _refresh_wt_undo_buttons(self) -> None:
        if hasattr(self, "_bed_undo_btn"):
            self._bed_undo_btn.setEnabled(bool(self._wt_undo))
            self._bed_redo_btn.setEnabled(bool(self._wt_redo))

    def _on_wt_undo(self) -> None:
        if not self._wt_undo or self._worktable is None:
            return
        self._wt_redo.append(self._worktable.model_copy(deep=True))
        self._worktable = self._wt_undo.pop()
        self._after_wt_restore("Undo")

    def _on_wt_redo(self) -> None:
        if not self._wt_redo or self._worktable is None:
            return
        self._wt_undo.append(self._worktable.model_copy(deep=True))
        self._worktable = self._wt_redo.pop()
        self._after_wt_restore("Redo")

    def _after_wt_restore(self, label: str) -> None:
        """Re-bind the canvas/panel to a bed restored by undo/redo (keeps the maker's
        zoom — a structural change doesn't need a refit)."""
        self._clear_nest()
        self.bed_canvas.set_selected(None)
        self.bed_canvas.refresh(self._worktable)
        self.bed_canvas.update_work_area(
            self._worktable.work_area_width_mm, self._worktable.work_area_height_mm)
        self._refresh_worktable_panel()
        self._bed_prompt_answered = False
        self._mark_dirty()
        self._refresh_wt_undo_buttons()
        self.append_log(f"[worktable] {label}")

    # ---- default-bed prompt (M7.4 UX) --------------------------------------

    def _bed_differs_from_default(self) -> bool:
        """True when the current bed is not the session default (user default, else the
        shipped Guild bed) — the condition to offer 'set as default'."""
        from guildmodel.core.cam.worktable import default_worktable, load_user_default_bed
        if self._worktable is None:
            return False
        try:
            base = (load_user_default_bed() or default_worktable()).model_dump(mode="json")
        except Exception:
            return False
        return self._worktable.model_dump(mode="json") != base

    def _maybe_prompt_default_bed(self) -> None:
        """On save / nested-NC export of a changed bed, offer to make it the default —
        once per bed change, and only while the maker hasn't opted out (M7.4)."""
        if self._worktable is None or self._bed_prompt_answered:
            return
        if not self._prefs.get("prompt_set_default_bed", True):
            return
        if not self._bed_differs_from_default():
            return
        from guildmodel.core.cam.worktable import save_user_default_bed
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Set default bed?")
        box.setText("This worktable differs from your default bed.")
        box.setInformativeText(
            "Make it your default so it loads automatically in new sessions?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        cb = QCheckBox("Don't ask again")
        box.setCheckBox(cb)
        res = box.exec()
        self._bed_prompt_answered = True
        if cb.isChecked():
            self._prefs["prompt_set_default_bed"] = False
            prefs_mod.save(self._prefs)
        if res == QMessageBox.StandardButton.Yes:
            try:
                save_user_default_bed(self._worktable)
                self.append_log("[worktable] set as the default bed")
                self.status_lbl.setText("Default bed updated")
            except Exception:
                self.append_log("[worktable] could not write the default bed:\n"
                                + traceback.format_exc())

    def _on_bed_size_changed(self, _val: float = 0.0) -> None:
        """Bed work-envelope W/H edited — resize the worktable in place (M7.4)."""
        if self._worktable is None:
            return
        w = float(self._bed_width_spin.value())
        h = float(self._bed_height_spin.value())
        self._worktable.work_area_width_mm = w
        self._worktable.work_area_height_mm = h
        self.bed_canvas.update_work_area(w, h)
        self._bed_removal = None            # bed sim / nest bounds depend on the envelope
        self._bed_report = None
        self._bed_prompt_answered = False   # a changed bed re-arms the default prompt
        self._mark_dirty()

    def _on_perimeter_selected(self) -> None:
        """The maker clicked the bed perimeter — select the work envelope: clear any
        region selection and focus the size fields (M7.4)."""
        if self._worktable is None:
            return
        self._bed_region_list.blockSignals(True)
        self._bed_region_list.clearSelection()
        self._bed_region_list.setCurrentRow(-1)
        self._bed_region_list.blockSignals(False)
        self._bed_role_combo.setEnabled(False)
        self._bed_remove_btn.setEnabled(False)
        if self._bed_width_spin.isEnabled():
            self._bed_width_spin.setFocus()
        self.status_lbl.setText(
            f"Bed work envelope: {self._worktable.work_area_width_mm:.0f} × "
            f"{self._worktable.work_area_height_mm:.0f} mm")

    def _on_remove_region(self) -> None:
        """Delete the selected region from the bed (a sliver or a leftover face)."""
        zid = self.bed_canvas.selected_id()
        if zid is None or self._worktable is None:
            return
        try:
            z = self._worktable.zone(zid)
        except KeyError:
            return
        self._wt_snapshot()                # undoable
        self._worktable.zones = [zz for zz in self._worktable.zones if zz.id != zid]
        self._clear_nest()                 # the nest referenced the old zone set
        self.bed_canvas.set_selected(None)
        self.bed_canvas.refresh(self._worktable)
        self._refresh_worktable_panel()
        self._bed_prompt_answered = False
        self._mark_dirty()
        self.append_log(f"[worktable] removed region {z.label or z.id}")

    # ---- nesting (BUILDPLAN M7.6) ------------------------------------------

    def _clear_nest(self) -> None:
        self._nest = None
        self._nest_specs = None
        self._bed_removal = None              # the bed sim no longer matches
        self._bed_report = None
        if hasattr(self, "_bed_nest_status"):
            self._bed_nest_status.setText("")
        if hasattr(self, "_bed_gen_btn"):
            self._bed_gen_btn.setEnabled(False)
        self.bed_canvas.clear_nest()
        self._update_view_toggles()

    def _posting_limits(self, cam):
        """The (machine profile, material dict) any posting path must clamp against.

        Nesting builds the ops and the worktable post consumes them, so both have to
        resolve the same pair — one place to read it from (INCIDENT-2026-07-29)."""
        import yaml
        config_dir = Path(__file__).parent.parent / "config"
        from guildmodel.core.post.machine import load_machine_profile
        mats_cfg = yaml.safe_load((config_dir / "materials.yaml").read_text(encoding="utf-8"))
        mat_name = self.params.material_name()
        return (load_machine_profile(cam.machine_name, config_dir),
                mats_cfg.get(mat_name.split()[0].lower(), mats_cfg["acetate"]))

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

        # The nest's ops ARE the worktable program — built on the posting grid,
        # against the posting machine + material limits (INCIDENT-2026-07-29).
        cam = self.params.cam_params()
        machine, mat = self._posting_limits(cam)
        self._nest_worker = NestWorker(specs, self._worktable, cam_params=cam,
                                       machine=machine, material=mat)
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
        self._mark_dirty()

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
        from guildmodel.core.cam.layout import worktable_clearance_violations
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
        self._bed_removal = None              # a (re)nest invalidates the cached bed sim
        self._bed_report = None
        self._update_view_toggles()           # refresh the Sim-view toggle availability
        self.status_lbl.setText(
            "Bed nested — " + ("all clear" if not all_viol
                               else f"{len(all_viol)} keep-out collision(s)"))
        # Keep the selection valid (its placement may be gone after a re-nest), reflect
        # it on the canvas, and update the rotate controls. The app owns the selection.
        if self._selected_placement() is None:
            self._selected_placement_zone = None
        self.bed_canvas.set_selected_placement(self._selected_placement_zone)
        self._sync_rotation_controls()

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
        self._mark_dirty()

    # ---- rotate a placed component (M-UX) ----------------------------------

    def _selected_placement(self):
        """The nest placement currently selected on the bed, or None."""
        if self._nest is None or not self._selected_placement_zone:
            return None
        for pl in self._nest.placements:
            if pl.zone_id == self._selected_placement_zone:
                return pl
        return None

    def _set_rotation_controls_enabled(self, on: bool) -> None:
        for w in (self._bed_rot_ccw, self._bed_rot_cw, self._bed_rot_180,
                  self._bed_rot_spin):
            w.setEnabled(on)

    def _sync_rotation_controls(self) -> None:
        """Reflect the selected placement on the rotate controls (label + angle)."""
        if not hasattr(self, "_bed_sel_label"):
            return
        pl = self._selected_placement()
        if pl is None:
            self._bed_sel_label.setText(
                "Click a component footprint on the bed to select it.")
            self._set_rotation_controls_enabled(False)
            return
        self._set_rotation_controls_enabled(True)
        self._bed_sel_label.setText(f"Selected: {pl.label}  ·  {pl.rotation_deg:.0f}°")
        self._bed_rot_spin.blockSignals(True)
        self._bed_rot_spin.setValue(pl.rotation_deg % 360.0)
        self._bed_rot_spin.blockSignals(False)

    def _on_bed_placement_selected(self, zone_id: str) -> None:
        """A footprint was clicked on the bed — target the rotate controls at it."""
        self._selected_placement_zone = zone_id or None
        self._sync_rotation_controls()

    def _rotate_selected_placement(self, ddeg: float) -> None:
        """Rotate the selected placement by `ddeg` about its centre, then re-render +
        re-check clearance (no program regeneration — the placed ops carry the spin)."""
        pl = self._selected_placement()
        if pl is None:
            return
        pl.rotate(ddeg)
        self._refresh_nest_render()          # re-extract footprints + re-check clearance
        self.append_log(f"[nest] Rotated {pl.label} to {pl.rotation_deg:.0f}°.")
        self._mark_dirty()

    def _on_bed_rot_spin(self) -> None:
        """The absolute-angle spinbox was edited — rotate to that bed angle."""
        pl = self._selected_placement()
        if pl is None:
            return
        delta = float(self._bed_rot_spin.value()) - pl.rotation_deg
        if abs(delta) > 1e-6:
            self._rotate_selected_placement(delta)

    def _bed_safe_z(self, cam) -> float:
        """Safe rapid height above the tallest obstacle on the bed — the tallest
        stock OR the hold-downs (so rapids clear the screw heads / clamps, M7.12.3)."""
        tops: list[float] = []
        for pl in self._nest.placements:
            z = self._worktable.zone(pl.zone_id) if self._worktable else None
            if z is not None and z.stock_thickness_mm:
                tops.append(float(z.stock_thickness_mm))
        if self._worktable is not None:
            tops.append(float(self._worktable.hold_down_height_mm))
        return (max(tops) if tops else 12.0) + cam.safe_z_clearance_mm

    def _on_holddown_height_changed(self, val: float) -> None:
        """Hold-down height edited — store it on the bed and drop the cached bed sim
        (the collision check + the program's safe-Z depend on it, M7.12.3)."""
        if self._worktable is not None:
            self._worktable.hold_down_height_mm = float(val)
            self._mark_dirty()
        self._bed_removal = None
        self._bed_report = None
        self._update_view_toggles()

    def _on_bed_zero_changed(self, idx: int) -> None:
        """Bed-zero datum edited (M11) — store it on the worktable. The whole-bed
        worktable.nc touches off here; each component keeps its own separate zero."""
        if self._worktable is None or idx < 0:
            return
        from guildmodel.core.project.schema import ProgramZero
        mode, x_ref, y_ref = self._bed_zero_combo.itemData(idx)
        self._worktable.program_zero = ProgramZero(mode=mode, x_ref=x_ref, y_ref=y_ref)
        self._mark_dirty()

    def _on_generate_worktable_nest(self) -> None:
        """Post the whole nested bed as one ``worktable.nc`` (BUILDPLAN M7.7).

        Generalises the M6.5 fixture worktable onto the user-tagged ``Worktable`` +
        the multi-component nest (M7.6): one combined, tool-change-minimised program,
        linted + keep-out-clearance-checked + cut-timed over the whole bed, stored in
        the project. The component programs were already generated by Nest Components
        — on the posting grid, under the posting machine limits — so this is a fast
        post (no relief rebuild). Per-component tabs still Generate each part on its
        own — this is the bed-wide output."""
        if self._nest is None or not self._nest.placements:
            QMessageBox.information(
                self, "Nest first",
                "Click Nest Components to place the model on the bed, then generate "
                "the worktable program.")
            return
        from guildmodel.core.cam.castle_ops import (
            CastleCamParams, build_tool_settings, op_summaries, write_castle_program,
        )
        from guildmodel.core.cam.cuttime import (
            MachineDynamics, estimate_program, format_report,
        )
        from guildmodel.core.cam.layout import (
            build_nest_program, worktable_clearance_violations,
        )
        from guildmodel.core.post.grbl import GRBLPost
        from guildmodel.core.post.machine import clamp_cam_to_machine, lint_program

        try:
            cam = self.params.cam_params() or CastleCamParams()
            tools_cfg = _tools_cfg()
            machine, mat = self._posting_limits(cam)
            mat_name = self.params.material_name()
            # The same clamp Nest Components generated these ops under — the post
            # must not re-open feeds/stepdown the ops were built to respect.
            cam, clamp = clamp_cam_to_machine(cam, machine, mat)
            for w in clamp.warnings:
                self.append_log(f"[gcode] machine: {w}")

            bed = build_nest_program(self._nest)
            if not bed.ops:
                QMessageBox.information(self, "Nothing to cut",
                                       "The nested components produced no toolpaths.")
                return
            self.append_log(
                f"[gcode] Worktable: {len(bed.placements)} part(s), {len(bed.ops)} ops, "
                f"{bed.n_tool_changes} tool change(s) (grouped by tool).")

            tool_settings, ts_warns = build_tool_settings(
                bed.ops, tools_cfg, default_feed=clamp.feed_rate_mmpm,
                default_plunge=clamp.plunge_rate_mmpm, default_spindle=clamp.spindle_rpm,
                machine=machine)
            for w in ts_warns:
                self.append_log(f"[gcode] tool: {w}")

            violations = worktable_clearance_violations(
                bed.ops, self._worktable, skip_op_names=bed.drill_op_names)
            for vmsg in violations:
                self.append_log(f"[gcode] WARNING: {vmsg}")

            first_ts = tool_settings[bed.ops[0].tool_name]
            bed_offset = self._worktable.bed_work_offset()
            self.append_log(
                f"[gcode] Bed zero: {self._worktable.program_zero.label()} · "
                f"offset ({bed_offset[0]:+.2f}, {bed_offset[1]:+.2f}) mm")
            post = GRBLPost(
                job_name="worktable", material=mat_name,
                tool_diameter_mm=first_ts.diameter_mm, spindle_rpm=first_ts.spindle_rpm,
                feed_rate_mmpm=first_ts.feed_rate_mmpm,
                plunge_rate_mmpm=first_ts.plunge_rate_mmpm,
                safe_z_mm=self._bed_safe_z(cam), work_offset=bed_offset)
            write_castle_program(
                bed.ops, post, side="Worktable", arc_tol_mm=clamp.arc_tol_mm,
                contour_stepdown_mm=cam.contour_stepdown_mm,
                contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
                contour_lead_in=cam.contour_lead_in,
                tool_settings=tool_settings, tool_change_mode=machine.tool_change_mode,
                contour_op_names=bed.contour_op_names, drill_op_names=bed.drill_op_names)
            text = post.to_string()

            machine_warnings = lint_program(text, machine)
            for w in machine_warnings:
                self.append_log(f"[gcode] ⚠ machine: {w}")
            self._diag_bed_clearance = list(violations)    # feed the Inspector (M7.14)
            self._diag_bed_lint = list(machine_warnings)
            self._diag_bed_collisions = []                 # stale until the bed re-sims
            self._refresh_inspector()
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

        # Fold straight into an open project (single DXF or whole .gdraw model — both
        # are embedded, so the container stays self-contained).
        if self._project_path is not None and (
                self._source_dxf_bytes is not None or self._source_gdraw_bytes is not None):
            self._save_gmodel_to(self._project_path, announce=False)
            self.append_log(
                f"[project] Updated {self._project_path.name} with the worktable program.")
        else:
            self._mark_dirty()       # program held in memory until Save Project
        self.status_lbl.setText("Worktable G-code ready")
        QMessageBox.information(self, "Worktable program", summary)
        self._maybe_prompt_default_bed()   # offer to keep this bed as the default

    def _start_bed_sim(self) -> None:
        """Run the whole nested bed's cut sim off-thread (driven by the Sim view on
        the Worktable tab, BUILDPLAN M7.12). The Sim toggle is only enabled when the
        bed is nested and the view is already in sim mode (the caller switched it)."""
        if self._nest is None or not self._nest.placements or not self._nest_specs:
            return
        if self._sim_thread is not None and self._sim_thread.isRunning():
            return
        self.view3d.clear_sim()                   # no stale block while this runs
        self.status_lbl.setText("Simulating bed…")
        self.append_log("[bed-sim] Simulating the whole nested bed…")

        self._sim_worker = BedSimWorker(
            self._nest_specs, self._nest.placements,
            (self._worktable.work_area_width_mm, self._worktable.work_area_height_mm),
            cam_params=self.params.effective_cam_params(),
            material_name=self.params.effective_material_name())
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

    def _on_sim_bed_finished(self, report, lines, plan=None) -> None:
        self._close_progress()
        # Hold-down collision check (M7.12.3): the tool/holder envelope vs the bed's
        # keep-outs, flagged per toolpath position and rendered on the bed.
        if plan is not None and self._worktable is not None:
            from guildmodel.core.sim import plan_collisions
            h = float(self._worktable.hold_down_height_mm)
            keep_outs = []
            for z in self._worktable.keep_outs():
                cx, cy = z.center()
                r = z.radius_mm if z.radius_mm else max(z.width(), z.height()) / 2.0
                keep_outs.append((cx, cy, float(r)))
            plan.keep_outs = keep_outs
            plan.hold_down_height_mm = h
            plan.collision_pos = plan_collisions(plan, keep_outs, h)
            ncol = int(plan.collision_pos.sum())
            self._diag_bed_collisions = (                 # feed the Inspector (M7.14)
                [f"The tool or its holder passes over a hold-down at {ncol} point(s) "
                 f"of the bed cut — raise the hold-down height ({h:.1f} mm now) or "
                 "reposition the part"] if ncol else [])
            self._refresh_inspector()
            if ncol:
                self.append_log(
                    "[bed-sim] ⚠ the tool or its holder passes over a hold-down — "
                    "check clearance (highlighted red in the 3D view).")
                # Robust warning up front (the per-frame pause needs you to press play).
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "Hold-down collision",
                    "The tool or its holder reaches a hold-down during this bed cut "
                    "(flagged on the badge; the tool turns red there).\n\n"
                    "Play or scrub the Simulation to see where, then reposition the part, "
                    "raise the hold-down height, or adjust the toolpath before cutting."))
        self._bed_report = report                 # cache for instant Sim re-toggle (M7.12)
        self._bed_removal = plan
        self.view3d.show_report(report)           # badge
        self.view3d.set_plan(plan)                # volumetric bed block (M7.12.3)
        self._update_view_toggles()
        for line in lines:
            self.append_log("[bed-sim] " + line)
        self.status_lbl.setText({
            "ok": "Bed verified — every component reached",
            "warn": "Bed simulated — review the flagged regions",
            "fail": "Bed incomplete — see the flagged regions",
        }.get(report.status(), "Bed simulated"))

    def _on_sim_bed_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[bed-sim ERROR]\n" + tb)
        self.status_lbl.setText("Bed simulation failed — see log")
        self._update_view_toggles()

    def _on_sim_bed_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[bed-sim] Cancelled.")
        self.status_lbl.setText("Bed simulation cancelled")
        self._update_view_toggles()

    def _on_save_bed(self) -> None:
        if self._worktable is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save worktable", "worktable.bed",
            "Bed files (*.bed);;All files (*)")
        if not path_str:
            return
        from guildmodel.core.cam.worktable import save_bed
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
        from guildmodel.core.project.schema import BedRole, bed_role_label
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
        self._bed_remove_btn.setEnabled(zone_id is not None)
        if zone_id is not None and self._worktable is not None:
            z = self._worktable.zone(zone_id)
            self._bed_role_combo.blockSignals(True)
            idx = self._bed_role_combo.findData(BedRole(z.role).value)
            if idx >= 0:
                self._bed_role_combo.setCurrentIndex(idx)
            self._bed_role_combo.blockSignals(False)
            self.status_lbl.setText(f"Region {zone_id}: {bed_role_label(z.role)}")

    def _on_bed_role_changed(self, idx: int) -> None:
        from guildmodel.core.project.schema import BedRole, bed_role_label
        zid = self.bed_canvas.selected_id()
        if zid is None or self._worktable is None or idx < 0:
            return
        role = self._bed_role_combo.itemData(idx)
        if self._worktable.zone(zid).role == BedRole(role):
            return                          # no-op (e.g. reselecting the same role)
        self._wt_snapshot()                 # undoable
        z = self._worktable.set_role(zid, BedRole(role))
        self.bed_canvas.refresh(self._worktable)
        self._refresh_worktable_panel(keep_selection=zid)
        self._bed_prompt_answered = False
        self.append_log(f"[worktable] {zid} → {bed_role_label(z.role)}")
        self._mark_dirty()

    def _refresh_worktable_panel(self, keep_selection=None) -> None:
        from guildmodel.core.project.schema import bed_role_label
        wt = self._worktable
        self._bed_region_list.blockSignals(True)
        self._bed_region_list.clear()
        if wt is not None:
            for z in wt.zones:
                it = QListWidgetItem(f"{z.label or z.id}  ·  {bed_role_label(z.role)}")
                it.setData(Qt.ItemDataRole.UserRole, z.id)
                self._bed_region_list.addItem(it)
        self._bed_region_list.blockSignals(False)

        for btn in (self._bed_save_btn, self._bed_setdefault_btn):
            btn.setEnabled(wt is not None)
        self._bed_remove_btn.setEnabled(False)     # re-enabled below if a region stays selected
        for sp in (self._bed_width_spin, self._bed_height_spin):
            sp.setEnabled(wt is not None)
            sp.blockSignals(True)
        if wt is not None:
            self._bed_width_spin.setValue(wt.work_area_width_mm)
            self._bed_height_spin.setValue(wt.work_area_height_mm)
        for sp in (self._bed_width_spin, self._bed_height_spin):
            sp.blockSignals(False)
        self._bed_zero_combo.setEnabled(wt is not None)
        self._bed_zero_combo.blockSignals(True)
        if wt is not None:
            pz = wt.program_zero
            want = (("fixture", "left", "bottom") if pz.mode == "fixture"
                    else (pz.mode, pz.x_ref, pz.y_ref))
            for i in range(self._bed_zero_combo.count()):
                if self._bed_zero_combo.itemData(i) == want:
                    self._bed_zero_combo.setCurrentIndex(i)
                    break
        self._bed_zero_combo.blockSignals(False)
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
        # A horizontal toolbar's separators are vertical (thickness = width); a vertical
        # toolbar's are horizontal (thickness = height). One static QSS rule can't serve
        # both, so we restyle live whenever the toolbar is re-docked (restoreState may
        # move it from the default left edge to the top).
        tb.orientationChanged.connect(lambda *_: self._style_toolbar_separators())

        # The .gdraw drawing is the featured open (Ctrl+O, toolbar) — GuildDraw
        # is the ecosystem's native design source; a bare DXF stays available
        # on Ctrl+Shift+O for makers with their own CAD workflow (rc2).
        self._act_open = QAction("Open DXF", self)
        self._act_open.setShortcut("Ctrl+Shift+O")
        self._act_open.setToolTip("Open a DXF…  (Ctrl+Shift+O)")
        self._act_open.triggered.connect(self._on_open)

        self._act_open_model = QAction("Open Drawing…", self)
        self._act_open_model.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open_model.setToolTip(
            "Open a GuildDraw drawing (.gdraw)  (Ctrl+O)")
        self._act_open_model.triggered.connect(self._on_open_model)

        self._act_open_project = QAction("Open Project…", self)
        self._act_open_project.setToolTip("Open a GuildModel .gmodel project")
        self._act_open_project.triggered.connect(self._on_open_project)
        self._act_save_project = QAction("Save Project", self)
        self._act_save_project.setShortcut("Ctrl+S")
        self._act_save_project.setToolTip("Save the project  (Ctrl+S)")
        self._act_save_project.triggered.connect(self._on_save_project)
        self._act_save_project_as = QAction("Save Project As…", self)
        self._act_save_project_as.setToolTip("Save the project to a new .gmodel file")
        self._act_save_project_as.triggered.connect(self._on_save_project_as)

        self._act_build = QAction("Build 3D Model", self)
        self._act_build.setShortcut("F5")
        self._act_build.setToolTip("Build the 3D model  (F5)")
        self._act_build.setEnabled(False)
        self._act_build.triggered.connect(self._on_build_3d)

        self._act_gcode = QAction("Generate G-code", self)
        self._act_gcode.setShortcut("Ctrl+G")
        self._act_gcode.setToolTip("Generate the G-code program  (Ctrl+G)")
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
            "Export the program to a .nc file…  (Ctrl+Shift+G)")
        self._act_export_nc.setEnabled(False)
        self._act_export_nc.triggered.connect(self._on_export_nc)

        self._act_block = QAction("Generate Base-Curve Block", self)
        self._act_block.setToolTip(
            "Generate the base-curve heat-forming block from the frame's lens")
        self._act_block.setEnabled(False)
        self._act_block.triggered.connect(self._on_generate_block)

        # "Open in GuildSend" RETIRED from the menu (rc2, user decision): the
        # three tools stand alone — GuildSend natively opens .gmodel jobs, just
        # as GuildModel natively opens .gdraw drawings — so a cross-launch
        # button is unnecessary coupling. The action, its launcher
        # (_on_open_in_guildsend / _find_guildsend), and the hotkey-registry row
        # are kept but disconnected in case the decision is revisited.
        self._act_send = QAction("Open in GuildSend", self)
        self._act_send.setToolTip(
            "Hand the saved .gmodel job to GuildSend, the ecosystem's sender —\n"
            "programs, setup sheet, tools, and the tagged worktable travel whole")
        self._act_send.setEnabled(False)          # tracks Export G-code
        self._act_send.triggered.connect(self._on_open_in_guildsend)
        # A stored program enables both actions — mirror the single authority
        # instead of duplicating every setEnabled site.
        self._act_export_nc.changed.connect(
            lambda: self._act_send.setEnabled(self._act_export_nc.isEnabled()))

        self._act_worktable = QAction("Generate Worktable Program", self)
        self._act_worktable.setToolTip(
            "Cut the frame and its base-curve block in one bed program")
        self._act_worktable.setEnabled(False)
        self._act_worktable.triggered.connect(self._on_generate_worktable)

        self._act_view2d = QAction("2D Outline", self, checkable=True)
        self._act_view2d.setChecked(True)
        self._act_view2d.setToolTip("2D outline view")
        self._act_view2d.triggered.connect(lambda: self._switch_view(0))
        self._act_view3d = QAction("3D Preview", self, checkable=True)
        self._act_view3d.setToolTip("3D preview view")
        self._act_view3d.triggered.connect(lambda: self._switch_view(1))

        # The Simulation view — the third view toggle (2D / 3D / Sim). On a component
        # it cut-sims that part; on the Worktable tab it cut-sims the whole bed.
        # Disabled until there's something to simulate, guiding the maker (M7.12).
        self._act_simulate = QAction("Simulation", self, checkable=True)
        self._act_simulate.setShortcut("Ctrl+Shift+S")
        self._act_simulate.setToolTip(
            "Simulate the cut and verify the result  (Ctrl+Shift+S)")
        self._act_simulate.setEnabled(False)
        self._act_simulate.triggered.connect(lambda: self._switch_view(2, run=True))

        # Measure tool (M7.13) — a 2D-canvas inspect mode: click points (snapped to
        # curve vertices) to read a distance or a corner angle. Only the component
        # outline view; toggling it on switches there.
        self._act_measure = QAction("Measure", self, checkable=True)
        self._act_measure.setShortcut("M")
        self._act_measure.setToolTip(
            "Measure distance / angle on the 2D outline  (M)")
        self._act_measure.setEnabled(False)
        self._act_measure.toggled.connect(self._on_toggle_measure)

        self._act_show_worktable = QAction("Worktable", self)
        self._act_show_worktable.setShortcut("Ctrl+B")
        self._act_show_worktable.setToolTip(
            "Open the worktable bed  (Ctrl+B)")
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
        self._act_log.triggered.connect(self._toggle_log_dock)
        self._log_dock.visibilityChanged.connect(self._act_log.setChecked)

        # triggered, NOT toggled: dragging a dock makes Qt hide/re-show it
        # mid-drag → visibilityChanged → setChecked → toggled — and a
        # splitDockWidget from inside that cascade re-docks the widget out
        # from under Qt's drag handler (native crash). `triggered` only fires
        # on a real user click, never from programmatic setChecked.
        self._act_toolpaths = QAction("Toolpaths", self, checkable=True)
        self._act_toolpaths.setToolTip("Show/hide the toolpaths panel")
        self._act_toolpaths.triggered.connect(self._toggle_toolpath_dock)
        self._toolpath_dock.visibilityChanged.connect(self._act_toolpaths.setChecked)

        self._act_inspector = QAction("Inspector", self, checkable=True)
        self._act_inspector.setToolTip("Show/hide the inspector panel")
        self._act_inspector.triggered.connect(self._toggle_inspector_dock)
        self._inspector_dock.visibilityChanged.connect(self._act_inspector.setChecked)

        # (action, icon-name) for the runtime recolor hook (text fallback if
        # the SVG is missing). op-fit / view-sidebar are reused from GuildDraw.
        self._icon_actions = [
            (self._act_open_model, "op-open-dxf"),   # toolbar: open a .gdraw model
            (self._act_open, "op-open-dxf"),         # File menu: open a DXF
            (self._act_build, "op-build-3d"),
            (self._act_gcode, "op-gcode"),
            (self._act_export_nc, "op-export-gcode"),
            (self._act_export, "op-export-stl"),
            (self._act_view2d, "view-2d"),
            (self._act_view3d, "view-3d"),
            (self._act_simulate, "sim-cut"),
            (self._act_measure, "measure"),
            # Worktable is reached via its own component tab (and View ▸ Worktable /
            # Ctrl+B); it deliberately has no toolbar icon, so if the maker adds it to
            # the toolbar it reads as a text label rather than a second Fit magnifier.
            (self._act_fit, "op-fit"),
            (self._act_log, "toggle-log"),
            (self._act_toolpaths, "toggle-toolpaths"),
            (self._act_inspector, "toggle-inspector"),
            (self._act_sidebar, "view-sidebar"),
        ]
        # Build the customizable action registry, then assemble the toolbar from the
        # saved/default order (M7.15). Groups get auto-inserted ToolSep dividers
        # (painted, not stylesheet → identical on fractional-DPI screens).
        self._tool_seps: list[ToolSep] = []
        self._build_action_registry()
        self._rebuild_toolbar()

    # Bottom-row dock arrangement (rc2 fix): a dragged or stale-saved layout
    # could leave Toolpaths and Inspector in ONE tab group, making them
    # impossible to show side-by-side. Every user-driven show re-asserts the
    # canonical arrangement — Log+Toolpaths tabbed on the left, Inspector
    # split beside them — so both can share the row; with only one visible,
    # Qt gives it the whole row. The re-arrangement is DEFERRED (singleShot 0)
    # so it can never run inside a Qt dock-drag cascade, and a floating panel
    # is left where the user put it.

    def _toggle_log_dock(self, on: bool) -> None:
        # The log shares a tab group with Toolpaths: shown BEHIND the front
        # tab, Qt reports it not-visible — isVisible() can't express the
        # user's intent there, so track it explicitly. Same triggered +
        # deferred-arrange pattern as the other bottom panels.
        self._log_want = on
        self._log_dock.setVisible(on)
        if on:
            QTimer.singleShot(0, self._arrange_log_dock)

    def _arrange_log_dock(self) -> None:
        if not getattr(self, "_log_want", True):
            return
        if not self._log_dock.isFloating():
            self._log_dock.setVisible(True)
            self._log_dock.raise_()             # front tab → visible → checked
        self._act_log.setChecked(True)

    def _toggle_toolpath_dock(self, on: bool) -> None:
        self._toolpath_dock.setVisible(on)
        if on:
            QTimer.singleShot(0, self._arrange_toolpath_dock)

    def _arrange_toolpath_dock(self) -> None:
        if self._toolpath_dock.isVisible() and not self._toolpath_dock.isFloating():
            self.tabifyDockWidget(self._log_dock, self._toolpath_dock)
            self._toolpath_dock.raise_()

    def _toggle_inspector_dock(self, on: bool) -> None:
        self._inspector_dock.setVisible(on)
        if on:
            QTimer.singleShot(0, self._arrange_inspector_dock)

    def _arrange_inspector_dock(self) -> None:
        if self._inspector_dock.isVisible() and not self._inspector_dock.isFloating():
            self.splitDockWidget(self._log_dock, self._inspector_dock,
                                 Qt.Orientation.Horizontal)
            self._inspector_dock.raise_()

    def _rebuild_toolbar(self) -> None:
        """(Re)assemble the toolbar from the effective action order (M7.15): the saved
        selection/order from prefs, or the shipped default. A ToolSep divider is added
        at every group boundary, so grouping survives reordering; an action without an
        icon falls back to its text label so it isn't a blank button."""
        from guildmodel.gui.shortcuts import effective_toolbar
        tb = self._toolbar
        tb.clear()
        self._tool_seps = []
        spec_by_key = {s.key: s for s in self._action_specs}
        order = effective_toolbar(self._action_specs, self._prefs.get("toolbar", []))
        prev_group = None
        for key in order:
            spec = spec_by_key.get(key)
            act = self._actions_by_key.get(key)
            if spec is None or act is None:
                continue
            if prev_group is not None and spec.group != prev_group:
                sep = ToolSep(tb)
                self._tool_seps.append(sep)
                tb.addWidget(sep)
            tb.addAction(act)
            prev_group = spec.group
        self._fit_toolbar_button_styles()
        self._style_toolbar_separators()

    def _fit_toolbar_button_styles(self) -> None:
        """Icon-only where the action has an icon, text-only where it doesn't (so a
        user-added iconless action shows a label rather than a blank button)."""
        from PySide6.QtWidgets import QToolButton
        for act in self._toolbar.actions():
            btn = self._toolbar.widgetForAction(act)
            if isinstance(btn, QToolButton):
                btn.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly if not act.icon().isNull()
                    else Qt.ToolButtonStyle.ToolButtonTextOnly)

    def _style_toolbar_separators(self) -> None:
        """Re-tint + re-orient the custom ToolSep dividers (BUILDPLAN M7.12 UI). Run on
        re-dock + theme change. Charcoal on light / a darker amber on dark keeps them
        subtle but well-defined against either toolbar background."""
        colour = "#8d7030" if self._dark_mode else "#383838"
        for sep in getattr(self, "_tool_seps", []):
            sep.set_color(colour)
            sep.refresh()                             # flip axis for the new orientation

    # -------------------------------------------------- customizable actions (M7.15)

    def _build_action_registry(self) -> None:
        """The customizable action set for Preferences ▸ Hotkeys / Toolbar (M7.15).
        Default shortcuts are captured live from the actions, so the table always
        mirrors the shipped bindings; `group` drives the rebuilt toolbar's dividers."""
        from guildmodel.gui.shortcuts import ActionSpec
        # (key, action, label, group, on-default-toolbar)
        rows = [
            ("open_model", self._act_open_model, "Open Drawing", "input", True),
            ("open", self._act_open, "Open DXF", "input", False),
            ("open_project", self._act_open_project, "Open Project", "input", False),
            ("save_project", self._act_save_project, "Save Project", "input", False),
            ("save_project_as", self._act_save_project_as, "Save Project As", "input", False),
            ("build", self._act_build, "Build 3D Model", "build", True),
            ("gcode", self._act_gcode, "Generate G-code", "build", True),
            ("export_nc", self._act_export_nc, "Export G-code", "build", True),
            ("export", self._act_export, "Export STL", "build", True),
            # ("send_guildsend", self._act_send, "Open in GuildSend", "build", False),  # retired rc2
            ("block", self._act_block, "Generate Base-Curve Block", "build", False),
            ("worktable_gen", self._act_worktable, "Generate Worktable Program", "build", False),
            ("view2d", self._act_view2d, "2D View", "view", True),
            ("view3d", self._act_view3d, "3D View", "view", True),
            ("simulate", self._act_simulate, "Simulation", "view", True),
            ("measure", self._act_measure, "Measure", "view", True),
            ("show_worktable", self._act_show_worktable, "Worktable", "view", False),
            ("fit", self._act_fit, "Fit to View", "view", True),
            ("log", self._act_log, "Log Panel", "panels", True),
            ("toolpaths", self._act_toolpaths, "Toolpaths Panel", "panels", True),
            ("inspector", self._act_inspector, "Inspector Panel", "panels", True),
            ("sidebar", self._act_sidebar, "Parameters Panel", "panels", True),
        ]
        self._actions_by_key = {key: act for key, act, *_ in rows}
        self._action_specs = [
            ActionSpec(key, label, act.shortcut().toString(), group, tb_default)
            for key, act, label, group, tb_default in rows
        ]

    def _apply_hotkeys(self) -> None:
        """Bind every registered action's shortcut from prefs (override or default)."""
        from guildmodel.gui.shortcuts import effective_shortcuts
        from PySide6.QtGui import QKeySequence
        eff = effective_shortcuts(self._action_specs, self._prefs.get("hotkeys", {}))
        for key, sc in eff.items():
            act = self._actions_by_key.get(key)
            if act is not None:
                act.setShortcut(QKeySequence(sc) if sc else QKeySequence())

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
        file_menu.addAction(self._act_save_project_as)
        file_menu.addSeparator()
        file_menu.addAction(self._act_build)
        file_menu.addAction(self._act_gcode)
        file_menu.addAction(self._act_block)
        file_menu.addAction(self._act_worktable)
        file_menu.addAction(self._act_export_nc)
        file_menu.addAction(self._act_export)
        file_menu.addSeparator()
        # file_menu.addAction(self._act_send)   # retired rc2 — see _act_send note
        # file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._act_view2d)
        view_menu.addAction(self._act_view3d)
        view_menu.addAction(self._act_simulate)
        view_menu.addAction(self._act_measure)
        view_menu.addAction(self._act_show_worktable)
        view_menu.addAction(self._act_fit)
        view_menu.addSeparator()
        view_menu.addAction(self._act_sidebar)
        view_menu.addAction(self._act_log)
        view_menu.addAction(self._act_toolpaths)
        view_menu.addAction(self._act_inspector)

        # Settings menu mirrors GuildDraw: Dark Mode toggle + Preferences…
        settings_menu = mb.addMenu("&Settings")
        self._act_dark = QAction("Dark Mode", self, checkable=True, checked=False)
        self._act_dark.triggered.connect(self._on_toggle_dark_mode)
        settings_menu.addAction(self._act_dark)
        settings_menu.addSeparator()
        # Ctrl+, — the ecosystem-wide Preferences shortcut (GuildSend set the
        # convention; GuildDraw and GuildModel now match). Kept on self: a
        # text+slot addAction's wrapper is Python-owned in PySide6, and losing
        # the last reference deletes the underlying QAction.
        self._act_prefs = settings_menu.addAction(
            "Preferences…", self._open_preferences)
        self._act_prefs.setShortcut(QKeySequence("Ctrl+,"))

        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About GuildModel", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ------------------------------------------------------------------ window state

    def _restore_window_state(self) -> None:
        geo = self._prefs.get("main_window_geometry", "")
        state = self._prefs.get("main_window_state", "")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        # restoreState reinstates dock sizes/visibility — but ONLY when the saved
        # layout version matches. Bumping _DOCK_STATE_VERSION invalidates a stale
        # saved layout (e.g. the pre-M11 tabbed inspector) so the new code default
        # (inspector split beside the toolpaths) takes effect; restoreState then
        # returns False and we keep the default.
        if state and self.restoreState(
                QByteArray.fromBase64(state.encode()), _DOCK_STATE_VERSION):
            self._act_sidebar.setChecked(self._right_dock.isVisible())
            self._act_log.setChecked(self._log_dock.isVisible())
        self._style_toolbar_separators()          # match the restored dock orientation

    def _save_window_state(self) -> None:
        self._prefs["main_window_geometry"] = bytes(
            self.saveGeometry().toBase64()
        ).decode()
        self._prefs["main_window_state"] = bytes(
            self.saveState(_DOCK_STATE_VERSION).toBase64()
        ).decode()
        prefs_mod.save(self._prefs)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self._clear_autosave()
        self._save_window_state()
        super().closeEvent(event)

    # ------------------------------------------------------------------ unsaved changes

    def _update_title(self) -> None:
        """Window title: the open project (or source design) plus a dirty star."""
        if self._project_path is not None:
            name = self._project_path.name
        else:
            name = self._source_name or "Frame CAM"
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"GuildModel  —  {name}{star}")

    def _mark_dirty(self) -> None:
        if self._restoring:
            return
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _clear_dirty(self) -> None:
        self._dirty = False
        self._update_title()

    def _confirm_discard(self) -> bool:
        """If there are unsaved changes, offer Save / Discard / Cancel.

        Returns True when it is safe to proceed (saved, discarded, or clean).
        """
        if not self._dirty:
            return True
        r = QMessageBox.warning(
            self, "Unsaved changes",
            "This project has unsaved changes.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            self._on_save_project()
            return not self._dirty   # False if the save dialog was cancelled
        return True   # Discard

    def _post_load_baseline(self) -> None:
        """Set the dirty baseline after a design finishes loading: clean for a
        fresh open/import or a project reopen; dirty when the load restored the
        crash-recovery snapshot (recovered work is unsaved by definition)."""
        if self._baseline_dirty_once:
            self._baseline_dirty_once = False
            self._dirty = True
            self._update_title()
        else:
            self._clear_dirty()

    # ------------------------------------------------------------------ autosave + crash recovery

    _AUTOSAVE_MS = 180_000   # 3 minutes

    @staticmethod
    def _autosave_dir() -> Path:
        # Resolved lazily (not a class constant) so a redirected home — e.g.
        # the test harness's per-test HOME — is honored.
        return Path.home() / ".guildmodel" / "autosave"

    def _autosave_paths(self) -> tuple[Path, Path]:
        d = self._autosave_dir()
        return d / "recovery.gmodel", d / "recovery.json"

    def _do_autosave(self) -> None:
        """Timer tick: snapshot dirty work to the recovery slot.

        Must never interrupt the user — failures are silent; success shows a
        brief status note.
        """
        if not self._dirty:
            return
        if self._source_dxf_bytes is None and self._source_gdraw_bytes is None:
            return                    # nothing loaded — nothing worth recovering
        rec, meta = self._autosave_paths()
        try:
            self._autosave_dir().mkdir(parents=True, exist_ok=True)
            tmp = Path(str(rec) + ".tmp")
            self._write_gmodel(tmp)
            os.replace(tmp, rec)
            meta.write_text(json.dumps({
                "source_path": str(self._project_path) if self._project_path else None,
                "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }), encoding="utf-8")
            self.statusBar().showMessage("Autosaved", 2000)
        except Exception:
            pass

    def _clear_autosave(self) -> None:
        for p in self._autosave_paths():
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def _offer_recovery(self) -> None:
        """On startup: if a recovery autosave exists, offer to restore it."""
        rec, meta = self._autosave_paths()
        if not rec.exists():
            return
        source = None
        when = "an unknown time"
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            source = info.get("source_path")
            when = info.get("saved_at", when)
        except Exception:
            pass
        name = os.path.basename(source) if source else "an unsaved project"
        r = QMessageBox.question(
            self, "Recover unsaved work?",
            f"GuildModel found autosaved work from {when}\n({name}).\n\n"
            "Restore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            self._clear_autosave()
            return
        self._baseline_dirty_once = True   # recovered work is unsaved
        self._open_project(rec, remember=False)
        # The recovered content belongs to the original project, not the
        # recovery file: restore the real path and mark it unsaved.
        self._project_path = (Path(source) if source and os.path.isfile(source)
                              else None)
        self._update_title()

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
        if not self._confirm_discard():
            return
        self.open_path(path)

    def open_path(self, path: str) -> None:
        """Open any supported file by suffix — a .gmodel project, a .gdraw/.svg
        drawing, or a DXF. Used by the recent-files menu and by a file passed on
        the command line (the installer's file association)."""
        lower = path.lower()
        if lower.endswith(".gmodel"):
            self._open_project(Path(path))
        elif lower.endswith((".gdraw", ".svg")):
            self._load_model(Path(path))
        else:
            self._load_dxf(Path(path))

    # ------------------------------------------------------------------ .gmodel project I/O (M5.1)

    def _build_project_schema(self):
        from guildmodel.core.project.schema import (
            Component, MachineRef, MaterialRef, ProjectSchema, component_param_field)
        self._sync_active_workspace()     # capture the active component's live dock edits
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
        # One Component per workspace, carrying its kind + edited params, so a whole-
        # model (.gdraw) session round-trips — not just the active frame (M7.1).
        comps = []
        ws_param = {"castle": "castle_params", "temple": "temple_params",
                    "base_curve_block": "block_params"}
        for ws in self._workspaces:
            field = component_param_field(ws.kind)
            param = getattr(ws, ws_param[field], None)
            kwargs = dict(
                id=ws.source_workspace or ws.kind.value, kind=ws.kind,
                label=ws.label, enabled=ws.enabled,
                source_workspace=ws.source_workspace, source_file=self._source_name,
                has_program=ws.program_stored)
            if param is not None:
                kwargs[field] = param
            if ws.program_zero is not None:
                kwargs["program_zero"] = ws.program_zero       # per-component datum (M11)
            if ws.cam_overrides is not None:
                kwargs["cam_overrides"] = ws.cam_overrides     # per-component CAM (M16)
            comps.append(Component(**kwargs))
        if comps:
            proj.components = comps
        return proj

    def _write_gmodel(self, path: Path) -> None:
        """Assemble the current session and write it to ``path``. No UI side
        effects (raises on failure) — shared by Save and the autosave snapshot."""
        from guildmodel.core.project.gmodel import save_gmodel
        from guildmodel.core.post.machine import load_machine_profile
        cam = self.params.cam_params()
        config_dir = Path(__file__).parent.parent / "config"
        machine = self._last_machine
        if machine is None:
            try:
                machine = load_machine_profile(cam.machine_name, config_dir).model_dump()
            except Exception:
                machine = None
        save_gmodel(
            path, project=self._build_project_schema(),
            dxf_bytes=self._source_dxf_bytes,
            gdraw_bytes=self._source_gdraw_bytes,
            programs=self._last_programs or None,
            machine=machine, setup=self._last_setup, report=self._last_report,
        )

    def _save_gmodel_to(self, path: Path, announce: bool = True) -> bool:
        if self._source_dxf_bytes is None and self._source_gdraw_bytes is None:
            QMessageBox.warning(self, "No design",
                                "Open a drawing (.gdraw) or import a DXF before saving a project.")
            return False
        try:
            self._write_gmodel(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._project_path = path
        self._add_recent(str(path))
        self._clear_dirty()          # saved — title refreshes without the star
        # Green only once a program is actually stored in the .gmodel (M5.2).
        self._program_stored = bool(self._last_programs)
        self._refresh_readiness()
        if announce:
            self.append_log(f"[project] Saved {path.name}")
            self.status_lbl.setText(f"Project saved — {path.name}")
        return True

    def _on_save_project(self) -> None:
        """Save (Ctrl+S): write straight back to the open .gmodel — no overwrite
        prompt — and only fall through to Save As when the project has never been
        saved (mirrors GuildDraw's plain Save)."""
        if self._source_dxf_bytes is None and self._source_gdraw_bytes is None:
            QMessageBox.warning(self, "No design",
                                "Open a drawing (.gdraw) or import a DXF before saving a project.")
            return
        if self._project_path is not None:
            if self._save_gmodel_to(self._project_path):
                self._maybe_prompt_default_bed()
            return
        self._on_save_project_as()

    def _on_save_project_as(self) -> None:
        """Save As…: always prompt for a new .gmodel path, then save there."""
        if self._source_dxf_bytes is None and self._source_gdraw_bytes is None:
            QMessageBox.warning(self, "No design",
                                "Open a drawing (.gdraw) or import a DXF before saving a project.")
            return
        default = self._project_path or (
            Path(self._prefs["last_output_dir"] or ".")
            / ((self._source_name.rsplit(".", 1)[0] if self._source_name else "frame") + ".gmodel"))
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save GuildModel project", str(default), "GuildModel project (*.gmodel)")
        if not path_str:
            return
        if not path_str.lower().endswith(".gmodel"):
            path_str += ".gmodel"
        if self._save_gmodel_to(Path(path_str)):
            self._prefs["last_output_dir"] = str(Path(path_str).parent)
            prefs_mod.save(self._prefs)
            self._maybe_prompt_default_bed()

    def _on_open_project(self) -> None:
        if not self._confirm_discard():
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open GuildModel project", self._prefs["last_output_dir"],
            "GuildModel project (*.gmodel);;All files (*)")
        if path_str:
            self._open_project(Path(path_str))

    def _open_project(self, path: Path, *, remember: bool = True) -> None:
        from guildmodel.core.project.gmodel import GModelError, load_gmodel
        try:
            bundle = load_gmodel(path)
        except GModelError as exc:
            QMessageBox.critical(self, "Open failed", f"{path.name}:\n{exc}")
            return
        proj = bundle.project
        # A programmatic restore, not user edits — don't let the param setters
        # or the rebuild below mark the freshly-opened project dirty.
        self._restoring += 1
        try:
            self._open_project_body(bundle, proj, path, remember)
        finally:
            self._restoring -= 1

    def _open_project_body(self, bundle, proj, path: Path, remember: bool) -> None:
        # Restore params first so the post-import rebuild uses them.
        self.params.set_material(proj.cam.material.name)
        self.params.set_castle_params(proj.castle)
        self.params.set_cam_params(proj.cam_params)
        self._worktable = proj.worktable          # restore the tagged bed (M7.4)
        self._wt_undo.clear()                     # a fresh project starts a clean history
        self._wt_redo.clear()
        self._bed_prompt_answered = False
        self._refresh_wt_undo_buttons()
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
        if remember:
            self._add_recent(str(path))
        self._update_title()
        self.append_log(
            f"[project] Opened {path.name} "
            f"({'with program' if bundle.has_program() else 'no program yet'})")
        if bundle.gdraw_bytes:
            # Whole-model project: rebuild every component from the embedded drawing,
            # then overlay the saved per-component params (M7.1 round-trip).
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"gmodel_{path.stem}.gdraw"
            tmp.write_bytes(bundle.gdraw_bytes)
            self._source_gdraw_bytes = bundle.gdraw_bytes
            self._source_dxf_bytes = None
            self._load_model(tmp, from_project=True)
            self._source_name = proj.source_file or tmp.name
            self._apply_components_to_workspaces(proj.components)
        elif bundle.dxf_bytes:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"gmodel_{path.stem}.dxf"
            tmp.write_bytes(bundle.dxf_bytes)
            self._load_dxf(tmp, from_project=True)
            self._source_dxf_bytes = bundle.dxf_bytes
            self._source_name = proj.source_file or tmp.name
        else:
            QMessageBox.warning(self, "No DXF",
                                "This project has no embedded design; parameters restored only.")
            self._post_load_baseline()

    # ------------------------------------------------------------------ preferences

    def _open_preferences(self) -> None:
        current = {**self._prefs, "dark_mode": self._dark_mode}
        dlg = PrefsDialog(current, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p = dlg.to_prefs()
        old_preview_res = self._prefs["preview_resolution_mm"]
        scale_changed = p.get("ui_scale") != self._prefs.get("ui_scale")
        appearance_changed = any(
            p.get(k) != self._prefs.get(k)
            for k in ("viewport", "render3d", "toolpath_palette",
                      "layer_colors", "grid"))
        self._prefs.update(p)
        prefs_mod.save(self._prefs)

        # UI scale (BUILDPLAN-NEW UI-0): re-derive and re-apply immediately —
        # font here, stylesheet via the restyle below. `apply_ui_scale` is
        # idempotent (absolute, from the platform base), so this is safe to
        # run any number of times.
        if scale_changed:
            app = QApplication.instance()
            hidpi.apply_ui_scale(
                app, hidpi.ui_scale(app.primaryScreen(), self._prefs))
            self.append_log("[ui] " + hidpi.scale_decision(
                app.primaryScreen(), self._prefs, app))
            appearance_changed = True     # force the stylesheet re-apply below

        # Re-bind shortcuts + rebuild the toolbar from the (possibly edited) prefs (M7.15).
        if "hotkeys" in p:
            self._apply_hotkeys()
        if "toolbar" in p:
            self._rebuild_toolbar()

        # The tool library may have changed (Preferences ▸ Tools) — refresh every
        # tool combo so new/edited tools appear without a restart (M7.8).
        self.params.refresh_tool_lists()

        # Appearance (viewport preset / light rig / model color / path palette):
        # push into the theme module, then refresh every surface. A dark-mode
        # flip refreshes them anyway; otherwise re-apply the current mode.
        if appearance_changed:
            _apply_appearance_prefs(self._prefs)
        if p["dark_mode"] != self._dark_mode:
            self._act_dark.setChecked(p["dark_mode"])
            self._apply_dark_mode(p["dark_mode"])
        elif appearance_changed:
            self._apply_dark_mode(self._dark_mode)
        if appearance_changed:
            self._recolor_toolpath_table(
                self.canvas.recolor_toolpaths(theme.toolpath_colors()))
        if p["preview_resolution_mm"] != old_preview_res:
            # Cached stage meshes were built at the old resolution.
            self._stage_cache.clear()
            self._edge_cache.clear()
            if self.stack.currentIndex() == 1 and self._castle_ready():
                self._rebuild_timer.start()

    # ------------------------------------------------------------------ connections

    def _connect_signals(self) -> None:
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.measure_changed.connect(self._on_measure_changed)

        for layer, cb in self.params.layer_checks.items():
            cb.toggled.connect(
                lambda checked, lyr=layer: self.canvas.set_layer_visible(lyr, checked)
            )

        # Live parametric rebuild (debounced; only while the 3D view is up)
        self.params.castle_changed.connect(self._on_castle_params_changed)
        self.params.stock_changed.connect(self._on_stock_changed)
        self.params.zone_hovered.connect(self._on_zone_hover)
        self.params.cam_changed.connect(self._on_cam_changed)
        # Any user param edit means unsaved work (suppressed during restores).
        self.params.castle_changed.connect(self._mark_dirty)
        self.params.stock_changed.connect(self._mark_dirty)
        self.params.cam_changed.connect(self._mark_dirty)
        self.view3d.stage_changed.connect(self._on_stage_changed)
        self.view3d.playback_step_changed.connect(self._on_playback_step)
        self.view3d.collision_paused.connect(self._on_collision_paused)

        # Restore persisted material + CAM params (machine / tool / strategy /
        # feeds). Set the material first (without repopulating), then apply the
        # persisted CAM values so the user's last edits survive the restart.
        self.params.set_material(self._prefs.get("material_name") or "acetate")
        saved_cam = self._prefs.get("cam_params") or {}
        if saved_cam:
            from guildmodel.core.project.schema import CastleCamParams
            try:
                self.params.set_cam_params(CastleCamParams(**saved_cam))
            except Exception:
                pass

    # ------------------------------------------------------------------ view switch

    def _on_worktable_tab(self) -> bool:
        return (self._worktable_tab_index >= 0
                and self.component_tabs.currentIndex() == self._worktable_tab_index)

    def _component_sim_enabled(self) -> bool:
        """The active component can be cut-simulated (a buildable castle frame or
        a flat part)."""
        castle_ready = self._partition is not None and self._partition.classified
        return castle_ready or self._active_is_flat()

    def _bed_sim_enabled(self) -> bool:
        return self._nest is not None and bool(self._nest.placements)

    # ------------------------------------------------ view-aware sidebar (UX pass)

    def _build_sim_panel(self) -> QWidget:
        """The dock's Simulation page — shown while the Simulation view is active on a
        component (BUILDPLAN UX pass — view-aware sidebar). A read-only cut verdict so
        the result sits where the maker's eyes already are, plus a re-run and a scrub
        hint; the editable parameters return the moment they switch back to 2D / 3D."""
        page = QWidget()
        page.setObjectName("simPanel")
        v = QVBoxLayout(page)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        title = QLabel("Simulation")
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        self._sim_verdict_lbl = QLabel("No cut simulated yet.")
        self._sim_verdict_lbl.setWordWrap(True)
        v.addWidget(self._sim_verdict_lbl)

        self._sim_summary_lbl = QLabel("")
        self._sim_summary_lbl.setObjectName("smallLabel")
        self._sim_summary_lbl.setWordWrap(True)
        v.addWidget(self._sim_summary_lbl)

        v.addSpacing(6)
        self._sim_rerun_btn = QPushButton("Re-run simulation")
        self._sim_rerun_btn.setToolTip("Re-simulate the cut for the active component.")
        self._sim_rerun_btn.clicked.connect(lambda: self._switch_view(2, run=True))
        v.addWidget(self._sim_rerun_btn)

        hint = QLabel("Use the ▶ play control below the view to scrub the cut "
                      "op by op. Warnings are listed in the Inspector.")
        hint.setObjectName("mutedSmallLabel")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return page

    def _update_sim_panel(self) -> None:
        """Fill the Simulation dock page from the active component's cut report."""
        if getattr(self, "_sim_verdict_lbl", None) is None:
            return
        report = self._active_sim_report
        if report is None:
            self._sim_verdict_lbl.setText("No cut simulated yet — press Re-run.")
            self._sim_verdict_lbl.setStyleSheet("font-weight: 700;")
            self._sim_summary_lbl.setText("")
            return
        try:
            status = report.status()
            lines = report.summary_lines()
        except Exception:               # a shape without the CutReport helpers
            self._sim_verdict_lbl.setText("Cut simulated.")
            self._sim_verdict_lbl.setStyleSheet("font-weight: 700;")
            self._sim_summary_lbl.setText("")
            return
        text, color = {
            "ok": ("✓ Cut verified", "#3a8c3a"),
            "warn": ("⚠ Cut needs attention", "#c08a00"),
            "fail": ("✗ Cut incomplete", "#c0392b"),
        }.get(status, ("Cut result", ""))
        self._sim_verdict_lbl.setText(text)
        self._sim_verdict_lbl.setStyleSheet(
            f"font-weight: 700; color: {color};" if color else "font-weight: 700;")
        self._sim_summary_lbl.setText("\n".join(lines))

    def _sync_dock_page(self) -> None:
        """Point the right dock at the page matching the active tab + view (UX pass —
        view-aware sidebar): worktable controls on the bed, the Simulation verdict in
        Sim view, else the component parameters. The single authority for the dock
        page, called at the end of every `_switch_view`."""
        if self._on_worktable_tab():
            self._dock_stack.setCurrentIndex(1)
        elif self._current_view == 2:
            self._update_sim_panel()
            self._dock_stack.setCurrentIndex(2)
        else:
            self._dock_stack.setCurrentIndex(0)

    def _switch_view(self, view: int, *, run: bool = False) -> None:
        """Single source of truth for the central view. Renders `view`
        (0 = 2D, 1 = 3D, 2 = Sim) for the ACTIVE tab and always re-pushes that tab's
        content, so a (tab, view) combination is never stale (BUILDPLAN M7.12).

        Tab mapping — a component: outline / mesh / cut-sim; the Worktable: bed canvas
        / (no 3D) / bed cut-sim. `run=True` (an explicit Sim-toggle click) starts the
        sim when no fresh result is cached; a passive switch (tab change, build done)
        falls back to 2D rather than auto-running an expensive sim."""
        # Push the viewer's content BEFORE making its page current: while the page is
        # hidden the renders are skipped (no framebuffer error), so the showEvent on
        # `setCurrentIndex` draws the new content directly — no one-frame flash of the
        # previous component's view (BUILDPLAN M7.12).
        if self._on_worktable_tab():
            if view == 2 and self._show_bed_sim(run):
                self.view3d.set_mode("sim")
                self.stack.setCurrentIndex(1)
            else:                                 # 2D bed (3D N/A on the bed)
                view = 0
                self.stack.setCurrentIndex(self._worktable_page_index)
        else:
            if view == 1:
                self.view3d.set_mode("model")
                self._show_active_3d()            # re-push the active component's mesh
                self.stack.setCurrentIndex(1)
            elif view == 2 and self._show_component_sim(run):
                self.view3d.set_mode("sim")
                self.stack.setCurrentIndex(1)
            else:
                view = 0
                self.stack.setCurrentIndex(0)
        self._current_view = view
        self._sync_dock_page()            # dock follows the view (view-aware sidebar)
        self._update_view_toggles()

    def _update_view_toggles(self) -> None:
        """Reflect the active view + per-tab availability on the toolbar toggles. The
        Sim toggle disables when nothing's ready — guiding the user to load / build /
        nest first; 3D disables on the Worktable (the bed has no model view)."""
        on_wt = self._on_worktable_tab()
        self._act_view2d.setChecked(self._current_view == 0)
        self._act_view3d.setChecked(self._current_view == 1)
        self._act_simulate.setChecked(self._current_view == 2)
        self._act_view3d.setEnabled(not on_wt)
        self._act_simulate.setEnabled(
            self._bed_sim_enabled() if on_wt else self._component_sim_enabled())
        self.zoom_label.setVisible(self._current_view == 0 and not on_wt)
        # Measure: only on the component 2D outline, and only with geometry loaded.
        # Leaving that view ends measure mode (uncheck fires _on_toggle_measure).
        measure_ok = self._current_view == 0 and not on_wt and self.canvas.has_layers()
        self._act_measure.setEnabled(measure_ok)
        if not measure_ok and self._act_measure.isChecked():
            self._act_measure.setChecked(False)

    def _show_component_sim(self, run: bool) -> bool:
        """Show the active component's cut-sim — the cached result, or start it when
        `run` and it's runnable. Returns True if the sim view should be shown."""
        if self._active_sim_removal is not None:
            self.view3d.show_report(self._active_sim_report)
            self.view3d.set_plan(self._active_sim_removal)
            return True
        if run and self._component_sim_enabled():
            self._start_component_sim()
            return True
        return False

    def _show_bed_sim(self, run: bool) -> bool:
        """Show the bed cut-sim — the cached result, or start it when `run`."""
        if self._bed_removal is not None:
            self.view3d.show_report(self._bed_report)
            self.view3d.set_plan(self._bed_removal)
            return True
        if run and self._bed_sim_enabled():
            self._start_bed_sim()
            return True
        return False

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
        the view if nothing is built yet, so the 3D always reflects the active tab.

        Verifies here as well as at the two `finished` handlers, because this is
        the path Build 3D and every component-tab switch take. Without it the
        toolbar button displayed unverified meshes, and switching tabs left the
        *previous* component's verdict in the status bar and the Inspector —
        UI-0's hole reopening in the third worker, which is the exact failure
        `gui/mesh_build.py` was created to stop repeating.
        """
        mesh = self._stage_cache.get(self._active_mesh_key())
        if mesh is None:
            self.view3d.clear()
            # Nothing on screen to have an opinion about. Without this, the
            # verdict from whichever component was shown last would keep
            # flagging problems against an empty viewer.
            self._mesh_verdict = None
            self._refresh_inspector()
            return
        zero, _ = self._active_program_zero_3d()
        edges = self._edge_cache.get(self._active_mesh_key())
        if self._active_is_flat():
            self.view3d.show_mesh(mesh, stock=self._flat_stock(),
                                  core_guide=self._active_core_guide,
                                  program_zero=zero, edges=edges)
        else:
            self.view3d.show_mesh(mesh, stock=self.params.castle_params().stock,
                                  program_zero=zero, edges=edges)
        self._set_mesh_verdict(mesh)

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
        from guildmodel.core.project.schema import ComponentKind
        ws = self._workspaces[i]
        ws.stage = self._stage
        ws.stage_cache = self._stage_cache
        ws.edge_cache = self._edge_cache
        ws.mesh_built = self._mesh_built
        ws.core_guide = self._active_core_guide
        ws.last_programs = self._last_programs
        ws.last_setup = self._last_setup
        ws.last_machine = self._last_machine
        ws.last_report = self._last_report
        ws.program_stored = self._program_stored
        ws.diag = {                               # M7.14 inspector inputs per component
            "reach": self._diag_reach, "clearance": self._diag_clearance,
            "lint": self._diag_lint, "cut_report": self._diag_cut_report,
        }
        # Capture this component's editable params from the kind-aware dock (M7.3).
        if ws.kind == ComponentKind.FRAME_FRONT:
            ws.castle_params = self.params.castle_params()
        elif ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
            ws.temple_params = self.params.temple_params()
        elif ws.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            ws.block_params = self.params.block_params()
        ws.program_zero = self.params._program_zero()    # per-component G54 datum (M11)
        ws.cam_overrides = self.params.cam_overrides()   # per-component CAM (M16)

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
        self._edge_cache = ws.edge_cache
        self._mesh_built = ws.mesh_built
        self._active_core_guide = ws.core_guide
        self._last_programs = ws.last_programs
        self._last_setup = ws.last_setup
        self._last_machine = ws.last_machine
        self._last_report = ws.last_report
        self._program_stored = ws.program_stored
        d = ws.diag or {}                         # M7.14 inspector inputs per component
        self._diag_reach = d.get("reach", [])
        self._diag_clearance = d.get("clearance", [])
        self._diag_lint = d.get("lint", [])
        self._diag_cut_report = d.get("cut_report")
        self._refresh_inspector()

    def _apply_workspace_to_ui(self, ws: ComponentWorkspace) -> None:
        """Re-render the shared views + dock + actions for the active component."""
        from guildmodel.core.project.schema import ComponentKind

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
            if ws.kind == ComponentKind.FRAME_FRONT and ws.forming is not None:
                # Seed the pad-splay angle from the drawing's bridge angle (M13.1)
                # — a no-op once the maker has touched the splay controls.
                self.params.seed_pad_splay_angle(
                    getattr(ws.forming, "bridge_angle_deg", 0.0) or 0.0)
            if ws.kind == ComponentKind.FRAME_FRONT and ws.partition is not None:
                # Seed the splay run from this frame: bottom-center to just past
                # the lower nosepad SCULPT line (user rule, M13 fixes).
                from guildmodel.core.relief.features import default_splay_run_mm
                run = default_splay_run_mm(ws.partition)
                if run is not None:
                    self.params.seed_pad_splay_run(run)
            elif (ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)
                  and ws.temple_params is not None):
                self.params.set_temple_params(ws.temple_params)
            elif (ws.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT)
                  and ws.block_params is not None):
                self.params.set_block_params(ws.block_params)
            if ws.program_zero is not None:          # restore this part's G54 datum (M11)
                self.params._set_program_zero(ws.program_zero)
            self.params.set_cam_overrides(ws.cam_overrides)   # this part's CAM (M16)
        finally:
            self.params.blockSignals(False)
        self.view3d.set_stage_enabled(ws.castle_ready)
        self.view3d.set_stage(ws.stage)

        has_outline = ws.outline_poly is not None
        # Build 3D: a matched frame castle, or a flat part — a temple (outline) or
        # a base-curve block (its lens) — via the flat-extrusion mesher (M7).
        flat_buildable = ws.is_temple or (ws.outline_poly is None and ws.lens_od is not None)
        self._act_build.setEnabled(ws.castle_ready or flat_buildable)
        self._act_export.setEnabled(ws.castle_ready)
        # Cut simulation now runs on every component — a matched frame, a temple, or
        # a base-curve block (BUILDPLAN M7: machine sim on multiple components).
        self._act_simulate.setEnabled(ws.castle_ready or flat_buildable)
        self._act_gcode.setEnabled(has_outline)          # frame castle or temple profile
        self._act_block.setEnabled(ws.lens_od is not None)
        self._act_worktable.setEnabled(ws.castle_ready and ws.lens_od is not None)
        self._act_export_nc.setEnabled(bool(ws.last_programs))

        if ws.boxing is not None:
            b = ws.boxing
            self.params.update_boxing(b.a, b.b, b.dbl, b.ed)
        self._update_stock_canvas()
        # Re-apply the active view to THIS component, refreshing its content. On a
        # passive tab switch, fall back to 2D when the chosen view has nothing to show
        # for this component yet — an unbuilt 3D, or a Sim with no cached result — so
        # we never flash an empty 3D / sim or auto-run an expensive sim.
        view = self._current_view
        if view == 1 and not self._has_active_3d():
            view = 0
        elif view == 2 and self._active_sim_removal is None:
            view = 0
        self._switch_view(view)

    def _activate_workspace(self, index: int) -> None:
        """Make component ``index`` active: persist the current one, swap the
        working set, and re-render the shared views/dock/actions (M7.3)."""
        # Activation pushes the component's stored params into the dock — a
        # programmatic restore, not a user edit; it must not mark the project
        # dirty even where a setter's change signal slips through.
        self._restoring += 1
        try:
            self._activate_workspace_body(index)
        finally:
            self._restoring -= 1

    def _activate_workspace_body(self, index: int) -> None:
        if not (0 <= index < len(self._workspaces)):
            return
        if self._active_ws != index:
            # Persist the outgoing component only when there really is one (a fresh
            # file leaves _active_ws at the -1 sentinel — nothing to sync)…
            if 0 <= self._active_ws < len(self._workspaces):
                self._sync_active_workspace()
            # …but always drop the transient cut-sim cache: it belonged to whatever
            # was shown before — a sibling component OR the previous file. Not doing
            # this on a new-file open left the old sim on screen (Sim view never
            # refreshed; an inspector click flashed the stale render).
            self._active_sim_removal = None
            self._active_sim_report = None
        self._active_ws = index
        ws = self._workspaces[index]
        self._load_active_geometry(ws)
        self._apply_workspace_to_ui(ws)
        # The dock PAGE is chosen by _switch_view (called from _apply_workspace_to_ui)
        # so it follows the active view; here we only honour the sidebar toggle.
        self._right_dock.setVisible(self._act_sidebar.isChecked())
        if self.component_tabs.currentIndex() != index:
            self.component_tabs.blockSignals(True)
            self.component_tabs.setCurrentIndex(index)
            self.component_tabs.blockSignals(False)
        self._refresh_readiness()

    # ------------------------------------------------------------------ DXF import

    def _on_open(self) -> None:
        if not self._confirm_discard():
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open DXF file", "", "DXF files (*.dxf);;All files (*)",
        )
        if not path_str:
            return
        self._load_dxf(Path(path_str))

    def _on_open_model(self) -> None:
        if not self._confirm_discard():
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open GuildDraw drawing", self._prefs.get("last_output_dir") or "",
            "GuildDraw drawing (*.gdraw);;GuildDraw SVG (*.svg);;All files (*)")
        if path_str:
            self._load_model(Path(path_str))

    def _load_model(self, path: Path, *, from_project: bool = False) -> None:
        """Import a GuildDraw ``.gdraw`` as a multi-component project (M7.3): one
        workspace tab per component (frame front + temples + base-curve templates).

        ``from_project`` rebuilds the workspaces from a ``.gmodel``'s embedded drawing
        (a temp file): the caller keeps the project path / window title / recents and
        overlays the saved per-component params, so we skip those here."""
        from guildmodel.core.io_import.gdraw import GdrawError
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
        # Retain the .gdraw bytes so a saved .gmodel is self-contained: reopening
        # rebuilds every component's geometry from this embedded drawing, then
        # overlays the saved per-component params (see _build_project_schema /
        # _open_project). The single-DXF source does not apply to a whole model.
        try:
            self._source_gdraw_bytes = path.read_bytes()
        except Exception:
            self._source_gdraw_bytes = None
        self._source_dxf_bytes = None
        if not from_project:
            self._project_path = None
        self._clear_nest()                 # the previous file's bed nest / sim is stale
        self._inject_gdraw_engraving(workspaces)
        self._workspaces = workspaces
        self._active_ws = -1
        self._populate_component_tabs()

        populated = [w.label for w in workspaces if w.enabled]
        self.append_log(
            f"[model] {len(workspaces)} components, {len(populated)} populated: "
            + ", ".join(populated))
        for w in workspaces:
            self._log_outline_holes(w, prefix=f"{w.label}: ")
        self._dxf_loaded = True
        self._activate_workspace(0)
        if not from_project:
            self._update_title()
            self.status_lbl.setText(
                f"Loaded drawing: {path.name}  ({len(populated)} of {len(workspaces)} "
                f"components) — Build 3D to model them all")
            self._add_recent(str(path))
        self._post_load_baseline()   # a just-loaded design is the clean baseline

    def _log_outline_holes(self, ws, prefix: str = "") -> None:
        """Report the decorative OUTLINE openings by name (Hole1…), plus any
        closed OUTLINE curve that fell outside the profile (an authoring
        mistake — it is ignored rather than cut)."""
        from guildmodel.core.io_import.normalize import hole_label

        if ws.outline_holes:
            named = ", ".join(
                f"{hole_label(i)} {h.area:.1f} mm²"
                for i, h in enumerate(ws.outline_holes))
            self.append_log(
                f"[holes] {prefix}{len(ws.outline_holes)} opening(s) inside the "
                f"outline — {named} (cut, not grooved)")
        if ws.outline_stray:
            self.append_log(
                f"[warn]  {prefix}{len(ws.outline_stray)} closed OUTLINE curve(s) "
                "outside the profile — ignored; the largest curve is the profile.")

    def _inject_gdraw_engraving(self, workspaces) -> None:
        """Outline GuildDraw engraving *text objects* into ENGRAVING polylines.

        A ``.gdraw`` stores engraving as a text object (string + font), not curves, so
        the Qt-free core reader can't produce geometry for it — this fills that gap here
        (fonts need Qt). Temples only for now (the frame-front castle relief/CAM don't
        consume engraving): a temple is drawn posterior in GuildDraw, so its engraving
        lands on the interior — the same top face the hinge pocket and the temple relief
        already cut. The glyphs go into ``ws.layers["ENGRAVING"]`` (2D canvas) and
        ``ws.engraving_curves`` (3D relief + G-code), aligned with the outline/hinge."""
        from guildmodel.core.project.schema import ComponentKind
        from guildmodel.gui.text_outline import engraving_polylines_from_texts

        temple_kinds = (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)
        for ws in workspaces:
            texts = getattr(ws, "texts", None)
            if not texts or ws.kind not in temple_kinds:
                continue
            try:
                polys = engraving_polylines_from_texts(
                    texts, posterior=getattr(ws, "posterior", True))
            except Exception:
                self.append_log(
                    f"[engraving] {ws.label}: could not outline engraving text — skipped.")
                continue
            if not polys:
                continue
            # derive_workspace already reflected the temple's other layers across the
            # Y axis (temples are drawn posterior); flip the engraving to match so the
            # glyphs land on the part and read correctly on the interior face.
            polys = [[(-x, y) for x, y in poly] for poly in polys]
            ws.layers["ENGRAVING"] = list(ws.layers.get("ENGRAVING", [])) + polys
            # Outlined glyphs have no authored curve behind them; pad so
            # `ws.curves` stays index-aligned with `ws.layers` as documented.
            if ws.curves:
                ws.curves["ENGRAVING"] = (list(ws.curves.get("ENGRAVING", []))
                                          + [None] * len(polys))
            ws.engraving_curves = list(ws.layers["ENGRAVING"])
            self.append_log(
                f"[engraving] {ws.label}: outlined {len(polys)} glyph contour(s) "
                f"from {len(texts)} text object(s).")

    def _apply_components_to_workspaces(self, components) -> None:
        """Overlay saved per-component params (from a reopened .gmodel) onto the
        freshly-rebuilt workspaces, matched by kind (M7.1)."""
        from guildmodel.core.project.schema import component_param_field
        ws_attr = {"castle": "castle_params", "temple": "temple_params",
                   "base_curve_block": "block_params"}
        by_kind = {c.kind: c for c in (components or [])}
        for ws in self._workspaces:
            comp = by_kind.get(ws.kind)
            if comp is None:
                continue
            ws.enabled = comp.enabled
            ws.program_zero = comp.program_zero          # restore per-component datum (M11)
            ws.cam_overrides = comp.cam_overrides        # restore per-component CAM (M16)
            field = component_param_field(ws.kind)
            setattr(ws, ws_attr[field], getattr(comp, field))
        if 0 <= self._active_ws < len(self._workspaces):
            self._activate_workspace(self._active_ws)   # push restored params into the dock

    def _load_dxf(self, path: Path, *, from_project: bool = False) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            return                            # an import is already in flight
        self.status_lbl.setText(f"Loading {path.name}…")
        self.append_log(f"[import] {path.name}")

        # Retain the source DXF bytes so a .gmodel is self-contained (M5.1).
        try:
            self._source_dxf_bytes = Path(path).read_bytes()
            self._source_name = path.name
        except Exception:
            self._source_dxf_bytes = None
        self._source_gdraw_bytes = None        # a DXF is a single frame front, not a model
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

        # Remembered for _on_import_finished: a .gmodel re-import of the embedded
        # DXF (a temp file) must not land in the recent-files menu.
        self._import_from_project = from_project
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
        self, layers: dict, boxing, raw_summary: dict, unrecognised: list,
        curves: dict | None = None,
    ) -> None:
        from guildmodel.core.project.schema import ComponentKind, component_label

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
        ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="", layers=layers,
                                curves=curves or {})
        derive_workspace(ws, boxing=boxing)
        if ws.is_temple:
            ws.kind = ComponentKind.TEMPLE_RIGHT
        ws.label = component_label(ws.kind)
        self._clear_nest()                 # the previous file's bed nest / sim is stale
        self._workspaces = [ws]
        self._active_ws = -1
        self._populate_component_tabs()

        if ws.is_temple:
            self.append_log(
                f"[temple] Temple component: outline + "
                f"{len(ws.engraving_curves)} engraving curve(s) — "
                f"engrave + profile program on Generate G-code."
            )
        self._log_outline_holes(ws)
        if ws.partition is not None:
            if ws.partition.matched:
                layout = "standard castle layout"
            elif ws.partition.classified:
                layout = "non-standard layout — builds; override zone heights as needed"
            else:
                layout = "generic zones — castle relief needs lenses + section cuts"
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
        if self._import_worker is not None and not self._import_from_project:
            self._add_recent(str(self._import_worker.path))
            self._update_title()
        self._post_load_baseline()   # a just-loaded design is the clean baseline

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
        return self._partition is not None and self._partition.classified

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
            if ws.castle_ready or ws.is_temple or (ws.outline_poly is None and ws.lens_od is not None):
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
        if ws.castle_ready:
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

        self._mesh_worker = MultiMeshWorker(
            specs, self._prefs["preview_resolution_mm"],
            solid=bool(self._prefs.get("use_solid_model", False)))
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

    def _on_multi_mesh_built(self, i: int, mesh, edges, core_guide) -> None:
        """One component's mesh is ready — cache it into that component (M7 UX)."""
        ws = self._workspaces[i]
        if ws.castle_ready:
            key = ws.stage
            ws.stage_cache[key] = mesh            # shared with self._stage_cache iff active
        else:
            key = "flat"
            ws.stage_cache[key] = mesh
            ws.core_guide = core_guide
            if i == self._active_ws:
                self._active_core_guide = core_guide
        # Edges belong to the component, not the window — see `edge_cache` on
        # ComponentWorkspace. Keeping them in a window-level dict was survivable
        # only while exactly one component could produce them. Shared with
        # self._edge_cache iff active, exactly like stage_cache above.
        ws.edge_cache[key] = edges
        ws.mesh_built = True
        self.append_log(
            f"[3D]   {ws.label}: {len(mesh.vertices):,} verts"
            + (f", {len(edges):,} edges" if edges else ""))

    def _on_multi_mesh_finished(self) -> None:
        self._close_progress()
        self._act_build.setEnabled(True)
        self._mesh_built = True
        self._show_active_3d()                    # show whichever component is active
        self._refresh_readiness()
        verdict = self._mesh_verdict
        if verdict is not None and not verdict.ok:
            self.status_lbl.setText("⚠ 3D model has problems")
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
        self._edge_cache.clear()
        self._invalidate_program()
        if self.stack.currentIndex() == 1 and self._castle_ready():
            self._rebuild_timer.start()

    def _on_stage_changed(self, stage: str) -> None:
        self._stage = stage
        cached = self._stage_cache.get(stage)
        if cached is not None:
            self._show_stage_mesh(cached, self._edge_cache.get(stage))
        elif self._castle_ready():
            self._start_mesh_build(show_progress=False)

    def _on_stock_changed(self) -> None:
        self._invalidate_program()
        self._update_stock_canvas()
        # Re-draw the stock ghost around the currently shown stage, if any.
        cached = self._stage_cache.get(self._stage)
        if cached is not None and self.stack.currentIndex() == 1:
            self._show_stage_mesh(cached, self._edge_cache.get(self._stage))

    def _on_cam_changed(self) -> None:
        """Persist the CAM tab (material / machine / tool / strategy / feeds).

        A frame's CAM params don't change its model, so no rebuild — but a flat part
        (temple / base-curve block) puts its GEOMETRY on its own kind tab (blank size,
        the blank-end snap + stock side, engrave depth, holes), and those controls also
        fire cam_changed. They DO change the solid, so the flat preview must rebuild
        live — otherwise toggling e.g. 'Snap to blank end' looks like it does nothing."""
        # Feeds/tool/strategy changes invalidate any stored program (M5.2).
        self._invalidate_program()
        if self._active_is_flat():
            self._update_stock_canvas()      # blank box follows size / snap / side
        self._update_program_zero_marker()   # 2D datum marker may have moved
        # Live-update the 3D datum triad too (no camera reset) when viewing 3D.
        if self.stack.currentIndex() == 1:
            zero, stock_z = self._active_program_zero_3d()
            self.view3d.set_program_zero(zero, stock_z)
            # A flat part's geometry rides cam_changed → rebuild its preview (debounced;
            # the worker reads the live temple/block params, snap included).
            if self._active_is_flat():
                self._rebuild_timer.start()
        try:
            self._prefs["cam_params"] = self.params.cam_params().model_dump()
            self._prefs["material_name"] = self.params.material_name()
            prefs_mod.save(self._prefs)
        except Exception:
            pass

    def _temple_snap_frame(self):
        """The active temple's design→blank-frame snap transform ``(flipped, dx, dy)``
        (a design point q lands on the blank at ``(−q if flipped else q) + (dx, dy)``),
        or None when the active part is not a snapped temple. Drives the 2D
        back-projection: blank box, datum marker and toolpath overlay draw in the
        DESIGN frame exactly where the cut lands on the blank."""
        if not self._is_temple or self._outline_poly is None:
            return None
        t = self.params.temple_params()
        if not t.snap_to_blank_end:
            return None
        from guildmodel.core.relief.flat import temple_snap_transform
        return temple_snap_transform(
            self._outline_poly, self._hinge_polys, t.blank_length_mm,
            stock_side=t.stock_side, snap=True)

    @staticmethod
    def _snap_to_design(q, frame):
        """Map a blank-frame XY point back into the design frame (see
        `_temple_snap_frame`): p = ±(q − (dx, dy))."""
        flipped, dx, dy = frame
        x, y = q[0] - dx, q[1] - dy
        return (-x, -y) if flipped else (x, y)

    def _update_stock_canvas(self) -> None:
        # Flat parts (temple / base-curve block): a single-level blank framed around
        # the part (the temple's 170×30 blank, the block's 70×70 blank) — not the
        # frame's two-level stock (BUILDPLAN M7 UX fix). A SNAPPED temple's blank
        # draws where the blank really sits relative to the drawing (the butt end
        # flush on its short edge), via the inverse snap transform.
        if self._active_is_flat():
            if self._is_temple:
                s = self.params.temple_params().stock()
                geom = self._outline_poly
            else:
                s = self.params.block_params().stock()
                geom = self._lens_od
            frame = self._temple_snap_frame()
            if frame is not None:
                cx, cy = self._snap_to_design((0.0, 0.0), frame)  # the blank centre
            else:
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
        mode (BUILDPLAN M6.2). Flat parts draw it too (2026-07-09): a snapped
        temple back-projects the blank-frame datum through the inverse snap, a
        block offsets it by the lens centre its CAM frame is centred on."""
        if self._active_is_flat():
            pz = self.params.cam_params().program_zero
            label = pz.label()
            stock = self._flat_stock()
            q = pz.datum_world(stock)
            if self._is_temple:
                frame = self._temple_snap_frame()
                if frame is None:      # un-snapped temple: the datum frame is ambiguous
                    self.canvas.set_program_zero(None)
                    return
                self.canvas.set_program_zero(self._snap_to_design(q, frame), label)
            else:
                cx, cy = 0.0, 0.0
                if self._lens_od is not None:
                    x0, y0, x1, y1 = self._lens_od.bounds
                    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                self.canvas.set_program_zero((q[0] + cx, q[1] + cy), label)
            return
        if self._outline_poly is None:
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
            solid=bool(self._prefs.get("use_solid_model", False)),
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
        self._edge_cache["flat"] = None      # flat parts are raster-built: no edges
        self._active_core_guide = core_guide
        zero, _ = self._active_program_zero_3d()
        self.view3d.show_mesh(mesh, stock=self._flat_stock(),
                              core_guide=core_guide, program_zero=zero)
        n_v, n_t = len(mesh.vertices), len(mesh.faces)
        self._set_mesh_verdict(mesh)          # same honest gate as the castle path
        state = ("3D model ready" if self._mesh_verdict.ok
                 else "⚠ 3D model has problems")
        self.status_lbl.setText(f"{state} — {n_v:,} verts · {n_t:,} tris")
        self.append_log(f"[3D] Done — {n_v:,} verts, {n_t:,} tris")
        self._act_build.setEnabled(True)
        self._mesh_built = True
        self._refresh_readiness()

    def _show_stage_mesh(self, mesh, edges=None) -> None:
        zero, _ = self._active_program_zero_3d()
        self.view3d.show_mesh(mesh, stock=self.params.castle_params().stock,
                              program_zero=zero, edges=edges)
        n_v = len(mesh.vertices)
        n_t = len(mesh.faces)
        extra = f" · {len(edges):,} edges" if edges else ""
        # "Ready" has to mean *verified* (BUILDPLAN-NEW UI-0). The screenshot
        # that started this work showed a visibly broken model over this exact
        # label, because the label only ever meant "the builder returned".
        self._set_mesh_verdict(mesh)
        state = ("3D model ready" if self._mesh_verdict.ok
                 else "⚠ 3D model has problems")
        self.status_lbl.setText(
            f"{state} — {n_v:,} verts · {n_t:,} tris{extra}")

    def _set_mesh_verdict(self, mesh) -> None:
        """Run the tessellation oracle and surface it (status + Inspector).

        The kernel's own `IsValid` is not consulted: it returns True for the
        empty results, the order-dependent boolean corruption and the leaking
        shells catalogued in BUILDPLAN-NEW §3.1. The mesh is the only check
        that has caught any of them.
        """
        from guildmodel.core.mesh_check import verify_mesh

        self._mesh_verdict = verify_mesh(mesh)
        if not self._mesh_verdict.ok:
            self.append_log("[verify] " + self._mesh_verdict.summary)
            for problem in self._mesh_verdict.problems[1:]:
                self.append_log("[verify] " + problem)
        self._refresh_inspector()

    def _on_mesh_finished(self, mesh, stage: str, edges=None) -> None:
        self._close_progress()
        self._stage_cache[stage] = mesh
        self._edge_cache[stage] = edges
        if stage == self._stage:
            self._show_stage_mesh(mesh, edges)
        self.append_log(
            f"[3D] Done ({stage}) — {len(mesh.vertices):,} verts, "
            f"{len(mesh.faces):,} tris"
            + (f", {len(edges):,} edges" if edges else "")
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

    # ------------------------------------------------------------------ measure (M7.13)

    def _on_toggle_measure(self, on: bool) -> None:
        """Toggle the 2D measure tool. Turning it on snaps to the component outline
        view first so the maker is actually looking at what they're measuring."""
        if on and self._current_view != 0:
            self._switch_view(0)                  # measure lives on the 2D outline
        self.canvas.set_measure_mode(on)
        self._measure_lbl.setVisible(on)
        if on:
            self._measure_lbl.setText("Measure: click a point")
            self.status_lbl.setText("Measure — click points on the outline; Esc clears")
        else:
            self._measure_lbl.setText("")

    def _on_measure_changed(self, text: str) -> None:
        self._measure_lbl.setText(text)

    # ------------------------------------------------------------ inspector (M7.14)

    def _refresh_inspector(self) -> None:
        """Fold the latest engine checks into the Inspector dock + its title badge.
        Reach/depth are pre-combined in `_diag_reach`; the cut report is the live
        `CutReport` object (or None when superseded by a fresh program)."""
        if not hasattr(self, "_inspector"):
            return
        from guildmodel.core.diagnostics import collect_issues, severity_counts
        if self._on_worktable_tab():               # the bed has its own diagnostics
            issues = collect_issues(
                clearance_violations=self._diag_bed_clearance,
                machine_lint=self._diag_bed_lint,
                collisions=self._diag_bed_collisions,
            )
        else:
            issues = collect_issues(
                reach_warnings=self._diag_reach,
                clearance_violations=self._diag_clearance,
                machine_lint=self._diag_lint,
                cut_report=self._diag_cut_report,
            )
            # The model's own verdict leads the list (BUILDPLAN-NEW UI-0): a
            # broken model makes every downstream check meaningless, so it must
            # not sit below a tool-reach warning.
            verdict = getattr(self, "_mesh_verdict", None)
            if verdict is not None and not verdict.ok:
                from guildmodel.core.diagnostics import Issue
                issues = [Issue("error", "Model", p, ("view", "3d"))
                          for p in verdict.problems] + issues
        self._inspector.set_issues(issues)
        counts = severity_counts(issues)
        n = counts["error"] + counts["warning"]
        self._inspector_dock.setWindowTitle("Inspector" if n == 0 else f"Inspector ({n})")

    def _on_issue_activated(self, target) -> None:
        """Jump to the place an inspector issue points at (best-effort navigation)."""
        if not target:
            return
        kind, ref = target
        if kind == "op" and ref:
            if self._current_view != 0:
                self._switch_view(0)
            self.canvas.set_toolpath_highlight(ref)
            self._toggle_toolpath_dock(True)       # canonical bottom-row arrangement
        elif kind == "view" and ref == "sim":
            self._switch_view(2, run=True)
        elif kind == "collision":
            # open the bed cut sim and scrub to the first fouling position (red tool)
            self._switch_view(2, run=True)
            if not self.view3d.goto_first_collision():
                self.status_lbl.setText("No collision position in the current sim")
        elif kind == "view" and ref == "worktable":
            self._on_show_worktable()

    # ------------------------------------------------------------------ cut simulation

    def _start_component_sim(self) -> None:
        """Run the active component's cut sim off-thread (driven by the Sim view,
        BUILDPLAN M7.12). The Sim toggle is only enabled when runnable and the view
        is already in sim mode (the caller switched it), so this just starts the work
        and caches + shows the result on finish."""
        mode = self._flat_build_mode()
        if mode is None and not self._castle_ready():
            return
        if self._sim_thread is not None and self._sim_thread.isRunning():
            return
        self.view3d.clear_sim()                   # no stale block while this runs
        self.status_lbl.setText("Simulating cut…")
        self.append_log(f"[sim] Simulating the machined result ({mode or 'frame'})…")

        res = self._prefs["preview_resolution_mm"]
        # The sim must simulate the program the tab posts, overrides and all (M16).
        cam = self.params.effective_cam_params()
        mat = self.params.effective_material_name()
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

    def _on_sim_finished(self, report, lines, plan=None) -> None:
        self._close_progress()
        self._active_sim_report = report          # cache for instant Sim re-toggle (M7.12)
        self._active_sim_removal = plan
        self._diag_cut_report = report            # feed cut completeness/gouge to M7.14
        self._refresh_inspector()
        self._update_sim_panel()                  # fill the dock's Simulation verdict
        self.view3d.show_report(report)           # badge + (bed) floor sheet fallback
        self.view3d.set_plan(plan)                # volumetric block, carved along the path
        self._update_view_toggles()
        for line in lines:
            self.append_log("[sim] " + line)
        self.status_lbl.setText({
            "ok": "Cut verified — surface fully reached",
            "warn": "Cut simulated — review the flagged regions",
            "fail": "Cut incomplete — see the flagged regions",
        }.get(report.status(), "Cut simulated"))
        # Keep a serialisable summary for the .gmodel (no numpy masks).
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
            self._save_gmodel_to(self._project_path, announce=False)

    def _on_sim_error(self, tb: str) -> None:
        self._close_progress()
        self.append_log("[sim ERROR]\n" + tb)
        self.status_lbl.setText("Simulation failed — see log")
        self._update_view_toggles()

    def _on_sim_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[sim] Cancelled.")
        self.status_lbl.setText("Simulation cancelled")
        self._update_view_toggles()

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
            cam_params=self.params.effective_cam_params(),   # per-component CAM (M16)
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
        interior (BUILDPLAN M6.4) — its own program, folded into the .gmodel."""
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
            params=self._collect_gcode_params(), cam_params=self.params.effective_cam_params())
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
        if not (self._partition is not None and self._partition.classified
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
            hinge_polys=self._hinge_polys, cam_params=self.params.effective_cam_params())
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
            "material_name":     p.effective_material_name(),   # per-component (M16)
            "stock_thickness":   p.blank_thickness.value(),
            "stepdown_profile":  p.stepdown_profile.value(),
            "tab_count":         p.tab_count.value(),
            "tab_width":         p.tab_width.value(),
            "tab_height":        p.tab_height.value(),
        }

    def _maybe_write_back_material(self) -> None:
        """If the CAM tab's feeds/speeds/stepover/stepdown differ from the
        selected material's stored defaults, offer to save them back."""
        from guildmodel.gui import material_store
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
        colors = theme.toolpath_colors()
        for i, op in enumerate(overlay):
            op["color"] = colors[i % len(colors)]
        self.canvas.set_toolpaths(overlay)
        self._populate_toolpath_inspector(rows, overlay)
        self._toggle_toolpath_dock(True)           # canonical bottom-row arrangement
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

    def _recolor_toolpath_table(self, color_by: dict[str, str]) -> None:
        """Follow a toolpath-palette change onto the inspector's op names
        (Preferences ▸ Appearance); no-op while no program is shown."""
        t = getattr(self, "_toolpath_table", None)
        if t is None or not color_by:
            return
        for r in range(t.rowCount()):
            it = t.item(r, 0)
            name = it.data(Qt.ItemDataRole.UserRole) if it else None
            if name and color_by.get(name):
                it.setForeground(QColor(color_by[name]))

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

    def _on_collision_paused(self, frame: int) -> None:
        """Bed playback hit a hold-down — it paused on the collision frame; warn the
        maker (BUILDPLAN M7.12.3). Resuming plays through the rest of this run."""
        label = ""
        if self._bed_removal is not None:
            label = self._bed_removal.label_at(frame)
        self.status_lbl.setText("Cut paused — hold-down collision")
        # Defer the modal out of the play-timer/signal callback — a QMessageBox shown
        # from inside a timer tick can be swallowed (so it never appeared).
        QTimer.singleShot(0, lambda: QMessageBox.warning(
            self, "Hold-down collision",
            "The tool or its holder reaches a hold-down at this point in the cut "
            f"({label}) — the simulation paused here (the tool is red).\n\n"
            "Reposition the part on the bed, raise the hold-down height if it's set "
            "too low, or adjust the toolpath before cutting. Press play to continue."))

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
            self._partition is not None and self._partition.classified
            and self._lens_od is not None)
        self.status_lbl.setText("G-code ready")
        # Capture the program + setup for the .gmodel container (M5.1). A new
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
                self._save_gmodel_to(self._project_path, announce=False)
                self.append_log(f"[project] Updated {self._project_path.name} with the new program.")
            else:
                self._mark_dirty()   # program held in memory until Save Project
        # Fold this program's checks into the Inspector (M7.14). A fresh program
        # supersedes any prior cut report, so clear it until the sim re-runs.
        if w is not None:
            self._diag_reach = list(getattr(w, "reach_warnings", []))
            self._diag_clearance = list(getattr(w, "clearance_violations", []))
            self._diag_lint = list(getattr(w, "machine_warnings", []))
            self._diag_cut_report = None
            self._refresh_inspector()
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
            self._partition is not None and self._partition.classified
            and self._lens_od is not None)
        self.status_lbl.setText("G-code generation failed — see log")

    def _on_gcode_cancelled(self) -> None:
        self._close_progress()
        self.append_log("[gcode] Cancelled.")
        self._act_gcode.setEnabled(True)
        self._act_block.setEnabled(self._lens_od is not None)
        self._act_worktable.setEnabled(
            self._partition is not None and self._partition.classified
            and self._lens_od is not None)
        self.status_lbl.setText("G-code cancelled")

    def _on_open_in_guildsend(self) -> None:
        """Hand the job to GuildSend (the ecosystem's sender). The saved
        .gmodel travels whole — GuildSend reads it natively: programs, setup
        sheet, tools, material, and the tagged worktable (its M7.2 bundle
        path), so nothing is lost to a loose .nc export."""
        if not self._last_programs:
            QMessageBox.information(
                self, "Open in GuildSend",
                "Generate a program first — GuildSend runs the stored G-code.")
            return
        if self._project_path is None or self._dirty:
            # The handoff is the file on disk; make sure it holds this session.
            self._on_save_project()
            if self._project_path is None or self._dirty:
                return                            # save dialog cancelled
        cmd = _find_guildsend()
        if cmd is None:
            QMessageBox.warning(
                self, "GuildSend not found",
                "GuildSend isn't installed (or isn't in its usual place).\n\n"
                "Install GuildSend, then use File ▸ Open in GuildSend again —\n"
                "or open the saved .gmodel from GuildSend's File ▸ Open Job.")
            return
        import subprocess
        try:
            subprocess.Popen(cmd + [str(self._project_path)])
        except OSError as exc:
            QMessageBox.warning(self, "Open in GuildSend",
                                f"Could not launch GuildSend:\n{exc}")
            return
        self.append_log(f"[send] Opened {self._project_path.name} in GuildSend.")
        self.status_lbl.setText(f"Sent to GuildSend — {self._project_path.name}")

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
        from guildmodel import __version__

        QMessageBox.about(
            self,
            "About GuildModel",
            f"<b>GuildModel</b> v{__version__}<br><br>"
            "Free, open-source CAM tool for spectacle frame cutting on GRBL CNCs.<br>"
            "Companion to the Guild CNC and gSender fork.<br><br>"
            "The frame-front workflow is hardware-proven on real acetate. The "
            "temple, base-curve-block, and worktable-nesting paths are "
            "<i>beta</i> — built and cut-sim-verified, not yet fully "
            "hardware-validated.<br><br>"
            "GPLv3 — see LICENSE for details.",
        )


# ------------------------------------------------------------------ entry point

class _FboProbe(logging.Handler):
    """Diagnostic for the once-per-session VTK 0×0-framebuffer error (see the
    BUILDPLAN known issue). VTK routes render errors through Python logging;
    when the framebuffer one arrives, snapshot what the window was doing so
    the next occurrence pinpoints the trigger. Remove once root-caused."""

    def __init__(self, win) -> None:
        super().__init__()
        self._win = win

    def emit(self, record) -> None:  # noqa: D102
        try:
            if "ramebuffer" not in record.getMessage():
                return
            w = self._win
            v = w.view3d
            msg = (f"[fbo-probe] view={w._current_view} "
                   f"tab={w.component_tabs.currentIndex()} "
                   f"minimized={w.isMinimized()} active={w.isActiveWindow()} "
                   f"v3d hidden={v.isHidden()} size={v.width()}x{v.height()} "
                   f"mode={v.mode()}")
            print(msg, file=sys.__stderr__)
            QTimer.singleShot(0, lambda m=msg: w.append_log(m))
        except Exception:
            pass   # a diagnostic must never break a render


def _find_guildsend() -> Optional[list]:
    """Locate GuildSend as a launchable command, or None.

    Tried in order: the per-user install (Inno's ``{localappdata}\\Programs``
    default), a ``guildsend`` on PATH (pip/venv install), then — for
    developers — the sibling source checkout run through its own venv."""
    import shutil
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        exe = Path(local) / "Programs" / "GuildSend" / "GuildSend.exe"
        if exe.is_file():
            return [str(exe)]
    which = shutil.which("guildsend")
    if which:
        return [which]
    sibling = Path(__file__).resolve().parents[3].parent / "GuildSend"
    for py_name in ("pythonw.exe", "python.exe"):
        py = sibling / ".venv" / "Scripts" / py_name
        if py.is_file() and (sibling / "main.py").is_file():
            return [str(py), str(sibling / "main.py")]
    return None


def _app_icon():
    """The GuildModel app/window icon, or None if the asset is missing.

    Prefers the multi-resolution ``.ico`` (crisp at every taskbar size); falls
    back to the source ``.svg``. The ``assets/`` dir sits beside the package and
    is bundled by the PyInstaller build (see build_common.py)."""
    from pathlib import Path
    from PySide6.QtGui import QIcon

    assets = Path(__file__).resolve().parents[1] / "assets"
    for name in ("icon.ico", "icon.svg"):
        p = assets / name
        if p.exists():
            return QIcon(str(p))
    return None


def main() -> None:
    """Back-compat entry (``python -m guildmodel.gui.app``). The real boot
    sequence — splash before the heavy VTK import — lives in gui/boot.py,
    which the ``guildmodel`` entry point and main.py use directly."""
    from guildmodel.gui.boot import main as boot_main
    boot_main()


if __name__ == "__main__":
    main()
