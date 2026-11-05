"""The Embossing section: the maker's own meshes, embossed onto or debossed
into a part (BUILDPLAN M22 §7.4 on the front; the temple since 2026-11-02).

A list and one editor, as Edge Features. The file, the host surface and the
snap belong to the window (it has the model and the dialogs); the group keeps
the records and says when one moved. The dock carries one of these on the
Model tab for the front and one on the Temple tab for a temple, and forwards
their requests as its own signals.

"Sculpt" stays the name in the code and the files; on the screen a SCULPT is
the posterior's scalloping, so this is *Embossing* and each record a *mesh*.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget)

from guildmodel.core.project.schema import SculptFeature


class EmbossingGroup(QWidget):
    """``group = EmbossingGroup("front")``; `host` is ``front`` or ``temple``."""

    #: The section header's explanation.
    TIP = ("Your own meshes, embossed or debossed. Drop an .stl on the model in "
            "the 3D view, or add one here. GuildModel repairs it, finds its flat "
            "back and seats it on the part under the cursor; Move on the part "
            "drags it over the surface. Emboss adds the relief standing out; "
            "Deboss turns it over and imprints it. A mesh on the back is machined "
            "by the posterior program, one on the front by the anterior program "
            "of a two-sided job.")

    changed = Signal()                     # a record's own fields: the model rebuilds
    add_requested = Signal()               # "+ Add STL…"
    mount_changed = Signal(int, bool)      # row; True when the face moved (re-read the host)
    resnap_requested = Signal(int)         # row: read the host again at the stored point
    handle_requested = Signal(int, bool)   # row, on: the drag in the 3D view

    def __init__(self, host: str = "front", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from guildmodel.gui.widgets.params_panel import _slider
        self.host = host
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        self.sculpt_list = QListWidget()
        self.sculpt_list.setFixedHeight(96)
        self.sculpt_list.currentRowChanged.connect(self._on_sculpt_selected)
        v.addWidget(self.sculpt_list)

        row = QHBoxLayout()
        add = QPushButton("+ Add STL…")
        add.clicked.connect(self.add_requested)
        row.addWidget(add)
        for text, slot in (("Duplicate", self._on_sculpt_duplicate),
                           ("Remove", self._on_sculpt_remove)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        v.addLayout(row)

        self._sculpt_editor = QWidget()
        form = QFormLayout(self._sculpt_editor)
        form.setContentsMargins(8, 4, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.sc_enabled = QCheckBox("Enabled")
        self.sc_enabled.setChecked(True)
        form.addRow("", self.sc_enabled)
        self.sc_label = QLineEdit()
        self.sc_label.setPlaceholderText("Crest")
        form.addRow("Name:", self.sc_label)
        self.sc_face = QComboBox()
        if host == "temple":
            self.sc_face.addItems(["Hinge face (top)", "Outer face (bottom)", "Edge"])
            self.sc_face.setToolTip(
                "Where the mesh's flat back sits. A deboss on the hinge face is cut "
                "by the temple program; one on the outer face by the anterior setup "
                "of a two-sided job; one on the edge is modeled only.")
        else:
            self.sc_face.addItems(["Posterior (back)", "Anterior (front)", "Rim (outline wall)"])
            self.sc_face.setToolTip(
                "Where the mesh's flat back sits. A mesh on the back is cut by the "
                "posterior program; one on the front by the anterior program of a "
                "two-sided job; one on the rim is modeled only.")
        form.addRow("Snap to:", self.sc_face)
        self.sc_op = QComboBox()
        self.sc_op.addItems(["Emboss (add)", "Deboss (cut)"])
        self.sc_op.setToolTip(
            "Emboss adds the mesh to the part, its relief standing out. Deboss "
            "cuts the mesh out of the part: with Flip on, the relief is turned "
            "into the surface and imprinted, as a stamp.")
        form.addRow("Operation:", self.sc_op)
        self.sc_flip = QCheckBox("Flip: relief into the part")
        self.sc_flip.setToolTip(
            "Turn the mesh over, its flat back up and its relief into the "
            "surface. Sink is then the depth of the imprint. On by default for a "
            "Deboss; off for an Emboss, whose back sits on the surface.")
        form.addRow("", self.sc_flip)
        self.sc_size = _slider(15.0, 0.5, 200.0, step=0.5, decimals=1, suffix=" mm")
        self.sc_size.setToolTip(
            "The longest side of the mesh as placed. A mesh wider than 15 mm "
            "is scaled to 15 mm when it is added; Scale shows the same thing as a "
            "factor of the file.")
        form.addRow("Size:", self.sc_size)
        self.sc_scale = _slider(1.0, 0.01, 10.0, step=0.05, decimals=3, suffix="×")
        self.sc_scale.setToolTip("The mesh's size as a factor of the file, about its back.")
        form.addRow("Scale:", self.sc_scale)
        self.sc_spin = _slider(0.0, -180.0, 180.0, step=1.0, decimals=0, suffix="°")
        self.sc_spin.setToolTip("Turn the mesh about the surface it sits on.")
        form.addRow("Spin:", self.sc_spin)
        self.sc_overlap = _slider(0.05, 0.0, 3.0, step=0.05, decimals=2, suffix=" mm")
        self.sc_overlap.setToolTip(
            "How deep the mesh goes into the part, measured at its leading face. "
            "Relief out: the back, sunk so the two are one body (the snap sets it to "
            "the sag under the back plus 0.05 mm; a back across a terrace step needs "
            "the step). Flipped: the crown, the depth of the imprint. The range runs "
            "to the relief's own height.")
        form.addRow("Sink:", self.sc_overlap)
        self.sc_flush = QCheckBox("Flush (coplanar on a flat surface)")
        form.addRow("", self.sc_flush)
        self.sc_mirror = QCheckBox("Mirror to the other side")
        self.sc_mirror.setToolTip("The twin across the center line, derived and never stored.")
        form.addRow("", self.sc_mirror)
        if host == "temple":
            # a temple has no center line: its other side is the other
            # temple, which the link copies (hidden, not grayed)
            self.sc_mirror.setVisible(False)
            label = form.labelForField(self.sc_mirror)
            if label is not None:
                label.setVisible(False)
        btns = QHBoxLayout()
        self.sc_resnap = QPushButton("Re-snap")
        self.sc_resnap.setToolTip("Read the part again under the mesh and sit it there.")
        self.sc_resnap.clicked.connect(self._on_sculpt_resnap)
        btns.addWidget(self.sc_resnap)
        self.sc_handle = QPushButton("Move on the part")
        self.sc_handle.setCheckable(True)
        self.sc_handle.setToolTip(
            "Drag the mesh over the part in the 3D view: it slides on the "
            "surface, its back seated to the surface under the cursor, and the "
            "model rebuilds when you let go. Spin and Size stay yours; Sink is read "
            "again from the surface there, never less than you set.")
        self.sc_handle.toggled.connect(self._on_sculpt_handle_toggled)
        btns.addWidget(self.sc_handle)
        form.addRow("", btns)
        self.sc_info = QLabel("")
        self.sc_info.setWordWrap(True)
        self.sc_info.setObjectName("hintLabel")
        form.addRow("", self.sc_info)
        v.addWidget(self._sculpt_editor)

        self._sculpts: list[SculptFeature] = []
        self._sculpt_loading = False
        for chk in (self.sc_enabled, self.sc_mirror):
            chk.toggled.connect(self._on_sculpt_edited)
        self.sc_label.textEdited.connect(self._on_sculpt_edited)
        self.sc_op.currentIndexChanged.connect(self._on_sculpt_edited)
        self.sc_face.currentIndexChanged.connect(lambda *_: self._on_sculpt_mount_edited(True))
        for w in (self.sc_scale, self.sc_spin, self.sc_overlap):
            w.valueChanged.connect(lambda *_: self._on_sculpt_mount_edited(False))
        self.sc_size.valueChanged.connect(self._on_sculpt_size_edited)
        self.sc_flush.toggled.connect(lambda *_: self._on_sculpt_mount_edited(False))
        self.sc_flip.toggled.connect(lambda *_: self._on_sculpt_mount_edited(False))
        if host == "temple":
            hint = QLabel("A deboss is cut, on the hinge face by the temple program and on "
                          "the outer face by a two-sided job's anterior setup. An emboss "
                          "stands above the blank's face and is modeled only.")
            hint.setWordWrap(True)
            hint.setObjectName("hintLabel")
            v.addWidget(hint)
        self._refresh_sculpt_list()


    _SC_FACES = ("posterior", "anterior", "rim")
    _SC_OPS = ("emboss", "deboss")

    def _sculpt_summary(self, f: SculptFeature) -> str:
        where = ({"posterior": "hinge face", "anterior": "outer face", "rim": "edge",
                  "pick": "placed"} if self.host == "temple" else
                 {"posterior": "back", "anterior": "front", "rim": "rim", "pick": "placed"})
        name = f.label or f.source_name or f.id
        flag = "" if f.enabled else "  (off)"
        op = f"{f.op}, flipped" if f.mount.flip else f.op
        return (f"{name} — {op} · {where.get(f.mount.face, f.mount.face)}"
                f"{'  ⇔' if f.mirror else ''}{flag}")

    def _load_sculpt_mount_fields(self, f: SculptFeature) -> None:
        """Scale, Size, Spin, Sink (ranged to the relief), Flush and Flip,
        from the record, signals held."""
        was = self._sculpt_loading
        self._sculpt_loading = True
        self.sc_scale.setValue(f.scale)
        if f.extent_mm > 0:
            self.sc_size.setValue(f.size_mm)
        self.sc_size.setEnabled(f.extent_mm > 0)
        self.sc_spin.setValue(f.spin_deg)
        top = max(3.0, f.placed_height_mm + 1.0, f.mount.overlap_mm)
        self.sc_overlap.setRange(0.0, top)
        self.sc_overlap.setValue(f.mount.overlap_mm)
        self.sc_flush.setChecked(f.mount.flush)
        self.sc_flip.setChecked(f.mount.flip)
        self.sc_overlap.setEnabled(not f.mount.flush)
        self._sculpt_loading = was

    def _refresh_sculpt_list(self) -> None:
        row = self.sculpt_list.currentRow()
        self.sculpt_list.blockSignals(True)
        self.sculpt_list.clear()
        for f in self._sculpts:
            self.sculpt_list.addItem(self._sculpt_summary(f))
        self.sculpt_list.blockSignals(False)
        if self._sculpts:
            self.sculpt_list.setCurrentRow(min(max(row, 0), len(self._sculpts) - 1))
        self._sculpt_editor.setEnabled(bool(self._sculpts))

    def _release_handle(self) -> None:
        """Put the drag away: the overlay in the 3D view belongs to the row
        that asked for it, and outlived a selection change or a removal,
        taking the clicks over it and dropping the wrong mesh (the 2.1 bug
        hunt). Says so to the window whatever the loading guard."""
        if not self.sc_handle.isChecked():
            return
        was = self._sculpt_loading
        self._sculpt_loading = True
        self.sc_handle.setChecked(False)
        self._sculpt_loading = was
        row = getattr(self, "_handle_row", None)
        self._handle_row = None
        self.handle_requested.emit(self.sculpt_list.currentRow() if row is None else row, False)

    def _on_sculpt_selected(self, row: int) -> None:
        if not (0 <= row < len(self._sculpts)):
            return
        self._release_handle()
        f = self._sculpts[row]
        self._sculpt_loading = True
        self.sc_enabled.setChecked(f.enabled)
        self.sc_label.setText(f.label)
        face = f.mount.face if f.mount.face in self._SC_FACES else "posterior"
        self.sc_face.setCurrentIndex(self._SC_FACES.index(face))
        self.sc_op.setCurrentIndex(self._SC_OPS.index(f.op))
        self._load_sculpt_mount_fields(f)
        self.sc_mirror.setChecked(f.mirror)
        self.sc_handle.setChecked(False)
        self._sculpt_loading = False

    def _on_sculpt_edited(self, *_a) -> None:
        """The record's own fields: nothing about where it sits changes."""
        if self._sculpt_loading:
            return
        row = self.sculpt_list.currentRow()
        if not (0 <= row < len(self._sculpts)):
            return
        before = self._sculpts[row]
        op = self._SC_OPS[self.sc_op.currentIndex()]
        self._sculpts[row] = before.model_copy(update=dict(
            enabled=self.sc_enabled.isChecked(),
            label=self.sc_label.text(),
            op=op,
            mirror=self.sc_mirror.isChecked(),
        ))
        self._refresh_sculpt_list()
        if op != before.op:
            # A deboss means the stamp: the relief turned into the frame, sunk
            # halfway. An emboss means the back on the surface. The switch
            # sets the mount that way; Flip and Sink stay the maker's after.
            f = self._sculpts[row]
            if op == "deboss" and not f.mount.flip:
                depth = max(0.05, round(0.5 * f.placed_height_mm, 2)) if f.height_mm else 0.5
                self._sculpts[row] = f.model_copy(update=dict(mount=f.mount.model_copy(
                    update=dict(flip=True, overlap_mm=depth, flush=False))))
                self._load_sculpt_mount_fields(self._sculpts[row])
                self._refresh_sculpt_list()
                # the mount signal alone: the window re-places, rebuilds and
                # marks dirty from it; `castle_changed` first would clear the
                # built model before the re-read (the 2026-11-01 review)
                self.mount_changed.emit(row, False)
                return
            if op == "emboss" and f.mount.flip:
                self._sculpts[row] = f.model_copy(update=dict(mount=f.mount.model_copy(
                    update=dict(flip=False, overlap_mm=0.05))))
                self._load_sculpt_mount_fields(self._sculpts[row])
                self._refresh_sculpt_list()
                self.mount_changed.emit(row, True)      # read the sag again
                return
        self.changed.emit()

    def _on_sculpt_mount_edited(self, face_moved: bool) -> None:
        """Scale, spin, overlap, flush or the face: the placement must be
        recomputed, which the window does with the host in hand."""
        if self._sculpt_loading:
            return
        row = self.sculpt_list.currentRow()
        if not (0 <= row < len(self._sculpts)):
            return
        f = self._sculpts[row]
        flush = self.sc_flush.isChecked()
        self.sc_overlap.setEnabled(not flush)
        scale = self.sc_scale.value()
        self._sculpts[row] = f.model_copy(update=dict(
            scale=scale,
            spin_deg=self.sc_spin.value(),
            mount=f.mount.model_copy(update=dict(
                face=self._SC_FACES[self.sc_face.currentIndex()] if face_moved else f.mount.face,
                overlap_mm=0.0 if flush else self.sc_overlap.value(),
                flush=flush, flip=self.sc_flip.isChecked())),
        ))
        g = self._sculpts[row]
        was = self._sculpt_loading
        self._sculpt_loading = True
        if g.extent_mm > 0:
            self.sc_size.setValue(g.size_mm)                  # Size follows Scale
        self.sc_overlap.setRange(0.0, max(3.0, g.placed_height_mm + 1.0, g.mount.overlap_mm))
        self._sculpt_loading = was
        self._refresh_sculpt_list()
        self.mount_changed.emit(row, face_moved)

    def _on_sculpt_size_edited(self, *_a) -> None:
        """Size in mm is Scale by another name: the longest side of the file
        times the factor."""
        if self._sculpt_loading:
            return
        row = self.sculpt_list.currentRow()
        if not (0 <= row < len(self._sculpts)):
            return
        f = self._sculpts[row]
        if f.extent_mm <= 0:
            return
        scale = max(0.01, float(self.sc_size.value()) / float(f.extent_mm))
        was = self._sculpt_loading
        self._sculpt_loading = True
        self.sc_scale.setValue(scale)
        self._sculpt_loading = was
        self._on_sculpt_mount_edited(False)

    def _on_sculpt_resnap(self) -> None:
        row = self.sculpt_list.currentRow()
        if 0 <= row < len(self._sculpts):
            self.resnap_requested.emit(row)

    def _on_sculpt_handle_toggled(self, on: bool) -> None:
        if self._sculpt_loading:
            return
        row = self.sculpt_list.currentRow()
        if 0 <= row < len(self._sculpts):
            self._handle_row = row if on else None      # the row the drag belongs to
            self.handle_requested.emit(row, bool(on))

    def _unique_sculpt_id(self, base: str = "sculpt") -> str:
        taken = {f.id for f in self._sculpts}
        n = 1
        while f"{base}_{n}" in taken:
            n += 1
        return f"{base}_{n}"

    def add_sculpt(self, feature: SculptFeature) -> int:
        """Append a sculpt the window imported and snapped; returns its row."""
        if not feature.id or feature.id in {f.id for f in self._sculpts}:
            feature = feature.model_copy(update={"id": self._unique_sculpt_id()})
        self._sculpts.append(feature)
        self._refresh_sculpt_list()
        self.sculpt_list.setCurrentRow(len(self._sculpts) - 1)
        self.changed.emit()
        return len(self._sculpts) - 1

    def sculpt_at(self, row: int) -> SculptFeature | None:
        return self._sculpts[row].model_copy() if 0 <= row < len(self._sculpts) else None

    def set_sculpt(self, row: int, feature: SculptFeature) -> None:
        """Replace one record (a new transform, after a snap or a drag);
        says nothing — the caller decides whether the model rebuilds."""
        if not (0 <= row < len(self._sculpts)):
            return
        self._sculpts[row] = feature.model_copy()
        self._refresh_sculpt_list()
        if self.sculpt_list.currentRow() == row:
            self._load_sculpt_mount_fields(feature)

    def set_sculpt_info(self, row: int, text: str) -> None:
        if self.sculpt_list.currentRow() == row:
            self.sc_info.setText(text)

    def _on_sculpt_duplicate(self) -> None:
        row = self.sculpt_list.currentRow()
        if not (0 <= row < len(self._sculpts)):
            return
        src = self._sculpts[row]
        self._sculpts.insert(row + 1, src.model_copy(update={
            "id": self._unique_sculpt_id(),
            "label": f"{src.label} copy" if src.label else "",
        }))
        self._refresh_sculpt_list()
        self.sculpt_list.setCurrentRow(row + 1)
        self.changed.emit()

    def _on_sculpt_remove(self) -> None:
        row = self.sculpt_list.currentRow()
        if not (0 <= row < len(self._sculpts)):
            return
        self._release_handle()
        self._sculpts.pop(row)
        self._refresh_sculpt_list()
        if self._sculpts:
            self._on_sculpt_selected(self.sculpt_list.currentRow())
        self.changed.emit()

    def sculpts(self) -> list[SculptFeature]:
        return [f.model_copy() for f in self._sculpts]

    def set_sculpts(self, features: list[SculptFeature]) -> None:
        self._release_handle()
        self._sculpts = [f.model_copy() for f in (features or [])]
        self._refresh_sculpt_list()
        if self._sculpts:
            self._on_sculpt_selected(self.sculpt_list.currentRow())

