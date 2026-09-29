"""Shop defaults per kind of part — Preferences ▸ Parts — and the save-time
offer to adopt a project's departures as the new defaults (2026-09-27).

Why. A maker cutting components one at a time on a bed with macroed zero
positions (the Small Batch Tools bed; the maker's own earlier setup) touches
off every part at the same corner of its blank, job after job. Until now every
freshly opened drawing started each part at the schema's center/center/bottom,
so the datum was re-picked per part, per project. The temples' blank-end snap
and stock side are the same shape of thing: a shop's cores are shot from one
end of the blank and stay there. Blank sizes, the base-curve block's mounting
hole pattern (it is the jig's) and each part's tools round out the set — all
shop constants a project may still depart from.

Three groups, not five kinds: both temples are cut from identical blanks and
both base-curve blocks likewise, so a default is per *kind of part*.

Two rules keep this honest:

* **Only the GUI reads preferences.** `Component.for_kind` keeps building the
  schema defaults; `seed_workspaces` overlays the shop's own on the fresh
  workspaces at open time. A reopened project's saved per-component values are
  applied after that and win — a project keeps what it saved.
* **Sparse storage.** `part_defaults` holds only what differs from the schema
  default, so a shipped default that moves later still reaches a maker who never
  had an opinion about it (the `PREFS_VERSION` concern in `prefs.py`).

The save-time offer covers the maker's ask — the program zero for every group
and the temples' snap and stock side (`OFFERED_FIELDS`) — and each part's stock
(`STOCK_FIELDS`, 2026-09-28: a maker standardizes their own blanks as surely as
their zeros), and only when every enabled component of a group agrees: two
temples zeroed differently are a project's business, not a default. The rest of
the page (holes, tools) is set in Preferences and never prompted for; those vary
per job often enough that an offer on every save would be noise.

The offer is one checkbox per departure (2026-09-28), so a maker can take a new
zero and leave a one-off job's blank, and "once" is per line: each departure's
`key` is remembered for the session whether it was adopted or left, and a later
save offers only the lines not yet asked about.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from guildmodel.core.project.schema import (
    BaseCurveBlockParams,
    CastleParams,
    ComponentKind,
    ProgramZero,
    TempleParams,
    component_fixture_zone,
)

GROUPS: tuple[str, ...] = ("frame_front", "temple", "base_curve")

GROUP_LABELS: dict[str, str] = {
    "frame_front": "Frame Front",
    "temple": "Temples",
    "base_curve": "Base-curve blocks",
}

_GROUP_OF_KIND: dict[ComponentKind, str] = {
    ComponentKind.FRAME_FRONT: "frame_front",
    ComponentKind.TEMPLE_RIGHT: "temple",
    ComponentKind.TEMPLE_LEFT: "temple",
    ComponentKind.BASE_CURVE_RIGHT: "base_curve",
    ComponentKind.BASE_CURVE_LEFT: "base_curve",
}

#: The param fields Preferences ▸ Parts can default, per group. Anything else in a
#: stored "params" dict is ignored, so a hand-edited prefs file cannot reach into
#: fields the page never offered.
PARAM_FIELDS: dict[str, tuple[str, ...]] = {
    "frame_front": ("stock",),
    "temple": ("snap_to_blank_end", "stock_side",
               "blank_length_mm", "blank_width_mm", "blank_thickness_mm",
               "engrave_tool", "hinge_tool", "profile_tool"),
    "base_curve": ("blank_length_mm", "blank_width_mm", "blank_thickness_mm",
                   "hole_count", "hole_spacing_mm", "hole_diameter_mm",
                   "hole_arrangement", "profile_tool", "drill_tool"),
}

#: The fields that name a tool. A stored default naming a tool the library no
#: longer carries is dropped at read time (`with_overrides`), so the schema's
#: tool applies and is shown: left in, the dock kept whatever it last showed,
#: an inactive part fell back to the library's first entry, and the page kept
#: the dead name — three different tools for one stored word, none announced.
TOOL_FIELDS: frozenset[str] = frozenset(
    {"engrave_tool", "hinge_tool", "profile_tool", "drill_tool"})

#: What a saved project offers to adopt, besides the program zero and the stock
#: (every group).
OFFERED_FIELDS: dict[str, tuple[str, ...]] = {
    "frame_front": (),
    "temple": ("snap_to_blank_end", "stock_side"),
    "base_curve": (),
}

#: Each group's stock, offered as one line and adopted whole: a blank is one
#: thing on the shelf, not three numbers. The front's is the blank and the pad
#: block as Preferences ▸ Parts sets them; the pad's offset is not on the page.
_BLANK: tuple[str, ...] = ("blank_length_mm", "blank_width_mm", "blank_thickness_mm")
STOCK_FIELDS: dict[str, tuple[str, ...]] = {
    "frame_front": _BLANK + ("pad_block_length_mm", "pad_block_width_mm",
                             "pad_block_thickness_mm", "use_pad_block"),
    "temple": _BLANK,
    "base_curve": _BLANK,
}


def empty() -> dict:
    """The shipped `part_defaults` pref: every group present, nothing overridden."""
    return {g: {} for g in GROUPS}


def group_of(kind) -> str:
    return _GROUP_OF_KIND[ComponentKind(kind)]


def schema_default(kind):
    """The kind's param model exactly as the schema ships it (fixture zone set)."""
    kind = ComponentKind(kind)
    if kind == ComponentKind.FRAME_FRONT:
        return CastleParams()
    if kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        return TempleParams(fixture_zone=component_fixture_zone(kind))
    return BaseCurveBlockParams(fixture_zone=component_fixture_zone(kind))


_REPRESENTATIVE_KIND: dict[str, ComponentKind] = {
    "frame_front": ComponentKind.FRAME_FRONT,
    "temple": ComponentKind.TEMPLE_RIGHT,
    "base_curve": ComponentKind.BASE_CURVE_RIGHT,
}


def schema_default_for_group(group: str):
    return schema_default(_REPRESENTATIVE_KIND[group])


def _group_prefs(prefs: dict | None, group: str) -> dict:
    pd = prefs.get("part_defaults") if isinstance(prefs, dict) else None
    g = pd.get(group) if isinstance(pd, dict) else None
    return g if isinstance(g, dict) else {}


def param_overrides(prefs: dict | None, group: str) -> dict:
    """The group's stored sparse "params" overrides; {} when none are set."""
    raw = _group_prefs(prefs, group).get("params")
    return dict(raw) if isinstance(raw, dict) else {}


# ------------------------------------------------------------------ reading

def default_program_zero(prefs: dict | None, kind) -> ProgramZero:
    """The shop's default G54 datum for `kind`; the schema's when none is set or
    the stored one no longer validates."""
    raw = _group_prefs(prefs, group_of(kind)).get("program_zero")
    if isinstance(raw, dict):
        try:
            return ProgramZero(**raw)
        except ValidationError:
            pass
    return ProgramZero()


def with_overrides(params, group: str, overrides: dict | None):
    """`params` with the group's stored overrides on top.

    Nested dicts (the front's `stock`) merge field by field. Validated as a whole
    first; if that fails, field by field, so one value that no longer validates
    is dropped rather than taking the rest down — or failing the open."""
    if not isinstance(overrides, dict) or not overrides:
        return params
    allowed = PARAM_FIELDS[group]
    picked = {k: v for k, v in overrides.items()
              if k in allowed and (k not in TOOL_FIELDS or _known_tool(v))}
    if not picked:
        return params

    def merged(base_dump: dict, subset: dict) -> dict:
        data = dict(base_dump)
        for k, v in subset.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k] = {**data[k], **v}
            else:
                data[k] = v
        return data

    cls = type(params)
    dump = params.model_dump()
    try:
        return cls(**merged(dump, picked))
    except ValidationError:
        pass
    out = params
    for k, v in picked.items():
        try:
            out = cls(**merged(out.model_dump(), {k: v}))
        except ValidationError:
            continue
    return out


def _known_tool(name) -> bool:
    """Whether the tool library carries `name`; True when the library cannot
    be consulted, so a stored default is never dropped on a read error."""
    try:
        from guildmodel.gui import tool_store
        return name in tool_store.names()
    except Exception:
        return True


def default_params(prefs: dict | None, kind):
    """The kind's param model: schema defaults with the shop's overrides on top."""
    group = group_of(kind)
    return with_overrides(schema_default(kind), group,
                          _group_prefs(prefs, group).get("params"))


def stock_of(group: str, params) -> dict:
    """The part's `STOCK_FIELDS` as a dict — nested under `stock` on the front."""
    src = params.stock if group == "frame_front" else params
    return {f: getattr(src, f) for f in STOCK_FIELDS[group]}


def _params_attr(kind) -> str:
    kind = ComponentKind(kind)
    if kind == ComponentKind.FRAME_FRONT:
        return "castle_params"
    if kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        return "temple_params"
    return "block_params"


def seed_workspace(ws, prefs: dict | None) -> None:
    """Give a fresh workspace the shop's defaults for its kind: the program zero
    and the param overrides, laid over whatever params it came with (the schema
    defaults today; a drawing's own values, should a drawing ever carry them)."""
    kind = ComponentKind(ws.kind)
    group = group_of(kind)
    ws.program_zero = default_program_zero(prefs, kind)
    attr = _params_attr(kind)
    base = getattr(ws, attr, None) or schema_default(kind)
    setattr(ws, attr, with_overrides(base, group,
                                     _group_prefs(prefs, group).get("params")))


def seed_workspaces(workspaces, prefs: dict | None) -> None:
    for ws in workspaces:
        seed_workspace(ws, prefs)


# ------------------------------------------------------------------ the save-time offer

@dataclass(frozen=True)
class Departure:
    """One way this project's parts differ from the shop defaults."""
    group: str
    field: str          # "program_zero", "stock", or a name in OFFERED_FIELDS[group]
    value: Any          # JSON-able: a ProgramZero dump, a `stock_of` dict, or the field's value

    def key(self) -> tuple:
        """A hashable identity: the same departure is offered once a session."""
        return (self.group, self.field, json.dumps(self.value, sort_keys=True, default=str))

    def text(self) -> str:
        who = GROUP_LABELS[self.group]
        if self.field == "program_zero":
            return f"{who}: program zero — {ProgramZero(**self.value).label()}"
        if self.field == "snap_to_blank_end":
            return f"{who}: snap to blank end {'on' if self.value else 'off'}"
        if self.field == "stock_side":
            return f"{who}: stock side {self.value}"
        if self.field == "stock":
            return f"{who}: {_stock_text(self.value)}"
        return f"{who}: {self.field.replace('_', ' ')} {self.value}"


def _mm(*values) -> str:
    return " × ".join(f"{v:g}" for v in values) + " mm"


def _stock_text(v: dict) -> str:
    text = "blank " + _mm(v["blank_length_mm"], v["blank_width_mm"],
                          v["blank_thickness_mm"])
    if "use_pad_block" not in v:
        return text
    if not v["use_pad_block"]:
        return text + ", no pad block"
    return text + ", pad block " + _mm(v["pad_block_length_mm"], v["pad_block_width_mm"],
                                       v["pad_block_thickness_mm"])


def departures(workspaces, prefs: dict | None) -> list[Departure]:
    """What this project's parts have that the shop defaults do not — the program
    zero for every group, `OFFERED_FIELDS` and the stock — counting only enabled
    components, and only where every component of a group agrees."""
    by_group: dict[str, list] = {}
    for ws in workspaces:
        if not getattr(ws, "enabled", True):
            continue
        by_group.setdefault(group_of(ws.kind), []).append(ws)

    out: list[Departure] = []
    for group in GROUPS:
        members = by_group.get(group)
        if not members:
            continue
        kind = members[0].kind
        zeros = [ws.program_zero for ws in members]
        if all(z is not None for z in zeros):
            dumps = [z.model_dump() for z in zeros]
            if (all(d == dumps[0] for d in dumps)
                    and dumps[0] != default_program_zero(prefs, kind).model_dump()):
                out.append(Departure(group, "program_zero", dumps[0]))
        params = [getattr(ws, _params_attr(ws.kind), None) for ws in members]
        if any(p is None for p in params):
            continue
        default = default_params(prefs, kind)
        for field in OFFERED_FIELDS[group]:
            vals = [getattr(p, field) for p in params]
            if all(v == vals[0] for v in vals) and vals[0] != getattr(default, field):
                out.append(Departure(group, field, vals[0]))
        stocks = [stock_of(group, p) for p in params]
        if all(s == stocks[0] for s in stocks) and stocks[0] != stock_of(group, default):
            out.append(Departure(group, "stock", stocks[0]))
    return out


def adopt(prefs: dict, deps: list[Departure]) -> None:
    """Write the departures into `prefs["part_defaults"]` (sparse, like the page).

    Rebuilds the touched group dicts rather than updating them in place, so a
    prefs dict that happens to share structure with another is never edited
    through."""
    pd = prefs.get("part_defaults")
    pd = dict(pd) if isinstance(pd, dict) else empty()
    for d in deps:
        g = pd.get(d.group)
        g = dict(g) if isinstance(g, dict) else {}
        # A departure is measured against the *shop* default, so a project that
        # went back to the schema's value is a departure too; stored sparsely,
        # that is the entry's absence, not the schema value written out.
        if d.field == "program_zero":
            zero = sparse_zero(ProgramZero(**d.value))
            if zero is None:
                g.pop("program_zero", None)
            else:
                g["program_zero"] = zero
        else:
            params = g.get("params")
            params = dict(params) if isinstance(params, dict) else {}
            schema = schema_default_for_group(d.group)
            if d.field == "stock" and d.group == "frame_front":
                stock = params.get("stock")
                stock = dict(stock) if isinstance(stock, dict) else {}
                _store_sparse(stock, d.value, schema.stock)
                if stock:
                    params["stock"] = stock
                else:
                    params.pop("stock", None)
            elif d.field == "stock":
                _store_sparse(params, d.value, schema)
            else:
                _store_sparse(params, {d.field: d.value}, schema)
            if params:
                g["params"] = params
            else:
                g.pop("params", None)
        pd[d.group] = g
    prefs["part_defaults"] = pd


# ------------------------------------------------------------------ sparse storage

def _store_sparse(into: dict, values: dict, schema) -> None:
    """Write `values` into `into`, each one the schema already has as its absence."""
    for k, v in values.items():
        if v == getattr(schema, k):
            into.pop(k, None)
        else:
            into[k] = v


def sparse_params(group: str, params) -> dict:
    """The group's `params` entry for a fully populated param model: only the
    `PARAM_FIELDS` that differ from the schema default (nested for `stock`)."""
    base = schema_default_for_group(group).model_dump()
    full = params.model_dump()
    out: dict = {}
    for k in PARAM_FIELDS[group]:
        v = full.get(k)
        b = base.get(k)
        if isinstance(v, dict) and isinstance(b, dict):
            inner = {kk: vv for kk, vv in v.items() if vv != b.get(kk)}
            if inner:
                out[k] = inner
        elif v != b:
            out[k] = v
    return out


def sparse_zero(pz: ProgramZero) -> dict | None:
    """The stored `program_zero`, or None when it is the schema default."""
    d = pz.model_dump()
    return None if d == ProgramZero().model_dump() else d
