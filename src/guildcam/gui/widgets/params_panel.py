"""Left-sidebar parameter panel.

Organises all GuildCAM parameters into collapsible QGroupBox sections:
  Import, Boxing (read-only / auto-computed), Relief, CAM, Hinges.

Signals fire whenever the user changes a value.  The owning window
connects them to update the preview and marks the project as modified.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout,
    QGroupBox, QFormLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from guildcam.core.layers import LAYER_STYLES


def _heading_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("heading", "true")
    return lbl


def _ro_field(value: str = "—") -> QLineEdit:
    """Read-only display field."""
    f = QLineEdit(value)
    f.setReadOnly(True)
    f.setAlignment(Qt.AlignmentFlag.AlignRight)
    return f


def _spinbox(
    value: float,
    min_: float,
    max_: float,
    step: float = 0.1,
    decimals: int = 2,
    suffix: str = " mm",
) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(min_, max_)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(value)
    sb.setSuffix(suffix)
    return sb


class ParamsPanel(QWidget):
    """Scrollable panel with all GuildCAM parameter groups."""

    # --- signals emitted when values change ---
    relief_changed = Signal()
    cam_changed = Signal()
    hinge_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(290)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        scroll.setWidget(container)

        self._build_import_group()
        self._build_boxing_group()
        self._build_relief_group()
        self._build_cam_group()
        self._build_hinge_group()
        self._layout.addStretch()

    # ------------------------------------------------------------------ import

    def _build_import_group(self) -> None:
        grp = QGroupBox("Import")
        lay = QVBoxLayout(grp)

        self.import_btn = QPushButton("Open DXF…")
        lay.addWidget(self.import_btn)

        self.source_label = QLabel("No file loaded")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet("font-size: 11px; color: #555;")
        lay.addWidget(self.source_label)

        # layer visibility checkboxes
        vis_label = QLabel("Layer visibility:")
        vis_label.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 4px;")
        lay.addWidget(vis_label)

        self._layer_checks: dict[str, QCheckBox] = {}
        for layer, (color, _) in LAYER_STYLES.items():
            cb = QCheckBox(layer)
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {color}; font-size: 11px;")
            lay.addWidget(cb)
            self._layer_checks[layer] = cb

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------ boxing

    def _build_boxing_group(self) -> None:
        grp = QGroupBox("Boxing Dimensions  (ISO 8624)")
        lay = QVBoxLayout(grp)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.field_a   = _ro_field()
        self.field_b   = _ro_field()
        self.field_dbl = _ro_field()
        self.field_ed  = _ro_field()

        form.addRow("A  (lens width):", self.field_a)
        form.addRow("B  (lens height):", self.field_b)
        form.addRow("DBL  (bridge gap):", self.field_dbl)
        form.addRow("ED  (eff. dia.):", self.field_ed)
        lay.addLayout(form)

        note = QLabel("Auto-calculated from lens outline on import.")
        note.setStyleSheet("font-size: 10px; color: #888; margin-top: 2px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        self._layout.addWidget(grp)

    def update_boxing(
        self, a: float, b: float, dbl: float, ed: float
    ) -> None:
        """Populate boxing fields from measured values."""
        self.field_a.setText(f"{a:.2f} mm")
        self.field_b.setText(f"{b:.2f} mm")
        self.field_dbl.setText(f"{dbl:.2f} mm")
        self.field_ed.setText(f"{ed:.2f} mm")

    # ------------------------------------------------------------------ relief

    def _build_relief_group(self) -> None:
        grp = QGroupBox("Relief")
        lay = QVBoxLayout(grp)

        # Scallop
        self.scallop_cb = QCheckBox("Back scallop")
        self.scallop_cb.setChecked(True)
        self.scallop_cb.toggled.connect(self.relief_changed)
        lay.addWidget(self.scallop_cb)

        scallop_form = QFormLayout()
        scallop_form.setContentsMargins(16, 0, 0, 0)
        self.scallop_central = _spinbox(10.0, 1.0, 30.0, suffix=" mm")
        self.scallop_slope   = _spinbox(8.0, 1.0, 20.0, suffix=" mm")
        self.scallop_min     = _spinbox(1.2, 0.5, 3.0, suffix=" mm")
        scallop_form.addRow("Central zone:", self.scallop_central)
        scallop_form.addRow("Slope extent:", self.scallop_slope)
        scallop_form.addRow("Min thickness:", self.scallop_min)
        for sb in (self.scallop_central, self.scallop_slope, self.scallop_min):
            sb.valueChanged.connect(self.relief_changed)
        lay.addLayout(scallop_form)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # Nosepad
        self.nosepad_cb = QCheckBox("Nosepad dome")
        self.nosepad_cb.setChecked(True)
        self.nosepad_cb.toggled.connect(self.relief_changed)
        lay.addWidget(self.nosepad_cb)

        nosepad_form = QFormLayout()
        nosepad_form.setContentsMargins(16, 0, 0, 0)
        self.nosepad_height    = _spinbox(1.5, 0.5, 5.0, suffix=" mm")
        self.nosepad_footprint = _spinbox(12.0, 5.0, 25.0, suffix=" mm")
        nosepad_form.addRow("Height:", self.nosepad_height)
        nosepad_form.addRow("Footprint:", self.nosepad_footprint)
        for sb in (self.nosepad_height, self.nosepad_footprint):
            sb.valueChanged.connect(self.relief_changed)
        lay.addLayout(nosepad_form)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        # Groove
        self.groove_cb = QCheckBox("Lens groove (bevel)")
        self.groove_cb.setChecked(True)
        self.groove_cb.toggled.connect(self.relief_changed)
        lay.addWidget(self.groove_cb)

        groove_form = QFormLayout()
        groove_form.setContentsMargins(16, 0, 0, 0)
        self.groove_depth = _spinbox(0.8, 0.2, 2.0, suffix=" mm")
        self.groove_width = _spinbox(0.6, 0.2, 2.0, suffix=" mm")
        groove_form.addRow("Depth:", self.groove_depth)
        groove_form.addRow("Width:", self.groove_width)
        for sb in (self.groove_depth, self.groove_width):
            sb.valueChanged.connect(self.relief_changed)
        lay.addLayout(groove_form)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------ CAM

    def _build_cam_group(self) -> None:
        grp = QGroupBox("CAM Settings")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.tool_relief = QComboBox()
        self.tool_relief.addItems(["ball_1mm", "ball_2mm"])
        self.tool_relief.setCurrentText("ball_2mm")
        form.addRow("Relief tool:", self.tool_relief)

        self.tool_profile = QComboBox()
        self.tool_profile.addItems(["flat_3mm", "flat_6mm"])
        self.tool_profile.setCurrentText("flat_3mm")
        form.addRow("Profile tool:", self.tool_profile)

        self.material = QComboBox()
        self.material.addItems(["acetate", "zyl (auto)", "horn", "metal"])
        form.addRow("Material:", self.material)

        self.stock_thickness = _spinbox(6.0, 1.0, 12.0, step=0.5, suffix=" mm")
        form.addRow("Stock thickness:", self.stock_thickness)

        self.stepover = _spinbox(0.4, 0.1, 2.0, suffix=" mm")
        self.stepdown_relief = _spinbox(0.5, 0.1, 2.0, suffix=" mm")
        self.stepdown_profile = _spinbox(1.5, 0.5, 3.0, suffix=" mm")
        form.addRow("Relief stepover:", self.stepover)
        form.addRow("Relief stepdown:", self.stepdown_relief)
        form.addRow("Profile stepdown:", self.stepdown_profile)

        self.tab_count = QSpinBox()
        self.tab_count.setRange(0, 8)
        self.tab_count.setValue(4)
        self.tab_count.setSuffix("  tabs")
        self.tab_width = _spinbox(3.0, 1.0, 8.0, suffix=" mm")
        self.tab_height = _spinbox(1.0, 0.3, 3.0, suffix=" mm")
        form.addRow("Hold-down tabs:", self.tab_count)
        form.addRow("Tab width:", self.tab_width)
        form.addRow("Tab height:", self.tab_height)

        for w in (self.tool_relief, self.tool_profile, self.material,
                  self.stock_thickness,
                  self.stepover, self.stepdown_relief, self.stepdown_profile,
                  self.tab_count, self.tab_width, self.tab_height):
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.cam_changed)
            else:
                w.currentIndexChanged.connect(self.cam_changed)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------ hinges

    def _build_hinge_group(self) -> None:
        grp = QGroupBox("Hinges")
        lay = QVBoxLayout(grp)

        self.hinge_enabled = QCheckBox("Enable hinge pockets")
        self.hinge_enabled.setChecked(True)
        self.hinge_enabled.toggled.connect(self.hinge_changed)
        lay.addWidget(self.hinge_enabled)

        form = QFormLayout()
        self.hinge_type = QComboBox()
        self.hinge_type.addItems([
            "screw_barrel_14x5p5",
            "screw_barrel_14x7",
            "spring_hinge_16x5p5",
        ])
        form.addRow("Type:", self.hinge_type)

        self.hinge_od_x = _spinbox(0.0, -200.0, 200.0, suffix=" mm")
        self.hinge_od_y = _spinbox(0.0, -100.0, 100.0, suffix=" mm")
        self.hinge_od_rot = _spinbox(0.0, -180.0, 180.0, suffix=" °")
        form.addRow("OD  X:", self.hinge_od_x)
        form.addRow("OD  Y:", self.hinge_od_y)
        form.addRow("OD  rot:", self.hinge_od_rot)

        self.hinge_os_x = _spinbox(0.0, -200.0, 200.0, suffix=" mm")
        self.hinge_os_y = _spinbox(0.0, -100.0, 100.0, suffix=" mm")
        self.hinge_os_rot = _spinbox(0.0, -180.0, 180.0, suffix=" °")
        form.addRow("OS  X:", self.hinge_os_x)
        form.addRow("OS  Y:", self.hinge_os_y)
        form.addRow("OS  rot:", self.hinge_os_rot)

        lay.addLayout(form)

        for w in (self.hinge_type, self.hinge_od_x, self.hinge_od_y, self.hinge_od_rot,
                  self.hinge_os_x, self.hinge_os_y, self.hinge_os_rot):
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.hinge_changed)
            else:
                w.currentIndexChanged.connect(self.hinge_changed)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------ helpers

    @property
    def layer_checks(self) -> dict[str, QCheckBox]:
        return self._layer_checks
