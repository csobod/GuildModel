"""3D preview widget — PyVista/VTK embedded in a Qt window.

Accepts a trimesh.Trimesh and renders it with a lit, face-coloured surface.
Provides camera presets (top, front, iso) and a simple toolbar.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSizePolicy,
)
from PySide6.QtCore import Qt


_PLACEHOLDER_TEXT = "Click 'Build 3D' to generate the preview mesh"


class Preview3D(QWidget):
    """PyVista viewport embedded in PySide6.

    The pyvistaqt.QtInteractor is created lazily on first use to avoid
    import overhead at startup.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Top camera toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(30)
        toolbar.setStyleSheet("background: #ffe8a8; border-bottom: 1px solid #c8a040;")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(6, 2, 6, 2)
        tb_lay.setSpacing(4)

        for label, slot_name in [("Iso", "_cam_iso"), ("Top", "_cam_top"), ("Front", "_cam_front"), ("Reset", "_cam_reset")]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setFixedWidth(44)
            btn.clicked.connect(getattr(self, slot_name))
            tb_lay.addWidget(btn)
        tb_lay.addStretch()

        self._mesh_label = QLabel("No mesh")
        self._mesh_label.setStyleSheet("font-size: 10px; color: #888;")
        tb_lay.addWidget(self._mesh_label)

        self._layout.addWidget(toolbar)

        # Placeholder until PyVista is initialised
        self._placeholder = QLabel(_PLACEHOLDER_TEXT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #c8a040; font-size: 13px;")
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
            self._plotter.set_background("#fafaf5")
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

    def show_mesh(self, mesh: "trimesh.Trimesh") -> None:  # noqa: F821
        """Load a trimesh.Trimesh into the viewer."""
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
        pv_mesh.compute_normals(inplace=True)

        self._plotter.clear()
        self._mesh_actor = self._plotter.add_mesh(
            pv_mesh,
            color="#d4a84b",
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.3,
            specular_power=20,
        )
        self._plotter.add_light(
            pv.Light(position=(100, -50, 200), focal_point=(0, 0, 0), intensity=0.8)
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
