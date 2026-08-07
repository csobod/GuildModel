"""Per-component workspace state for the component notebook (BUILDPLAN M7.3).

A :class:`ComponentWorkspace` is one component's working set — its layer geometry,
the derived polygons (outline / lenses / SCULPT partition / hinges / engraving), the
per-component mesh stage cache, generated artifacts, and readiness — over the
MainWindow's *single shared* set of heavy views (2D canvas, 3D preview, cut-sim).
On a component-tab switch the window swaps its active ``self._*`` working set to the
selected workspace, so the existing build / generate / simulate code operates on
the active component transparently (one live set of VTK views, not five).

`derive_workspace` and `build_workspaces_from_gdraw` are pure (shapely + core, no
Qt), so the multi-component intake is unit-tested without a Qt platform.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guildmodel.core.project.schema import ComponentKind, component_label


@dataclass
class ComponentWorkspace:
    """One component's working set (see module docstring)."""
    kind: ComponentKind
    label: str
    layers: dict
    # The exact curves the drawing was authored with, index-aligned with
    # `layers` — `{layer: [NurbsCurve | None, ...]}` from `import_curves` /
    # `read_workspace_curves`. Optional: empty means every consumer falls back
    # to the flattened points, which is how this worked before 2026-08-07.
    # `derive_workspace` turns them into the partition's `source_curves`, which
    # is what lets the B-Rep castle be built from curves instead of polygons.
    curves: dict = field(default_factory=dict)
    enabled: bool = True
    source_workspace: str = ""
    forming: object = None
    # Raw GuildDraw text objects (engraving) for this workspace; the GUI outlines them
    # to ENGRAVING polylines on open (fonts need Qt, so not done in this pure module).
    texts: list = field(default_factory=list)
    # Set once derive_workspace has applied the temple Y-axis re-orientation, so a
    # re-derive never double-flips the layers.
    layers_oriented: bool = False

    # per-component editable params (pushed into / pulled from the kind-aware
    # param dock on a tab switch, M7.3). Exactly one is populated, per kind;
    # None means "leave the dock as-is" (a plain DXF frame uses the panel state).
    castle_params: object = None
    temple_params: object = None
    block_params: object = None
    program_zero: object = None     # per-component G54 datum (M11); None = panel default
    # Per-component departures from the project-global cam_params (M16) — a
    # ComponentCamOverrides, most usefully a different material. None = inherit.
    cam_overrides: object = None

    # derived geometry (filled by derive_workspace)
    outline_poly: object = None      # profile WITH decorative holes as interior rings
    outline_holes: list = field(default_factory=list)   # Hole1..HoleN, standalone
    outline_stray: list = field(default_factory=list)   # closed OUTLINE curves outside the profile
    lens_od: object = None
    lens_os: object = None
    partition: object = None
    hinge_polys: list = field(default_factory=list)
    engraving_curves: list = field(default_factory=list)
    is_temple: bool = False
    # The SCULPT cuts yielded fully-named castle zones, so the castle relief can
    # look a height up for each one — not necessarily the *standard* 9-zone
    # layout (that is `partition.matched`). Aviators and other non-standard
    # frames are castle_ready but unmatched.
    castle_ready: bool = False
    boxing: object = None

    # per-component mesh + generated artifacts + readiness (swapped on tab switch)
    stage: str = "pockets"
    stage_cache: dict = field(default_factory=dict)
    # Topological edges per stage key, parallel to `stage_cache`. Solid builds
    # only — None on the raster path, which is what disables the display-mode
    # combo. This lived on the main window until 2026-08-07 and was the one piece
    # of per-component render state that tab-switching did not swap; harmless
    # only while a single frame front was the only thing that could produce
    # edges, and wrong the moment Build 3D started emitting them for every
    # component.
    edge_cache: dict = field(default_factory=dict)
    mesh_built: bool = False
    core_guide: object = None        # temple injected-core bar bounds (3D marker)
    last_programs: dict = field(default_factory=dict)
    last_setup: object = None
    last_machine: object = None
    last_report: object = None
    program_stored: bool = False
    diag: dict = field(default_factory=dict)   # M7.14 inspector inputs (reach/clearance/lint)


def derive_workspace(ws: ComponentWorkspace, boxing=None) -> ComponentWorkspace:
    """Fill ``ws``'s derived geometry from ``ws.layers`` — the same extraction the
    DXF import does (outline / holes / lenses / OD-OS / SCULPT partition /
    hinges / engraving / is_temple / castle_ready / boxing). Pure shapely; no Qt.

    A frame front has an OUTLINE + two LENS curves (+ SCULPT for the castle); a
    temple has an OUTLINE and no lenses; a base-curve template carries its single
    LENS (placed in ``lens_od`` so the block generator can build from it).

    When ``ws.curves`` carries the drawing's exact curves they are folded into the
    partition as ``source_curves``, and the B-Rep castle builds from them. Without
    them everything here behaves exactly as it did.
    """
    from guildmodel.core.geometry.boxing import measure_from_polygon
    from guildmodel.core.geometry.curves import mirror_x as mirror_curve_x
    from guildmodel.core.geometry.regions import curves_by_ring, partition_zones
    from guildmodel.core.io_import.normalize import assemble_outline, points_to_polygon

    layers = ws.layers

    # Temples are drawn in the POSTERIOR view in GuildDraw, but the reader applies the
    # frame-front's anterior->posterior x-mirror to every workspace — over-mirroring a
    # temple so its geometry (and engraving) reads backwards. Reflect a temple back
    # across the Y axis (negate X) once, up front, so the whole part builds correctly.
    # A temple is an OUTLINE with no lens openings; temple-ness is invariant under the
    # flip, so the pre-flip check is valid. Idempotent via `layers_oriented`.
    if not ws.layers_oriented:
        _outline = layers.get("OUTLINE", [])
        _lenses = [points_to_polygon(c) for c in layers.get("LENS", []) if len(c) >= 3]
        if _outline and not any(p.is_valid and p.area > 1.0 for p in _lenses):
            layers = ws.layers = {lyr: [[(-x, y) for x, y in c] for c in curves]
                                  for lyr, curves in layers.items()}
            # The exact curves have to make the same trip, or they and the
            # points describe different parts (BUILDPLAN M1.2's single-flip rule
            # applies to both representations).
            ws.curves = {
                lyr: [mirror_curve_x(c) if c is not None else None for c in cs]
                for lyr, cs in (ws.curves or {}).items()
            }
        ws.layers_oriented = True

    ws.engraving_curves = list(layers.get("ENGRAVING", []))

    # Extra closed OUTLINE curves drawn inside the profile are decorative holes
    # (Hole1..HoleN) — they ride along as interior rings of `outline_poly`.
    assembly = assemble_outline(layers.get("OUTLINE", []))
    ws.outline_poly = assembly.polygon
    ws.outline_holes = list(assembly.holes)
    ws.outline_stray = list(assembly.stray)

    lens_polys = [points_to_polygon(c) for c in layers.get("LENS", []) if len(c) >= 3]
    valid_lens = [p for p in lens_polys if p.is_valid and p.area > 1.0]

    # A temple is an outline with no lenses (no castle relief).
    ws.is_temple = ws.outline_poly is not None and len(valid_lens) == 0
    if len(valid_lens) >= 2:
        ordered = sorted(valid_lens, key=lambda p: p.centroid.x)
        ws.lens_os, ws.lens_od = ordered[0], ordered[-1]      # OD on +x (posterior)
    elif len(valid_lens) == 1:
        ws.lens_od = valid_lens[0]                            # base-curve template's lens

    ws.hinge_polys = [
        p for p in (points_to_polygon(c) for c in layers.get("HINGE", []) if len(c) >= 3)
        if p.is_valid and p.area > 0.5
    ]

    sculpt = layers.get("SCULPT", [])
    if ws.outline_poly is not None and len(valid_lens) >= 2 and sculpt:
        # Only OUTLINE and LENS: those are the rings that bound the body, and a
        # ring is the only thing `source_curves` is ever looked up by. SCULPT
        # cuts are open polylines (straight in every drawing so far) and HINGE
        # pockets are cut, not bounded.
        source: dict = {}
        for layer in ("OUTLINE", "LENS"):
            source.update(curves_by_ring(layers.get(layer, []),
                                         (ws.curves or {}).get(layer, [])))
        ws.partition = partition_zones(ws.outline_poly, valid_lens[:2], sculpt,
                                       source_curves=source)
        ws.castle_ready = bool(ws.partition.classified)

    if boxing is not None:
        ws.boxing = boxing
    elif len(valid_lens) >= 2:
        try:
            ws.boxing = measure_from_polygon(valid_lens[0], valid_lens[1])
        except Exception:
            ws.boxing = None
    return ws


def build_workspaces_from_gdraw(path) -> tuple[list[ComponentWorkspace], str]:
    """Read a ``.gdraw`` and build a derived :class:`ComponentWorkspace` per
    component (frame front + both temples + a base-curve template per lens). Pure;
    no Qt. Returns ``(workspaces, active_tab)`` — the front is always index 0.
    """
    from guildmodel.core.io_import.gdraw import build_project_from_gdraw

    gp = build_project_from_gdraw(path)
    out: list[ComponentWorkspace] = []
    for gc in gp.components:
        c = gc.component
        ws = ComponentWorkspace(
            kind=c.kind, label=component_label(c.kind), layers=gc.layers,
            curves=gc.curves,
            enabled=c.enabled, source_workspace=c.source_workspace, forming=c.forming,
            texts=list(gc.texts),
            castle_params=c.castle, temple_params=c.temple,
            block_params=c.base_curve_block,
            # Every model component starts with its OWN G54 datum (M11 + 2026-07-09
            # fix): with None here the dock's on-screen zero leaked into each
            # component on first visit, so separately-set zeros smeared into one.
            program_zero=c.program_zero)
        derive_workspace(ws)
        out.append(ws)
    return out, gp.active_tab
