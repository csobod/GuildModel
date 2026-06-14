"""Cut Simulation view — renders the simulated machined piece (BUILDPLAN M5).

Takes a ``core.sim.CutReport`` and draws the achieved cut-piece top surface,
tinting cells the toolpaths left **uncut** (red) or **gouged** (orange), with a
pass/warn/fail badge and camera presets. The verification it visualises is what
catches incompleteness (like the pad-block/nosepad rims) before cutting acetate.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QFrame, QLabel, QCheckBox, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize

from guildcam.gui.style import theme
from guildcam.gui import icons as icons_mod

_PLACEHOLDER = "Click 'Simulate Cut' to verify the machined result"
_UNCUT_RGB = (0.85, 0.33, 0.31)      # red
_GOUGE_RGB = (0.94, 0.68, 0.31)      # orange
_BADGE = {
    "ok":   ("✓  Cut verified", "#2e7d32"),
    "warn": ("⚠  Review cut",    "#b8860b"),
    "fail": ("✕  Incomplete cut", "#c0392b"),
}


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


class CutSimView(QWidget):
    """PyVista viewport showing the simulated cut piece + verification overlays."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._palette = theme.palette(False)
        self._dark = False
        self._report = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

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

        self._chk_uncut = QCheckBox("Uncut"); self._chk_uncut.setChecked(True)
        self._chk_uncut.setToolTip("Highlight regions the toolpaths leave proud of the target")
        self._chk_gouge = QCheckBox("Gouge"); self._chk_gouge.setChecked(True)
        self._chk_gouge.setToolTip("Highlight regions cut below the target surface")
        self._chk_uncut.toggled.connect(self._refresh_colors)
        self._chk_gouge.toggled.connect(self._refresh_colors)
        tb.addWidget(self._chk_uncut); tb.addWidget(self._chk_gouge)

        tb.addStretch()
        self._badge = QLabel("")
        self._badge.setObjectName("hintLabel")
        tb.addWidget(self._badge)
        self._layout.addWidget(toolbar)

        self._placeholder = QLabel(_PLACEHOLDER)
        self._placeholder.setObjectName("placeholderLabel")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)

        self._plotter = None
        self._mesh = None

    # ------------------------------------------------------------------ icons/theme

    def _apply_camera_icons(self) -> None:
        for icon_name, (btn, label) in self._cam_buttons.items():
            icon = icons_mod.themed_icon(icon_name, self._dark)
            if icon is not None:
                btn.setIcon(icon); btn.setText("")
            else:
                btn.setText(label)

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = dark
        self._palette = theme.palette(dark)
        self._apply_camera_icons()
        if self._plotter is not None:
            self._plotter.set_background(self._palette.canvas_bg)
            self._plotter.render()

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

    # ------------------------------------------------------------------ render

    def show_report(self, report) -> None:
        """Render the cut piece from a core.sim.CutReport."""
        self._report = report
        status = report.status()
        text, color = _BADGE.get(status, ("", "#888"))
        c = report.completeness
        self._badge.setText(
            f"{text} — {100 * (1 - c.uncut_fraction):.1f}% reached")
        self._badge.setStyleSheet(f"color: {color}; font-weight: 600;")
        if not self._ensure_plotter():
            return
        self._build_mesh(report)
        self._refresh_colors()
        self._plotter.reset_camera()

    def _build_mesh(self, report) -> None:
        import pyvista as pv
        floor = report.floor
        inside = np.isfinite(report.target)
        rows, cols = floor.shape
        ox, oy = report.origin
        res = report.resolution
        xs = ox + np.arange(cols) * res
        ys = oy + np.arange(rows) * res
        X, Y = np.meshgrid(xs, ys)
        pts = np.column_stack([X.ravel(), Y.ravel(), floor.ravel()]).astype(np.float32)

        # quads where all four corners are body cells (lens holes drop out)
        idx = np.arange(rows * cols).reshape(rows, cols)
        c00 = idx[:-1, :-1]; c10 = idx[1:, :-1]; c01 = idx[:-1, 1:]; c11 = idx[1:, 1:]
        quad_ok = (inside[:-1, :-1] & inside[1:, :-1] &
                   inside[:-1, 1:] & inside[1:, 1:])
        q = quad_ok.ravel()
        tris = np.empty((quad_ok.sum() * 2, 4), dtype=np.int64)
        a, b, c2, d = c00.ravel()[q], c10.ravel()[q], c11.ravel()[q], c01.ravel()[q]
        tris[0::2] = np.column_stack([np.full(a.shape, 3), a, b, c2])
        tris[1::2] = np.column_stack([np.full(a.shape, 3), a, c2, d])
        self._mesh = pv.PolyData(pts, tris.ravel())

    def _refresh_colors(self) -> None:
        if self._plotter is None or self._mesh is None or self._report is None:
            return
        rep = self._report
        n = self._mesh.n_points
        base = np.array(_hex_rgb(self._palette.mesh_surface))
        rgb = np.tile(base, (n, 1))
        if self._chk_uncut.isChecked():
            rgb[rep.completeness.uncut_mask.ravel()] = _UNCUT_RGB
        if self._chk_gouge.isChecked():
            rgb[rep.gouge.gouge_mask.ravel()] = _GOUGE_RGB
        self._mesh["colors"] = (rgb * 255).astype(np.uint8)
        self._plotter.clear()
        self._plotter.add_mesh(self._mesh, scalars="colors", rgb=True,
                               smooth_shading=False, show_edges=False, lighting=True)
        self._plotter.render()

    def clear(self) -> None:
        if self._plotter is not None:
            self._plotter.clear()
        self._badge.setText("")

    # ------------------------------------------------------------------ camera

    def _cam_iso(self):
        if self._plotter: self._plotter.view_isometric()

    def _cam_top(self):
        if self._plotter: self._plotter.view_xy()

    def _cam_front(self):
        if self._plotter: self._plotter.view_xz()

    def _cam_reset(self):
        if self._plotter: self._plotter.reset_camera()
