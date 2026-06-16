"""Right-dock parameter panel — a tabbed container (BUILDPLAN M4.6 Part A).

``ParamsPanel`` is a ``QTabWidget`` with four tabs, each its own scroll area
(no fixed width, no horizontal clipping):

  * **Frame**  — file identity, raw layer summary, layer-visibility checks,
                 Boxing read-outs (ISO 8624);
  * **Castle** — the parametric castle (Towers / Walls / Footing) + the Zones
                 inspector;
  * **Stock**  — blank + pad block;
  * **CAM**    — material, onion skin, hand-finishing allowance, and the
                 no-SCULPT profile fallback.

Castle vocabulary (towers / walls / footing) appears only in tab/group titles
and labels — the teaching frame. Widget identifiers and the schema built by
:meth:`castle_params` keep the anatomical/boxing vocabulary (BUILDPLAN §2).

Signals fire whenever the user changes a value.  The owning window connects
them to rebuild the preview and redraw the stock outline.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import yaml

from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout,
    QGroupBox, QFormLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QListWidget, QListWidgetItem, QFrame, QTabWidget,
)
from PySide6.QtCore import Qt, Signal

from guildcam.core.layers import LAYER_STYLES
from guildcam.gui.style import theme
from guildcam.gui import material_store
from guildcam.core.post.machine import available_machines
from guildcam.core.project.schema import (
    CastleCamParams, CastleParams, FootingFillet, FootingSchedule,
    POSTERIOR_OPS, ProgramZero, StockDefinition, ZoneThicknesses,
)

# Sentinel shown in a per-op tool combo meaning "use the global Tool above".
_SAME_AS_GLOBAL = "(same as Tool)"

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _tool_names() -> list[str]:
    try:
        data = yaml.safe_load((_CONFIG_DIR / "tools.yaml").read_text(encoding="utf-8"))
        return list(data.keys())
    except Exception:
        return ["flat_3175"]


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


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionLabel")
    return lbl


class _ZoneList(QListWidget):
    """QListWidget that reports when the pointer leaves it."""

    pointer_left = Signal()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.pointer_left.emit()
        super().leaveEvent(event)


class ParamsPanel(QTabWidget):
    """Tabbed parameter panel (Frame / Castle / Stock / CAM)."""

    # --- signals emitted when values change ---
    castle_changed = Signal()      # any zone height / footing / pocket depth
    stock_changed = Signal()       # blank / pad block dimensions
    cam_changed = Signal()         # tool / material / allowances / fallback
    zone_hovered = Signal(str)     # zone name under the cursor, "" on leave

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)

        self._partition = None    # CastlePartition from the last import

        # Each tab is an independently scrolling column; no fixed width so the
        # Footing label + spinbox-pair rows never clip at the right edge.
        self.addTab(self._scroll_tab(self._build_frame_tab), "Frame")
        self.addTab(self._scroll_tab(self._build_castle_tab), "Castle")
        self.addTab(self._scroll_tab(self._build_stock_tab), "Stock")
        self.addTab(self._scroll_tab(self._build_cam_tab), "CAM")

    # ------------------------------------------------------------------ tab scaffold

    def _scroll_tab(self, build) -> QScrollArea:
        """Wrap a tab-builder's column in a vertically scrolling area."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        build(lay)
        lay.addStretch()
        scroll.setWidget(container)
        return scroll

    # ------------------------------------------------------------------ Frame tab

    def _build_frame_tab(self, lay: QVBoxLayout) -> None:
        self._build_file_group(lay)
        self._build_boxing_group(lay)

    def _build_file_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Frame")
        glay = QVBoxLayout(grp)

        self.source_label = QLabel("No file loaded")
        self.source_label.setWordWrap(True)
        self.source_label.setObjectName("smallLabel")
        glay.addWidget(self.source_label)

        self.raw_layers_label = QLabel("Layers: —")
        self.raw_layers_label.setWordWrap(True)
        self.raw_layers_label.setObjectName("mutedSmallLabel")
        glay.addWidget(self.raw_layers_label)

        # layer visibility checkboxes (tinted with the layer color)
        glay.addWidget(_section_label("Layer visibility:"))

        self._layer_checks: dict[str, QCheckBox] = {}
        for layer in LAYER_STYLES:
            cb = QCheckBox(layer)
            cb.setChecked(True)
            glay.addWidget(cb)
            self._layer_checks[layer] = cb
        self._tint_layer_checks(dark=False)

        lay.addWidget(grp)

    def _tint_layer_checks(self, dark: bool) -> None:
        for layer, cb in self._layer_checks.items():
            color = theme.layer_color(LAYER_STYLES[layer][0], dark)
            cb.setStyleSheet(f"color: {color}; font-size: 11px;")

    def set_dark_mode(self, dark: bool) -> None:
        """Re-tint the layer checkboxes (everything else restyles via QSS)."""
        self._tint_layer_checks(dark)

    def set_file(self, name: str, layer_summary: str) -> None:
        """Update the Frame tab's file identity (called on import)."""
        self.source_label.setText(name)
        self.raw_layers_label.setText(layer_summary)

    # ------------------------------------------------------------------ boxing

    def _build_boxing_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Boxing Dimensions  (ISO 8624)")
        glay = QVBoxLayout(grp)

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
        glay.addLayout(form)

        note = QLabel("Auto-calculated from lens outline on import.")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        glay.addWidget(note)

        lay.addWidget(grp)

    def update_boxing(
        self, a: float, b: float, dbl: float, ed: float
    ) -> None:
        """Populate boxing fields from measured values."""
        self.field_a.setText(f"{a:.2f} mm")
        self.field_b.setText(f"{b:.2f} mm")
        self.field_dbl.setText(f"{dbl:.2f} mm")
        self.field_ed.setText(f"{ed:.2f} mm")

    # ------------------------------------------------------------------ Castle tab

    def _build_castle_tab(self, lay: QVBoxLayout) -> None:
        self._build_castle_group(lay)
        self._build_zones_group(lay)

    def _build_castle_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Castle")
        glay = QVBoxLayout(grp)

        # --- Towers: the high load-bearing masses ---
        glay.addWidget(_section_label("Towers"))
        towers = QFormLayout()
        towers.setContentsMargins(8, 0, 0, 0)
        towers.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.zone_endpiece = _spinbox(5.5, 0.5, 12.0, decimals=1)
        self.zone_bridge = _spinbox(5.3, 0.5, 12.0, decimals=1)
        self.zone_nosepad = _spinbox(10.0, 0.5, 15.0, decimals=1)
        self.hinge_pocket_depth = _spinbox(1.0, 0.0, 3.0, decimals=1)
        towers.addRow("Endpieces:", self.zone_endpiece)
        towers.addRow("Bridge:", self.zone_bridge)
        towers.addRow("Nosepads:", self.zone_nosepad)
        towers.addRow("Hinge pocket depth:", self.hinge_pocket_depth)
        self.hinge_pocket_depth.setToolTip(
            "Pocket floor sits this far below the endpiece height."
        )
        glay.addLayout(towers)

        # --- Walls: the eyewires spanning between the towers ---
        glay.addWidget(_section_label("Walls"))
        walls = QFormLayout()
        walls.setContentsMargins(8, 0, 0, 0)
        walls.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.zone_eyewire_superior = _spinbox(4.8, 0.5, 12.0, decimals=1)
        self.zone_eyewire_inferior = _spinbox(4.2, 0.5, 12.0, decimals=1)
        walls.addRow("Superior eyewires:", self.zone_eyewire_superior)
        walls.addRow("Inferior eyewires:", self.zone_eyewire_inferior)
        glay.addLayout(walls)

        # --- Footing: rolling-ball fillet pairs per step edge ---
        glay.addWidget(_section_label("Footing  (exterior / interior)"))
        footing = QFormLayout()
        footing.setContentsMargins(8, 0, 0, 0)
        footing.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # canonical edge -> (label, ext default, int default); the application
        # order ("first") is not exposed — defaults follow the Fusion timeline.
        edge_rows = [
            ("endpiece_superior", "Endpiece sup.:", 32.0, 48.0),
            ("endpiece_inferior", "Endpiece inf.:", 16.0, 32.0),
            ("bridge_superior", "Bridge sup.:", 24.0, 32.0),
            ("nosepad_superior", "Nosepad sup.:", 6.0, 4.0),
            ("nosepad_inferior", "Nosepad inf.:", 9.0, 10.0),
        ]
        self.footing_spins: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        for canonical, label, ext, intr in edge_rows:
            ext_sb = _spinbox(ext, 0.0, 60.0, step=1.0, decimals=1, suffix="")
            int_sb = _spinbox(intr, 0.0, 60.0, step=1.0, decimals=1, suffix="")
            ext_sb.setToolTip("Exterior (convex) radius at the top of the step, mm")
            int_sb.setToolTip("Interior (concave) radius at the base of the step, mm")
            pair = QHBoxLayout()
            pair.setSpacing(4)
            pair.addWidget(ext_sb)
            pair.addWidget(int_sb)
            footing.addRow(label, pair)
            self.footing_spins[canonical] = (ext_sb, int_sb)
        glay.addLayout(footing)

        for sb in self._castle_spinboxes():
            sb.valueChanged.connect(self._on_castle_spin)

        lay.addWidget(grp)

    def _castle_spinboxes(self) -> list[QDoubleSpinBox]:
        boxes = [
            self.zone_endpiece, self.zone_bridge, self.zone_nosepad,
            self.hinge_pocket_depth,
            self.zone_eyewire_superior, self.zone_eyewire_inferior,
        ]
        for ext_sb, int_sb in self.footing_spins.values():
            boxes += [ext_sb, int_sb]
        return boxes

    def _on_castle_spin(self) -> None:
        self._refresh_zone_list()
        self.castle_changed.emit()

    # ------------------------------------------------------------------ Stock tab

    def _build_stock_tab(self, lay: QVBoxLayout) -> None:
        self._build_stock_group(lay)

    def _build_stock_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Stock")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.blank_length = _spinbox(170.0, 50.0, 300.0, step=1.0, decimals=1)
        self.blank_width = _spinbox(85.0, 30.0, 200.0, step=1.0, decimals=1)
        self.blank_thickness = _spinbox(6.0, 1.0, 12.0, step=0.5, decimals=1)
        form.addRow("Blank length:", self.blank_length)
        form.addRow("Blank width:", self.blank_width)
        form.addRow("Blank thickness:", self.blank_thickness)

        self.pad_length = _spinbox(45.0, 10.0, 120.0, step=1.0, decimals=1)
        self.pad_width = _spinbox(45.0, 10.0, 120.0, step=1.0, decimals=1)
        self.pad_thickness = _spinbox(4.0, 0.5, 10.0, step=0.5, decimals=1)
        form.addRow("Pad block length:", self.pad_length)
        form.addRow("Pad block width:", self.pad_width)
        form.addRow("Pad block thickness:", self.pad_thickness)

        for sb in (self.blank_length, self.blank_width, self.blank_thickness,
                   self.pad_length, self.pad_width, self.pad_thickness):
            sb.valueChanged.connect(self.stock_changed)

        lay.addWidget(grp)

    # ------------------------------------------------------------------ zones

    def _build_zones_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Zones")
        glay = QVBoxLayout(grp)

        self.zones_status = QLabel("No SCULPT zones — load a frame DXF.")
        self.zones_status.setWordWrap(True)
        self.zones_status.setObjectName("hintLabel")
        glay.addWidget(self.zones_status)

        self.zone_list = _ZoneList()
        self.zone_list.setMouseTracking(True)
        self.zone_list.setFixedHeight(140)
        self.zone_list.itemEntered.connect(
            lambda item: self.zone_hovered.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        self.zone_list.pointer_left.connect(lambda: self.zone_hovered.emit(""))
        glay.addWidget(self.zone_list)

        lay.addWidget(grp)

    def set_zones(self, partition) -> None:
        """Populate the zone inspector from a CastlePartition (or None)."""
        self._partition = partition
        if partition is None:
            self.zones_status.setText(
                "No SCULPT zones — draw 5 section cuts per side in GuildDraw."
            )
        elif partition.matched:
            self.zones_status.setText(
                f"{len(partition.zones)} zones — standard castle layout."
            )
        else:
            self.zones_status.setText(
                "⚠ Generic zones — the castle needs the 5-cuts-per-side layout."
            )
        self._refresh_zone_list()

    def _refresh_zone_list(self) -> None:
        self.zone_list.clear()
        if self._partition is None:
            return
        zones = self._castle_zone_thicknesses()
        for z in self._partition.zones:
            if z.kind == "generic":
                item = QListWidgetItem(f"⚠ {z.name} — unmatched")
                item.setForeground(Qt.GlobalColor.darkRed)
            else:
                item = QListWidgetItem(f"{z.name} — {zones.for_kind(z.kind):.1f} mm")
            item.setData(Qt.ItemDataRole.UserRole, z.name)
            self.zone_list.addItem(item)

    # ------------------------------------------------------------------ CAM tab

    def _build_cam_tab(self, lay: QVBoxLayout) -> None:
        self._build_machine_tool_group(lay)
        self._build_program_zero_group(lay)
        self._build_strategy_group(lay)
        self._build_cam_group(lay)

    # mapping between schema literals and the combo display order
    _PZ_MODE = [("stock_box", "Stock box"), ("fixture", "Fixture (design frame)")]
    _PZ_X = [("left", "Left"), ("center", "Center"), ("right", "Right")]
    _PZ_Y = [("bottom", "Bottom"), ("center", "Center"), ("top", "Top")]
    _PZ_Z = [("top", "Top face"), ("bottom", "Bottom face (anterior)")]

    def _build_program_zero_group(self, lay: QVBoxLayout) -> None:
        """Where the program's G54 work zero lands (BUILDPLAN M6.2)."""
        d = ProgramZero()
        grp = QGroupBox("Program Zero  (G54 work datum)")
        grp.setToolTip(
            "Where you touch off work zero. 'Stock box' zeroes to a corner/centre "
            "of the blank and its top or bottom face — what a maker sets on the "
            "stock. 'Fixture' keeps the design frame (blank centre, anterior). "
            "A post-time offset only — the 3D model and cut simulation are "
            "unaffected."
        )
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def _combo(pairs, current):
            cb = QComboBox()
            for _key, label in pairs:
                cb.addItem(label)
            cb.setCurrentIndex([k for k, _ in pairs].index(current))
            cb.currentIndexChanged.connect(self.cam_changed)
            return cb

        self.pz_mode = _combo(self._PZ_MODE, d.mode)
        self.pz_x = _combo(self._PZ_X, d.x_ref)
        self.pz_y = _combo(self._PZ_Y, d.y_ref)
        self.pz_z = _combo(self._PZ_Z, d.z_ref)
        self.pz_mode.currentIndexChanged.connect(self._sync_program_zero_enabled)
        form.addRow("Zero mode:", self.pz_mode)
        form.addRow("X datum:", self.pz_x)
        form.addRow("Y datum:", self.pz_y)
        form.addRow("Z datum:", self.pz_z)
        lay.addWidget(grp)
        self._sync_program_zero_enabled()

    def _sync_program_zero_enabled(self) -> None:
        """The X/Y/Z datum pickers only apply in stock-box mode."""
        stock_box = self._PZ_MODE[self.pz_mode.currentIndex()][0] == "stock_box"
        for cb in (self.pz_x, self.pz_y, self.pz_z):
            cb.setEnabled(stock_box)

    def _program_zero(self) -> ProgramZero:
        return ProgramZero(
            mode=self._PZ_MODE[self.pz_mode.currentIndex()][0],
            x_ref=self._PZ_X[self.pz_x.currentIndex()][0],
            y_ref=self._PZ_Y[self.pz_y.currentIndex()][0],
            z_ref=self._PZ_Z[self.pz_z.currentIndex()][0],
        )

    def _set_program_zero(self, pz: ProgramZero) -> None:
        for cb, pairs, val in (
            (self.pz_mode, self._PZ_MODE, pz.mode),
            (self.pz_x, self._PZ_X, pz.x_ref),
            (self.pz_y, self._PZ_Y, pz.y_ref),
            (self.pz_z, self._PZ_Z, pz.z_ref),
        ):
            keys = [k for k, _ in pairs]
            if val in keys:
                cb.blockSignals(True)
                cb.setCurrentIndex(keys.index(val))
                cb.blockSignals(False)
        self._sync_program_zero_enabled()

    def _build_machine_tool_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Machine & Tool")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.machine = QComboBox()
        self._machine_names: list[str] = []
        for name, display in available_machines():
            self._machine_names.append(name)
            self.machine.addItem(display)
        self.machine.setToolTip(
            "Target controller. Feeds, plunge, spindle and depth-of-cut are "
            "clamped to this machine; curves are linearized if it has no arc "
            "support. Profiles are user-editable YAML in config/machines/."
        )
        form.addRow("Machine:", self.machine)

        self.cam_tool = QComboBox()
        self.cam_tool.addItems(_tool_names())
        self.cam_tool.setCurrentText("flat_3175")
        self.cam_tool.setToolTip(
            "Default tool for the posterior program; every op uses it unless "
            "given its own tool below. Add tools by editing config/tools.yaml."
        )
        form.addRow("Tool:", self.cam_tool)
        lay.addWidget(grp)
        self._build_op_tools_group(lay)

    def _build_op_tools_group(self, lay: QVBoxLayout) -> None:
        """Per-operation tool selectors (BUILDPLAN M6.1 multi-tool jobs).

        Each op may keep the global tool or pick its own; a tool change is posted
        at op boundaries where the tool differs (a small tool for the hinge
        pockets, the bulk tool for relief / eyewires / perimeter is the everyday
        case)."""
        grp = QGroupBox("Per-operation tools  (multi-tool jobs)")
        grp.setToolTip(
            "Assign a tool per operation. '(same as Tool)' uses the default above. "
            "Differing tools post a tool-change block (M6/M0 per machine profile); "
            "the order pockets → relief → contours keeps same-tool ops grouped."
        )
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        names = _tool_names()
        self.op_tool_combos: dict[str, QComboBox] = {}
        for op in POSTERIOR_OPS:
            cb = QComboBox()
            cb.addItem(_SAME_AS_GLOBAL)
            cb.addItems(names)
            cb.currentIndexChanged.connect(self.cam_changed)
            self.op_tool_combos[op] = cb
            form.addRow(f"{op}:", cb)
        lay.addWidget(grp)

    def _build_strategy_group(self, lay: QVBoxLayout) -> None:
        d = CastleCamParams()
        grp = QGroupBox("Cut Strategy  (time / finish)")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.relief_stepover = _spinbox(d.relief_stepover_mm, 0.2, 3.0, step=0.05)
        self.relief_stepover.setToolTip(
            "Spacing between relief finishing passes. Lower = finer surface but "
            "longer cut; 0.9 mm matches the Fusion reference's coverage."
        )
        form.addRow("Relief stepover:", self.relief_stepover)

        self.contour_stepdown = _spinbox(d.contour_stepdown_mm, 0.5, 6.0, step=0.1)
        self.contour_stepdown.setToolTip(
            "Axial depth per through-cut pass (capped by material and machine "
            "max depth-of-cut)."
        )
        form.addRow("Contour stepdown:", self.contour_stepdown)

        self.rough_axial_stock = _spinbox(d.rough_axial_stock_mm, 0.0, 5.0, step=0.1)
        self.rough_axial_stock.setToolTip("Axial stock the rough pass leaves for the fine pass.")
        form.addRow("Rough axial stock:", self.rough_axial_stock)

        self.contour_ramp_angle = _spinbox(
            d.contour_ramp_angle_deg, 0.0, 90.0, step=1.0, decimals=1, suffix="°")
        self.contour_ramp_angle.setToolTip(
            "Lead-in ramp angle for through-cuts: the tool ramps to depth over a "
            "short lead-in then cuts one finish lap. Steeper = shorter lead-in "
            "(faster); 0 ramps a full extra lap (gentlest)."
        )
        form.addRow("Contour ramp angle:", self.contour_ramp_angle)

        self.arc_tolerance = _spinbox(
            d.arc_tolerance_mm, 0.0, 0.2, step=0.005, decimals=3)
        self.arc_tolerance.setToolTip(
            "Arc-fitting tolerance for G2/G3 output. 0 disables arcs (linearized "
            "G1). Ignored on machines without arc support."
        )
        form.addRow("Arc tolerance:", self.arc_tolerance)
        lay.addWidget(grp)

        # Feeds & speeds — populated from the selected material; editable.
        og = QGroupBox("Feeds & Speeds  (from material)")
        of = QFormLayout(og)
        of.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.feed_override = _spinbox(0.0, 0.0, 10000.0, step=50.0, decimals=0, suffix=" mm/min")
        self.plunge_override = _spinbox(0.0, 0.0, 5000.0, step=25.0, decimals=0, suffix=" mm/min")
        self.spindle_override = QSpinBox()
        self.spindle_override.setRange(0, 60000)
        self.spindle_override.setSingleStep(500)
        self.spindle_override.setSuffix(" RPM")
        self.safe_z_clearance = _spinbox(
            CastleCamParams().safe_z_clearance_mm, 1.0, 30.0, step=0.5)
        self.safe_z_clearance.setToolTip("Rapid clearance height above the stock top.")
        of.addRow("Feed override:", self.feed_override)
        of.addRow("Plunge override:", self.plunge_override)
        of.addRow("Spindle override:", self.spindle_override)
        of.addRow("Safe-Z clearance:", self.safe_z_clearance)
        lay.addWidget(og)

        for w in (self.relief_stepover, self.contour_stepdown, self.rough_axial_stock,
                  self.contour_ramp_angle, self.arc_tolerance, self.feed_override,
                  self.plunge_override, self.safe_z_clearance):
            w.valueChanged.connect(self.cam_changed)
        self.spindle_override.valueChanged.connect(self.cam_changed)
        self.machine.currentIndexChanged.connect(self.cam_changed)
        self.cam_tool.currentIndexChanged.connect(self.cam_changed)

    def _build_cam_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("CAM Settings")
        glay = QVBoxLayout(grp)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.material = QComboBox()
        self.material.addItems(material_store.names() or ["acetate"])
        self.material.setToolTip(
            "Selecting a material loads its feeds, speeds, stepover and stepdown "
            "into the CAM tab. After generating, you'll be asked whether to save "
            "any changes back as this material's defaults."
        )
        form.addRow("Material:", self.material)

        self.onion_skin = _spinbox(0.4, 0.0, 2.0, step=0.1, decimals=2)
        self.onion_skin.setToolTip(
            "Axial stock left under through-cuts — the part stays attached "
            "until released by hand (no tabs)."
        )
        form.addRow("Onion skin:", self.onion_skin)

        self.hand_allowance = _spinbox(0.1, 0.0, 1.0, step=0.05, decimals=2)
        self.hand_allowance.setToolTip(
            "places radial leave-behind stock on contour operations"
        )
        form.addRow("Hand finishing allowance:", self.hand_allowance)
        glay.addLayout(form)

        # Fallback profile cut for DXFs without SCULPT zones (legacy path).
        glay.addWidget(_section_label("Profile fallback  (no SCULPT)"))
        fb = QFormLayout()
        fb.setContentsMargins(8, 0, 0, 0)
        fb.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.tool_profile = QComboBox()
        self.tool_profile.addItems(["flat_3mm", "flat_6mm", "flat_3175"])
        self.tool_profile.setCurrentText("flat_3mm")
        fb.addRow("Profile tool:", self.tool_profile)

        self.stepdown_profile = _spinbox(1.5, 0.5, 3.0)
        fb.addRow("Profile stepdown:", self.stepdown_profile)

        self.tab_count = QSpinBox()
        self.tab_count.setRange(0, 8)
        self.tab_count.setValue(4)
        self.tab_count.setSuffix("  tabs")
        self.tab_width = _spinbox(3.0, 1.0, 8.0)
        self.tab_height = _spinbox(1.0, 0.3, 3.0)
        fb.addRow("Hold-down tabs:", self.tab_count)
        fb.addRow("Tab width:", self.tab_width)
        fb.addRow("Tab height:", self.tab_height)
        glay.addLayout(fb)

        for w in (self.onion_skin, self.hand_allowance,
                  self.tool_profile, self.stepdown_profile,
                  self.tab_count, self.tab_width, self.tab_height):
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.cam_changed)
            else:
                w.currentIndexChanged.connect(self.cam_changed)

        # Selecting a material repopulates feeds/speeds/stepover/stepdown.
        self.material.currentIndexChanged.connect(self._on_material_changed)
        lay.addWidget(grp)
        # Seed the feeds/strategy fields from the initial material.
        self.apply_material_values(material_store.cam_values(self.material.currentText()))

    # ------------------------------------------------------------------ schema

    def _castle_zone_thicknesses(self) -> ZoneThicknesses:
        return ZoneThicknesses(
            endpiece_mm=self.zone_endpiece.value(),
            bridge_mm=self.zone_bridge.value(),
            nosepad_mm=self.zone_nosepad.value(),
            eyewire_superior_mm=self.zone_eyewire_superior.value(),
            eyewire_inferior_mm=self.zone_eyewire_inferior.value(),
        )

    def castle_params(self) -> CastleParams:
        """Snapshot the panel into the CastleParams schema (API vocabulary)."""
        defaults = FootingSchedule()
        footing = FootingSchedule(**{
            canonical: FootingFillet(
                exterior_mm=ext_sb.value(),
                interior_mm=int_sb.value(),
                first=defaults.for_edge(canonical).first,
            )
            for canonical, (ext_sb, int_sb) in self.footing_spins.items()
        })
        return CastleParams(
            zones=self._castle_zone_thicknesses(),
            footing=footing,
            hinge_pocket_depth_mm=self.hinge_pocket_depth.value(),
            stock=StockDefinition(
                blank_length_mm=self.blank_length.value(),
                blank_width_mm=self.blank_width.value(),
                blank_thickness_mm=self.blank_thickness.value(),
                pad_block_length_mm=self.pad_length.value(),
                pad_block_width_mm=self.pad_width.value(),
                pad_block_thickness_mm=self.pad_thickness.value(),
            ),
            onion_skin_mm=self.onion_skin.value(),
            hand_finishing_allowance_mm=self.hand_allowance.value(),
        )

    def set_castle_params(self, c: CastleParams) -> None:
        """Restore the Castle / Stock tabs from a CastleParams (opening a .gcam)."""
        z = c.zones
        pairs = [
            (self.zone_endpiece, z.endpiece_mm), (self.zone_bridge, z.bridge_mm),
            (self.zone_nosepad, z.nosepad_mm),
            (self.zone_eyewire_superior, z.eyewire_superior_mm),
            (self.zone_eyewire_inferior, z.eyewire_inferior_mm),
            (self.hinge_pocket_depth, c.hinge_pocket_depth_mm),
            (self.onion_skin, c.onion_skin_mm),
            (self.hand_allowance, c.hand_finishing_allowance_mm),
            (self.blank_length, c.stock.blank_length_mm),
            (self.blank_width, c.stock.blank_width_mm),
            (self.blank_thickness, c.stock.blank_thickness_mm),
            (self.pad_length, c.stock.pad_block_length_mm),
            (self.pad_width, c.stock.pad_block_width_mm),
            (self.pad_thickness, c.stock.pad_block_thickness_mm),
        ]
        for canonical, (ext_sb, int_sb) in self.footing_spins.items():
            f = c.footing.for_edge(canonical)
            pairs += [(ext_sb, f.exterior_mm), (int_sb, f.interior_mm)]
        for sb, val in pairs:
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)
        self.castle_changed.emit()
        self.stock_changed.emit()

    def cam_params(self) -> CastleCamParams:
        """Snapshot the CAM tab into the persisted CastleCamParams schema."""
        idx = self.machine.currentIndex()
        machine_name = self._machine_names[idx] if 0 <= idx < len(self._machine_names) else "guild_cnc"

        def _opt(v: float) -> Optional[float]:
            return v if v > 0 else None

        op_tools = {}
        for op, cb in getattr(self, "op_tool_combos", {}).items():
            txt = cb.currentText()
            if txt and txt != _SAME_AS_GLOBAL:
                op_tools[op] = txt

        return CastleCamParams(
            tool_name=self.cam_tool.currentText(),
            machine_name=machine_name,
            op_tools=op_tools,
            program_zero=self._program_zero(),
            relief_stepover_mm=self.relief_stepover.value(),
            contour_stepdown_mm=self.contour_stepdown.value(),
            rough_axial_stock_mm=self.rough_axial_stock.value(),
            contour_ramp_angle_deg=self.contour_ramp_angle.value(),
            arc_tolerance_mm=self.arc_tolerance.value(),
            feed_rate_mmpm=_opt(self.feed_override.value()),
            plunge_rate_mmpm=_opt(self.plunge_override.value()),
            spindle_rpm=int(self.spindle_override.value()) or None,
            safe_z_clearance_mm=self.safe_z_clearance.value(),
        )

    def set_cam_params(self, cp: CastleCamParams) -> None:
        """Restore the CAM tab from a persisted CastleCamParams (prefs/project)."""
        if cp.tool_name:
            self.cam_tool.setCurrentText(cp.tool_name)
        for op, cb in getattr(self, "op_tool_combos", {}).items():
            name = cp.op_tools.get(op)
            cb.blockSignals(True)
            cb.setCurrentText(name if name and cb.findText(name) >= 0 else _SAME_AS_GLOBAL)
            cb.blockSignals(False)
        if cp.machine_name in self._machine_names:
            self.machine.setCurrentIndex(self._machine_names.index(cp.machine_name))
        self._set_program_zero(cp.program_zero)
        self.relief_stepover.setValue(cp.relief_stepover_mm)
        self.contour_stepdown.setValue(cp.contour_stepdown_mm)
        self.rough_axial_stock.setValue(cp.rough_axial_stock_mm)
        self.contour_ramp_angle.setValue(cp.contour_ramp_angle_deg)
        self.arc_tolerance.setValue(cp.arc_tolerance_mm)
        self.feed_override.setValue(cp.feed_rate_mmpm or 0.0)
        self.plunge_override.setValue(cp.plunge_rate_mmpm or 0.0)
        self.spindle_override.setValue(cp.spindle_rpm or 0)
        self.safe_z_clearance.setValue(cp.safe_z_clearance_mm)

    # ------------------------------------------------------------------ material

    def material_name(self) -> str:
        return self.material.currentText()

    def set_material(self, name: str) -> None:
        """Select a material without repopulating the feeds (used on restore,
        where the persisted CAM values are applied separately)."""
        i = self.material.findText(name)
        if i >= 0:
            self.material.blockSignals(True)
            self.material.setCurrentIndex(i)
            self.material.blockSignals(False)

    def _on_material_changed(self) -> None:
        self.apply_material_values(material_store.cam_values(self.material.currentText()))

    def apply_material_values(self, vals: dict) -> None:
        """Load a material's feeds/speeds/stepover/stepdown into the CAM tab."""
        spins = {
            "feed_rate_mmpm": self.feed_override,
            "plunge_rate_mmpm": self.plunge_override,
            "relief_stepover_mm": self.relief_stepover,
            "contour_stepdown_mm": self.contour_stepdown,
            "rough_axial_stock_mm": self.rough_axial_stock,
        }
        for key, sb in spins.items():
            if key in vals:
                sb.blockSignals(True); sb.setValue(float(vals[key])); sb.blockSignals(False)
        if "spindle_rpm" in vals:
            self.spindle_override.blockSignals(True)
            self.spindle_override.setValue(int(vals["spindle_rpm"]))
            self.spindle_override.blockSignals(False)
        self.cam_changed.emit()

    def current_material_values(self) -> dict:
        """The feeds/speeds/stepover/stepdown currently in the CAM tab — for
        comparing against the material's stored defaults (write-back prompt)."""
        return {
            "spindle_rpm": int(self.spindle_override.value()),
            "feed_rate_mmpm": float(self.feed_override.value()),
            "plunge_rate_mmpm": float(self.plunge_override.value()),
            "relief_stepover_mm": float(self.relief_stepover.value()),
            "contour_stepdown_mm": float(self.contour_stepdown.value()),
            "rough_axial_stock_mm": float(self.rough_axial_stock.value()),
        }

    # ------------------------------------------------------------------ helpers

    @property
    def layer_checks(self) -> dict[str, QCheckBox]:
        return self._layer_checks
