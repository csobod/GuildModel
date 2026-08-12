"""Right-dock parameter panel — a tabbed container (BUILDPLAN M4.6 Part A).

``ParamsPanel`` is a ``QTabWidget`` whose tabs are shown per active component
kind (``set_component_kind``), each its own scroll area (no fixed width, no
horizontal clipping):

  * **Info**    — file identity, raw layer summary, layer-visibility checks, and
                  (frame only) the Boxing read-outs (ISO 8624);
  * **Castle**  — the parametric castle (Towers / Walls / Footing) + the Zones
                  inspector (frame only);
  * **Stock**   — blank + pad block (frame only);
  * **Temple** / **Base Curve** — that component's own blank + tools;
  * **Cut**     — the everyday cut choices: material, feeds & speeds, the
                  chip-load check, and the hand-finishing allowances;
  * **Machine** — set-once machine setup: controller, Program Zero, and (frame
                  only) per-op tools, cut strategy and the no-SCULPT fallback.

Info / Cut / Machine are universal; the rest are kind-specific. The everyday
"Cut" and the setup "Machine" tabs are the old catch-all "CAM" tab, split so a
bench optician's routine choices aren't buried under machine setup (UX pass).

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
    QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from guildmodel.core.layers import LAYER_STYLES
from guildmodel.gui.style import theme
from guildmodel.gui import material_store
from guildmodel.gui.widgets.param_slider import ParamSlider
from guildmodel.core.post.machine import available_machines
from guildmodel.core.project.schema import (
    BaseCurveBlockParams, BridgeReliefParams, CastleCamParams, CastleParams,
    ComponentCamOverrides, ComponentKind, DEFAULT_OP_TOOLS, EdgeFeature,
    EyewireBezelParams, FootingFillet, FootingSchedule, HoldingParams, LensGrooveParams,
    PadSplayParams, POSTERIOR_OPS, ProgramZero, StockDefinition, TempleParams,
    ZoneThicknesses,
)

# Sentinel shown in a per-op tool combo meaning "use the global Tool above".
_SAME_AS_GLOBAL = "(same as Tool)"

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _tool_names() -> list[str]:
    """Every tool in the effective library — shipped + the user's own (M7.8)."""
    try:
        from guildmodel.gui import tool_store
        return tool_store.names() or ["flat_3175"]
    except Exception:
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


#: Anything the panel reads a millimetre out of. `ParamSlider` is a drop-in for
#: the spin box everywhere the panel touches one, so the two are interchangeable
#: at every call site and only the constructor picks between them.
Numeric = QDoubleSpinBox | ParamSlider


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


def _slider(
    value: float,
    min_: float,
    max_: float,
    step: float = 0.1,
    decimals: int = 2,
    suffix: str = " mm",
) -> ParamSlider:
    """A `_spinbox` you can also drag — same arguments, same API.

    Used for the numbers that describe the *shape*: the Model tab and the Stock
    tab. A frame is found by feel and then recorded, and you cannot feel a
    footing radius by typing 6.0 and waiting for a rebuild.

    Deliberately **not** used on the Cut and Machine tabs. A feed rate or a safe
    Z is a decision, not a shape — there is nothing to scrub for, and a slider
    there would only make an exact number harder to hit. The footing pairs keep
    their spin boxes too: two of them share one row, which leaves no width for a
    handle worth dragging, and neither radius has a derived limit to show.
    """
    return ParamSlider(value, min_, max_, step=step, decimals=decimals,
                       suffix=suffix)


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
    """Tabbed parameter panel (Info / Model / Stock / Temple / Base Curve / Cut /
    Machine), shown per component kind. The Model tab carries the castle
    parameters (towers / walls / footing)."""

    # --- signals emitted when values change ---
    castle_changed = Signal()      # any zone height / footing / pocket depth
    stock_changed = Signal()       # blank / pad block dimensions
    cam_changed = Signal()         # tool / material / allowances / fallback
    zone_hovered = Signal(str)     # zone name under the cursor, "" on leave
    # A Model-tab handle is being dragged: the value is not settled, but the
    # shape it describes is worth showing. Separate from `castle_changed`
    # because the two want different work — see `_connect_live_handles`.
    castle_sliding = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)

        self._partition = None    # CastlePartition from the last import
        # `_refresh_limits` reads widgets from every tab, and a few of the
        # per-group setup calls (the groove toggle) reach it while those tabs are
        # still being built. Set true once, at the end of __init__.
        self._limits_ready = False
        # Per-zone height overrides keyed by Zone.name, for zones the per-kind
        # defaults don't suit. Cleared when the drawing no longer has the zone.
        self._zone_overrides: dict[str, float] = {}
        self._temple_fixture_zone = "temple_right"
        self._block_fixture_zone = "bc_template_right"
        self._block_material = "acetal"

        # Each tab is an independently scrolling column; no fixed width so the
        # Footing label + spinbox-pair rows never clip at the right edge. Tabs are
        # shown per active component kind (set_component_kind): Info / Cut / Machine
        # apply to every component; Model (castle) + Stock are frame-only, Temple
        # and Base Curve their own. The old catch-all "CAM" tab split into the
        # everyday "Cut" and the setup-once "Machine" (BUILDPLAN UX pass).
        self._tab_info = self.addTab(self._scroll_tab(self._build_info_tab), "Info")
        self._tab_castle = self.addTab(self._scroll_tab(self._build_castle_tab), "Model")
        self._tab_stock = self.addTab(self._scroll_tab(self._build_stock_tab), "Stock")
        self._tab_temple = self.addTab(self._scroll_tab(self._build_temple_tab), "Temple")
        self._tab_block = self.addTab(self._scroll_tab(self._build_block_tab), "Base Curve")
        self._tab_cut = self.addTab(self._scroll_tab(self._build_cut_tab), "Cut")
        self._tab_machine = self.addTab(self._scroll_tab(self._build_machine_tab), "Machine")

        # The material seed writes across the Cut tab (feeds) and the Machine tab
        # (stepovers), and the chip read-out reads the Machine tab's tool — so both
        # must run only after every tab's widgets exist.
        self.apply_material_values(material_store.cam_values(self.material.currentText()))
        self.cam_changed.connect(self._update_chip_readout)   # keep it live (M7.10)
        self._update_chip_readout()

        # What each Model / Stock number is allowed to be depends on the others,
        # so it is re-derived after every change rather than only at build time.
        # Connected here, before the window connects its rebuild, so the ranges a
        # rebuild is about to be measured against are already current.
        self._groove_ceiling: float | None = None
        self._groove_ceiling_for = None
        self._limits_ready = True
        self.castle_changed.connect(self._refresh_limits)
        self.stock_changed.connect(self._refresh_limits)
        self._refresh_limits()

        self._connect_live_handles()
        self.set_component_kind(ComponentKind.FRAME_FRONT)

    # ------------------------------------------------------------ kind-aware tabs

    # Layers that only exist on a frame front (a temple / base curve has no lens).
    _LENS_ONLY_LAYERS = ("LENS", "BRIDGE", "SCULPT")

    def set_component_kind(self, kind) -> None:
        """Show only what applies to the active component's kind (M7.3 + UX pass).

        Info / Cut / Machine are universal; Model + Stock are frame-only, Temple
        and Base Curve their own. Inside the universal tabs the frame-lens-only
        content also hides for a temple / base-curve component: the ISO-8624 boxing
        and lens layers on Info, and the per-op tools / relief strategy / profile
        fallback on Machine (those describe the frame's posterior toolpaths).

        Depth per pass (Cut) and the through-cut lead-in (Machine) are deliberately
        NOT in that hidden set: they drive every kind's through-cuts. Hiding them
        with the frame's relief strategy is what left a temple with no way to say how
        deep each pass should bite."""
        kind = ComponentKind(kind)
        self._component_kind = kind
        is_frame = kind == ComponentKind.FRAME_FRONT
        is_temple = kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)
        is_block = kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT)
        self.setTabVisible(self._tab_castle, is_frame)
        self.setTabVisible(self._tab_stock, is_frame)
        self.setTabVisible(self._tab_temple, is_temple)
        self.setTabVisible(self._tab_block, is_block)
        # Frame-lens-only content inside the universal Info / Machine tabs.
        self._boxing_group.setVisible(is_frame)
        for layer in self._LENS_ONLY_LAYERS:
            cb = self._layer_checks.get(layer)
            if cb is not None:
                cb.setVisible(is_frame)
        for grp in (self._op_tools_group, self._strategy_group, self._fallback_group):
            grp.setVisible(is_frame)
        self._update_passes_readout()        # the read-out is per-kind
        self._refresh_operations_hint()      # so is the operation list (M16)
        if not self.isTabVisible(self.currentIndex()):
            self.setCurrentIndex(self._tab_info)

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

    def _build_info_tab(self, lay: QVBoxLayout) -> None:
        self._build_file_group(lay)
        self._build_boxing_group(lay)

    def _build_file_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("File")
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
            # By NAME, so a Preferences ▸ Layers override tints the checkbox too.
            color = theme.layer_color_for(layer, dark)
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
        # Lens-only measurements — hidden on temple / base-curve components, which
        # have no lens outline (set_component_kind).
        self._boxing_group = grp
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
        self._build_style_preset_group(lay)
        self._build_castle_group(lay)
        self._build_posterior_finishing_group(lay)
        self._build_edge_features_group(lay)      # partial-span chamfers/fillets (M17)
        self._build_zones_group(lay)

    # ------------------------------------------------- edge features (M17)

    def _build_edge_features_group(self, lay: QVBoxLayout) -> None:
        """Partial-span chamfers and fillets on either face (BUILDPLAN M17).

        A list plus one editor, rather than a fixed set of named features, because
        this is the open-ended one: a frame may want an anterior brow chamfer, a
        posterior fillet along the lower rim, and a taper at one endpiece, all at
        once. The span is chosen by castle zone (see `EdgeFeature`), so the list
        reads in the maker's own vocabulary and mirrors by name.
        """
        grp = QGroupBox("Edge Features  (chamfers & fillets)")
        v = QVBoxLayout(grp)

        hint = QLabel(
            "Chamfer or round part of an edge — e.g. the anterior brow over each "
            "eyewire, stopping short of the bridge. Mirrored features cut both sides.")
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        v.addWidget(hint)

        self.edge_list = QListWidget()
        self.edge_list.setFixedHeight(96)
        self.edge_list.currentRowChanged.connect(self._on_edge_selected)
        v.addWidget(self.edge_list)

        row = QHBoxLayout()
        for text, slot in (("+ Add", self._on_edge_add),
                           ("Duplicate", self._on_edge_duplicate),
                           ("Remove", self._on_edge_remove)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        v.addLayout(row)

        self._edge_editor = QWidget()
        form = QFormLayout(self._edge_editor)
        form.setContentsMargins(8, 4, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        d = EdgeFeature()

        self.ef_enabled = QCheckBox("Enabled")
        self.ef_enabled.setChecked(True)
        form.addRow("", self.ef_enabled)
        self.ef_label = QLineEdit()
        self.ef_label.setPlaceholderText("Anterior brow chamfer")
        form.addRow("Name:", self.ef_label)

        self.ef_face = QComboBox()
        self.ef_face.addItems(["Anterior (front)", "Posterior (back)"])
        self.ef_face.setToolTip(
            "Anterior features are modelled and shown in 3D now; machining them "
            "needs the flip setup.")
        form.addRow("Face:", self.ef_face)

        self.ef_edge = QComboBox()
        self.ef_edge.addItems(["Outline", "Lens OD", "Lens OS"])
        form.addRow("Edge:", self.ef_edge)

        self.ef_zones = QListWidget()
        self.ef_zones.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.ef_zones.setFixedHeight(92)
        self.ef_zones.setToolTip(
            "Which castle zones the run covers. Select none for the whole edge.\n"
            "Leaving 'bridge' out is what keeps a brow chamfer from crossing the nose.")
        form.addRow("Spans zones:", self.ef_zones)

        self.ef_profile = QComboBox()
        self.ef_profile.addItems(["Chamfer", "Fillet (round-over)"])
        form.addRow("Profile:", self.ef_profile)

        self.ef_width = _slider(d.width_mm, 0.1, 12.0, step=0.1, decimals=2)
        self.ef_width.setToolTip("How far in from the edge the chamfer runs.")
        form.addRow("Width:", self.ef_width)
        self.ef_width_end = _slider(0.0, 0.0, 12.0, step=0.1, decimals=2)
        self.ef_width_end.setSpecialValueText("(constant)")
        self.ef_width_end.setToolTip(
            "Width at the far end of the run — set it to taper the chamfer along "
            "its length. '(constant)' keeps the width above all the way.")
        form.addRow("Width at end:", self.ef_width_end)
        self.ef_angle = _slider(d.angle_deg, 5.0, 85.0, step=1.0, decimals=1, suffix="°")
        form.addRow("Angle:", self.ef_angle)
        self.ef_radius = _slider(d.radius_mm, 0.1, 12.0, step=0.1, decimals=2)
        form.addRow("Fillet radius:", self.ef_radius)

        self.ef_trim_start = _slider(0.0, -50.0, 50.0, step=0.5, decimals=1)
        self.ef_trim_start.setToolTip("Pull the start of the run in (+) or out (−) along the edge.")
        form.addRow("Trim start:", self.ef_trim_start)
        self.ef_trim_end = _slider(0.0, -50.0, 50.0, step=0.5, decimals=1)
        form.addRow("Trim end:", self.ef_trim_end)
        self.ef_blend = _slider(d.blend_mm, 0.0, 30.0, step=0.5, decimals=1)
        self.ef_blend.setToolTip(
            "Taper the cut to nothing over this distance at each end, so it "
            "feathers out instead of stopping at full depth.")
        form.addRow("Blend:", self.ef_blend)
        self.ef_min_thickness = _slider(d.min_thickness_mm, 0.0, 8.0, step=0.1, decimals=2)
        self.ef_min_thickness.setToolTip(
            "The frame is never cut thinner than this where the feature runs.")
        form.addRow("Min thickness:", self.ef_min_thickness)

        self.ef_mirror = QCheckBox("Mirror to the other side")
        self.ef_mirror.setChecked(True)
        self.ef_mirror.setToolTip(
            "Cut the matching feature on the opposite side (OD ↔ OS zone names).")
        form.addRow("", self.ef_mirror)
        v.addWidget(self._edge_editor)

        self._edge_features: list[EdgeFeature] = []
        self._edge_loading = False
        for w in (self.ef_width, self.ef_width_end, self.ef_angle, self.ef_radius,
                  self.ef_trim_start, self.ef_trim_end, self.ef_blend,
                  self.ef_min_thickness):
            w.valueChanged.connect(self._on_edge_edited)
        for cb in (self.ef_face, self.ef_edge, self.ef_profile):
            cb.currentIndexChanged.connect(self._on_edge_edited)
        for chk in (self.ef_enabled, self.ef_mirror):
            chk.toggled.connect(self._on_edge_edited)
        self.ef_label.textEdited.connect(self._on_edge_edited)
        self.ef_zones.itemSelectionChanged.connect(self._on_edge_edited)
        self._refresh_edge_list()
        lay.addWidget(grp)

    _EF_FACES = ("anterior", "posterior")
    _EF_EDGES = ("outline", "lens_od", "lens_os")
    _EF_PROFILES = ("chamfer", "fillet")

    def _refresh_edge_zone_choices(self) -> None:
        """Offer the zones the LOADED drawing actually has — a stale name from a
        different frame would silently match nothing and the run would vanish."""
        chosen = {i.data(Qt.ItemDataRole.UserRole) for i in self.ef_zones.selectedItems()}
        self.ef_zones.blockSignals(True)
        self.ef_zones.clear()
        names = ([z.name for z in self._partition.zones]
                 if getattr(self, "_partition", None) is not None else [])
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.ef_zones.addItem(item)
            item.setSelected(name in chosen)
        self.ef_zones.blockSignals(False)

    def _edge_summary(self, f: EdgeFeature) -> str:
        where = "front" if f.face == "anterior" else "back"
        what = (f"fillet R{f.radius_mm:g}" if f.profile == "fillet"
                else f"chamfer {f.width_mm:g}mm@{f.angle_deg:g}°")
        span = ", ".join(f.zones) if f.zones else "whole edge"
        name = f.label or f"{f.edge} {what}"
        flag = "" if f.enabled else "  (off)"
        return f"{name} — {where} · {span}{'  ⇔' if f.mirror else ''}{flag}"

    def _refresh_edge_list(self) -> None:
        row = self.edge_list.currentRow()
        self.edge_list.blockSignals(True)
        self.edge_list.clear()
        for f in self._edge_features:
            self.edge_list.addItem(self._edge_summary(f))
        self.edge_list.blockSignals(False)
        if self._edge_features:
            self.edge_list.setCurrentRow(min(max(row, 0), len(self._edge_features) - 1))
        self._edge_editor.setEnabled(bool(self._edge_features))

    def _on_edge_selected(self, row: int) -> None:
        if not (0 <= row < len(self._edge_features)):
            return
        f = self._edge_features[row]
        self._edge_loading = True
        self._refresh_edge_zone_choices()
        self.ef_enabled.setChecked(f.enabled)
        self.ef_label.setText(f.label)
        self.ef_face.setCurrentIndex(self._EF_FACES.index(f.face))
        self.ef_edge.setCurrentIndex(self._EF_EDGES.index(f.edge))
        self.ef_profile.setCurrentIndex(self._EF_PROFILES.index(f.profile))
        for i in range(self.ef_zones.count()):
            item = self.ef_zones.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in f.zones)
        self.ef_width.setValue(f.width_mm)
        self.ef_width_end.setValue(f.width_end_mm or 0.0)
        self.ef_angle.setValue(f.angle_deg)
        self.ef_radius.setValue(f.radius_mm)
        self.ef_trim_start.setValue(f.trim_start_mm)
        self.ef_trim_end.setValue(f.trim_end_mm)
        self.ef_blend.setValue(f.blend_mm)
        self.ef_min_thickness.setValue(f.min_thickness_mm)
        self.ef_mirror.setChecked(f.mirror)
        self._edge_loading = False
        self._update_edge_editor_enabled()
        self._refresh_limits()      # a different feature runs along a different wall

    def _update_edge_editor_enabled(self) -> None:
        """Only the profile's own numbers stay live — a fillet has no angle."""
        fillet = self.ef_profile.currentIndex() == 1
        for w in (self.ef_width, self.ef_width_end, self.ef_angle):
            w.setEnabled(not fillet)
        self.ef_radius.setEnabled(fillet)

    def _on_edge_edited(self, *_a) -> None:
        if self._edge_loading:
            return
        row = self.edge_list.currentRow()
        if not (0 <= row < len(self._edge_features)):
            return
        end = self.ef_width_end.value()
        self._edge_features[row] = self._edge_features[row].model_copy(update=dict(
            enabled=self.ef_enabled.isChecked(),
            label=self.ef_label.text(),
            face=self._EF_FACES[self.ef_face.currentIndex()],
            edge=self._EF_EDGES[self.ef_edge.currentIndex()],
            profile=self._EF_PROFILES[self.ef_profile.currentIndex()],
            zones=[i.data(Qt.ItemDataRole.UserRole) for i in self.ef_zones.selectedItems()],
            width_mm=self.ef_width.value(),
            width_end_mm=end if end > 0 else None,
            angle_deg=self.ef_angle.value(),
            radius_mm=self.ef_radius.value(),
            trim_start_mm=self.ef_trim_start.value(),
            trim_end_mm=self.ef_trim_end.value(),
            blend_mm=self.ef_blend.value(),
            min_thickness_mm=self.ef_min_thickness.value(),
            mirror=self.ef_mirror.isChecked(),
        ))
        self._update_edge_editor_enabled()
        self._refresh_edge_list()
        self.castle_changed.emit()

    def _unique_edge_id(self, base: str = "edge") -> str:
        taken = {f.id for f in self._edge_features}
        n = 1
        while f"{base}_{n}" in taken:
            n += 1
        return f"{base}_{n}"

    def _on_edge_add(self) -> None:
        """A new feature starts as the brow chamfer — the case this exists for —
        pre-aimed at whichever superior-eyewire zone the drawing has."""
        zones = [z.name for z in getattr(self, "_partition", None).zones] \
            if getattr(self, "_partition", None) is not None else []
        brow = [z for z in zones if z.startswith("eyewire_superior")][:1]
        self._edge_features.append(EdgeFeature(
            id=self._unique_edge_id(), label="Brow chamfer",
            face="anterior", edge="outline", zones=brow,
            profile="chamfer", width_mm=2.0, angle_deg=45.0, blend_mm=6.0,
            mirror=True,
        ))
        self._refresh_edge_list()
        self.edge_list.setCurrentRow(len(self._edge_features) - 1)
        self.castle_changed.emit()

    def _on_edge_duplicate(self) -> None:
        row = self.edge_list.currentRow()
        if not (0 <= row < len(self._edge_features)):
            return
        src = self._edge_features[row]
        self._edge_features.insert(row + 1, src.model_copy(update={
            "id": self._unique_edge_id(),
            "label": f"{src.label} copy" if src.label else "",
        }))
        self._refresh_edge_list()
        self.edge_list.setCurrentRow(row + 1)
        self.castle_changed.emit()

    def _on_edge_remove(self) -> None:
        row = self.edge_list.currentRow()
        if not (0 <= row < len(self._edge_features)):
            return
        self._edge_features.pop(row)
        self._refresh_edge_list()
        if self._edge_features:
            self._on_edge_selected(self.edge_list.currentRow())
        self.castle_changed.emit()

    def edge_features(self) -> list[EdgeFeature]:
        return [f.model_copy() for f in self._edge_features]

    def set_edge_features(self, features: list[EdgeFeature]) -> None:
        self._edge_features = [f.model_copy() for f in (features or [])]
        self._refresh_edge_list()
        if self._edge_features:
            self._on_edge_selected(self.edge_list.currentRow())

    # ---------------------------------------------- frame-style presets (M7.16)

    def _build_style_preset_group(self, lay: QVBoxLayout) -> None:
        """Save / recall a whole CastleParams as a named house style (BUILDPLAN M7.16).
        Selecting a preset seeds the dock (one live rebuild); Save as… / Update / Delete
        manage the maker's library (shipped 'Guild demo' is the reference)."""
        grp = QGroupBox("Frame style")
        v = QVBoxLayout(grp)

        self.style_combo = QComboBox()
        self.style_combo.setToolTip("Recall a saved frame style.")
        self.style_combo.activated.connect(self._on_style_selected)
        v.addWidget(self.style_combo)

        row = QHBoxLayout()
        self._style_save_btn = QPushButton("Save as…")
        self._style_update_btn = QPushButton("Update")
        self._style_delete_btn = QPushButton("Delete")
        self._style_save_btn.setToolTip("Save the current parameters as a new frame style")
        self._style_update_btn.setToolTip("Overwrite the selected style with the current parameters")
        self._style_delete_btn.setToolTip("Delete the selected frame style")
        self._style_save_btn.clicked.connect(self._on_style_save_as)
        self._style_update_btn.clicked.connect(self._on_style_update)
        self._style_delete_btn.clicked.connect(self._on_style_delete)
        row.addWidget(self._style_save_btn)
        row.addWidget(self._style_update_btn)
        row.addWidget(self._style_delete_btn)
        v.addLayout(row)

        lay.addWidget(grp)
        self._refresh_style_combo()

    def _refresh_style_combo(self, select: str | None = None) -> None:
        from guildmodel.gui import style_store
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItem("— Frame style —")        # index 0: no selection
        for name in style_store.names():
            self.style_combo.addItem(name)
        if select is not None:
            i = self.style_combo.findText(select)
            self.style_combo.setCurrentIndex(max(0, i))
        self.style_combo.blockSignals(False)
        self._update_style_buttons()

    def _selected_style(self) -> str | None:
        return self.style_combo.currentText() if self.style_combo.currentIndex() > 0 else None

    def _update_style_buttons(self) -> None:
        name = self._selected_style()
        self._style_update_btn.setEnabled(name is not None)
        # a shipped preset can be re-hidden but not "updated" in place (fork instead)
        self._style_delete_btn.setEnabled(name is not None)

    def _on_style_selected(self, index: int) -> None:
        from guildmodel.gui import style_store
        self._update_style_buttons()
        if index <= 0:
            return
        preset = style_store.style(self.style_combo.itemText(index))
        if preset is not None:
            self.set_castle_params(preset)            # one live rebuild, like material apply

    def _on_style_save_as(self) -> None:
        from guildmodel.gui import style_store
        name, ok = QInputDialog.getText(self, "Save frame style", "Style name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in style_store.names() and QMessageBox.question(
                self, "Replace style", f"A style named “{name}” exists. Replace it?"
                ) != QMessageBox.StandardButton.Yes:
            return
        style_store.save_style(name, self.castle_params())
        self._refresh_style_combo(select=name)

    def _on_style_update(self) -> None:
        from guildmodel.gui import style_store
        name = self._selected_style()
        if name is None:
            return
        if style_store.is_shipped(name) and QMessageBox.question(
                self, "Update shipped style",
                f"“{name}” is a built-in reference. Save your edits over it "
                "(you can reset it later)?") != QMessageBox.StandardButton.Yes:
            return
        style_store.save_style(name, self.castle_params())
        self._refresh_style_combo(select=name)

    def _on_style_delete(self) -> None:
        from guildmodel.gui import style_store
        name = self._selected_style()
        if name is None:
            return
        if QMessageBox.question(
                self, "Delete style", f"Delete the frame style “{name}”?"
                ) != QMessageBox.StandardButton.Yes:
            return
        style_store.delete_style(name)
        self._refresh_style_combo()

    def _build_castle_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Model Properties")
        glay = QVBoxLayout(grp)

        # --- Towers: the high load-bearing masses ---
        glay.addWidget(_section_label("Towers"))
        towers = QFormLayout()
        towers.setContentsMargins(8, 0, 0, 0)
        towers.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.zone_endpiece = _slider(5.5, 0.5, 12.0, decimals=1)
        self.zone_bridge = _slider(5.3, 0.5, 12.0, decimals=1)
        self.zone_nosepad = _slider(10.0, 0.5, 15.0, decimals=1)
        self.hinge_pocket_depth = _slider(1.0, 0.0, 3.0, decimals=1)
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
        self.zone_eyewire_superior = _slider(4.8, 0.5, 12.0, decimals=1)
        self.zone_eyewire_inferior = _slider(4.2, 0.5, 12.0, decimals=1)
        walls.addRow("Superior eyewires:", self.zone_eyewire_superior)
        walls.addRow("Inferior eyewires:", self.zone_eyewire_inferior)
        self.zone_eyewire_superior.setToolTip(
            "Also drives a unified (OU) superior eyewire spanning both eyes — an "
            "aviator's brow bar. Double-click it in the Zones list to override."
        )
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

    # ------------------------------------------ posterior finishing (M13)

    def _build_posterior_finishing_group(self, lay: QVBoxLayout) -> None:
        """Pad splay / eyewire bezel / bridge relief — the posterior features a
        maker otherwise cuts by hand (BUILDPLAN M13). Each is off by default."""
        d = PadSplayParams()
        grp = QGroupBox("Posterior Finishing")
        glay = QVBoxLayout(grp)

        # --- Pad splay: chamfer under the bridge (M13.1) ---
        glay.addWidget(_section_label("Pad Splay"))
        self.splay_enable = QCheckBox("Cut pad splay chamfer")
        self.splay_enable.setChecked(d.enabled)
        self.splay_enable.setToolTip(
            "Chamfer the bridge underside so the frame sits on the nose.")
        glay.addWidget(self.splay_enable)
        splay = QFormLayout()
        splay.setContentsMargins(8, 0, 0, 0)
        splay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.splay_run = _slider(d.run_mm, 2.0, 60.0, step=1.0, decimals=1)
        self.splay_run.setToolTip(
            "How far the chamfer runs along the outline each side of bottom-center.")
        self.splay_dev_center = _slider(d.crest_deviation_center_mm, 0.0, 20.0,
                                        step=0.5, decimals=1)
        self.splay_dev_center.setToolTip(
            "Crest inset from the outline at the bottom-center point.")
        self.splay_dev_end = _slider(d.crest_deviation_end_mm, 0.0, 20.0,
                                     step=0.5, decimals=1)
        self.splay_dev_end.setToolTip("Crest inset at each end of the run.")
        self.splay_angle_center = _slider(d.angle_center_deg, 5.0, 60.0,
                                          step=1.0, decimals=1, suffix="°")
        self.splay_angle_middle = _slider(d.angle_middle_deg, 5.0, 60.0,
                                          step=1.0, decimals=1, suffix="°")
        self.splay_angle_end = _slider(d.angle_end_deg, 5.0, 60.0,
                                       step=1.0, decimals=1, suffix="°")
        self.splay_toric = QCheckBox("Toric (blend three angles)")
        self.splay_toric.setChecked(d.toric)
        self.splay_toric.setToolTip(
            "Blend the splay from a center angle through a middle to an end angle.")
        self.splay_clamp = _slider(d.anterior_clamp_mm, 0.2, 5.0, step=0.1, decimals=1)
        self.splay_clamp.setToolTip(
            "Cut floor above the anterior face — the edge never gets thinner than this.")
        self.splay_feather = _slider(d.feather_mm, 0.0, 10.0, step=0.5, decimals=1)
        self.splay_feather.setToolTip(
            "Run the cut out to nothing over this distance at EVERY end of the "
            "run — including the two inner ends facing the keyhole when the "
            "splay is non-contiguous.\n"
            "The chamfer keeps its angle and lifts out of the surface, so the "
            "cut narrows away instead of flattening into a shelf and stopping.")
        self.splay_blend = _slider(d.crest_blend_mm, 0.0, 6.0, step=0.5, decimals=1)
        self.splay_blend.setToolTip(
            "Round-over radius where the chamfer meets the surface (0 = sharp crest).")
        self.splay_noncontig = QCheckBox("Non-contiguous (keyhole bridge)")
        self.splay_noncontig.setChecked(d.non_contiguous)
        self.splay_noncontig.setToolTip(
            "Start the cut away from bottom-center, leaving the middle uncut — "
            "so a keyhole bridge keeps its shape instead of being planed off.")
        self.splay_gap = _slider(d.gap_mm, 1.0, 40.0, step=0.5, decimals=1)
        self.splay_gap.setToolTip(
            "Total uncut width at bottom-center, split evenly either side. "
            "Each half then runs from here out to the run length.")
        splay.addRow("Run per side:", self.splay_run)
        splay.addRow("Crest at center:", self.splay_dev_center)
        splay.addRow("Crest at ends:", self.splay_dev_end)
        splay.addRow("Splay angle:", self.splay_angle_center)
        splay.addRow("", self.splay_toric)
        splay.addRow("Middle angle:", self.splay_angle_middle)
        splay.addRow("End angle:", self.splay_angle_end)
        splay.addRow("Crest blend:", self.splay_blend)
        splay.addRow("Min edge thickness:", self.splay_clamp)
        splay.addRow("End feather:", self.splay_feather)
        splay.addRow("", self.splay_noncontig)
        splay.addRow("Center gap:", self.splay_gap)
        glay.addLayout(splay)

        self.splay_enable.toggled.connect(self._on_splay_toggled)
        self.splay_enable.toggled.connect(self.castle_changed)
        self.splay_toric.toggled.connect(self._on_splay_toric_toggled)
        self.splay_toric.toggled.connect(self.castle_changed)
        self.splay_noncontig.toggled.connect(self._on_splay_noncontig_toggled)
        self.splay_noncontig.toggled.connect(self.castle_changed)
        for sb in self._splay_spinboxes():
            sb.valueChanged.connect(self.castle_changed)
        self._on_splay_toggled(d.enabled)

        # --- Eyewire bezel: chamfer band around each lens opening (M13.2) ---
        b = EyewireBezelParams()
        glay.addWidget(_section_label("Eyewire Bezel"))
        self.bezel_enable = QCheckBox("Cut bezeled eyewire")
        self.bezel_enable.setChecked(b.enabled)
        self.bezel_enable.setToolTip(
            "Chamfer the posterior rim of each lens opening.")
        glay.addWidget(self.bezel_enable)
        bezel = QFormLayout()
        bezel.setContentsMargins(8, 0, 0, 0)
        bezel.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.bezel_width = _slider(b.width_mm, 0.2, 8.0, step=0.1, decimals=1)
        self.bezel_width.setToolTip("Band width from the lens rim inward.")
        self.bezel_angle = _slider(b.angle_deg, 5.0, 60.0, step=1.0,
                                   decimals=1, suffix="°")
        self.bezel_clamp = _slider(b.anterior_clamp_mm, 0.2, 5.0, step=0.1, decimals=1)
        self.bezel_clamp.setToolTip(
            "Cut floor above the anterior face — the rim never gets thinner than this.")
        # Which face the band is cut into (M17). The posterior band seats the lens;
        # the anterior one is cosmetic, so it carries its own width and angle.
        self.bezel_face = QComboBox()
        self.bezel_face.addItems(["Posterior", "Anterior", "Both faces"])
        self.bezel_face.setToolTip(
            "Which side of the frame the bezel is cut into.\nAn anterior band is "
            "modelled and shown in 3D now; machining it needs the flip setup.")
        self.bezel_ant_width = _slider(b.anterior_width_mm, 0.2, 8.0, step=0.1, decimals=1)
        self.bezel_ant_angle = _slider(b.anterior_angle_deg, 5.0, 80.0, step=1.0,
                                       decimals=1, suffix="°")
        bezel.addRow("Cut into:", self.bezel_face)
        bezel.addRow("Band width:", self.bezel_width)
        bezel.addRow("Bezel angle:", self.bezel_angle)
        bezel.addRow("Min edge thickness:", self.bezel_clamp)
        bezel.addRow("Anterior width:", self.bezel_ant_width)
        bezel.addRow("Anterior angle:", self.bezel_ant_angle)
        glay.addLayout(bezel)

        self.bezel_enable.toggled.connect(self._on_bezel_toggled)
        self.bezel_enable.toggled.connect(self.castle_changed)
        self.bezel_face.currentIndexChanged.connect(self._on_bezel_toggled)
        self.bezel_face.currentIndexChanged.connect(self.castle_changed)
        for sb in (self.bezel_width, self.bezel_angle, self.bezel_clamp,
                   self.bezel_ant_width, self.bezel_ant_angle):
            sb.valueChanged.connect(self.castle_changed)
        self._on_bezel_toggled(b.enabled)

        # --- Bridge relief: conic scoop down the posterior bridge (M13.3) ---
        g = BridgeReliefParams()
        glay.addWidget(_section_label("Bridge Relief"))
        self.bridge_relief_enable = QCheckBox("Cut bridge projection relief")
        self.bridge_relief_enable.setChecked(g.enabled)
        self.bridge_relief_enable.setToolTip(
            "Scoop a conic relief down the posterior bridge — wide at the top "
            "edge, tapering to a rounded tip on the lower bridge.")
        glay.addWidget(self.bridge_relief_enable)
        groove = QFormLayout()
        groove.setContentsMargins(8, 0, 0, 0)
        groove.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.bridge_relief_width = _slider(g.width_mm, 1.0, 24.0, step=0.5, decimals=1)
        self.bridge_relief_width.setToolTip("Scoop width at its base (the top edge).")
        self.bridge_relief_depth = _slider(g.depth_mm, 0.1, 4.0, step=0.1, decimals=1)
        self.bridge_relief_depth.setToolTip("Cut depth at the base centerline.")
        self.bridge_relief_taper = _slider(g.taper_angle_deg, 5.0, 80.0,
                                           step=1.0, decimals=1, suffix="°")
        self.bridge_relief_taper.setToolTip(
            "Side taper of the cone — steeper reaches the tip sooner.")
        self.bridge_relief_clamp = _slider(g.anterior_clamp_mm, 0.2, 5.0,
                                           step=0.1, decimals=1)
        self.bridge_relief_rext = _slider(g.exterior_radius_mm, 0.0, 20.0,
                                          step=0.5, decimals=1)
        self.bridge_relief_rext.setToolTip(
            "Convex round-over where the scoop leaves the bridge face — the "
            "footing's exterior radius, applied to the rim of the depression.")
        self.bridge_relief_rint = _slider(g.interior_radius_mm, 0.0, 20.0,
                                          step=0.5, decimals=1)
        self.bridge_relief_rint.setToolTip(
            "Concave fillet at the bottom of the U — the footing's interior "
            "radius. 0 is a sharp V, which no ball tool can finish.")
        groove.addRow("Width:", self.bridge_relief_width)
        groove.addRow("Depth:", self.bridge_relief_depth)
        groove.addRow("Taper angle:", self.bridge_relief_taper)
        groove.addRow("Exterior radius:", self.bridge_relief_rext)
        groove.addRow("Interior radius:", self.bridge_relief_rint)
        groove.addRow("Min edge thickness:", self.bridge_relief_clamp)
        self._bridge_relief_shape = QLabel("")
        self._bridge_relief_shape.setObjectName("mutedSmallLabel")
        self._bridge_relief_shape.setWordWrap(True)
        groove.addRow("", self._bridge_relief_shape)
        glay.addLayout(groove)

        self.bridge_relief_enable.toggled.connect(self._on_bridge_relief_toggled)
        self.bridge_relief_enable.toggled.connect(self.castle_changed)
        for sb in self._bridge_relief_spinboxes():
            sb.valueChanged.connect(self.castle_changed)
            sb.valueChanged.connect(self._refresh_bridge_relief_shape)
        self._on_bridge_relief_toggled(g.enabled)
        self._refresh_bridge_relief_shape()

        lay.addWidget(grp)

        # --- Lens bevel groove (V1): the drageoir V in each eyewire wall ---
        grp = QGroupBox("Lens Bevel Groove")
        glay = QVBoxLayout(grp)
        lg = LensGrooveParams()
        self.groove_enable = QCheckBox("Cut lens bevel groove")
        self.groove_enable.setChecked(lg.enabled)
        self.groove_enable.setToolTip(
            "V-groove each eyewire wall to seat the lens bevel. The visible\n"
            "aperture (the rim lip) is cut smaller by the groove depth so the\n"
            "groove bottom lands exactly on the drawn LENS contour, and the\n"
            "eyewire channel is widened so the grooving tool's head can enter.\n"
            "Needs a groove-type form cutter — the shipped 5.5 mm fraise drageoir.")
        glay.addWidget(self.groove_enable)
        gform = QFormLayout()
        gform.setContentsMargins(8, 0, 0, 0)
        gform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.groove_offset = _slider(lg.anterior_offset_mm, 0.3, 6.0,
                                     step=0.1, decimals=2)
        self.groove_offset.setToolTip(
            "Groove apex height above the anterior (front) face.")
        self.groove_depth = _slider(lg.depth_mm, 0.2, 2.0, step=0.05, decimals=2)
        self.groove_depth.setToolTip(
            "Radial depth into the rim — also how much smaller the visible\n"
            "aperture is than the drawn lens.")
        self.groove_width = _slider(lg.width_mm, 0.5, 4.0, step=0.1, decimals=2)
        self.groove_width.setToolTip("V opening height at the rim face.")
        self.groove_angle_lbl = QLabel("")
        self.groove_angle_lbl.setObjectName("hintLabel")
        self.groove_angle_lbl.setToolTip(
            "Included V angle, derived from depth and width — match it to the\n"
            "grooving tool's form (the shipped drageoir is ≈106°).")
        self.groove_tool = QComboBox()
        self.groove_tool.addItems(_tool_names())
        idx = self.groove_tool.findText(lg.tool)
        if idx >= 0:
            self.groove_tool.setCurrentIndex(idx)
        self.groove_tool.setToolTip(
            "The side-cutting form tool for the groove (a groove-type tool).")
        gform.addRow("Apex from anterior:", self.groove_offset)
        gform.addRow("Depth:", self.groove_depth)
        gform.addRow("Width:", self.groove_width)
        gform.addRow("Included angle:", self.groove_angle_lbl)
        gform.addRow("Tool:", self.groove_tool)
        glay.addLayout(gform)

        self.groove_enable.toggled.connect(self._on_groove_toggled)
        self.groove_enable.toggled.connect(self.castle_changed)
        for sb in (self.groove_offset, self.groove_depth, self.groove_width):
            sb.valueChanged.connect(self._update_groove_angle)
            sb.valueChanged.connect(self.castle_changed)
        self.groove_tool.currentIndexChanged.connect(self.castle_changed)
        self._on_groove_toggled(lg.enabled)
        self._update_groove_angle()

        lay.addWidget(grp)

    def _on_groove_toggled(self, on: bool) -> None:
        """Grey out the groove controls when the groove is off."""
        for w in (self.groove_offset, self.groove_depth, self.groove_width,
                  self.groove_tool):
            w.setEnabled(on)
        if on:
            self._refresh_limits()   # the depth ceiling is measured on first use

    def _update_groove_angle(self) -> None:
        """Included V angle read-out: 2·atan((width/2) / depth)."""
        import math as _math
        d = max(self.groove_depth.value(), 1e-6)
        ang = 2.0 * _math.degrees(_math.atan((self.groove_width.value() / 2.0) / d))
        self.groove_angle_lbl.setText(f"{ang:.0f}°")

    def _bridge_relief_spinboxes(self) -> list[Numeric]:
        return [self.bridge_relief_width, self.bridge_relief_depth,
                self.bridge_relief_taper, self.bridge_relief_clamp,
                self.bridge_relief_rext, self.bridge_relief_rint]

    def _refresh_bridge_relief_shape(self, *_a) -> None:
        """Say what the U the numbers describe actually comes out as.

        The two radii do not act independently of the width and depth: past
        `(a**2 + d**2) / 2d` on their sum the section has no straight ramp left
        and `blends._fit_radii` shrinks both to fit. A maker turning the radius
        up and seeing the shape stop changing deserves to be told why, and the
        ramp angle is the number that decides the finishing stepover anyway."""
        if not hasattr(self, "_bridge_relief_shape"):
            return
        from guildmodel.core.geometry.blends import scoop_ramp_angle
        import math
        w = self.bridge_relief_width.value()
        d = self.bridge_relief_depth.value()
        asked_e = self.bridge_relief_rext.value()
        asked_i = self.bridge_relief_rint.value()
        theta, re, ri = scoop_ramp_angle(max(w / 2.0, 1e-9), max(d, 1e-9),
                                          asked_e, asked_i)
        txt = f"U wall {math.degrees(float(theta)):.1f}°"
        if abs(float(re) - asked_e) > 0.05 or abs(float(ri) - asked_i) > 0.05:
            txt += (f" · radii capped to {float(re):.2f} / {float(ri):.2f} mm "
                    f"by this width and depth")
        self._bridge_relief_shape.setText(txt)

    def _on_bridge_relief_toggled(self, on: bool) -> None:
        """Grey out the bridge-relief controls when the groove is off."""
        for sb in self._bridge_relief_spinboxes():
            sb.setEnabled(on)

    def _on_bezel_toggled(self, *_a) -> None:
        """Grey out the bezel controls when it is off, and each face's own numbers
        when that face is not being cut — so the enabled fields are exactly the
        ones that reach the model."""
        on = self.bezel_enable.isChecked()
        face = self.bezel_face.currentIndex()          # 0 post · 1 ant · 2 both
        self.bezel_face.setEnabled(on)
        for sb in (self.bezel_width, self.bezel_angle, self.bezel_clamp):
            sb.setEnabled(on and face in (0, 2))
        for sb in (self.bezel_ant_width, self.bezel_ant_angle):
            sb.setEnabled(on and face in (1, 2))

    def _splay_spinboxes(self) -> list[Numeric]:
        return [self.splay_run, self.splay_dev_center, self.splay_dev_end,
                self.splay_angle_center, self.splay_angle_middle,
                self.splay_angle_end, self.splay_blend, self.splay_clamp,
                self.splay_feather, self.splay_gap]

    def _on_splay_toggled(self, on: bool) -> None:
        """Grey out the pad-splay controls when the chamfer is off."""
        for sb in self._splay_spinboxes():
            sb.setEnabled(on)
        self.splay_toric.setEnabled(on)
        self.splay_noncontig.setEnabled(on)
        self._on_splay_toric_toggled(self.splay_toric.isChecked())
        self._on_splay_noncontig_toggled(self.splay_noncontig.isChecked())

    def _on_splay_toric_toggled(self, toric: bool) -> None:
        """Middle/end angles only apply in toric mode."""
        on = self.splay_enable.isChecked() and toric
        self.splay_angle_middle.setEnabled(on)
        self.splay_angle_end.setEnabled(on)

    def _on_splay_noncontig_toggled(self, split: bool) -> None:
        """The center gap only means anything once the cut is non-contiguous."""
        self.splay_gap.setEnabled(self.splay_enable.isChecked() and split)

    def seed_pad_splay_angle(self, deg: float) -> None:
        """Seed the splay angle from the drawing's forming bridge angle — only
        while the splay is untouched (disabled and all angles at the default)."""
        d = PadSplayParams()
        if self.splay_enable.isChecked() or deg <= 0.0:
            return
        if any(sb.value() != default for sb, default in (
                (self.splay_angle_center, d.angle_center_deg),
                (self.splay_angle_middle, d.angle_middle_deg),
                (self.splay_angle_end, d.angle_end_deg))):
            return
        for sb in (self.splay_angle_center, self.splay_angle_middle,
                   self.splay_angle_end):
            sb.blockSignals(True)
            sb.setValue(deg)
            sb.blockSignals(False)

    def seed_pad_splay_run(self, run_mm: float) -> None:
        """Seed the splay run from THIS frame's geometry (bottom-center to just
        past the lower nosepad SCULPT line) — only while untouched, same guard
        as the angle seed."""
        d = PadSplayParams()
        if (self.splay_enable.isChecked() or run_mm <= 0.0
                or self.splay_run.value() != d.run_mm):
            return
        self.splay_run.blockSignals(True)
        self.splay_run.setValue(run_mm)
        self.splay_run.blockSignals(False)

    def _castle_spinboxes(self) -> list[Numeric]:
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

    # ------------------------------------------------------- what fits (limits)
    #
    # `core.project.limits` derives the safe range of every Model / Stock number
    # from the rest of the project; this is the part that knows which widget each
    # of its keys belongs to and when to ask again. Nothing here writes a value:
    # a number that no longer fits is marked by its own `ParamSlider`, never
    # rewritten, so opening a project whose nosepad no longer fits its stock says
    # so instead of quietly shortening the tower.

    def _limit_targets(self) -> dict[str, Numeric]:
        """Widget per `core.project.limits` key."""
        return {
            "zones.endpiece_mm": self.zone_endpiece,
            "zones.bridge_mm": self.zone_bridge,
            "zones.nosepad_mm": self.zone_nosepad,
            "zones.eyewire_superior_mm": self.zone_eyewire_superior,
            "zones.eyewire_inferior_mm": self.zone_eyewire_inferior,
            "hinge_pocket_depth_mm": self.hinge_pocket_depth,
            "pad_splay.anterior_clamp_mm": self.splay_clamp,
            "pad_splay.gap_mm": self.splay_gap,
            "eyewire_bezel.anterior_clamp_mm": self.bezel_clamp,
            "bridge_relief.anterior_clamp_mm": self.bridge_relief_clamp,
            "bridge_relief.depth_mm": self.bridge_relief_depth,
            "bridge_relief.exterior_radius_mm": self.bridge_relief_rext,
            "bridge_relief.interior_radius_mm": self.bridge_relief_rint,
            "lens_groove.anterior_offset_mm": self.groove_offset,
            "lens_groove.depth_mm": self.groove_depth,
            "lens_groove.width_mm": self.groove_width,
            "stock.pad_block_length_mm": self.pad_length,
            "stock.pad_block_width_mm": self.pad_width,
        }

    def _groove_depth_ceiling(self) -> float | None:
        """The deepest groove this drawing's apertures survive, or None.

        Costs a castle re-partition per probe — about 0.6 s for the search — so
        it is computed only when the groove is actually on, and cached against
        the partition it was measured from. None while the groove is off leaves
        the depth control its full range; nothing is being built from it.
        """
        part = getattr(self, "_partition", None)
        if part is None or not self.groove_enable.isChecked():
            return None
        if getattr(self, "_groove_ceiling_for", None) is part:
            return self._groove_ceiling
        from guildmodel.core.project.limits import max_groove_depth

        try:
            ceiling = max_groove_depth(part, high=self.groove_depth.hard_range()[1])
        except Exception:
            ceiling = None        # never let a probe stop the panel from painting
        self._groove_ceiling_for, self._groove_ceiling = part, ceiling
        return ceiling

    def _refresh_limits(self) -> None:
        """Re-derive every safe range. Cheap, and idempotent.

        Writes no values, so it cannot loop back through the signals that call
        it — which is what lets it hang off `castle_changed` and `stock_changed`
        rather than needing a list of everything that might have moved.
        """
        if not self._limits_ready:
            return                # tabs still under construction
        from guildmodel.core.project.limits import (castle_limits,
                                                    edge_feature_limits)

        castle = self.castle_params()
        bounds = dict(castle_limits(castle, getattr(self, "_partition", None),
                                    self._groove_depth_ceiling()))
        widgets = dict(self._limit_targets())

        row = self.edge_list.currentRow()
        if 0 <= row < len(self._edge_features):
            for key, limit in edge_feature_limits(
                    castle, self._edge_features[row]).items():
                bounds[f"edge.{key}"] = limit
            widgets.update({"edge.width_mm": self.ef_width,
                            "edge.angle_deg": self.ef_angle,
                            "edge.radius_mm": self.ef_radius,
                            "edge.min_thickness_mm": self.ef_min_thickness})

        for path, widget in widgets.items():
            limit = bounds.get(path)
            if limit is not None and isinstance(widget, ParamSlider):
                widget.set_safe_range(limit.low, limit.high, limit.reason)

    def _connect_live_handles(self) -> None:
        """Every Model-tab handle reports while it is being dragged.

        Found by walking the tab rather than listed, so a control added later is
        live without anyone remembering this method — the failure mode of a list
        is one slider that drags dead, which looks like a broken slider rather
        than a missing connection.

        The **Stock** tab is deliberately not walked. Its numbers move the ghost
        box drawn around the part, not the part, and `_on_stock_changed` already
        redraws that from the cached mesh. Feeding them into the model rebuild
        would make dragging a blank dimension the most expensive thing here and
        buy nothing.
        """
        for handle in self.widget(self._tab_castle).findChildren(ParamSlider):
            handle.sliding.connect(self.castle_sliding)

    def out_of_range_paths(self) -> list[tuple[str, str]]:
        """`(schema path, what is wrong)` for every control outside its safe range.

        The panel marks each one in place; this is how the rest of the app can
        say the same thing in a job's issue list, where a maker looks before
        posting rather than while dragging.
        """
        out: list[tuple[str, str]] = []
        for path, widget in self._limit_targets().items():
            if isinstance(widget, ParamSlider) and widget.out_of_range():
                lo, hi = widget.safe_range()
                out.append((path, f"{widget.value():g} is outside {lo:g}–{hi:g}"))
        return out

    # ------------------------------------------------------------------ Stock tab

    def _build_stock_tab(self, lay: QVBoxLayout) -> None:
        self._build_stock_group(lay)

    def _build_stock_group(self, lay: QVBoxLayout) -> None:
        grp = QGroupBox("Stock")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.blank_length = _slider(170.0, 50.0, 300.0, step=1.0, decimals=1)
        self.blank_width = _slider(85.0, 30.0, 200.0, step=1.0, decimals=1)
        self.blank_thickness = _slider(6.0, 1.0, 12.0, step=0.5, decimals=1)
        form.addRow("Blank length:", self.blank_length)
        form.addRow("Blank width:", self.blank_width)
        form.addRow("Blank thickness:", self.blank_thickness)

        self.use_pad_block = QCheckBox("Add nosepad pad block")
        self.use_pad_block.setChecked(True)
        self.use_pad_block.setToolTip(
            "Add a raised pad block for the tall nosepad towers.")
        form.addRow("", self.use_pad_block)

        self.pad_length = _slider(45.0, 10.0, 120.0, step=1.0, decimals=1)
        self.pad_width = _slider(45.0, 10.0, 120.0, step=1.0, decimals=1)
        self.pad_thickness = _slider(4.0, 0.5, 10.0, step=0.5, decimals=1)
        form.addRow("Pad block length:", self.pad_length)
        form.addRow("Pad block width:", self.pad_width)
        form.addRow("Pad block thickness:", self.pad_thickness)

        for sb in (self.blank_length, self.blank_width, self.blank_thickness,
                   self.pad_length, self.pad_width, self.pad_thickness):
            sb.valueChanged.connect(self.stock_changed)
        self.use_pad_block.toggled.connect(self._on_pad_block_toggled)
        self.use_pad_block.toggled.connect(self.stock_changed)

        lay.addWidget(grp)

    def _on_pad_block_toggled(self, on: bool) -> None:
        """Grey out the pad-block dimensions when the pad block is off."""
        for sb in (self.pad_length, self.pad_width, self.pad_thickness):
            sb.setEnabled(on)

    def _on_temple_snap_toggled(self, on: bool) -> None:
        """Stock side only matters when snapping to the blank; invalidate the path."""
        self.temple_stock_side.setEnabled(on)
        self.cam_changed.emit()

    # ------------------------------------------------------------------ Temple tab

    def _build_temple_tab(self, lay: QVBoxLayout) -> None:
        d = TempleParams()
        grp = QGroupBox("Temple")
        grp.setToolTip("A flat temple: ENGRAVING grooves on top + an OUTLINE through-cut.")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.temple_blank_length = _spinbox(d.blank_length_mm, 50.0, 300.0, step=1.0, decimals=1)
        self.temple_blank_width = _spinbox(d.blank_width_mm, 8.0, 80.0, step=1.0, decimals=1)
        self.temple_blank_thickness = _spinbox(d.blank_thickness_mm, 1.0, 12.0, step=0.5, decimals=1)
        form.addRow("Blank length:", self.temple_blank_length)
        form.addRow("Blank width:", self.temple_blank_width)
        form.addRow("Blank thickness:", self.temple_blank_thickness)
        self.temple_snap_blank = QCheckBox("Snap to blank end")
        self.temple_snap_blank.setChecked(d.snap_to_blank_end)
        self.temple_snap_blank.setToolTip(
            "Re-centre the temple on its blank for cutting (hinge butted to one end).")
        self.temple_snap_blank.toggled.connect(self._on_temple_snap_toggled)
        form.addRow("", self.temple_snap_blank)
        self.temple_stock_side = QComboBox()
        self.temple_stock_side.addItems(["right", "left"])
        self.temple_stock_side.setCurrentText(d.stock_side)
        self.temple_stock_side.setToolTip(
            "Which blank end the hinge registers to (when 'Snap to blank end' is on).")
        self.temple_stock_side.currentIndexChanged.connect(self.cam_changed)
        self.temple_stock_side.setEnabled(d.snap_to_blank_end)
        form.addRow("Stock side:", self.temple_stock_side)

        self.temple_engrave_depth = _spinbox(d.engrave_depth_mm, 0.0, 3.0, step=0.05, decimals=2)
        self.temple_engrave_depth.setToolTip("Groove depth below the top face.")
        form.addRow("Engrave depth:", self.temple_engrave_depth)
        self.temple_engrave_stepdown = _spinbox(
            d.engrave_stepdown_mm, 0.05, 3.0, step=0.05, decimals=2)
        self.temple_engrave_stepdown.setToolTip(
            "Depth per engraving pass. A groove deeper than this is cut in several "
            "passes\ninstead of one plunge to full depth — engraving bits are the "
            "most slender in the program.")
        form.addRow("Engrave depth/pass:", self.temple_engrave_stepdown)
        self.temple_engrave_tool = QComboBox()
        self.temple_engrave_tool.addItems(_tool_names())
        self.temple_engrave_tool.setCurrentText(d.engrave_tool)
        self.temple_engrave_tool.setToolTip("Bit for the ENGRAVING grooves.")
        form.addRow("Engrave tool:", self.temple_engrave_tool)
        self.temple_engrave_centerline = QCheckBox("Engrave stroke centerlines")
        self.temple_engrave_centerline.setChecked(d.engrave_centerline)
        self.temple_engrave_centerline.setToolTip(
            "Engrave one centre line per stroke instead of tracing the outlines.")
        self.temple_engrave_centerline.toggled.connect(self.cam_changed)
        form.addRow("", self.temple_engrave_centerline)
        self.temple_hinge_tool = QComboBox()
        self.temple_hinge_tool.addItems(_tool_names())
        self.temple_hinge_tool.setCurrentText(d.hinge_tool)
        self.temple_hinge_tool.setToolTip("Endmill for the HINGE pockets.")
        form.addRow("Hinge-pocket tool:", self.temple_hinge_tool)
        self.temple_profile_tool = QComboBox()
        self.temple_profile_tool.addItems(_tool_names())
        self.temple_profile_tool.setCurrentText(d.profile_tool)
        form.addRow("Profile tool:", self.temple_profile_tool)

        self.temple_onion = _spinbox(d.onion_skin_mm, 0.0, 2.0, step=0.1, decimals=2)
        form.addRow("Onion skin:", self.temple_onion)
        self.temple_allowance = _spinbox(d.hand_finishing_allowance_mm, 0.0, 1.0, step=0.05, decimals=2)
        form.addRow("Hand allowance:", self.temple_allowance)

        for w in (self.temple_blank_length, self.temple_blank_width,
                  self.temple_blank_thickness, self.temple_engrave_depth,
                  self.temple_engrave_stepdown,
                  self.temple_onion, self.temple_allowance):
            w.valueChanged.connect(self.cam_changed)
        self.temple_engrave_tool.currentIndexChanged.connect(self.cam_changed)
        self.temple_hinge_tool.currentIndexChanged.connect(self.cam_changed)
        self.temple_profile_tool.currentIndexChanged.connect(self.cam_changed)
        lay.addWidget(grp)

    # ------------------------------------------------------------------ Base Curve tab

    def _build_block_tab(self, lay: QVBoxLayout) -> None:
        d = BaseCurveBlockParams()
        grp = QGroupBox("Base-Curve Holding Block")
        grp.setToolTip("Acetal block: the lens shape cut free, with M4 mounting holes.")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.block_blank_length = _spinbox(d.blank_length_mm, 30.0, 150.0, step=1.0, decimals=1)
        self.block_blank_width = _spinbox(d.blank_width_mm, 30.0, 150.0, step=1.0, decimals=1)
        # 4 decimals so imperial gauges round-trip exactly (3/16" = 4.7625 mm).
        self.block_blank_thickness = _spinbox(d.blank_thickness_mm, 3.0, 20.0, step=0.0125, decimals=4)
        form.addRow("Blank length:", self.block_blank_length)
        form.addRow("Blank width:", self.block_blank_width)
        form.addRow("Blank thickness:", self.block_blank_thickness)

        self.block_profile_tool = QComboBox()
        self.block_profile_tool.addItems(_tool_names())
        self.block_profile_tool.setCurrentText(d.profile_tool)
        form.addRow("Profile tool:", self.block_profile_tool)

        self.block_onion = _spinbox(d.onion_skin_mm, 0.0, 2.0, step=0.1, decimals=2)
        form.addRow("Onion skin:", self.block_onion)
        self.block_allowance = _spinbox(d.hand_finishing_allowance_mm, 0.0, 1.0, step=0.05, decimals=2)
        form.addRow("Hand allowance:", self.block_allowance)
        lay.addWidget(grp)

        hg = QGroupBox("Mounting holes  (M4 clearance)")
        hf = QFormLayout(hg)
        hf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.block_hole_count = QSpinBox()
        self.block_hole_count.setRange(0, 6)
        self.block_hole_count.setValue(d.hole_count)
        hf.addRow("Hole count:", self.block_hole_count)
        self.block_hole_spacing = _spinbox(d.hole_spacing_mm, 4.0, 40.0, step=1.0, decimals=1)
        hf.addRow("Hole spacing:", self.block_hole_spacing)
        self.block_hole_diameter = _spinbox(d.hole_diameter_mm, 1.0, 10.0, step=0.1, decimals=2)
        hf.addRow("Hole Ø:", self.block_hole_diameter)
        self.block_hole_arrangement = QComboBox()
        self.block_hole_arrangement.addItems(["inline", "triangle"])
        self.block_hole_arrangement.setCurrentText(d.hole_arrangement)
        hf.addRow("Arrangement:", self.block_hole_arrangement)
        self.block_drill_tool = QComboBox()
        self.block_drill_tool.addItems(_tool_names())
        self.block_drill_tool.setCurrentText(d.drill_tool)
        hf.addRow("Drill tool:", self.block_drill_tool)
        self.block_peck_depth = _spinbox(d.peck_depth_mm, 0.2, 5.0, step=0.1, decimals=2)
        hf.addRow("Peck depth:", self.block_peck_depth)
        self.block_breakthrough = _spinbox(d.drill_breakthrough_mm, 0.0, 5.0, step=0.1, decimals=2)
        hf.addRow("Breakthrough:", self.block_breakthrough)
        lay.addWidget(hg)

        for w in (self.block_blank_length, self.block_blank_width,
                  self.block_blank_thickness,
                  self.block_onion, self.block_allowance, self.block_hole_spacing,
                  self.block_hole_diameter, self.block_peck_depth, self.block_breakthrough):
            w.valueChanged.connect(self.cam_changed)
        self.block_hole_count.valueChanged.connect(self.cam_changed)
        for cb in (self.block_profile_tool,
                   self.block_hole_arrangement, self.block_drill_tool):
            cb.currentIndexChanged.connect(self.cam_changed)

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
        self.zone_list.setToolTip(
            "Double-click a zone to override its height for this drawing only.\n"
            "Overridden zones are marked ✎; clear the box to go back to the "
            "per-kind default above."
        )
        self.zone_list.itemDoubleClicked.connect(self._on_zone_double_clicked)
        glay.addWidget(self.zone_list)

        self.zone_reset_btn = QPushButton("Clear zone overrides")
        self.zone_reset_btn.setEnabled(False)
        self.zone_reset_btn.clicked.connect(self._clear_zone_overrides)
        glay.addWidget(self.zone_reset_btn)

        lay.addWidget(grp)

    def _on_zone_double_clicked(self, item) -> None:
        """Edit one zone's height, overriding the per-kind default. Keyed by zone
        *name*, so a drawing with two bridge bars (an opening splitting the
        bridge) can give each its own height."""
        name = item.data(Qt.ItemDataRole.UserRole)
        zone = next((z for z in self._partition.zones if z.name == name), None)
        if zone is None:
            return
        current = self._zone_overrides.get(
            name, self._castle_zone_thicknesses().for_kind(zone.kind)
            if zone.kind != "generic" else 4.0)
        # An override answers to this zone's own footprint, which is the whole
        # point of having one: a nosepad that runs off the pad block does not
        # get the block's height just because its twin does.
        from guildmodel.core.project.limits import stock_ceiling

        ceiling = stock_ceiling(self.stock_definition(), zone.polygon)
        value, ok = QInputDialog.getDouble(
            self, "Zone height",
            f"{name} height (mm) — {ceiling:g} mm of stock over it:",
            current, 0.0, ceiling, 2)
        if not ok:
            return
        self._zone_overrides[name] = value
        self._refresh_zone_list()
        self.castle_changed.emit()

    def _clear_zone_overrides(self) -> None:
        if not self._zone_overrides:
            return
        self._zone_overrides.clear()
        self._refresh_zone_list()
        self.castle_changed.emit()

    def set_zones(self, partition) -> None:
        """Populate the zone inspector from a CastlePartition (or None)."""
        self._partition = partition
        # Both are measured against the drawing: the stock ceilings from where
        # each zone's footprint stands, the groove ceiling from how far the
        # apertures can shrink. A new drawing invalidates both.
        self._groove_ceiling = None
        self._groove_ceiling_for = None
        # The edge-feature span picker lists this drawing's zones (M17), so it has
        # to be rebuilt whenever the drawing changes.
        if hasattr(self, "ef_zones"):
            self._refresh_edge_zone_choices()
            row = self.edge_list.currentRow()
            if 0 <= row < len(self._edge_features):
                self._on_edge_selected(row)
        if partition is None:
            self.zones_status.setText(
                "No SCULPT zones — draw 5 section cuts per side in GuildDraw."
            )
        elif partition.matched:
            self.zones_status.setText(
                f"{len(partition.zones)} zones — standard castle layout."
            )
        elif partition.classified:
            # Not the reference 5-cuts-per-side castle, but every zone is named,
            # so the castle builds — an aviator's brow bar, an extra section cut.
            kinds = ", ".join(sorted({z.kind for z in partition.zones}))
            self.zones_status.setText(
                f"{len(partition.zones)} zones — non-standard layout ({kinds}). "
                "Double-click a zone to set its height."
            )
        else:
            self.zones_status.setText(
                "⚠ Generic zones — the castle needs the 5-cuts-per-side layout."
            )
        self._refresh_zone_list()

    def _refresh_zone_list(self) -> None:
        self.zone_list.clear()
        if self._partition is None:
            self.zone_reset_btn.setEnabled(False)
            return
        # Drop overrides for zones this drawing no longer has, so a stale entry
        # can't silently apply to a same-named zone in a different frame.
        live = {z.name for z in self._partition.zones}
        self._zone_overrides = {k: v for k, v in self._zone_overrides.items()
                                if k in live}
        zones = self._castle_zone_thicknesses()
        for z in self._partition.zones:
            if z.kind == "generic":
                item = QListWidgetItem(f"⚠ {z.name} — unmatched")
                item.setForeground(Qt.GlobalColor.darkRed)
            elif z.name in self._zone_overrides:
                item = QListWidgetItem(
                    f"✎ {z.name} — {self._zone_overrides[z.name]:.1f} mm")
            else:
                item = QListWidgetItem(f"{z.name} — {zones.for_kind(z.kind):.1f} mm")
            item.setData(Qt.ItemDataRole.UserRole, z.name)
            self.zone_list.addItem(item)
        self.zone_reset_btn.setEnabled(bool(self._zone_overrides))

    # ---------------------------------------------------------------- Cut tab

    def _build_cut_tab(self, lay: QVBoxLayout) -> None:
        """Everyday cut controls — what the material dictates and the chip-load check.
        Universal (every component kind); the old 'CAM' tab split into Cut + Machine
        so the maker's routine choices aren't buried under machine setup (UX pass)."""
        self._build_material_group(lay)      # material (leads) + allowances
        self._build_feeds_group(lay)         # feeds & speeds, from the material
        self._build_depth_group(lay)         # depth per pass + the pass read-out
        self._build_holding_group(lay)       # onion skin | hold-down tabs (M16)
        self._build_operations_group(lay)    # per-op enable/skip (M16)
        self._build_overrides_group(lay)     # per-component CAM overrides (M16)
        self._build_chip_group(lay)          # chip-load / surface-speed read-out

    # ------------------------------------------------------------ Machine tab

    def _build_machine_tab(self, lay: QVBoxLayout) -> None:
        """Machine setup + the frame's toolpath detail (set once / expert). Machine
        target, Program Zero and the through-cut lead-in are universal; the per-op
        tools, relief strategy and profile fallback are frame-posterior-only and hide
        for temple/base-curve."""
        self._build_machine_tool_group(lay)  # controller + default tool
        self._build_program_zero_group(lay)  # G54 work datum
        self._build_leadin_group(lay)        # ramp angle + arc output (universal)
        self._build_op_tools_group(lay)      # per-op tools (frame-only)
        self._build_strategy_group(lay)      # relief strategy (frame-only)
        self._build_fallback_group(lay)      # profile fallback (frame-only)

    def _update_chip_readout(self) -> None:
        """Re-derive the chip load + surface speed for the active tool / feed /
        spindle / material and flag it against the material's window (M7.10)."""
        if not hasattr(self, "_chip_load_lbl"):
            return
        from guildmodel.core.cam import feeds
        from guildmodel.gui import material_store, tool_store
        mat = material_store.material(self.material.currentText())
        tool = tool_store.spec(self.cam_tool.currentText())
        feed = float(self.feed_override.value()) or float(mat.get("feed_rate_mmpm", 0) or 0)
        spindle = float(self.spindle_override.value()) or float(mat.get("spindle_rpm", 0) or 0)
        cl = feeds.chip_load_mm(feed, spindle, int(tool.flutes or 0))
        vc = feeds.surface_speed_m_per_min(float(tool.diameter_mm or 0), spindle)
        self._chip_load_lbl.setText(f"{cl:.4f} mm/tooth" if cl is not None else "—")
        self._surface_speed_lbl.setText(f"{vc:.0f} m/min" if vc else "—")
        status = feeds.chip_load_status(cl, mat.get("chip_load_min_mm"),
                                        mat.get("chip_load_max_mm"))
        text, color = {
            "ok": ("✓ within the material's window", "#3a8c3a"),
            "low": ("⚠ light cut — chip too thin (rubbing); raise feed or lower RPM",
                    "#c08a00"),
            "high": ("⚠ heavy cut — chip too thick; lower feed or raise RPM", "#c0392b"),
            "unknown": ("", ""),
        }[status]
        self._chip_status_lbl.setText(text)
        self._chip_status_lbl.setStyleSheet(
            f"color: {color}; font-weight: 600;" if color else "")

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
            "Where you touch off work zero — a stock-box corner/centre, or fixture.")
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
            "Target controller — feeds, spindle and depth-of-cut are clamped to it.")
        form.addRow("Machine:", self.machine)

        self.cam_tool = QComboBox()
        self.cam_tool.addItems(_tool_names())
        self.cam_tool.setCurrentText("flat_3175")
        self.cam_tool.setToolTip(
            "Default tool for the program; per-op tools below override it.")
        form.addRow("Tool:", self.cam_tool)
        # Cross-group wiring lives with the widgets themselves so the Cut / Machine
        # tabs can be built in either order (BUILDPLAN UX pass — split CAM tab).
        self.machine.currentIndexChanged.connect(self.cam_changed)
        self.cam_tool.currentIndexChanged.connect(self.cam_changed)
        lay.addWidget(grp)

    def _build_op_tools_group(self, lay: QVBoxLayout) -> None:
        """Per-operation tool selectors (BUILDPLAN M6.1 multi-tool jobs).

        Each op may keep the global tool or pick its own; a tool change is posted
        at op boundaries where the tool differs (a small tool for the hinge
        pockets, the bulk tool for relief / eyewires / perimeter is the everyday
        case)."""
        grp = QGroupBox("Per-operation tools  (multi-tool jobs)")
        self._op_tools_group = grp        # frame-only — hidden on temple / base curve
        grp.setToolTip(
            "Assign a tool per operation ('(same as Tool)' uses the default above).")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        names = _tool_names()
        self.op_tool_combos: dict[str, QComboBox] = {}
        # "Features" is not in POSTERIOR_OPS (it only exists when a posterior
        # feature is on, and listing it there would make every job read as
        # multi-tool — the same reasoning that keeps "Lens Groove" out). It gets
        # a selector regardless, because picking a ball for the features and an
        # end mill for everything else is the everyday multi-tool job.
        for op in (*POSTERIOR_OPS, "Features"):
            cb = QComboBox()
            cb.addItem(_SAME_AS_GLOBAL)
            cb.addItems(names)
            default = DEFAULT_OP_TOOLS.get(op)        # fine-tool default (M11)
            if default and cb.findText(default) >= 0:
                cb.setCurrentText(default)
            cb.currentIndexChanged.connect(self.cam_changed)
            self.op_tool_combos[op] = cb
            form.addRow(f"{op}:", cb)
        self.op_tool_combos["Features"].setToolTip(
            "Tool for the posterior features (pad splay, eyewire bezel, bridge "
            "relief, edge features). '(same as Tool)' follows Fine Relief — the "
            "tool these were cut with before they became their own operation. "
            "A ball is what finishes a chamfer toe or a scoop trough.")
        lay.addWidget(grp)

    def refresh_tool_lists(self) -> None:
        """Repopulate every tool combo from the (possibly edited) library, keeping
        the current selection where it still exists (BUILDPLAN M7.8 — called after
        the Preferences ▸ Tools editor closes)."""
        names = _tool_names()

        def _repop(cb, *, sentinel: bool = False) -> None:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            if sentinel:
                cb.addItem(_SAME_AS_GLOBAL)
            cb.addItems(names)
            idx = cb.findText(cur)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)

        if hasattr(self, "cam_tool"):
            _repop(self.cam_tool)
        for cb in getattr(self, "op_tool_combos", {}).values():
            _repop(cb, sentinel=True)
        for attr in ("temple_engrave_tool", "temple_hinge_tool", "temple_profile_tool",
                     "block_profile_tool", "block_drill_tool", "groove_tool"):
            cb = getattr(self, attr, None)
            if cb is not None:
                _repop(cb)
        self._update_chip_readout()         # a tool's flutes/Ø may have changed (M7.10)

    def _build_material_group(self, lay: QVBoxLayout) -> None:
        """The everyday cut choices: the material (which drives the feeds & speeds)
        and the two hand-finishing allowances. Leads the Cut tab (BUILDPLAN UX pass —
        the maker picks a material first)."""
        grp = QGroupBox("Material & Allowances")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.material = QComboBox()
        self.material.addItems(material_store.names() or ["acetate"])
        self.material.setToolTip(
            "Load this material's feeds, speeds and stepovers into the Cut tab.")
        form.addRow("Material:", self.material)

        self.onion_skin = _spinbox(0.4, 0.0, 2.0, step=0.1, decimals=2)
        self.onion_skin.setToolTip(
            "Axial stock left under through-cuts (no tabs — released by hand).")
        form.addRow("Onion skin:", self.onion_skin)

        self.hand_allowance = _spinbox(0.1, 0.0, 1.0, step=0.05, decimals=2)
        self.hand_allowance.setToolTip(
            "Radial leave-behind stock on contour operations.")
        form.addRow("Hand finishing allowance:", self.hand_allowance)

        for w in (self.onion_skin, self.hand_allowance):
            w.valueChanged.connect(self.cam_changed)
        # Selecting a material repopulates feeds/speeds/stepover/stepdown.
        self.material.currentIndexChanged.connect(self._on_material_changed)
        lay.addWidget(grp)

    def _build_feeds_group(self, lay: QVBoxLayout) -> None:
        """Feeds, speeds and rapid clearances — populated from the material, editable."""
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
        self.safe_z_clearance.setToolTip(
            "Rapid clearance height above the tallest obstacle (stock or hold-downs).")
        self.hold_down_height = _spinbox(
            CastleCamParams().hold_down_height_mm, 0.0, 60.0, step=0.5)
        self.hold_down_height.setToolTip(
            "Height of the work-holding clamps above the table; rapids clear it.")
        of.addRow("Feed override:", self.feed_override)
        of.addRow("Plunge override:", self.plunge_override)
        of.addRow("Spindle override:", self.spindle_override)
        of.addRow("Safe-Z clearance:", self.safe_z_clearance)
        of.addRow("Work-holding height:", self.hold_down_height)
        for w in (self.feed_override, self.plunge_override,
                  self.safe_z_clearance, self.hold_down_height):
            w.valueChanged.connect(self.cam_changed)
        self.spindle_override.valueChanged.connect(self.cam_changed)
        lay.addWidget(og)

    def _build_chip_group(self, lay: QVBoxLayout) -> None:
        """Chip-load / surface-speed read-out (BUILDPLAN M7.10): the relationship
        between the tool (flutes / diameter), the spindle, and the feed."""
        cg = QGroupBox("Chip load  (feed per tooth)")
        cg.setToolTip(
            "Chip load & surface speed vs the material's window "
            "(green = OK, amber = light, red = heavy).")
        cf = QFormLayout(cg)
        cf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._chip_load_lbl = QLabel("—")
        self._surface_speed_lbl = QLabel("—")
        self._chip_status_lbl = QLabel("")
        self._chip_status_lbl.setWordWrap(True)
        cf.addRow("Chip load:", self._chip_load_lbl)
        cf.addRow("Surface speed:", self._surface_speed_lbl)
        cf.addRow(self._chip_status_lbl)
        lay.addWidget(cg)

    def _build_depth_group(self, lay: QVBoxLayout) -> None:
        """How deep each pass bites — the everyday depth choice, on the Cut tab.

        **Universal.** These drive the through-cut and pocket passes of every
        component kind, not just the frame. They used to live in the frame-only Cut
        Strategy group, which `set_component_kind` hid for temples and base-curve
        blocks — so a temple was cut at whatever depth the frame's strategy happened
        to hold, with no way to see or change it. A 4 mm temple blank at the old
        4.0 mm default was one full-depth pass.
        """
        d = CastleCamParams()
        grp = QGroupBox("Depth per pass")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.contour_stepdown = _spinbox(d.contour_stepdown_mm, 0.1, 6.0, step=0.1)
        self.contour_stepdown.setToolTip(
            "Axial depth per through-cut pass — how much the cutter takes each time "
            "round the outline.\nCapped at post time by the material's and the "
            "machine's maximum depth of cut.")
        form.addRow("Through-cut:", self.contour_stepdown)

        self.pocket_stepdown = _spinbox(d.pocket_stepdown_mm, 0.1, 6.0, step=0.1)
        self.pocket_stepdown.setToolTip(
            "Axial depth per pocket level (hinge recesses). The pocket is cleared "
            "level by level\ninstead of ramping in and taking the whole remaining "
            "depth in one cascade.")
        form.addRow("Pocket:", self.pocket_stepdown)

        # The read-out is the point of this group: the pass count is what the maker
        # is actually deciding, and a silent "1 pass" is the failure we are fixing.
        self._passes_lbl = QLabel("—")
        self._passes_lbl.setWordWrap(True)
        self._passes_lbl.setObjectName("mutedSmallLabel")
        form.addRow("", self._passes_lbl)

        for w in (self.contour_stepdown, self.pocket_stepdown):
            w.valueChanged.connect(self.cam_changed)
        self.cam_changed.connect(self._update_passes_readout)
        lay.addWidget(grp)

    def _update_passes_readout(self) -> None:
        """Show the pass count the active component's blank works out to, so a
        full-depth single pass is visible before Generate rather than after."""
        if not hasattr(self, "_passes_lbl"):
            return
        from guildmodel.core.cam.castle_ops import contour_passes, tab_height_warning
        top_z, skin_z, what = self._active_blank_depth()
        if top_z is None:
            self._passes_lbl.setText("")
            return
        # Tabs cut to the bottom face instead of stopping at the skin, so the stack
        # is deeper — report what the chosen strategy actually cuts (M16).
        if self.hold_strategy.currentIndex() == 1:
            skin_z = 0.0
        # Report the depth that will actually be CUT, not the one requested: the
        # post clamps to the material's and the machine's depth-of-cut ceiling, and
        # a read-out that ignored that would mis-state an over-set project by a
        # whole pass. `capped` marks the difference so the number is explainable.
        step = float(self.contour_stepdown.value())
        ceiling = self._doc_ceiling_mm()
        capped = ceiling is not None and step > ceiling + 1e-9
        if capped:
            step = ceiling
        n = len(contour_passes(top_z, skin_z, step))
        deepest = max(top_z - skin_z if n == 1 else step, 0.0)
        text = (f"{what}: {n} pass{'' if n == 1 else 'es'} "
                f"through {top_z - skin_z:.2f} mm (deepest {deepest:.2f} mm)")
        if capped:
            text += f" — capped at the {ceiling:.2f} mm material/machine limit"
        if n == 1:
            text += " — the whole depth in one bite."
            self._passes_lbl.setStyleSheet("color: #c08a00; font-size: 11px;")
        else:
            self._passes_lbl.setStyleSheet("font-size: 11px;")
        self._passes_lbl.setText(text)

        # A tab can be no taller than the final pass is deep — the pass above has
        # already removed everything higher. Say so rather than silently shortening.
        if hasattr(self, "_tab_hint"):
            if self.hold_strategy.currentIndex() != 1:
                self._tab_hint.setText("")
            else:
                warn = tab_height_warning(contour_passes(top_z, skin_z, step), top_z,
                                          float(self.hold_tab_height.value()))
                self._tab_hint.setText(f"⚠ {warn}" if warn else "")
                self._tab_hint.setStyleSheet(
                    "color: #c08a00; font-size: 11px;" if warn else "font-size: 11px;")

    def _doc_ceiling_mm(self):
        """The lower of the active material's and machine's max depth of cut, or
        None when neither can be resolved (the read-out then shows the request)."""
        caps = []
        try:
            from guildmodel.gui import material_store
            doc = material_store.material(self.material.currentText()).get("max_doc_mm")
            if doc:
                caps.append(float(doc))
        except Exception:
            pass
        try:
            from guildmodel.core.post.machine import load_machine_profile
            idx = self.machine.currentIndex()
            if 0 <= idx < len(self._machine_names):
                caps.append(float(load_machine_profile(
                    self._machine_names[idx], _CONFIG_DIR).max_doc_mm))
        except Exception:
            pass
        return min(caps) if caps else None

    def _active_blank_depth(self):
        """``(top_z, skin_z, label)`` for the through-cut of the active component
        kind, or ``(None, None, "")`` when the kind has no simple blank."""
        kind = getattr(self, "_component_kind", None)
        if kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
            return (self.temple_blank_thickness.value(), self.temple_onion.value(),
                    "Temple profile")
        if kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            return (self.block_blank_thickness.value(), self.block_onion.value(),
                    "Block profile")
        if kind == ComponentKind.FRAME_FRONT:
            # The perimeter's depth passes start at the stock's HIGHEST level, so the
            # pad block counts when it is on (castle_ops: top_z = total_pad_height_mm).
            top = self.blank_thickness.value()
            if self.use_pad_block.isChecked():
                top += self.pad_thickness.value()
            return (top, self.onion_skin.value(), "Frame perimeter")
        return (None, None, "")

    def _build_holding_group(self, lay: QVBoxLayout) -> None:
        """How the part is held until the cut finishes — onion skin or tabs (M16).

        **Universal**, and stored on the active component's own params (each of
        `CastleParams` / `TempleParams` / `BaseCurveBlockParams` carries a
        `HoldingParams`), because it is a property of the part and its blank, not
        of the machine. One set of widgets serves whichever component is active —
        the per-kind `*_params()` snapshot reads them, `set_*_params` restores them.
        """
        d = HoldingParams()
        grp = QGroupBox("Holding  (how the part stays put)")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.hold_strategy = QComboBox()
        self.hold_strategy.addItems(["Onion skin", "Hold-down tabs"])
        self.hold_strategy.setToolTip(
            "Onion skin: stop the through-cut above the bottom face and break the "
            "wafer by hand.\nHold-down tabs: cut through to the bottom face, leaving "
            "a few uncut bridges to cut off.\nThese are alternatives — a tabbed cut "
            "has no skin, and a skinned cut needs no tabs.")
        form.addRow("Strategy:", self.hold_strategy)

        self.hold_tab_count = QSpinBox()
        self.hold_tab_count.setRange(0, 16)
        self.hold_tab_count.setValue(d.tab_count)
        self.hold_tab_count.setSuffix("  tabs")
        form.addRow("Tab count:", self.hold_tab_count)
        self.hold_tab_width = _spinbox(d.tab_width_mm, 0.5, 12.0, step=0.5, decimals=2)
        form.addRow("Tab width:", self.hold_tab_width)
        self.hold_tab_height = _spinbox(d.tab_height_mm, 0.2, 6.0, step=0.1, decimals=2)
        self.hold_tab_height.setToolTip(
            "Height of each uncut bridge, from the bottom face up.\nCannot exceed "
            "the depth of the final pass — everything above it is already cut away.")
        form.addRow("Tab height:", self.hold_tab_height)

        self._tab_hint = QLabel("")
        self._tab_hint.setWordWrap(True)
        self._tab_hint.setObjectName("mutedSmallLabel")
        form.addRow("", self._tab_hint)

        self._tab_rows = (self.hold_tab_count, self.hold_tab_width, self.hold_tab_height)
        self.hold_strategy.currentIndexChanged.connect(self._on_hold_strategy_changed)
        for w in self._tab_rows:
            w.valueChanged.connect(self.cam_changed)
        self._on_hold_strategy_changed()
        lay.addWidget(grp)

    def _on_hold_strategy_changed(self, *_a) -> None:
        """Grey the tab fields out on the skin strategy — they cut nothing there."""
        tabs = self.hold_strategy.currentIndex() == 1
        for w in getattr(self, "_tab_rows", ()):
            w.setEnabled(tabs)
        self.cam_changed.emit()

    def holding_params(self) -> HoldingParams:
        return HoldingParams(
            strategy="tabs" if self.hold_strategy.currentIndex() == 1 else "skin",
            tab_count=self.hold_tab_count.value(),
            tab_width_mm=self.hold_tab_width.value(),
            tab_height_mm=self.hold_tab_height.value(),
        )

    def set_holding_params(self, h: HoldingParams) -> None:
        self.hold_strategy.blockSignals(True)
        self.hold_strategy.setCurrentIndex(1 if h.strategy == "tabs" else 0)
        self.hold_strategy.blockSignals(False)
        for w, v in ((self.hold_tab_count, h.tab_count), (self.hold_tab_width, h.tab_width_mm),
                     (self.hold_tab_height, h.tab_height_mm)):
            w.blockSignals(True); w.setValue(v); w.blockSignals(False)
        for w in self._tab_rows:
            w.setEnabled(h.strategy == "tabs")

    # The operations each component kind can emit, in machining order. Superset:
    # an op whose geometry is absent (no HINGE layer, no decorative holes) simply
    # never appears in the program, and its checkbox is harmless.
    _KIND_OPS: dict = {
        "frame_front": ("Hinge Pockets", "Rough Relief", "Fine Relief",
                        "Features", "Eyewires", "Holes", "Lens Groove",
                        "Perimeter"),
        "temple": ("Hinge Pockets", "Engraving", "Holes", "Temple Profile"),
        "block": ("Drill Holes", "Block Profile"),
    }
    # Ops that release the part from the blank — switching one off is a deliberate
    # "leave it in the stock", worth saying out loud rather than discovering later.
    _RELEASING_OPS = {"Perimeter", "Temple Profile", "Block Profile"}

    def _build_operations_group(self, lay: QVBoxLayout) -> None:
        """Per-operation enable/skip (M16) — **universal**, kind-aware.

        The program was all-or-nothing: `op_tools` chose a tool per operation but
        nothing could leave one out. Cutting a job in stages (pocket and engrave
        now, release the part after the inserts go in) or re-running a single
        operation after a tool change both needed this.
        """
        grp = QGroupBox("Operations  (uncheck to skip)")
        self._operations_group = grp
        v = QVBoxLayout(grp)
        self.op_checks: dict[str, QCheckBox] = {}
        for name in dict.fromkeys(
                n for names in self._KIND_OPS.values() for n in names):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.toggled.connect(self._on_op_toggled)
            v.addWidget(cb)
            self.op_checks[name] = cb
        self._ops_hint = QLabel("")
        self._ops_hint.setWordWrap(True)
        self._ops_hint.setObjectName("mutedSmallLabel")
        v.addWidget(self._ops_hint)
        lay.addWidget(grp)

    def _on_op_toggled(self, *_a) -> None:
        self._refresh_operations_hint()
        self.cam_changed.emit()

    def _visible_op_names(self) -> tuple:
        kind = getattr(self, "_component_kind", None)
        if kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
            return self._KIND_OPS["temple"]
        if kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            return self._KIND_OPS["block"]
        return self._KIND_OPS["frame_front"]

    def _refresh_operations_hint(self) -> None:
        """Show only this kind's operations, and warn when the part is left in the
        blank or nothing is cut at all."""
        if not hasattr(self, "_ops_hint"):
            return
        shown = self._visible_op_names()
        for name, cb in self.op_checks.items():
            cb.setVisible(name in shown)
        off = [n for n in shown if not self.op_checks[n].isChecked()]
        held = [n for n in off if n in self._RELEASING_OPS]
        if len(off) == len(shown):
            self._ops_hint.setText("Nothing is enabled — the program would be empty.")
            self._ops_hint.setStyleSheet("color: #b34; font-size: 11px;")
        elif held:
            self._ops_hint.setText(
                f"{held[0]} is off — the part stays attached to the blank.")
            self._ops_hint.setStyleSheet("color: #c08a00; font-size: 11px;")
        elif off:
            self._ops_hint.setText(f"Skipping: {', '.join(off)}.")
            self._ops_hint.setStyleSheet("font-size: 11px;")
        else:
            self._ops_hint.setText("")

    def _build_overrides_group(self, lay: QVBoxLayout) -> None:
        """Per-component departures from the project-global CAM params (M16).

        The everyday case this exists for: the base-curve forming blocks are
        **acetal** while the frame and temples are acetate, and acetal's
        depth-of-cut ceiling is half. Before this the block inherited the frame's
        depth per pass and only its feeds re-read its own material.
        """
        grp = QGroupBox("This component only  (overrides)")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ov_material = QComboBox()
        self.ov_material.addItem("(project material)")
        self.ov_material.addItems(self._material_names())
        self.ov_material.setToolTip(
            "Cut this component from a different material than the rest of the "
            "project.\nIts depth per pass is re-clamped through that material's own "
            "maximum depth of cut.")
        form.addRow("Material:", self.ov_material)

        # 0 = inherit, matching the feed/spindle override convention already on the
        # Cut tab — one idiom for "leave it alone" across the whole panel.
        self.ov_stepdown = _spinbox(0.0, 0.0, 6.0, step=0.1)
        self.ov_stepdown.setSpecialValueText("(project)")
        form.addRow("Depth per pass:", self.ov_stepdown)
        self.ov_feed = _spinbox(0.0, 0.0, 5000.0, step=50.0, decimals=0, suffix=" mm/min")
        self.ov_feed.setSpecialValueText("(project)")
        form.addRow("Feed:", self.ov_feed)
        self.ov_spindle = QSpinBox()
        self.ov_spindle.setRange(0, 60000)
        self.ov_spindle.setSingleStep(500)
        self.ov_spindle.setSuffix(" RPM")
        self.ov_spindle.setSpecialValueText("(project)")
        form.addRow("Spindle:", self.ov_spindle)

        self.ov_material.currentIndexChanged.connect(self.cam_changed)
        for w in (self.ov_stepdown, self.ov_feed, self.ov_spindle):
            w.valueChanged.connect(self.cam_changed)
        lay.addWidget(grp)

    def _material_names(self) -> list:
        try:
            from guildmodel.gui import material_store
            return list(material_store.names())
        except Exception:
            return ["acetate", "acetal", "horn"]

    def cam_overrides(self) -> ComponentCamOverrides:
        """The active component's overrides (0 / "(project material)" = inherit)."""
        def _opt(v):
            return v or None
        return ComponentCamOverrides(
            material=(self.ov_material.currentText()
                      if self.ov_material.currentIndex() > 0 else None),
            contour_stepdown_mm=_opt(self.ov_stepdown.value()),
            feed_rate_mmpm=_opt(self.ov_feed.value()),
            spindle_rpm=_opt(int(self.ov_spindle.value())),
        )

    def set_cam_overrides(self, ov: ComponentCamOverrides | None) -> None:
        ov = ov or ComponentCamOverrides()
        self.ov_material.blockSignals(True)
        idx = self.ov_material.findText(ov.material) if ov.material else 0
        self.ov_material.setCurrentIndex(idx if idx >= 0 else 0)
        self.ov_material.blockSignals(False)
        for w, v in ((self.ov_stepdown, ov.contour_stepdown_mm or 0.0),
                     (self.ov_feed, ov.feed_rate_mmpm or 0.0),
                     (self.ov_spindle, ov.spindle_rpm or 0)):
            w.blockSignals(True); w.setValue(v); w.blockSignals(False)

    def _build_strategy_group(self, lay: QVBoxLayout) -> None:
        """Frame-posterior *relief* strategy — the surfacing passes that only a
        castle has. Frame-only (set_component_kind). The depth-per-pass and lead-in
        controls that apply to every kind live in `_build_depth_group` (Cut tab) and
        `_build_leadin_group` below."""
        d = CastleCamParams()
        grp = QGroupBox("Relief Strategy  (time / finish)")
        self._strategy_group = grp
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.relief_stepover = _spinbox(d.relief_stepover_mm, 0.2, 3.0, step=0.05)
        self.relief_stepover.setToolTip(
            "Spacing between relief passes (lower = finer surface, longer cut).")
        form.addRow("Relief stepover:", self.relief_stepover)

        self.rough_axial_stock = _spinbox(d.rough_axial_stock_mm, 0.0, 5.0, step=0.1)
        self.rough_axial_stock.setToolTip("Axial stock the rough pass leaves for the fine pass.")
        form.addRow("Rough axial stock:", self.rough_axial_stock)

        for w in (self.relief_stepover, self.rough_axial_stock):
            w.valueChanged.connect(self.cam_changed)
        lay.addWidget(grp)

    def _build_leadin_group(self, lay: QVBoxLayout) -> None:
        """Through-cut lead-in + arc output. **Universal**: both already applied to
        every component kind at post time — they were simply invisible on a temple
        or base-curve block, so those parts inherited whatever the frame was set to."""
        d = CastleCamParams()
        grp = QGroupBox("Through-cut lead-in & output")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cut_direction = QComboBox()
        self.cut_direction.addItems(["Climb", "Conventional"])
        self.cut_direction.setToolTip(
            "Climb (default): the chip thins to zero — the cleaner wall on acetate, "
            "and what the\nreference program cuts. Conventional reverses every "
            "contour: the choice on a machine\nwith backlash it cannot take out, "
            "where climb milling pulls the cutter into the work.")
        form.addRow("Cut direction:", self.cut_direction)

        self.contour_lead_in = QComboBox()
        self.contour_lead_in.addItems(["Ramp", "Plunge"])
        self.contour_lead_in.setToolTip(
            "How each through-cut pass enters the material.\nRamp: descend over a "
            "short lead-in along the contour — no slot-plunge.\nPlunge: drop "
            "straight to depth and cut one clean lap — shorter, and fine for a "
            "small tool in acetate.")
        form.addRow("Lead-in:", self.contour_lead_in)

        self.contour_ramp_angle = _spinbox(
            d.contour_ramp_angle_deg, 0.0, 90.0, step=1.0, decimals=1, suffix="°")
        self.contour_ramp_angle.setToolTip(
            "Lead-in ramp angle for through-cuts (steeper = shorter lead-in, faster).\n"
            "0 ramps the whole lap — to skip the ramp entirely, set Lead-in to Plunge.")
        form.addRow("Contour ramp angle:", self.contour_ramp_angle)

        self.arc_tolerance = _spinbox(
            d.arc_tolerance_mm, 0.0, 0.2, step=0.005, decimals=3)
        self.arc_tolerance.setToolTip(
            "Arc-fit tolerance for G2/G3 output (0 = linearized G1).")
        form.addRow("Arc tolerance:", self.arc_tolerance)

        self.contour_lead_in.currentIndexChanged.connect(self._on_lead_in_changed)
        self.cut_direction.currentIndexChanged.connect(self.cam_changed)
        for w in (self.contour_ramp_angle, self.arc_tolerance):
            w.valueChanged.connect(self.cam_changed)
        lay.addWidget(grp)

    def _on_lead_in_changed(self, *_a) -> None:
        """The ramp angle means nothing on a plunge entry — grey it out."""
        self.contour_ramp_angle.setEnabled(self.contour_lead_in.currentIndex() == 0)
        self.cam_changed.emit()

    def _build_fallback_group(self, lay: QVBoxLayout) -> None:
        """Legacy profile cut for frame DXFs without SCULPT zones. Frame-only."""
        grp = QGroupBox("Profile fallback  (no SCULPT)")
        self._fallback_group = grp
        fb = QFormLayout(grp)
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

        for w in (self.tool_profile, self.stepdown_profile,
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

    def stock_definition(self) -> StockDefinition:
        """Just the Stock tab. Split out of `castle_params` because the zone
        limits need the stock without the cost — and without the recursion — of
        snapshotting the whole castle."""
        return StockDefinition(
            blank_length_mm=self.blank_length.value(),
            blank_width_mm=self.blank_width.value(),
            blank_thickness_mm=self.blank_thickness.value(),
            pad_block_length_mm=self.pad_length.value(),
            pad_block_width_mm=self.pad_width.value(),
            pad_block_thickness_mm=self.pad_thickness.value(),
            use_pad_block=self.use_pad_block.isChecked(),
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
            zone_height_overrides=dict(self._zone_overrides),
            footing=footing,
            hinge_pocket_depth_mm=self.hinge_pocket_depth.value(),
            stock=self.stock_definition(),
            onion_skin_mm=self.onion_skin.value(),
            hand_finishing_allowance_mm=self.hand_allowance.value(),
            holding=self.holding_params(),
            pad_splay=PadSplayParams(
                enabled=self.splay_enable.isChecked(),
                run_mm=self.splay_run.value(),
                crest_deviation_center_mm=self.splay_dev_center.value(),
                crest_deviation_end_mm=self.splay_dev_end.value(),
                toric=self.splay_toric.isChecked(),
                angle_center_deg=self.splay_angle_center.value(),
                angle_middle_deg=self.splay_angle_middle.value(),
                angle_end_deg=self.splay_angle_end.value(),
                anterior_clamp_mm=self.splay_clamp.value(),
                feather_mm=self.splay_feather.value(),
                crest_blend_mm=self.splay_blend.value(),
                non_contiguous=self.splay_noncontig.isChecked(),
                gap_mm=self.splay_gap.value(),
            ),
            eyewire_bezel=EyewireBezelParams(
                enabled=self.bezel_enable.isChecked(),
                width_mm=self.bezel_width.value(),
                angle_deg=self.bezel_angle.value(),
                anterior_clamp_mm=self.bezel_clamp.value(),
                face=("posterior", "anterior", "both")[self.bezel_face.currentIndex()],
                anterior_width_mm=self.bezel_ant_width.value(),
                anterior_angle_deg=self.bezel_ant_angle.value(),
            ),
            edge_features=self.edge_features(),
            bridge_relief=BridgeReliefParams(
                enabled=self.bridge_relief_enable.isChecked(),
                width_mm=self.bridge_relief_width.value(),
                depth_mm=self.bridge_relief_depth.value(),
                taper_angle_deg=self.bridge_relief_taper.value(),
                exterior_radius_mm=self.bridge_relief_rext.value(),
                interior_radius_mm=self.bridge_relief_rint.value(),
                anterior_clamp_mm=self.bridge_relief_clamp.value(),
            ),
            lens_groove=LensGrooveParams(
                enabled=self.groove_enable.isChecked(),
                anterior_offset_mm=self.groove_offset.value(),
                depth_mm=self.groove_depth.value(),
                width_mm=self.groove_width.value(),
                tool=self.groove_tool.currentText() or "groove_drageoir",
            ),
        )

    def set_castle_params(self, c: CastleParams) -> None:
        """Restore the Castle / Stock tabs from a CastleParams (opening a .gmodel)."""
        z = c.zones
        self._zone_overrides = dict(c.zone_height_overrides)
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
        pairs += [
            (self.splay_run, c.pad_splay.run_mm),
            (self.splay_dev_center, c.pad_splay.crest_deviation_center_mm),
            (self.splay_dev_end, c.pad_splay.crest_deviation_end_mm),
            (self.splay_angle_center, c.pad_splay.angle_center_deg),
            (self.splay_angle_middle, c.pad_splay.angle_middle_deg),
            (self.splay_angle_end, c.pad_splay.angle_end_deg),
            (self.splay_clamp, c.pad_splay.anterior_clamp_mm),
            (self.splay_feather, c.pad_splay.feather_mm),
            (self.splay_blend, c.pad_splay.crest_blend_mm),
            (self.splay_gap, c.pad_splay.gap_mm),
            (self.bezel_width, c.eyewire_bezel.width_mm),
            (self.bezel_angle, c.eyewire_bezel.angle_deg),
            (self.bezel_clamp, c.eyewire_bezel.anterior_clamp_mm),
            (self.bezel_ant_width, c.eyewire_bezel.anterior_width_mm),
            (self.bezel_ant_angle, c.eyewire_bezel.anterior_angle_deg),
            (self.bridge_relief_width, c.bridge_relief.width_mm),
            (self.bridge_relief_depth, c.bridge_relief.depth_mm),
            (self.bridge_relief_taper, c.bridge_relief.taper_angle_deg),
            (self.bridge_relief_rext, c.bridge_relief.exterior_radius_mm),
            (self.bridge_relief_rint, c.bridge_relief.interior_radius_mm),
            (self.bridge_relief_clamp, c.bridge_relief.anterior_clamp_mm),
            (self.groove_offset, c.lens_groove.anterior_offset_mm),
            (self.groove_depth, c.lens_groove.depth_mm),
            (self.groove_width, c.lens_groove.width_mm),
        ]
        for sb, val in pairs:
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)
        for cb, val in ((self.use_pad_block, c.stock.use_pad_block),
                        (self.splay_enable, c.pad_splay.enabled),
                        (self.splay_toric, c.pad_splay.toric),
                        (self.splay_noncontig, c.pad_splay.non_contiguous),
                        (self.bezel_enable, c.eyewire_bezel.enabled),
                        (self.bridge_relief_enable, c.bridge_relief.enabled),
                        (self.groove_enable, c.lens_groove.enabled)):
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
        self.groove_tool.blockSignals(True)
        gi = self.groove_tool.findText(c.lens_groove.tool)
        if gi >= 0:
            self.groove_tool.setCurrentIndex(gi)
        self.groove_tool.blockSignals(False)
        self._on_pad_block_toggled(c.stock.use_pad_block)
        self._on_splay_toggled(c.pad_splay.enabled)
        self._on_bezel_toggled(c.eyewire_bezel.enabled)
        self._on_bridge_relief_toggled(c.bridge_relief.enabled)
        self._refresh_bridge_relief_shape()
        self._on_groove_toggled(c.lens_groove.enabled)
        self._refresh_zone_list()      # show the restored per-zone overrides
        self._update_groove_angle()
        self.bezel_face.blockSignals(True)
        self.bezel_face.setCurrentIndex(
            ("posterior", "anterior", "both").index(c.eyewire_bezel.face))
        self.bezel_face.blockSignals(False)
        self._on_bezel_toggled()
        self.set_edge_features(c.edge_features)          # M17 chamfers / fillets
        self.set_holding_params(c.holding)
        self._update_passes_readout()  # the restored stock drives the pass count
        self.castle_changed.emit()
        self.stock_changed.emit()

    def cam_params(self) -> CastleCamParams:
        """Snapshot the CAM tab into the persisted CastleCamParams schema.

        Updates the params last loaded via `set_cam_params` rather than building a
        fresh model. `CastleCamParams` carries a dozen fields with no widget —
        `pocket_stepover_mm`, `ramp_step_mm`, `relief_link_gap_mm`, the link-retract
        and screw-keepout settings — and constructing a new model reset every one of
        them to the schema default. Since `_build_project_schema` saves this snapshot
        back into the project, opening a `.gmodel` with any of those tuned and
        pressing Save silently discarded the tuning. Anything the panel does not own,
        the panel does not touch.
        """
        idx = self.machine.currentIndex()
        machine_name = self._machine_names[idx] if 0 <= idx < len(self._machine_names) else "guild_cnc"

        def _opt(v: float) -> Optional[float]:
            return v if v > 0 else None

        op_tools = {}
        for op, cb in getattr(self, "op_tool_combos", {}).items():
            txt = cb.currentText()
            if txt and txt != _SAME_AS_GLOBAL:
                op_tools[op] = txt

        base = getattr(self, "_cam_base", None) or CastleCamParams()
        return base.model_copy(update=dict(
            tool_name=self.cam_tool.currentText(),
            machine_name=machine_name,
            op_tools=op_tools,
            program_zero=self._program_zero(),
            relief_stepover_mm=self.relief_stepover.value(),
            contour_stepdown_mm=self.contour_stepdown.value(),
            pocket_stepdown_mm=self.pocket_stepdown.value(),
            rough_axial_stock_mm=self.rough_axial_stock.value(),
            contour_ramp_angle_deg=self.contour_ramp_angle.value(),
            contour_lead_in="plunge" if self.contour_lead_in.currentIndex() else "ramp",
            cut_direction="conventional" if self.cut_direction.currentIndex() else "climb",
            op_enabled={n: False for n, cb in self.op_checks.items()
                        if not cb.isChecked()},
            arc_tolerance_mm=self.arc_tolerance.value(),
            feed_rate_mmpm=_opt(self.feed_override.value()),
            plunge_rate_mmpm=_opt(self.plunge_override.value()),
            spindle_rpm=int(self.spindle_override.value()) or None,
            safe_z_clearance_mm=self.safe_z_clearance.value(),
            hold_down_height_mm=self.hold_down_height.value(),
        ))

    def set_cam_params(self, cp: CastleCamParams) -> None:
        """Restore the CAM tab from a persisted CastleCamParams (prefs/project)."""
        # Keep the whole model as the base `cam_params` updates, so the fields with
        # no widget survive the round-trip instead of reverting to schema defaults.
        self._cam_base = cp
        if cp.tool_name:
            self.cam_tool.setCurrentText(cp.tool_name)
        for op, cb in getattr(self, "op_tool_combos", {}).items():
            name = cp.op_tools.get(op) or DEFAULT_OP_TOOLS.get(op)   # M11 fine-tool default
            cb.blockSignals(True)
            cb.setCurrentText(name if name and cb.findText(name) >= 0 else _SAME_AS_GLOBAL)
            cb.blockSignals(False)
        if cp.machine_name in self._machine_names:
            self.machine.setCurrentIndex(self._machine_names.index(cp.machine_name))
        self._set_program_zero(cp.program_zero)
        self.relief_stepover.setValue(cp.relief_stepover_mm)
        self.contour_stepdown.setValue(cp.contour_stepdown_mm)
        self.pocket_stepdown.setValue(cp.pocket_stepdown_mm)
        self.rough_axial_stock.setValue(cp.rough_axial_stock_mm)
        self.contour_ramp_angle.setValue(cp.contour_ramp_angle_deg)
        self.contour_lead_in.blockSignals(True)
        self.contour_lead_in.setCurrentIndex(1 if cp.contour_lead_in == "plunge" else 0)
        self.contour_lead_in.blockSignals(False)
        self.contour_ramp_angle.setEnabled(cp.contour_lead_in != "plunge")
        self.cut_direction.blockSignals(True)
        self.cut_direction.setCurrentIndex(1 if cp.cut_direction == "conventional" else 0)
        self.cut_direction.blockSignals(False)
        for name, cb in self.op_checks.items():
            cb.blockSignals(True)
            cb.setChecked(cp.is_op_enabled(name))
            cb.blockSignals(False)
        self._refresh_operations_hint()
        self.arc_tolerance.setValue(cp.arc_tolerance_mm)
        self.feed_override.setValue(cp.feed_rate_mmpm or 0.0)
        self.plunge_override.setValue(cp.plunge_rate_mmpm or 0.0)
        self.spindle_override.setValue(cp.spindle_rpm or 0)
        self.safe_z_clearance.setValue(cp.safe_z_clearance_mm)
        self.hold_down_height.setValue(cp.hold_down_height_mm)

    def temple_params(self) -> TempleParams:
        """Temple component params from the Temple tab (BUILDPLAN M7.3)."""
        return TempleParams(
            blank_length_mm=self.temple_blank_length.value(),
            blank_width_mm=self.temple_blank_width.value(),
            blank_thickness_mm=self.temple_blank_thickness.value(),
            engrave_depth_mm=self.temple_engrave_depth.value(),
            engrave_stepdown_mm=self.temple_engrave_stepdown.value(),
            engrave_tool=self.temple_engrave_tool.currentText(),
            engrave_centerline=self.temple_engrave_centerline.isChecked(),
            hinge_tool=self.temple_hinge_tool.currentText(),
            profile_tool=self.temple_profile_tool.currentText(),
            snap_to_blank_end=self.temple_snap_blank.isChecked(),
            stock_side=self.temple_stock_side.currentText(),
            onion_skin_mm=self.temple_onion.value(),
            hand_finishing_allowance_mm=self.temple_allowance.value(),
            holding=self.holding_params(),
            fixture_zone=self._temple_fixture_zone,
        )

    def set_temple_params(self, t: TempleParams) -> None:
        """Restore the Temple tab from a TempleParams (component activation)."""
        self._temple_fixture_zone = t.fixture_zone
        for sb, val in (
            (self.temple_blank_length, t.blank_length_mm),
            (self.temple_blank_width, t.blank_width_mm),
            (self.temple_blank_thickness, t.blank_thickness_mm),
            (self.temple_engrave_depth, t.engrave_depth_mm),
            (self.temple_engrave_stepdown, t.engrave_stepdown_mm),
            (self.temple_onion, t.onion_skin_mm),
            (self.temple_allowance, t.hand_finishing_allowance_mm),
        ):
            sb.blockSignals(True); sb.setValue(val); sb.blockSignals(False)
        self.set_holding_params(t.holding)
        self._update_passes_readout()        # the temple blank drives the pass count
        for cb, val in ((self.temple_engrave_tool, t.engrave_tool),
                        (self.temple_hinge_tool, t.hinge_tool),
                        (self.temple_profile_tool, t.profile_tool),
                        (self.temple_stock_side, t.stock_side)):
            if cb.findText(val) >= 0:
                cb.blockSignals(True); cb.setCurrentText(val); cb.blockSignals(False)
        self.temple_engrave_centerline.blockSignals(True)
        self.temple_engrave_centerline.setChecked(t.engrave_centerline)
        self.temple_engrave_centerline.blockSignals(False)
        self.temple_snap_blank.blockSignals(True)
        self.temple_snap_blank.setChecked(t.snap_to_blank_end)
        self.temple_snap_blank.blockSignals(False)
        self.temple_stock_side.setEnabled(t.snap_to_blank_end)

    def block_params(self) -> BaseCurveBlockParams:
        """Base-curve forming-block params from the Base Curve tab (BUILDPLAN M7.3)."""
        return BaseCurveBlockParams(
            blank_length_mm=self.block_blank_length.value(),
            blank_width_mm=self.block_blank_width.value(),
            blank_thickness_mm=self.block_blank_thickness.value(),
            material=self._block_material,
            profile_tool=self.block_profile_tool.currentText(),
            onion_skin_mm=self.block_onion.value(),
            hand_finishing_allowance_mm=self.block_allowance.value(),
            holding=self.holding_params(),
            hole_count=self.block_hole_count.value(),
            hole_spacing_mm=self.block_hole_spacing.value(),
            hole_diameter_mm=self.block_hole_diameter.value(),
            hole_arrangement=self.block_hole_arrangement.currentText(),
            drill_tool=self.block_drill_tool.currentText(),
            peck_depth_mm=self.block_peck_depth.value(),
            drill_breakthrough_mm=self.block_breakthrough.value(),
            fixture_zone=self._block_fixture_zone,
        )

    def set_block_params(self, b: BaseCurveBlockParams) -> None:
        """Restore the Base Curve tab from a BaseCurveBlockParams (activation)."""
        self._block_fixture_zone = b.fixture_zone
        self._block_material = b.material
        for sb, val in (
            (self.block_blank_length, b.blank_length_mm),
            (self.block_blank_width, b.blank_width_mm),
            (self.block_blank_thickness, b.blank_thickness_mm),
            (self.block_onion, b.onion_skin_mm),
            (self.block_allowance, b.hand_finishing_allowance_mm),
            (self.block_hole_spacing, b.hole_spacing_mm),
            (self.block_hole_diameter, b.hole_diameter_mm),
            (self.block_peck_depth, b.peck_depth_mm),
            (self.block_breakthrough, b.drill_breakthrough_mm),
        ):
            sb.blockSignals(True); sb.setValue(val); sb.blockSignals(False)
        self.block_hole_count.blockSignals(True)
        self.block_hole_count.setValue(b.hole_count)
        self.block_hole_count.blockSignals(False)
        self.set_holding_params(b.holding)
        self._update_passes_readout()        # the block blank drives the pass count
        for cb, val in ((self.block_profile_tool, b.profile_tool),
                        (self.block_hole_arrangement, b.hole_arrangement),
                        (self.block_drill_tool, b.drill_tool)):
            if cb.findText(val) >= 0:
                cb.blockSignals(True); cb.setCurrentText(val); cb.blockSignals(False)

    # ------------------------------------------------------------------ material

    def material_name(self) -> str:
        """The project's selected material (the Cut tab's combo)."""
        return self.material.currentText()

    def effective_cam_params(self) -> CastleCamParams:
        """`cam_params()` with the ACTIVE component's overrides applied (M16).

        Every single-component posting path should call this rather than
        `cam_params()`, so a base-curve block in acetal is not cut at the acetate
        frame's depth per pass. The material itself is not a CAM field — it selects
        the preset the post clamps against; see `effective_material_name`.
        """
        return self.cam_overrides().apply(self.cam_params())

    def effective_material_name(self) -> str:
        """The material this component is actually cut from — its own override if
        it has one, else the project's."""
        return self.cam_overrides().material or self.material_name()

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
