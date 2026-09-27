"""The maker's presses: base-curve dies and the face form each one forms.

On the press the two numbers come as a pair — a die is tagged with one lens
base curve and the frame comes off it with one face form — so a preset sets
both, and touching either slider in the Forming panel turns the choice into
"Custom". A row also carries the die's own radius, which is what the model
bends to on that row; off a row the optical convention (530 / D) is the only
radius there is.

The shipped rows are the SBT base-curve press, read off its drawing on
2026-09-24, and live in ``config/presses.yaml``; a maker's own presses go in
``~/.guildmodel/presses.yaml`` and are merged over them the way tools and
materials already are (`gui.tool_store`): a user row with a shipped label
replaces it, a new label adds one, and ``{"_deleted": true}`` hides one.

Kept in `core` rather than beside the tool store because the export path
needs it without Qt: `mesh_build` labels a formed export by its press.
"""
from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

import yaml

__all__ = ["CUSTOM_LABEL", "FLAT_LABEL", "Press", "effective", "find",
           "matching", "on_row", "shipped"]

_log = logging.getLogger(__name__)

_SHIPPED = pathlib.Path(__file__).resolve().parents[2] / "config" / "presses.yaml"
_USER = pathlib.Path.home() / ".guildmodel" / "presses.yaml"

#: The two rows every list carries that are not presses.
FLAT_LABEL = "Flat"
CUSTOM_LABEL = "Custom"

#: How close a slider value has to sit to a row for the combo to name it. The
#: base curve moves in quarter steps, so anything under an eighth is "on it".
_MATCH_D = 0.05
_MATCH_DEG = 0.05


@dataclass(frozen=True)
class Press:
    label: str
    base_curve: float             # the lens base curve the die is tagged with, D
    radius_mm: float              # the die's own radius, or 530 / base_curve
    face_form_deg: float
    shipped: bool = True


def _read(path: pathlib.Path) -> dict:
    try:
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
    except Exception:                                        # noqa: BLE001
        pass
    return {}


def _rows(data: dict, *, shipped_flag: bool) -> list[Press]:
    from .thermoform import radius_for

    out: list[Press] = []
    for label, vals in data.items():
        if not isinstance(vals, dict) or vals.get("_deleted") is True:
            continue
        if str(label) in (FLAT_LABEL, CUSTOM_LABEL):
            _log.warning("presses.yaml: row %r skipped (the combo's own row)", label)
            continue
        try:
            base = float(vals["base_curve"])
            # A die radius that is not a positive number is no radius: the row
            # bends to the optical convention rather than to 0 (flat rims
            # under a badge that says otherwise).
            radius = float(vals.get("radius_mm") or 0.0)
            radius = radius if radius > 0.0 else radius_for(base)
            out.append(Press(str(label), base, radius,
                             float(vals["face_form_deg"]), shipped_flag))
        except (KeyError, TypeError, ValueError) as exc:
            # a malformed row is skipped, not fatal — but said, or a maker's
            # own press vanishes from the combo with nothing to go on
            _log.warning("presses.yaml: row %r skipped (%s)", label, exc)
    return out


def shipped() -> list[Press]:
    """The rows in ``config/presses.yaml``, in file order."""
    return _rows(_read(_SHIPPED), shipped_flag=True)


#: The merged rows, keyed on both files' (mtime, size): the Forming panel
#: asks for a row on every slider tick, and reading and parsing two YAML
#: files per tick was a measurable slice of a 110 ms redraw.
_cache: tuple | None = None


def _stamp(path: pathlib.Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def effective() -> list[Press]:
    """Shipped rows with the maker's file merged: overrides, additions and
    deletions, shipped order first and additions after."""
    global _cache
    key = (str(_SHIPPED), _stamp(_SHIPPED), str(_USER), _stamp(_USER))
    if _cache is not None and _cache[0] == key:
        return list(_cache[1])
    rows = _merged()
    _cache = (key, rows)
    return list(rows)


def _merged() -> list[Press]:
    user = _read(_USER)
    merged: dict[str, Press] = {p.label: p for p in shipped()}
    for label, vals in user.items():
        if not isinstance(vals, dict):
            continue
        if vals.get("_deleted") is True:
            merged.pop(str(label), None)
            continue
        for p in _rows({label: vals}, shipped_flag=False):
            merged[p.label] = p
    return list(merged.values())


def find(label: str) -> Press | None:
    for p in effective():
        if p.label == label:
            return p
    return None


def on_row(p: Press, base_curve: float, face_form_deg: float) -> bool:
    """Whether two slider values read as this row."""
    return (abs(p.base_curve - base_curve) <= _MATCH_D
            and abs(p.face_form_deg - face_form_deg) <= _MATCH_DEG)


def matching(base_curve: float, face_form_deg: float) -> Press | None:
    """The row these two values name, if any — how the combo decides whether
    a restored project is on a preset or is Custom."""
    for p in effective():
        if on_row(p, base_curve, face_form_deg):
            return p
    return None
