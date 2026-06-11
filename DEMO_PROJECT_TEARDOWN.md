# Demo Project Teardown — Fusion 360 Reference Workflow

Reconstruction of the user's manual GuildDraw-DXF → Fusion 360 → G-code workflow,
from the reference set in `Demo Project/`. This is the behavioural spec for what
GuildCAM must reproduce parametrically. Companion to `OLGA_TEARDOWN_AND_PLAN.md`.

Analyzed 2026-06-11 from: `GuildDraw DXF Export.dxf`, `Model.step`, `Model.stl`,
`Demo Program.nc`, `Setup Sheet.pdf`, and 22 timeline screenshots
(`Every Modeling Operation/` has one per feature, value-labeled filenames).
Reusable analysis scripts: `Demo Project/_analyze_*.py`.

---

## 1. Pipeline overview

```
GuildDraw DXF (anterior view)
  → FLIP (mirror across vertical axis — all modeling is done on the POSTERIOR)
  → ZONE EXTRUSIONS (SCULPT lines partition outline; each zone gets a thickness)
  → EDGE FILLETS (rolling-ball, constant radius, one convex + one concave per step)
  → CAM (5 ops, one tool, complex stock model, 0.4 mm onion skin — no tabs)
```

## 2. Input DXF contents

| Layer | Entities | Role |
|---|---|---|
| OUTLINE | 1 closed SPLINE | Frame perimeter |
| LENS | 2 closed SPLINEs | Lens openings |
| HINGE | 2 closed SPLINEs (~4.1 × 13.6 mm at X ±53.7–57.8) | Hinge pocket outlines |
| REF | 2 line segments (Y = 10.39, temple ends) | Datum, not machined |
| SCULPT | 10 straight 2-point LWPOLYLINEs (5 per side) | **Zone section lines** |

Key semantic: **SCULPT entities are straight section-cut lines** that partition
the frame body into thickness zones — endpiece cut (superior + inferior), bridge
superior cut, nosepad inferior cut, inferior-eyewire cut, mirrored L/R. They are
*not* freeform scallop guide curves. (BUILDPLAN M1 intake should be specced
against this.)

## 3. The zone model (modeling features 1–6)

Anterior face flat at Z = 0; posterior surfaces at per-zone heights.
Modeled as one extrusion per zone, in this order (filenames give exact values).
In the user's castle ethos (BUILDPLAN.md §2): zones 1–4 are the **towers**,
zones 5–6 are the **walls** connecting them; §4's fillets are the **footing**.

| # | Zone | Posterior height |
|---|---|---|
| 1 | Endpieces | 5.5 mm |
| 2 | Hinge pockets (cut into endpieces) | floor 4.5 mm (1.0 mm deep) |
| 3 | Bridge | 5.3 mm |
| 4 | Nosepads | 10.0 mm (top = raw pad-block stock, unmachined) |
| 5 | Superior eyewires | 4.8 mm |
| 6 | Inferior eyewires | 4.2 mm |

STEP plane levels and STL vertex histogram confirm exactly these plateaus.

## 4. The fillet schedule (modeling features 7–16)

All are Fusion **Fillet, constant radius, Rolling Ball corner type, tangent
chain**, applied to symmetric L/R edge pairs. All fillet cylinders in the STEP
are horizontal-axis — they ease the *step edges* between zones, in the plan
shape of the SCULPT section lines. Each zone step gets two:
**exterior** = convex top edge of the wall, **interior** = concave bottom edge.

| Step edge | Exterior r | Interior r |
|---|---|---|
| Endpiece superior | 32 mm | 48 mm |
| Endpiece inferior | 16 mm | 32 mm |
| Bridge superior | 24 mm | 32 mm |
| Nosepad superior | 6 mm | 4 mm |
| Nosepad inferior | 9 mm | 10 mm |

(Modeling order in the timeline: interior corners first, then nosepad
exterior/interior, then remaining exteriors — order is cosmetic, values above
are what matter.)

## 5. Stock model

CAM uses a **complex (two-level) stock body**, not a simple slab — derived from
the same guides GuildDraw displays:

- **Blank:** 170 × 85 mm, 6 mm thick (default; user-adjustable)
- **Pad block:** 45 × 45 mm, 4 mm thick, stacked centrally → 10 mm total in its
  zone (matches `config/fixtures/guild_cnc.yaml` nosepad sub-zone)

Rationale: a slab-stock setup would make Fusion air-cut above the 6 mm regions
expecting 10 mm of material. The complex stock keeps toolpaths tight.
GuildCAM's drop-cutter should likewise initialize its heightfield from this
two-level stock, with both bodies user-editable (defaults above).

Setup-sheet stock bounding box for this demo: 172 × 83 × 10 mm
(lower −86,−41.5,0; upper 86,41.5,10) — per-job artifact of an old stock model
in the user's Fusion library; **170 × 85 is the canonical default**.
Part bbox 123.017 × 43.359 × 10 mm.

## 6. CAM operations (Setup "Posterior Cut", from Setup Sheet)

One tool, one setup, total cycle ~10 m 15 s (7168 mm cutting distance).
**Tool T1:** 3.175 mm (1/8") single-flute flat end mill, 24 mm length,
S10000, F750 max (F333 ramps), flood coolant. NC origin = model origin.

| # | Op | Fusion strategy | Key params | Z min | Time |
|---|---|---|---|---|---|
| 1 | Hinge Pockets | Pocket 2D | tol 0.1, stepover 1.2, ramp entry | 4.5 | 0:46 |
| 2 | Rough Scallop | Scallop | tol 0.01, stepover 0.8, **axial stock to leave 2.0**, radial 0.1 | 6.2 | 3:00 |
| 3 | Fine Scallop | Scallop | tol 0.01, stepover 0.8, stock to leave 0 | 4.2 | 2:58 |
| 4 | Eyewires | Contour 2D | stepdown 2.5 (4 passes: 7.5/5.0/2.5/0.4), **axial stock to leave 0.4**, radial 0.1 | 0.4 | 1:32 |
| 5 | Perimeter | Contour 2D | same as Eyewires | 0.4 | 1:59 |

Notes:

- **Order matters:** hinge pockets are cut first, while the stock is still rigid.
- **"Scallop"** here is Fusion's constant-stepover 3D finishing strategy; the
  rough pass is the same pattern offset +2 mm axially.
- **No tabs.** Through-cuts (eyewires, perimeter) stop at Z 0.4 — a 0.4 mm
  **onion skin** above the anterior face holds the part (header `ZMIN=0.4`).
  This conflicts with GuildCAM's current `cam/tabs.py` approach — decide which
  is canonical before M0 hardware (the proven manual workflow uses skin).
- Both contour ops also leave 0.1 mm radially. This is a deliberate
  **hand finishing allowance** and must be a user-facing GuildCAM parameter:
  label it "Hand finishing allowance", default 0.1 mm, with a tooltip that
  states the mechanism tersely (e.g. "places radial leave-behind stock on
  contour operations").
- Rapids at Z 25, feed plane Z 15.

## 7. Implications for GuildCAM

1. **Parametric zone UI (user-confirmed intent):** zone thicknesses and the
   per-edge fillet radius pairs are *not* in the DXF — they must be GuildCAM UI
   parameters with immediate visual feedback in the 3D preview. Schema sketch:

   ```
   zones:
     endpiece:          {thickness_mm: 5.5}
     bridge:            {thickness_mm: 5.3}
     nosepad:           {thickness_mm: 10.0}
     eyewire_superior:  {thickness_mm: 4.8}
     eyewire_inferior:  {thickness_mm: 4.2}
   hinge_pocket:        {depth_mm: 1.0}        # floor = endpiece − depth
   fillets:                                    # per step edge
     endpiece_superior: {exterior_mm: 32, interior_mm: 48}
     endpiece_inferior: {exterior_mm: 16, interior_mm: 32}
     bridge_superior:   {exterior_mm: 24, interior_mm: 32}
     nosepad_superior:  {exterior_mm: 6,  interior_mm: 4}
     nosepad_inferior:  {exterior_mm: 9,  interior_mm: 10}
   stock:
     blank:     {x_mm: 170, y_mm: 85, thickness_mm: 6}
     pad_block: {x_mm: 45,  y_mm: 45, thickness_mm: 4, placement: centered}
   ```

2. **Heightfield implementation:** rasterize SCULPT-partitioned zones → assign
   per-zone Z → blend step edges. A rolling-ball fillet on a heightfield is
   grey morphology with a spherical structuring element (per-edge radii means
   per-edge masked application). This replaces the distance-based scallop in
   `relief/builder.py` as the primary posterior model.

3. **Zone identification must be automatic:** SCULPT lines + outline + lens
   curves are enough to label zones (endpiece = outboard of endpiece cuts,
   bridge = between superior cuts, nosepad = below bridge between lens, etc.)
   so the UI can offer named parameters without the user tagging regions.

4. **CAM op sequence to reproduce:** hinge pockets → rough relief (+2 mm axial)
   → fine relief → lens contours → perimeter contour, single 1/8" flat tool,
   onion-skin through-cuts.

---

## 8. Development readiness (assessed 2026-06-11)

Scope for the first milestone: **frame front only**, matching this demo.
Temples, base-curve forming blocks, and lens patterns come later (user will
supply reference material when each arises).

### In hand ✅

- Complete ground-truth fixture set (`Demo Project/`) — enables automated
  regression: GuildCAM heightfield vs `Model.stl`, toolpath envelopes vs
  `Demo Program.nc`.
- Semantic spec: this document (zones, fillets, stock, 5-op CAM recipe).
- GuildDraw contract verified in source: SCULPT is a front-workspace layer,
  line curves export as 2-point LWPOLYLINE, SCULPT mirrors at export like
  LENS/HINGE (`framedraft/export/dxf.py`).
- `config/fixtures/guild_cnc.yaml` already encodes the 170 × 85 front blank
  with the 45 × 45 nosepad sub-zone (6 + 4 mm) and flip axis.
- Working building blocks in `core/`: DXF intake (incl. SCULPT), boxing,
  pyclipper offset/pocket, drop-cutter morphology, GRBL post, watertight
  two-sided mesh, pydantic schema, GUI shell with live-rebuild pattern.
- Tool/feeds known: 3.175 mm single-flute flat, S10000, F750 cut / F333 ramp.

### To build (gap list, in suggested order)

1. **`geometry/regions.py`** (currently empty stub): partition OUTLINE by
   SCULPT section curves; auto-label zones (endpieces, bridge, nosepads,
   superior/inferior eyewires) from position relative to lens/outline.
2. **Anterior→posterior flip on import** (mirror x → −x): GuildDraw draws the
   anterior view; all GuildCAM geometry is posterior.
3. **Terraced relief builder**: replace distance-based scallop in
   `relief/builder.py` with per-zone heights + rolling-ball edge fillets
   (grey morphology, per-edge radius via masks).
4. **Two-level stock heightfield** (blank + pad block, user-editable defaults
   170×85×6 + 45×45×4 centered) used by both preview and CAM — the
   heightfield equivalent of Fusion's complex stock model.
5. **CAM pipeline → the 5-op recipe**: hinge Pocket 2D with ramp entry
   (`post/grbl.py` currently straight-plunges), rough relief (+2 mm axial),
   fine relief, eyewire + perimeter contours with 0.4 mm onion skin and the
   hand-finishing allowance (0.1 mm radial, user parameter with tooltip).
6. **Parametric UI**: zone thickness / fillet pairs / stock / allowance
   spinboxes with immediate 3D preview rebuild (wiring pattern already exists).
7. **Validation harness**: pytest comparing built heightfield against
   `Demo Project/Model.stl` within tolerance; NC Z-envelope sanity checks.

### Resolved decisions

- Tabs are **retired** for frame fronts in favor of the 0.4 mm onion skin
  (the user's proven workflow). `cam/tabs.py` remains available but unused.
- Stock 172 × 83 in the demo setup sheet was a per-job artifact; 170 × 85 is
  canonical.
- Hand finishing allowance: user-facing parameter, default 0.1 mm.

### Open (non-blocking) decisions

- **Zone labeling convention**: demo uses exactly 5 section lines per side.
  Proposal: auto-label when that pattern matches; generic numbered zones as
  fallback for other counts.
- **SCULPT discipline**: GuildDraw doesn't constrain the layer to straight
  lines. Proposal: v1 intake accepts any *open* SCULPT curve as a section cut.
- **Hinge pockets**: demo drives them from the HINGE outline + 1.0 mm depth —
  simpler than the CHA catalog in `relief/hinge.py`. Proposal: v1 uses
  HINGE-outline + depth parameter; keep the catalog for v2.
- **Lens groove/bevel**: absent from the demo (eyewires are straight-walled
  contour cuts). OLGA `bevel_flank()` stays dormant until the lens-pattern
  phase.
