"""3D preview widget — PyVista/VTK embedded in a Qt window.

Accepts a trimesh.Trimesh and renders it with a lit, face-coloured surface.
Provides camera presets (top, front, iso), the castle stage stepper
(BUILDPLAN M4.4 — Towers → +Walls → +Footing → Full), and an optional
stock-outline ghost.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QButtonGroup, QFrame, QLabel, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, Signal

from guildcam.gui.style import theme
from guildcam.gui import icons as icons_mod

_PLACEHOLDER_TEXT = "Click 'Build 3D' to generate the preview mesh"


class Preview3D(QWidget):
    """PyVista viewport embedded in PySide6.

    The pyvistaqt.QtInteractor is created lazily on first use to avoid
    import overhead at startup.
    """

    stage_changed = Signal(str)   # relief.castle.CASTLE_STAGES value

    # (button label, CASTLE_STAGES value, icon name, tooltip) — the teaching
    # stepper. Icons are a 4-step build storyboard; label is the text fallback.
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

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Top camera toolbar (styled by the theme via #toolbarStrip)
        toolbar = QWidget()
        toolbar.setObjectName("toolbarStrip")
        toolbar.setFixedHeight(30)
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(6, 2, 6, 2)
        tb_lay.setSpacing(4)

        # Camera presets — icon-only with tooltips (icons recolored per theme).
        # (label kept for the text fallback when an SVG is missing.)
        self._cam_buttons: dict[str, tuple[QPushButton, str]] = {}
        for icon_name, label, slot_name in [
            ("view-iso", "Iso", "_cam_iso"),
            ("view-top", "Top", "_cam_top"),
            ("view-front", "Front", "_cam_front"),
            ("view-reset", "Reset", "_cam_reset"),
        ]:
            btn = QPushButton()
            btn.setFixedHeight(22)
            btn.setFixedWidth(30)
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(f"{label} view" if icon_name != "view-reset" else "Reset camera")
            btn.clicked.connect(getattr(self, slot_name))
            tb_lay.addWidget(btn)
            self._cam_buttons[icon_name] = (btn, label)
        self._apply_camera_icons()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        tb_lay.addSpacing(6)
        tb_lay.addWidget(sep)
        tb_lay.addSpacing(6)

        # Castle stage stepper: watch the castle being built
        stage_lbl = QLabel("Castle:")
        stage_lbl.setObjectName("hintLabel")
        tb_lay.addWidget(stage_lbl)

        self._stage_group = QButtonGroup(self)
        self._stage_group.setExclusive(True)
        self._stage_buttons: dict[str, QPushButton] = {}
        # icon-name -> (button, text-fallback label), for per-theme recoloring
        self._stage_icons: dict[str, tuple[QPushButton, str]] = {}
        for label, stage, icon_name, tip in self._STAGE_BUTTONS:
            btn = QPushButton()
            btn.setFixedHeight(22)
            btn.setFixedWidth(30)
            btn.setIconSize(QSize(18, 18))
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, s=stage: self.stage_changed.emit(s))
            self._stage_group.addButton(btn)
            tb_lay.addWidget(btn)
            self._stage_buttons[stage] = btn
            self._stage_icons[icon_name] = (btn, label)
        self._stage_buttons["pockets"].setChecked(True)
        self._apply_stage_icons()

        tb_lay.addStretch()

        self._mesh_label = QLabel("No mesh")
        self._mesh_label.setObjectName("hintLabel")
        tb_lay.addWidget(self._mesh_label)

        self._layout.addWidget(toolbar)

        # Placeholder until PyVista is initialised
        self._placeholder = QLabel(_PLACEHOLDER_TEXT)
        self._placeholder.setObjectName("placeholderLabel")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)

        self._plotter: Optional[object] = None   # pyvistaqt.QtInteractor
        self._mesh_actor = None

    # ------------------------------------------------------------------ init plotter

    def _ensure_plotter(self) -> bool:
        """Create the PyVista Qt interactor on first use. Returns True on success."""
        if self._plotter is not None:
            return True
        try:
            from pyvistaqt import QtInteractor
            import pyvista as pv

            self._plotter = QtInteractor(self)
            self._plotter.set_background(self._palette.canvas_bg)
            self._plotter.enable_anti_aliasing()
            self._plotter.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

            # Replace placeholder
            self._layout.removeWidget(self._placeholder)
            self._placeholder.hide()
            self._layout.addWidget(self._plotter)
            return True
        except Exception as exc:
            self._placeholder.setText(f"3D viewer unavailable:\n{exc}")
            return False

    # ------------------------------------------------------------------ public API

    def _apply_camera_icons(self) -> None:
        """(Re)render the camera-preset icons for the current theme; fall back
        to the short text label when an SVG is missing."""
        for icon_name, (btn, label) in self._cam_buttons.items():
            icon = icons_mod.themed_icon(icon_name, self._dark)
            if icon is not None:
                btn.setIcon(icon)
                btn.setText("")
            else:
                btn.setText(label)

    def _apply_stage_icons(self) -> None:
        """(Re)render the castle stage-stepper icons for the current theme;
        fall back to the text label when an SVG is missing."""
        for icon_name, (btn, label) in self._stage_icons.items():
            icon = icons_mod.themed_icon(icon_name, self._dark)
            if icon is not None:
                btn.setIcon(icon)
                btn.setText("")
            else:
                btn.setText(label)

    def set_dark_mode(self, dark: bool) -> None:
        """Swap the viewport palette (the Qt chrome restyles via the app QSS)."""
        self._dark = dark
        self._palette = theme.palette(dark)
        self._apply_camera_icons()
        self._apply_stage_icons()
        if self._plotter is not None:
            self._plotter.set_background(self._palette.canvas_bg)
            self._plotter.render()

    def set_stage_enabled(self, enabled: bool) -> None:
        """Enable the castle stepper (matched SCULPT zone layouts only)."""
        for btn in self._stage_buttons.values():
            btn.setEnabled(enabled)

    def set_stage(self, stage: str) -> None:
        """Reflect the current stage in the stepper without emitting."""
        btn = self._stage_buttons.get(stage)
        if btn is not None:
            btn.setChecked(True)

    def show_mesh(self, mesh: "trimesh.Trimesh", stock=None) -> None:  # noqa: F821
        """Load a trimesh.Trimesh into the viewer.

        stock: optional project.schema.StockDefinition — drawn as wireframe
        ghosts of the blank and pad block around the part.
        """
        if not self._ensure_plotter():
            return

        import pyvista as pv
        import numpy as np

        # Convert trimesh → PyVista PolyData
        verts = np.array(mesh.vertices, dtype=np.float32)
        faces = mesh.faces
        # PyVista face format: prepend face size (always 3 for triangles)
        pv_faces = np.hstack([
            np.full((len(faces), 1), 3, dtype=np.int32),
            faces.astype(np.int32),
        ]).ravel()
        pv_mesh = pv.PolyData(verts, pv_faces)
        # Split sharp creases (rim corners, pocket walls) so smooth shading
        # keeps the footing blends soft without smearing the silhouette
        # (M4.5 Part B preview polish).
        pv_mesh = pv_mesh.compute_normals(
            split_vertices=True, feature_angle=40.0
        )

        self._plotter.clear()
        self._mesh_actor = self._plotter.add_mesh(
            pv_mesh,
            color=self._palette.mesh_surface,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.3,
            specular_power=20,
        )
        self._plotter.add_light(
            pv.Light(position=(100, -50, 200), focal_point=(0, 0, 0), intensity=0.8)
        )

        if stock is not None:
            half_l = stock.blank_length_mm / 2.0
            half_w = stock.blank_width_mm / 2.0
            boxes = [pv.Box(bounds=(
                -half_l, half_l, -half_w, half_w, 0.0, stock.blank_thickness_mm
            ))]
            half_pl = stock.pad_block_length_mm / 2.0
            half_pw = stock.pad_block_width_mm / 2.0
            dx, dy = stock.pad_block_dx_mm, stock.pad_block_dy_mm
            boxes.append(pv.Box(bounds=(
                dx - half_pl, dx + half_pl, dy - half_pw, dy + half_pw,
                stock.blank_thickness_mm, stock.total_pad_height_mm,
            )))
            for box in boxes:
                self._plotter.add_mesh(
                    box.extract_all_edges(),
                    color=self._palette.stock_ghost, line_width=1,
                )

        self._plotter.reset_camera()

        n_verts = len(verts)
        n_tris = len(faces)
        self._mesh_label.setText(f"{n_verts:,} verts · {n_tris:,} tris")

    def clear(self) -> None:
        if self._plotter is not None:
            self._plotter.clear()
            self._mesh_label.setText("No mesh")

    # ------------------------------------------------------------------ camera presets

    def _cam_iso(self) -> None:
        if self._plotter:
            self._plotter.view_isometric()

    def _cam_top(self) -> None:
        if self._plotter:
            self._plotter.view_xy()

    def _cam_front(self) -> None:
        if self._plotter:
            self._plotter.view_xz()

    def _cam_reset(self) -> None:
        if self._plotter:
            self._plotter.reset_camera()
