"""Unified 3D viewer — ONE PyVista/VTK render window for both the model preview
and the cut simulation (BUILDPLAN M7 VTK-context fix).

Earlier builds put the 3D model preview and the cut-sim in two *separate*
``QtInteractor`` windows inside the central ``QStackedWidget``. On Windows, hiding
one (navigating to the other view, or to another component tab) invalidated its
native OpenGL context and corrupted the surviving one — a burst of
``wglMakeCurrent: handle invalid`` and a blanked/frozen viewport.

This widget eliminates the second context: the cut-sim is a **mode** of the single
viewer, not a separate page. ``set_mode("model"|"sim")`` swaps the toolbar's
mode-specific section and the actors drawn into the shared plotter. There is only
ever one VTK window, so toggling model↔sim never hides a render window; the only
hide is the normal single-context case of leaving the 3D page entirely (handled by
``showEvent`` re-rendering on return).

Model mode shows the trimesh solid + stock ghost + program-zero triad + the temple
core-guide; sim mode shows the achieved cut floor tinted Uncut (red) / Gouge
(orange) with the pass/warn/fail badge. Both drive the same plotter.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QPushButton,
    QButtonGroup, QFrame, QLabel, QCheckBox, QSizePolicy, QSlider,
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer

from guildcam.gui.style import theme
from guildcam.gui import icons as icons_mod

_MODEL_PLACEHOLDER = "Click 'Build 3D' to generate the preview mesh"
_UNCUT_RGB = (0.85, 0.33, 0.31)      # red — material left proud of the target
_GOUGE_RGB = (0.94, 0.68, 0.31)      # orange — cut below the target surface
_BADGE = {
    "ok":   ("✓  Cut verified", "#2e7d32"),
    "warn": ("⚠  Review cut",    "#b8860b"),
    "fail": ("✕  Incomplete cut", "#c0392b"),
}


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


class Viewer3D(QWidget):
    """One embedded VTK viewport with a **model** mode and a **sim** mode.

    The ``QtInteractor`` is created lazily on first use. Model and sim scenes are
    cached separately, so ``set_mode`` re-draws the stored scene without a rebuild.
    """

    stage_changed = Signal(str)   # relief.castle.CASTLE_STAGES value (model mode)
    playback_step_changed = Signal(int, str)   # op index, op label (sim scrubber, M7.12)

    # the teaching stepper (model mode): (label, stage value, icon, tooltip)
    _STAGE_BUTTONS = [
        ("Towers",   "towers",  "stage-towers",  "Towers only"),
        ("+Walls",   "walls",   "stage-walls",   "Towers + walls"),
        ("+Footing", "footing", "stage-footing", "Towers + walls + footing"),
        ("Full",     "pockets", "stage-full",    "Full posterior (with pockets)"),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._palette = theme.palette(False)
        self._dark = False
        self._mode = "model"

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # ---- toolbar: shared camera presets + a mode-specific section ----------
        toolbar = QWidget()
        toolbar.setObjectName("toolbarStrip")
        toolbar.setFixedHeight(30)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(6, 2, 6, 2)
        tb.setSpacing(4)

        self._cam_buttons: dict[str, tuple[QPushButton, str]] = {}
        for icon_name, label, slot in [
            ("view-iso", "Iso", "_cam_iso"), ("view-top", "Top", "_cam_top"),
            ("view-front", "Front", "_cam_front"), ("view-reset", "Reset", "_cam_reset"),
        ]:
            b = QPushButton(); b.setFixedHeight(22); b.setFixedWidth(30)
            b.setIconSize(QSize(18, 18))
            b.setToolTip("Reset camera" if icon_name == "view-reset" else f"{label} view")
            b.clicked.connect(getattr(self, slot))
            tb.addWidget(b)
            self._cam_buttons[icon_name] = (b, label)
        self._apply_camera_icons()

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        tb.addSpacing(6); tb.addWidget(sep); tb.addSpacing(6)

        # the mode-specific section swaps with the viewer mode (plain Qt widgets —
        # no native GL, so the stacked-widget hide is harmless)
        self._mode_stack = QStackedWidget()
        self._mode_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._mode_stack.addWidget(self._build_model_section())   # 0 — model
        self._mode_stack.addWidget(self._build_sim_section())     # 1 — sim
        tb.addWidget(self._mode_stack, 1)
        self._layout.addWidget(toolbar)

        # ---- placeholder until the plotter is created --------------------------
        self._placeholder = QLabel(_MODEL_PLACEHOLDER)
        self._placeholder.setObjectName("placeholderLabel")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)

        self._plotter: Optional[object] = None    # pyvistaqt.QtInteractor (shared)

        # model-mode scene cache
        self._model_pv = None                     # pv.PolyData (computed normals)
        self._model_stock = None
        self._model_core_guide = None
        self._model_zero = None
        self._zero_actors: list = []
        self._zero_xyz: Optional[tuple] = None
        self._model_label_text = "No mesh"

        # sim-mode scene cache
        self._report = None
        self._sim_mesh = None                     # pv.PolyData (cut floor)
        self._sim_inside = None                   # bool grid: body cells (triangulation mask)

        # playback scrubber — volumetric removal (BUILDPLAN M7.12.1, was M7.12 sheet)
        self._removal = None                      # core.sim.RemovalPlayback
        self._removal_grid = None                 # pv.StructuredGrid (carved top, in-place)
        self._play_idx = 0
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(120)         # ~8 fps timeline (fine frames)
        self._play_timer.timeout.connect(self._advance_play)

    # ------------------------------------------------------------------ toolbar build

    def _build_model_section(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)

        stage_lbl = QLabel("Castle:"); stage_lbl.setObjectName("hintLabel")
        lay.addWidget(stage_lbl)

        self._stage_group = QButtonGroup(self)
        self._stage_group.setExclusive(True)
        self._stage_buttons: dict[str, QPushButton] = {}
        self._stage_icons: dict[str, tuple[QPushButton, str]] = {}
        for label, stage, icon_name, tip in self._STAGE_BUTTONS:
            b = QPushButton(); b.setFixedHeight(22); b.setFixedWidth(30)
            b.setIconSize(QSize(18, 18)); b.setCheckable(True); b.setEnabled(False)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=stage: self.stage_changed.emit(s))
            self._stage_group.addButton(b)
            lay.addWidget(b)
            self._stage_buttons[stage] = b
            self._stage_icons[icon_name] = (b, label)
        self._stage_buttons["pockets"].setChecked(True)
        self._apply_stage_icons()

        lay.addStretch()
        self._mesh_label = QLabel("No mesh"); self._mesh_label.setObjectName("hintLabel")
        lay.addWidget(self._mesh_label)
        return w

    def _build_sim_section(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)

        self._chk_uncut = QCheckBox("Uncut"); self._chk_uncut.setChecked(True)
        self._chk_uncut.setToolTip("Highlight regions the toolpaths leave proud of the target")
        self._chk_gouge = QCheckBox("Gouge"); self._chk_gouge.setChecked(True)
        self._chk_gouge.setToolTip("Highlight regions cut below the target surface")
        self._chk_uncut.toggled.connect(self._refresh_colors)
        self._chk_gouge.toggled.connect(self._refresh_colors)
        lay.addWidget(self._chk_uncut); lay.addWidget(self._chk_gouge)

        # ---- playback scrubber (BUILDPLAN M7.12) — hidden until snapshots set ----
        self._play_btn = QPushButton("▶"); self._play_btn.setFixedSize(24, 22)
        self._play_btn.setToolTip("Play / pause the cut, op by op")
        self._play_btn.clicked.connect(self._toggle_play)
        self._scrub = QSlider(Qt.Orientation.Horizontal)
        self._scrub.setToolTip("Scrub the cut to any op boundary")
        self._scrub.setMinimumWidth(120)
        self._scrub.valueChanged.connect(self._on_scrub)
        self._step_label = QLabel(""); self._step_label.setObjectName("hintLabel")
        self._step_label.setMinimumWidth(96)
        lay.addSpacing(8)
        lay.addWidget(self._play_btn); lay.addWidget(self._scrub, 1)
        lay.addWidget(self._step_label)
        for wdg in (self._play_btn, self._scrub, self._step_label):
            wdg.setVisible(False)

        lay.addStretch()
        self._badge = QLabel(""); self._badge.setObjectName("hintLabel")
        lay.addWidget(self._badge)
        return w

    # ------------------------------------------------------------------ icons/theme

    def _apply_camera_icons(self) -> None:
        for icon_name, (btn, label) in self._cam_buttons.items():
            icon = icons_mod.themed_icon(icon_name, self._dark)
            if icon is not None:
                btn.setIcon(icon); btn.setText("")
            else:
                btn.setText(label)

    def _apply_stage_icons(self) -> None:
        for icon_name, (btn, label) in self._stage_icons.items():
            icon = icons_mod.themed_icon(icon_name, self._dark)
            if icon is not None:
                btn.setIcon(icon); btn.setText("")
            else:
                btn.setText(label)

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = dark
        self._palette = theme.palette(dark)
        self._apply_camera_icons()
        self._apply_stage_icons()
        if self._plotter is not None:
            self._plotter.set_background(self._palette.canvas_bg)
            self._safe_render()

    # ------------------------------------------------------------------ plotter

    def _ensure_plotter(self) -> bool:
        if self._plotter is not None:
            return True
        try:
            from pyvistaqt import QtInteractor
            self._plotter = QtInteractor(self)
            self._plotter.set_background(self._palette.canvas_bg)
            self._plotter.enable_anti_aliasing()
            self._plotter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._layout.removeWidget(self._placeholder)
            self._placeholder.hide()
            self._layout.addWidget(self._plotter)
            return True
        except Exception as exc:
            self._placeholder.setText(f"3D viewer unavailable:\n{exc}")
            return False

    def _safe_render(self) -> None:
        """Render only when this widget is the visible stack page. Rendering a
        hidden QtInteractor throws `wglMakeCurrent: handle invalid`."""
        if self._plotter is not None and not self.isHidden():
            try:
                self._plotter.render()
            except Exception:
                pass

    def showEvent(self, event) -> None:
        """Re-render when this page becomes current — the QtInteractor loses its GL
        context while hidden (the first frame after a view switch is otherwise blank)."""
        super().showEvent(event)
        self._safe_render()

    # ------------------------------------------------------------------ mode

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Switch between the model and sim scenes in the *same* render window.

        Re-draws only when the mode actually changes; the new component's content
        is pushed right after via show_mesh/show_report, so a same-mode tab switch
        skips a redundant (and briefly stale) render."""
        if mode not in ("model", "sim") or mode == self._mode:
            self._mode = mode
            self._mode_stack.setCurrentIndex(0 if mode == "model" else 1)
            return
        self._mode = mode
        self._mode_stack.setCurrentIndex(0 if mode == "model" else 1)
        if mode == "model":
            self._render_model(reset_camera=False)
        else:
            self._render_sim(reset_camera=False)

    # ------------------------------------------------------------------ model mode

    def set_stage_enabled(self, enabled: bool) -> None:
        for btn in self._stage_buttons.values():
            btn.setEnabled(enabled)

    def set_stage(self, stage: str) -> None:
        btn = self._stage_buttons.get(stage)
        if btn is not None:
            btn.setChecked(True)

    def show_mesh(self, mesh, stock=None, core_guide=None, program_zero=None) -> None:
        """Cache a trimesh.Trimesh as the model scene and draw it if model mode is
        current. `stock`/`core_guide`/`program_zero` match the old Preview3D API."""
        if not self._ensure_plotter():
            return
        import pyvista as pv

        verts = np.array(mesh.vertices, dtype=np.float32)
        faces = mesh.faces
        pv_faces = np.hstack([
            np.full((len(faces), 1), 3, dtype=np.int32), faces.astype(np.int32),
        ]).ravel()
        pv_mesh = pv.PolyData(verts, pv_faces)
        # split sharp creases so smooth shading keeps the footing blends soft
        pv_mesh = pv_mesh.compute_normals(split_vertices=True, feature_angle=40.0)

        self._model_pv = pv_mesh
        self._model_stock = stock
        self._model_core_guide = core_guide
        self._model_zero = tuple(program_zero) if program_zero is not None else None
        self._model_label_text = f"{len(verts):,} verts · {len(faces):,} tris"
        if self._mode == "model":
            self._render_model(reset_camera=True)
        else:
            self._mesh_label.setText(self._model_label_text)

    def _render_model(self, reset_camera: bool) -> None:
        # A bare mode switch must not eagerly create a GL context — only re-draw an
        # existing plotter. The plotter is created on demand by show_mesh/show_report.
        if self._plotter is None:
            return
        import pyvista as pv

        self._plotter.clear()
        self._zero_actors = []
        if self._model_pv is None:
            self._mesh_label.setText("No mesh")
            self._safe_render()
            return

        self._plotter.add_mesh(
            self._model_pv, color=self._palette.mesh_surface, smooth_shading=True,
            show_edges=False, lighting=True, specular=0.3, specular_power=20,
        )
        self._plotter.add_light(
            pv.Light(position=(100, -50, 200), focal_point=(0, 0, 0), intensity=0.8))

        stock = self._model_stock
        if stock is not None:
            half_l = stock.blank_length_mm / 2.0
            half_w = stock.blank_width_mm / 2.0
            boxes = [pv.Box(bounds=(
                -half_l, half_l, -half_w, half_w, 0.0, stock.blank_thickness_mm))]
            if (stock.pad_block_length_mm > 0 and stock.pad_block_width_mm > 0
                    and stock.pad_block_thickness_mm > 0):
                half_pl = stock.pad_block_length_mm / 2.0
                half_pw = stock.pad_block_width_mm / 2.0
                dx, dy = stock.pad_block_dx_mm, stock.pad_block_dy_mm
                boxes.append(pv.Box(bounds=(
                    dx - half_pl, dx + half_pl, dy - half_pw, dy + half_pw,
                    stock.blank_thickness_mm, stock.total_pad_height_mm)))
            for b in boxes:
                self._plotter.add_mesh(b.extract_all_edges(),
                                       color=self._palette.stock_ghost, line_width=1)

        if self._model_core_guide is not None and stock is not None:
            x0, y0, x1, y1 = self._model_core_guide
            zc = stock.blank_thickness_mm / 2.0
            half_h = min(0.8, stock.blank_thickness_mm / 3.0)
            self._plotter.add_mesh(
                pv.Box(bounds=(x0, x1, y0, y1, zc - half_h, zc + half_h)),
                color="#7a7a7a", opacity=0.45, show_edges=True, edge_color="#555555")

        self._draw_program_zero(self._model_zero, stock)
        if reset_camera:
            self._plotter.reset_camera(render=False)
        self._safe_render()
        self._mesh_label.setText(self._model_label_text)

    def _axis_length(self, stock) -> float:
        if stock is not None:
            return max(8.0, min(stock.blank_length_mm, stock.blank_width_mm) * 0.18)
        return 12.0

    def _draw_program_zero(self, point, stock=None) -> None:
        """(Re)draw the program-zero axis triad at `point` (design-frame x,y,z) —
        +X red, +Y green, +Z blue, plus a sphere + 'G54 zero' label. Never resets
        the camera, so it updates live on a sidebar change."""
        if self._plotter is None:
            return
        import pyvista as pv

        for a in self._zero_actors:
            try:
                self._plotter.remove_actor(a, reset_camera=False, render=False)
            except Exception:
                pass
        self._zero_actors = []
        self._zero_xyz = tuple(point) if point is not None else None
        if point is None:
            self._safe_render()
            return

        x, y, z = point
        length = self._axis_length(stock)
        for (dx, dy, dz), color in (((length, 0, 0), "#d83a3a"),
                                    ((0, length, 0), "#3aa83a"),
                                    ((0, 0, length), "#3a6ed8")):
            self._zero_actors.append(self._plotter.add_mesh(
                pv.Line((x, y, z), (x + dx, y + dy, z + dz)),
                color=color, line_width=4, reset_camera=False))
        self._zero_actors.append(self._plotter.add_mesh(
            pv.Sphere(radius=length * 0.09, center=(x, y, z)),
            color="#222222", reset_camera=False))
        try:
            self._zero_actors.append(self._plotter.add_point_labels(
                [(x, y, z)], ["G54 zero"], font_size=11, point_size=1,
                text_color=self._palette.annotation, shape=None,
                reset_camera=False, render=False))
        except Exception:
            pass
        self._safe_render()

    def set_program_zero(self, point, stock=None) -> None:
        """Live-update the datum triad (sidebar change) without reloading the mesh.
        Only meaningful in model mode; the cached value is kept for the next render."""
        self._model_zero = tuple(point) if point is not None else None
        self._model_stock = stock if stock is not None else self._model_stock
        if self._mode == "model" and self._model_pv is not None:
            self._draw_program_zero(self._model_zero, self._model_stock)

    # ------------------------------------------------------------------ sim mode

    def show_report(self, report) -> None:
        """Cache a core.sim.CutReport as the sim scene and draw it if sim mode is
        current (matches the old CutSimView API). Resets any playback scrubber —
        a fresh report (e.g. the whole-bed sim) has no per-op sequence until
        ``set_playback`` provides one."""
        self._report = report
        self._reset_playback()
        status = report.status()
        text, color = _BADGE.get(status, ("", "#888"))
        c = report.completeness
        self._badge.setText(f"{text} — {100 * (1 - c.uncut_fraction):.1f}% reached")
        self._badge.setStyleSheet(f"color: {color}; font-weight: 600;")
        if not self._ensure_plotter():
            return
        self._sim_inside = np.isfinite(report.target)
        self._sim_mesh = self._floor_polydata(report.floor)
        if self._mode == "sim":
            self._render_sim(reset_camera=True)

    def _floor_polydata(self, floor):
        """Triangulate an achieved-floor grid into a pv.PolyData (body cells only),
        using the cached `report.origin/resolution` + the inside mask. Shared by the
        final report and every playback snapshot (BUILDPLAN M7.12)."""
        import pyvista as pv
        inside = self._sim_inside
        rows, cols = floor.shape
        ox, oy = self._report.origin
        res = self._report.resolution
        xs = ox + np.arange(cols) * res
        ys = oy + np.arange(rows) * res
        X, Y = np.meshgrid(xs, ys)
        pts = np.column_stack([X.ravel(), Y.ravel(), floor.ravel()]).astype(np.float32)

        idx = np.arange(rows * cols).reshape(rows, cols)
        c00 = idx[:-1, :-1]; c10 = idx[1:, :-1]; c01 = idx[:-1, 1:]; c11 = idx[1:, 1:]
        quad_ok = (inside[:-1, :-1] & inside[1:, :-1] &
                   inside[:-1, 1:] & inside[1:, 1:])
        q = quad_ok.ravel()
        tris = np.empty((quad_ok.sum() * 2, 4), dtype=np.int64)
        a, b, c2, d = c00.ravel()[q], c10.ravel()[q], c11.ravel()[q], c01.ravel()[q]
        tris[0::2] = np.column_stack([np.full(a.shape, 3), a, b, c2])
        tris[1::2] = np.column_stack([np.full(a.shape, 3), a, c2, d])
        return pv.PolyData(pts, tris.ravel())

    def _render_sim(self, reset_camera: bool) -> None:
        # Like _render_model: a bare mode switch never creates the GL context.
        if self._plotter is None:
            return
        # A removal playback (single-component) renders the volumetric block; a bare
        # report (bed sim) renders the floor sheet. On a model→sim switch the plotter
        # was cleared, so rebuild the block actors before re-carving to the cursor.
        if self._removal is not None:
            self._build_block_scene(self._removal)
            self._render_removal_frame(self._play_idx, reset_camera=reset_camera)
            return
        if self._sim_mesh is None or self._report is None:
            self._plotter.clear()
            self._safe_render()
            return
        self._apply_sim_colors()
        if reset_camera:
            self._plotter.reset_camera(render=False)
        self._safe_render()

    def _apply_sim_colors(self) -> None:
        rep = self._report
        n = self._sim_mesh.n_points
        base = np.array(_hex_rgb(self._palette.mesh_surface))
        rgb = np.tile(base, (n, 1))
        if self._chk_uncut.isChecked():
            rgb[rep.completeness.uncut_mask.ravel()] = _UNCUT_RGB
        if self._chk_gouge.isChecked():
            rgb[rep.gouge.gouge_mask.ravel()] = _GOUGE_RGB
        self._sim_mesh["colors"] = (rgb * 255).astype(np.uint8)
        self._plotter.clear()
        self._plotter.add_mesh(self._sim_mesh, scalars="colors", rgb=True,
                               smooth_shading=False, show_edges=False, lighting=True)

    def _refresh_colors(self) -> None:
        """Uncut/Gouge toggle — the floor-sheet view (bed sim) only; the volumetric
        block carries no uncut/gouge tint in v1."""
        if (self._plotter is None or self._mode != "sim" or self._sim_mesh is None
                or self._report is None or self._removal is not None):
            return
        self._apply_sim_colors()
        self._safe_render()

    # ------------------------------------------------------------------ removal playback (M7.12.1)

    def set_removal(self, playback) -> None:
        """Render the cut as a solid stock block carved frame by frame (M7.12.1).

        `playback` is a `core.sim.RemovalPlayback`: the remaining stock at fine
        timeline steps. The block is built once; scrubbing/playing updates only the
        carved top surface's Z in place (fixed topology → GPU-fast). Supersedes the
        M7.12 floor-sheet scrubber for single-component sims. None/empty hides it."""
        self._reset_playback()
        if playback is None or playback.n_frames == 0 or not self._ensure_plotter():
            return
        self._removal = playback
        self._chk_uncut.setVisible(False)         # the block has no uncut/gouge tint (v1)
        self._chk_gouge.setVisible(False)
        last = playback.n_frames - 1
        self._play_idx = last
        self._build_block_scene(playback)         # opaque carved top + stock envelope
        self._scrub.blockSignals(True)
        self._scrub.setRange(0, last)
        self._scrub.setValue(last)                # rest on the finished part
        self._scrub.blockSignals(False)
        for wdg in (self._play_btn, self._scrub, self._step_label):
            wdg.setVisible(True)
        if self._mode == "sim":
            self._render_removal_frame(last, reset_camera=True)
        self._update_step_label()

    def _reset_playback(self) -> None:
        self._play_timer.stop()
        self._removal = None
        self._removal_grid = None
        self._play_idx = 0
        self._play_btn.setText("▶")
        self._chk_uncut.setVisible(True)
        self._chk_gouge.setVisible(True)
        for wdg in (self._play_btn, self._scrub, self._step_label):
            wdg.setVisible(False)

    def _build_block_scene(self, pb) -> None:
        """Build the static stock envelope (walls + bottom) + the carved top surface
        as an in-place-updatable structured grid (BUILDPLAN M7.12.1)."""
        import pyvista as pv
        self._plotter.clear()
        rows, cols = pb.stock_top.shape
        ox, oy = pb.origin
        res = pb.resolution
        xs = ox + np.arange(cols) * res
        ys = oy + np.arange(rows) * res
        X, Y = np.meshgrid(xs, ys)                # (rows, cols), C-order ravel below

        # carved top surface — structured grid, points in C order, dims (cols, rows, 1)
        grid = pv.StructuredGrid()
        grid.points = np.column_stack([
            X.ravel(order="C"), Y.ravel(order="C"),
            pb.frames[self._play_idx].ravel(order="C")]).astype(np.float64)
        grid.dimensions = (cols, rows, 1)
        self._removal_grid = grid
        self._plotter.add_mesh(grid, color=self._palette.mesh_surface,
                               smooth_shading=False, show_edges=False, lighting=True,
                               specular=0.2, specular_power=15)

        # static stock envelope: bottom + 4 walls at the grid extent, blank height
        xmin, xmax = float(xs[0]), float(xs[-1])
        ymin, ymax = float(ys[0]), float(ys[-1])
        ztop = float(np.median(pb.stock_top))     # the blank height (edge-uniform)
        v = np.array([
            [xmin, ymin, 0.0], [xmax, ymin, 0.0], [xmax, ymax, 0.0], [xmin, ymax, 0.0],
            [xmin, ymin, ztop], [xmax, ymin, ztop], [xmax, ymax, ztop], [xmin, ymax, ztop],
        ], dtype=np.float64)
        faces = np.hstack([
            [4, 0, 1, 2, 3],                      # bottom
            [4, 0, 1, 5, 4], [4, 1, 2, 6, 5],     # front / right walls
            [4, 2, 3, 7, 6], [4, 3, 0, 4, 7],     # back / left walls
        ]).astype(np.int64)
        self._plotter.add_mesh(pv.PolyData(v, faces),
                               color=self._palette.stock_ghost, opacity=0.5,
                               show_edges=False, lighting=True)

    def _update_step_label(self) -> None:
        if self._removal is None:
            self._step_label.setText("")
            return
        label = self._removal.frame_labels[self._play_idx]
        self._step_label.setText(
            f"{self._play_idx + 1}/{self._removal.n_frames} · {label}")

    def _on_scrub(self, idx: int) -> None:
        if self._removal is None:
            return
        self._play_idx = max(0, min(idx, self._removal.n_frames - 1))
        self._render_removal_frame(self._play_idx)
        self._update_step_label()
        label = self._removal.frame_labels[self._play_idx]
        self.playback_step_changed.emit(self._play_idx, label)

    def _render_removal_frame(self, idx: int, reset_camera: bool = False) -> None:
        """Carve the block to frame `idx` by updating the top surface's Z in place."""
        if self._plotter is None or self._removal is None or self._removal_grid is None:
            return
        pts = self._removal_grid.points
        pts[:, 2] = self._removal.frames[idx].ravel(order="C")
        self._removal_grid.points = pts           # reassign → marks modified
        if reset_camera:
            self._plotter.reset_camera(render=False)
        self._safe_render()

    def _toggle_play(self) -> None:
        if self._removal is None:
            return
        if self._play_timer.isActive():
            self._play_timer.stop()
            self._play_btn.setText("▶")
            return
        if self._play_idx >= self._removal.n_frames - 1:
            self._scrub.setValue(0)               # replay from the uncut block
        self._play_btn.setText("▮▮")
        self._play_timer.start()

    def _advance_play(self) -> None:
        if self._removal is None or self._play_idx >= self._removal.n_frames - 1:
            self._play_timer.stop()
            self._play_btn.setText("▶")
            return
        self._scrub.setValue(self._play_idx + 1)   # → _on_scrub renders + emits

    # ------------------------------------------------------------------ clear

    def clear(self) -> None:
        """Drop the model scene (called when the active component has no mesh). The
        sim scene is left cached; sim isn't shared across tabs anyway."""
        self._model_pv = None
        self._model_stock = None
        self._model_core_guide = None
        self._model_zero = None
        self._model_label_text = "No mesh"
        self._zero_actors = []
        if self._plotter is not None and self._mode == "model":
            self._plotter.clear()
            self._mesh_label.setText("No mesh")
            self._safe_render()

    # ------------------------------------------------------------------ camera

    def _cam_iso(self):
        if self._plotter: self._plotter.view_isometric()

    def _cam_top(self):
        if self._plotter: self._plotter.view_xy()

    def _cam_front(self):
        if self._plotter: self._plotter.view_xz()

    def _cam_reset(self):
        if self._plotter: self._plotter.reset_camera()
