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
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout,
    QGroupBox, QFormLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QListWidget, QListWidgetItem, QFrame, QTabWidget,
)
from PySide6.QtCore import Qt, Signal

from guildcam.core.layers import LAYER_STYLES
from guildcam.gui.style import theme
from guildcam.core.project.schema import (
    CastleParams, FootingFillet, FootingSchedule, StockDefinition,
    ZoneThicknesses,
)


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
        self._build_cam_group(lay)

    def _build_cam_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("CAM Settings")
        glay = QVBoxLayout(grp)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.tool_label = _ro_field("flat_3175 · 3.175 mm")
        self.tool_label.setToolTip(
            "The five-op posterior program is single-tool (1/8\" single-flute flat)."
        )
        form.addRow("Tool:", self.tool_label)

        self.material = QComboBox()
        self.material.addItems(["acetate", "zyl (auto)", "horn", "metal"])
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

        for w in (self.material, self.onion_skin, self.hand_allowance,
                  self.tool_profile, self.stepdown_profile,
                  self.tab_count, self.tab_width, self.tab_height):
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.cam_changed)
            else:
                w.currentIndexChanged.connect(self.cam_changed)

        lay.addWidget(grp)

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

    # ------------------------------------------------------------------ helpers

    @property
    def layer_checks(self) -> dict[str, QCheckBox]:
        return self._layer_checks
