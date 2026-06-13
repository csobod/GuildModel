# BUILDPLAN.md — GuildCAM · Road to Version 1.0

A focused, open-source CAM application for acetate / horn eyewear manufacture.
Built on Python + PySide6 (Qt 6) over a headless, scriptable `core/`. Single
purpose: take a GuildDraw DXF, build the posterior relief of a frame front the
way a maker actually models it, generate the two-sided GRBL programs for the
Guild CNC, and prove the result on real stock — and nothing else.

> **This document is the v1.0 roadmap.** The original spike-era build plan
> (Sessions 1–6, M0 pipeline) is archived verbatim at
> **`docs/BUILDPLAN-spike-archive.md`**. The behavioural ground truth this
> roadmap is built against is **`DEMO_PROJECT_TEARDOWN.md`** (the user's manual
> Fusion 360 workflow, fully reconstructed from `Demo Project/`). OLGA
> behavioural reverse-engineering lives in `OLGA_TEARDOWN_AND_PLAN.md`;
> the GuildDraw-side export contract is `BUILDPLAN.md` §2 in the GuildDraw repo.

---

## Status snapshot *(2026-06-12, M4.6 implemented — tag `v0.4.6` pending; then M5)*

**M4.6 landed (same day):** the window architecture was rebuilt on
GuildDraw's pattern. The two fixed-width sidebars inside a `QSplitter` (the
cause of both the clipped Footing rows and the dead band at the right edge
when maximized) are gone, replaced by **one right `QDockWidget`** (title bar
hidden, View-toggle) holding the params as a four-tab `QTabWidget`
(**Frame / Castle / Stock / CAM**, each its own scroll area — no fixed width,
no horizontal clipping); the log moved to a **bottom dock**; primary actions
(Open · Build 3D · G-code · Export STL) plus the 2D/3D view toggle, Fit, and
the two dock toggles moved to a **left vertical icon `QToolBar`** (F5 /
Ctrl+G / Ctrl+E, menus matched) — **icon-only with tooltips**, GuildDraw's
icon sidebar exactly (the dock toggles pinned to the bottom). The **log dock
defaults to hidden** (Preferences ▸ Appearance ▸ *Show log panel on startup*
sets the default; the toolbar button toggles it for the session).
The app-level viewport strip and its `appTitle`/zoom readout
were dropped — camera presets (**icon buttons**: view-iso/top/front/reset) +
the castle stage stepper (**icon buttons**: stage-towers/walls/footing/full,
a 4-step build storyboard — supersedes the style guide's original "stay text"
note) stay on the 3D preview's own strip, all recolored per theme; zoom moved
to the status bar. Window geometry + dock
state persist via prefs (`main_window_geometry` / `main_window_state`,
base64). Long ops (Build 3D / Export STL / Generate G-code) drive a
determinate `QProgressDialog` with stage labels, fed by an optional
`progress(label, frac)` hook threaded through `build_castle_relief` /
`build_castle_stage` / `build_castle_mesh` / `generate_castle_program`
(core stays headless; a callback may raise to cancel at a stage boundary —
the workers use this for the Cancel button). Icons: `gui/icons.py` ports
GuildDraw's `_make_icon` (SVG → two-state QIcon, `currentColor` recolored per
theme), called from `_apply_dark_mode`; the 11 GuildCAM drawings + 2 reused
GuildDraw icons live in `gui/resources/icons/`, with text fallback when an
SVG is absent. Suite: 79 tests green (64 + 15 new M4.6 gates). Tag `v0.4.6`
once committed.

---

### Earlier same-day snapshot (v0.4.5 — M4.5)

**M4.5 landed (same day as the diagnosis):** both stoppers closed.

*Part A — design parity.* `gui/style/theme.py` now carries GuildDraw's `QSS`
/ `QSS_DARK` verbatim (same palette, Inter stack) extended for GuildCAM's
extra widgets, plus a `CanvasPalette` for everything QPainter/VTK draws;
`guild.qss` and the League Spartan stack are gone, and no `gui/` module
contains a hex literal that isn't sourced from theme.py (layer colors come
from `core.layers` and get dark variants via `theme.layer_color`). Live
**Settings ▸ Dark Mode** toggle (placed in a Settings menu exactly like
GuildDraw's, not View as first sketched) restyles the app sheet, both
canvases, and the layer-check tints; `gui/prefs.py` persists to
`~/.guildcam/prefs.json` (GuildDraw's DEFAULTS-merge pattern); tabbed
**Preferences** dialog (Appearance / Preview resolutions / Paths); **File ▸
Open Recent** (8 entries, missing-file pruning).

*Part B — mesh fidelity.* `build_castle_mesh` now snaps every silhouette
vertex onto the true ring it belongs to (outline exterior / lens interiors
for the mask boundary; hinge-pocket rings for the pocket walls, found via
8-neighbour z-jump pairs). Demo results: axis-aligned sharp edges **98.9 % →
15.3 %**, rim-vertex ring deviation **0.0000 mm**, watertight, and — better
than the planned ±0.5 %-of-pre-fix volume check — the mesh volume now equals
the Fusion reference (**7825 vs 7826 mm³**, resolution-independent; the old
staircase under-read by a half-pixel band, ~7.8 %). STL export rebuilds at
`export_resolution_mm` in its own worker (never the preview cache); preview
normals split at 40° so footing blends shade smooth while rims stay crisp.
Closeup render is visually indistinguishable from the reference
(`_m45_closeup_*.png`; theme screenshots `_m45_theme_*.png`).

Suite: 64 tests green (57 + 7 new M4.5 gates).

---

### Earlier same-day snapshot (v0.4.0 — M4)

**M4 landed:** the params panel is now the castle — **Towers** (endpiece /
bridge / nosepad heights + hinge-pocket depth), **Walls** (superior / inferior
eyewires), **Footing** (the five exterior/interior radius pairs; Fusion
application order kept as non-exposed defaults) — plus a **Stock** panel
(blank + pad block, dashed outlines on the 2D canvas, wireframe ghost in 3D),
onion-skin + hand-finishing-allowance spinboxes, a **Zones inspector** (hover
highlights the region on the canvas; generic zones flagged), and the **castle
stage stepper** in the 3D preview (Towers → +Walls → +Footing → Full) backed
by `build_castle_stage()` in core. Every castle spinbox live-rebuilds the
preview (350 ms debounce, per-stage mesh cache). G-code now uses the UI's
`CastleParams` and ends in an op-summary dialog (op, strategy, Z floor, cut
length, est. time — `op_summaries()` in core). Legacy spike relief retired:
`relief/builder.py` deleted, `ReliefRecipe` removed from the schema, the GUI
scallop/nosepad/groove and hinge-placement groups removed, dead back-relief
G-code path removed (no-SCULPT DXFs fall back to a profile-only cut).
Suite: 57 tests green.

---

### Earlier snapshot (v0.3.0 — M3)

**M3 landed:** `cam/castle_ops.py` generates the full posterior program —
Hinge Pockets (ramped lap entry, no plunge) → Rough Relief (stock-aware) →
Fine Relief → Eyewires → Perimeter (0.4 mm onion skin, 0.1 mm hand-finishing
allowance) — written as a single `posterior_cut.nc`. Envelopes match the
reference NC: hinge floor 4.5 exact (XY to 0.02 mm), contour pass stack
7.5/5.0/2.5/0.4 identical, fine relief 4.2–10.0 exact. Two deliberate
improvements over the reference: raster relief pattern, and the rough pass
skips everything without stock above target (the reference air-cut the whole
blank at +2). Fixture screw-clearance check: clean. `flat_3175` tool +
proven acetate feeds (S10000/F750/F333) in config; GUI G-code button now
emits the castle program when SCULPT zones match. Suite: 49 tests green.

---

### Earlier same-day snapshot (v0.2.0 — M2)

**M2 landed:** `relief/castle.py` builds the full posterior — terraces from
the zone partition, hinge pockets, and order-aware sequential rolling-ball
footing blends — and **matches `Demo Project/Model.stl` with plateau error
0.0000 mm and footing-band p95 0.045 mm** (gate was ≤ 0.1; worst corner-blend
point 0.18 mm). Key discovery en route: Fusion's fillet pairs are sequential —
the first fillet rolls *through* the step corner when the radius exceeds the
wall, the second lands tangent to it — and the application order changes the
surface, so `FootingFillet` gained a `first: interior|exterior` field
(demo defaults follow the Fusion timeline). Two-level stock heightfield in;
watertight masked-grid mesh (outline + lens-hole rims stitched) in; legacy
`scallop.py`/`nosepad.py` deleted and the GUI's mesh + G-code workers now
build from the castle when SCULPT zones match. Suite: 37 tests green.

**M1 (same day):** git baseline; posterior flip in `import_dxf`;
`geometry/regions.py` partition + auto-label (demo: 9 zones, 10 canonical
edges, first try); `CastleParams` schema. *Snag:* stale editable install
(pre-Google-Drive path) — reinstalled from G:.

---

### Snapshot at the 2026-06-11 replan (pre-v0.1)

**Working (from the Sessions 1–6 spike):** DXF intake for all seven layers
(SPLINE/LWPOLYLINE/ARC/CIRCLE, Y-up convention), ISO 8624 boxing from lens
polygons, drop-cutter via `scipy` grey-dilation (ball/flat/toroid), pyclipper
profile/pocket/offset with tabs, OLGA ruled two-flank bevel (`bevel_flank`),
CHA hinge module + catalog, GRBL post, watertight two-sided mesh, pydantic
project schema + JSON save/load, PySide6 GUI shell (QPainter 2D canvas with
layer toggles, PyVista 3D preview, params panel, background mesh + G-code
workers), end-to-end synthetic-frame G-code generation. 16 smoke tests green.

**Not yet built:** everything that makes GuildCAM reproduce the maker's real
workflow — the castle pipeline (zone partitioning from SCULPT cuts, terraced
relief, rolling-ball footing fillets), the complex two-level stock model, the
five-operation CAM recipe with onion skin, the parametric castle UI, and the
STL/NC validation harness. Also: the repo is **not under git** (M1 fixes this),
no packaging, no docs.

**Code health:** core/gui separation holding (core never imports gui); 16
smoke tests, <1 s. Known issues carried from the spike: `io_import/svg.py`
npoint float-arg bug (SVG intake unused for frame fronts — deferred),
`relief/scallop.py` + `relief/nosepad.py` legacy implementations superseded by
`builder.py`, `relief/pocket.py` lacks inward tool-radius offset (caller
pre-offsets), `post/grbl.py` straight plunge (M3 adds ramp entry),
`relief/builder.py` rim not stitched (M2 makes the mesh watertight),
`preview_3d.py` `add_light()` API drift.

---

## 1. Goal & scope

Import a GuildDraw frame-front DXF → flip to the posterior → partition into
zones from the SCULPT section cuts → build the terraced, fillet-blended relief
as a heightfield → generate the five-operation single-tool GRBL program →
cut a real frame on the Guild CNC.

**v1 scope is the frame front only**, matching the Demo Project reference.
Temples, base-curve forming holding blocks, and lens patterns are post-1.0
(the user supplies reference material for each when it arises). Explicit
non-goals: machining arbitrary meshes, B-rep modeling, adaptive/roughing
strategies, multi-tool jobs.

## 2. Design ethos — the castle

This is the concept the user teaches frame makers, and it is how GuildCAM must
visually and verbally frame the posterior modeling process. Like building a
sand castle as a child:

1. **Establish the towers first.** The high, load-bearing masses of the
   posterior: the **endpieces**, the **bridge**, and the **nosepads**. Each is
   a zone extruded to its own height (demo: 5.5 / 5.3 / 10.0 mm).
2. **Connect the towers with walls.** The **eyewires** — superior and inferior
   — span between the towers at lower heights (demo: 4.8 / 4.2 mm).
3. **Blend the walls into the towers with inverted-arch footing.** Each
   tower↔wall step gets a pair of rolling-ball fillets — a convex (exterior)
   round-over at the top of the step and a concave (interior) fillet at its
   base — forming a smooth depression that connects the towers along the
   walls (demo radii: 4–48 mm per edge).

Consequences, to be applied explicitly:

- **UI framing**: the parametric panel is organized as **Towers → Walls →
  Footing** stages; the 3D preview offers a stage stepper that shows the
  castle being built (towers only → +walls → +footing) for teaching.
- **Vocabulary split**: castle terms (towers/walls/footing) are the
  *presentation and teaching* frame — UI group titles, docs, preview stages.
  The *API surface* keeps the fixed anatomical/boxing vocabulary (endpiece,
  bridge, nosepad, eyewire, A/B/DBL/ED) per the Guild Design Brief; the two
  must never be conflated in code identifiers.
- **Docs**: the user guide's modeling chapter opens with the castle metaphor.

## 3. Import contract (GuildDraw → GuildCAM — confirmed, do not break)

GuildDraw v1.0.0-rc1 is upstream. Verified against GuildDraw source 2026-06-11.

| Property | Value |
|---|---|
| Format | DXF R2000 (AC1015); SPLINE for spline curves, **LWPOLYLINE for line curves**, ARC/CIRCLE native |
| Units | True mm at 1:1 (`$INSUNITS = 4` by convention, ignored on read) |
| Y-axis | Y negated on export (DXF Y-up); ezdxf reads correctly |
| Closure | Endpoints within 0.1 mm auto-closed at export |
| Mirror | LENS / HINGE / **SCULPT** doubled across the bridge axis at export when Ghost is on |
| View | **DXF is the anterior view — GuildCAM flips to posterior on import** (mirror x → −x) |

Layer vocabulary and treatment:

| Layer | Demo contents | GuildCAM treatment |
|---|---|---|
| `OUTLINE` | 1 closed spline | Perimeter contour cut (onion skin) |
| `LENS` | 2 closed splines | Eyewire contour cuts (onion skin) |
| `HINGE` | 2 closed splines | Hinge pockets (depth parameter, ramp entry) |
| `SCULPT` | 10 straight 2-point LWPOLYLINEs (5/side) | **Zone section cuts** — partition the outline into castle zones. Any *open* SCULPT curve is a section cut; straight lines are the recommended discipline |
| `REF` | 2 datum segments | Ignored by CAM |
| `BRIDGE` | absent | Reserved (angled bridge cutaway — post-1.0) |
| `ENGRAVING` | absent (temples only) | Post-1.0 |

**Open contract question (carried from GuildDraw M9):** asymmetric frames —
two distinct LENS entities vs. symmetric mirror. Resolve during M5 hardware
validation.

## 4. Reference workflow (the behavioural spec)

`DEMO_PROJECT_TEARDOWN.md` reconstructs the user's manual Fusion 360 workflow
end-to-end and is the acceptance target for M1–M3. Summary:

- **Zones** (posterior heights): endpieces 5.5, bridge 5.3, nosepads 10.0,
  superior eyewires 4.8, inferior eyewires 4.2 mm; hinge pockets 1.0 mm deep
  into the endpieces. Anterior face flat at Z = 0.
- **Footing fillets** (exterior/interior per step edge): endpiece superior
  32/48, endpiece inferior 16/32, bridge superior 24/32, nosepad superior
  6/4, nosepad inferior 9/10 mm. Rolling-ball, constant radius.
- **Stock**: complex two-level model — 170 × 85 × 6 mm blank + 45 × 45 × 4 mm
  pad block stacked centrally (10 mm in the nosepad zone). User-editable;
  these are the defaults and they match `config/fixtures/guild_cnc.yaml`.
- **CAM**: one tool (3.175 mm single-flute flat, S10000, F750/F333), five ops
  in order — Hinge Pockets (Pocket 2D, ramp) → Rough Scallop (+2.0 mm axial)
  → Fine Scallop → Eyewires → Perimeter (Contour 2D, 2.5 mm stepdown,
  **0.4 mm onion skin — no tabs**, 0.1 mm radial hand-finishing allowance).
  ~10 min cycle.
- **Regression fixtures**: `Demo Project/` holds the DXF, STEP, STL, NC,
  setup sheet, and 22 labeled feature screenshots; `_analyze_*.py` scripts
  are reusable.

## 5. Machine & fixture contract

- Guild CNC, GRBL post. Work area 300 × 200 mm, origin lower-left, Y+ up.
- Fixture is known and fixed: `config/fixtures/guild_cnc.yaml` (six blank
  zones, 24 hold-down screw circles r = 5 mm to avoid, flip axis
  x = 201.146 mm for two-sided work, nosepad sub-zone 6 + 4 mm).
- Two-file output is the default (back program / front+profile program);
  single-file with `M0` pause is an advanced option.
- Forming parameters (base curve, pantoscopic tilt, wrap) remain metadata
  only in v1 — heat-forming happens after cutting.

## 6. Engineering principles (unchanged from the spike)

- `core/` must never import from `gui/`. Headless, scriptable; all tests run
  against core only.
- **No OpenCASCADE, CadQuery, build123d, or OpenCAMLib.** The geometry is
  heightfields + polygons by design. Drop-cutter = `scipy.ndimage`
  grey-dilation; rolling-ball footing fillets = grey morphology with
  spherical structuring elements. The castle workflow is *why* this design
  holds: terraces and ball-blends are exactly what heightfields do well.
- Boxing-system parameter names are fixed API surface (Guild Design Brief).
- One milestone per version bump; commit (and tag milestones) in git.

---

# Road to 1.0

Seven milestones. Each is small enough to finish in one or two sessions, ends
in a working app, and gets a version bump + git commit. Order matters: the
geometry core is validated against the demo STL before any CAM is rewritten,
and CAM is validated against the demo NC before any UI is built, because every
later milestone builds on trusting the layer beneath it.

> **2026-06-11 replan:** the spike's M0–M6 series (archive) is superseded.
> The Demo Project teardown showed the posterior is built as **zones +
> footing fillets** (the castle), not a distance-based scallop, and through-
> cuts use an onion skin, not tabs. The roadmap below rebuilds the relief and
> CAM layers around that ground truth, frame front only.

## M1 — Foundation & castle regions (v0.1.0) · *the towers get their ground plan* — ✅ DONE 2026-06-11

1. ✅ **`git init`** + `.gitignore` + baseline commit (full spike + Demo
   Project fixtures + replanned BUILDPLAN); committed per item; tagged
   `v0.1.0`.
2. ✅ **Flip on import**: `import_dxf(posterior=True)` (the default) mirrors
   x → −x — GuildDraw DXF is the anterior view, everything downstream is
   posterior. OD lands on +x (matching `FrameRegions` convention). One
   transform, documented in the module docstring, involution-tested.
3. ✅ **`geometry/regions.py`**: `partition_zones(outline, lenses,
   sculpt_cuts)` — cuts extended 1 mm past their endpoints (snap-tolerance
   guard; over-extension is harmless since faces outside the body are
   discarded), `unary_union(body.boundary + cuts)` → `polygonize`, slivers
   < 0.05 mm² dropped. Auto-label when 10 cuts → 9 faces and the layout
   checks pass (endpieces = extreme |x|, bridge = sole centerline-crosser,
   nosepads = nearest centerline, walls split superior/inferior by centroid
   y per side); deterministic `zone_N` fallback otherwise. `ZoneEdge` names
   every cut from its adjacent zone kinds (`endpiece_superior_od` …) — the
   footing-schedule keys for M2. **First run against the demo DXF:
   `matched=True`, 9 zones, 10/10 canonical edges.**
4. ✅ **Castle schema**: `CastleParams` (`ZoneThicknesses`, `FootingSchedule`
   of `FootingFillet` pairs, `StockDefinition` blank+pad-block,
   `hinge_pocket_depth_mm`, `onion_skin_mm`, `hand_finishing_allowance_mm`)
   with demo defaults; `for_kind()` / `for_edge()` accessors keyed by
   `Zone.kind` / `ZoneEdge.canonical`. Wired into `ProjectSchema.castle`;
   the spike `ReliefRecipe` stays as legacy until M2/M4 retire it.
5. ✅ **Tests** (`tests/test_castle_m1.py`, suite 16 → 26): flip negates x
   only + involution; demo → 9 named zones, positions (OD +x, superior +y,
   bridge crosses center), full-cover/no-overlap, 10 canonical edges;
   generic fallback (3-cut synthetic, no-cut single zone with lens hole
   preserved); castle defaults + `.guildcam` round-trip.

## M2 — Terraced relief: towers, walls, footing (v0.2.0) · *the castle stands* — ✅ DONE 2026-06-11

1. ✅ **Two-level stock heightfield**: `stock_top_heightfield()` in
   `relief/castle.py` — blank + pad block from `StockDefinition` (defaults
   170 × 85 × 6 + 45 × 45 × 4 mm centered, offsettable), on any grid.
2. ✅ **Terraced builder**: `build_castle_relief(partition, castle, hinges)`
   — zone raster (orphan boundary pixels adopt the nearest zone via EDT),
   per-zone terrace heights, sharp-walled hinge pockets at
   `endpiece − depth`. Unmatched partitions require explicit `heights`.
3. ✅ **Footing fillets — analytic, order-aware.** Not grey morphology:
   profiles are exact per-edge cross-sections in signed distance to the cut.
   STL probing (`_probe_profiles.py`) showed Fusion's pairs are
   **sequential**: when the radius exceeds the step, the first fillet rolls
   through the far corner and the second lands tangent to it — interior-first
   (endpiece/bridge edges) and exterior-first (nosepad edges) produce
   different surfaces. `FootingFillet.first` records the order; clean-probe
   match < 0.01 mm rms. Composite rule: low-side fills, then high-side
   carves win. Tall steps degrade to quarter-rounds + wall.
4. ✅ **Watertight mesh**: `build_castle_mesh()` — masked-grid top + flat
   anterior + rim stitched from the top surface's boundary edges, so outline
   *and* lens-hole rims close (spike issue fixed). Demo: watertight,
   7257 mm³, builds ~3 s at 0.3 mm.
5. ✅ **Validation gate** (`test_demo_relief_matches_fusion_stl`): demo DXF +
   default castle vs `Model.stl`, translation-only registration (the Fusion
   model lives in the DXF's frame; its y-mirror cancels GuildDraw's export
   negation): **plateaus 0.0000 mm (exact), footing band p95 0.045 mm
   (gate ≤ 0.1), worst corner blend 0.18 mm (gate ≤ 0.3)**. Pocket-wall
   sampling straddle excluded. Legacy `scallop.py`/`nosepad.py` deleted;
   GUI mesh + G-code workers now use the castle when SCULPT zones match
   (`relief/builder.py` remains as the no-SCULPT preview fallback until M4).
   Suite 26 → 37.

## M3 — The five-operation CAM recipe (v0.3.0) · *cut the castle, not the air* — ✅ DONE 2026-06-11

All in `cam/castle_ops.py`; single-file `posterior_cut.nc` output (the
demo's one-setup posterior workflow — the old two-file back/front split is
not used for frame fronts).

1. ✅ **Hinge Pockets**: pyclipper inward cascade per HINGE outline; entry
   ramps by lapping the outer ring (0.6 mm/lap) from just above local stock
   to the floor — the straight-plunge issue is closed for pockets. Floor =
   `endpiece − depth` (4.5); XY matches the reference op to 0.02 mm.
2. ✅ **Rough + Fine relief**: drop-cutter rasters (boustrophedon, 0.8 mm
   stepover, RDP-simplified). Rough = fine + 2.0 mm axial, **stock-aware**:
   emitted only where the two-level stock sits above the target, so it
   confines itself to the pad-block zone (the reference air-cut the whole
   blank at +2 — deliberate improvement; min Z 6.2 matches). Fine rides the
   castle CLS, held at stock height beyond the body so the tool never dives
   off the rim; envelope 4.2–10.0 exact vs reference. Gouge-check tested.
3. ✅ **Eyewire + Perimeter contours**: rings offset by tool radius + the
   0.1 mm hand-finishing allowance; depth passes from stock max (both
   contours cross the pad zone) at 2.5 mm stepdown ending on the **0.4 mm
   onion skin** — pass stack 7.5/5.0/2.5/0.4 identical to the reference.
   Tabs retired for frame fronts (`cam/tabs.py` stays, unused).
4. ✅ **Config**: `flat_3175` (1/8", single flute) in `tools.yaml`; acetate
   feeds set to the proven program values S10000 / F750 / F333, max DOC 2.5.
5. ✅ **Fixture safety**: `fixture_clearance_violations()` maps frame→machine
   coords (blank-zone center) and tests every path point against the screw
   keep-outs + tool radius. Demo program: clean.
6. ✅ **Gate** (`test_against_reference_nc` + lint): modal-state parse of
   `Demo Program.nc` — hinge floor, contour pass stack, rough min Z, fine
   envelope all match; GRBL lint (G21/G90/M3/M30, only F750/F333, min cut
   Z = skin, rapids above stock+5). GUI G-code button emits the castle
   program with per-op log + clearance warnings. Suite 37 → 49.

## M4 — Parametric castle UI (v0.4.0) · *immediate parametric feedback* — ✅ DONE 2026-06-12

1. ✅ **Castle panel** (replaces the relief group): **Towers** (endpiece /
   bridge / nosepad thickness, hinge-pocket depth), **Walls** (superior /
   inferior eyewire thickness), **Footing** (the five exterior/interior
   fillet radius pairs; `first` order not exposed — Fusion-timeline defaults).
   Every spinbox triggers the live 3D rebuild (350 ms debounce, ~2 s at
   preview resolution 0.3 mm); the spike relief group + hinge-placement
   group are gone (`relief/builder.py` deleted, `ReliefRecipe` retired).
2. ✅ **Stock panel**: blank L × W × T + pad block L × W × T (defaults
   unchanged); dashed outlines on the 2D canvas (included in fit-to-view)
   and a wireframe ghost in the 3D preview.
3. ✅ **CAM panel additions**: onion-skin thickness; **"Hand finishing
   allowance"** spinbox (default 0.1 mm) with the tooltip *"places radial
   leave-behind stock on contour operations"*. Profile-fallback settings
   (no-SCULPT DXFs) kept in a sub-section.
4. ✅ **Castle stage stepper** in the 3D preview: towers only → +walls →
   +footing → +pockets, backed by `build_castle_stage()` in
   `relief/castle.py` (towers stage parks the eyewire zones on a 0.6 mm
   ground slab); per-stage mesh cache, invalidated on any castle change.
5. ✅ **Zone inspector**: hovering a zone row highlights the region on the
   2D canvas (orange fill, holes respected); unmatched/generic zones and
   missing-SCULPT imports flagged in the status line.
6. ✅ G-code action produces the five-op program from the **UI's**
   `CastleParams` and ends in an op-summary dialog (op, strategy, Z floor,
   cut length, est. cutting time — `op_summaries()` in `cam/castle_ops.py`).

## M4.5 — Fit & finish stopover (v0.4.5) · *look like the Guild, model like the reference* — ✅ DONE 2026-06-12

> **Status: diagnosed, planned, and implemented 2026-06-12; tagged `v0.4.5`.**
> User direction: GuildDraw is the design reference and **must not change**;
> GuildCAM adapts to it. And the M4 preview/STL output "doesn't produce a
> result we can use" — fix the mesh before any hardware gate.
> Implementation notes vs the plan below: the dark-mode action lives in a
> **Settings** menu (GuildDraw parity beats the "View ▸" wording in task 4);
> the preview-normals task used feature-angle vertex splitting (40°) instead
> of hand-built gradient normals; and the volume sanity check was replaced by
> a stronger gate — conformed volume must match the *Fusion reference*
> (7825 vs 7826 mm³), since the pre-fix mesh systematically under-read by a
> half-pixel rim band (−7.8 %).

### Part A — Design parity with GuildDraw

**Diagnosis.** GuildCAM's GUI was styled from memory of the Guild palette,
not from GuildDraw, and the two have drifted:

| Aspect | GuildDraw (reference — `framedraft/app.py`) | GuildCAM v0.4.0 |
|---|---|---|
| Theme source | Two complete inline QSS sheets: `QSS` (light) + `QSS_DARK` (app.py:118–302), swapped live by `_toggle_dark_mode` | One light-only `gui/style/guild.qss`, loaded once at startup |
| Light palette | bg `#ffd580`, text `#1f1f1f`, inputs/buttons `#fce9c2`, borders/accents `#d4a840`, amber buttons with 1 px black border; checked = inverted black/amber | Same bg, but **inverted black buttons** (`#1a1a1a` bg / amber text), panel `#ffe8a8`, border `#c8a040` — visibly different control language |
| Dark palette | bg `#1a1a1a`, warm-grey text `#d4cfc0`, surfaces `#2a2a2a`, borders `#554433`; canvas `#1e1e1e` | **None** |
| Font | `"Inter", "Segoe UI", …` 13 px everywhere | `"League Spartan", "Poppins", Arial` (a font GuildDraw never uses) |
| Canvas | bg `#faf6ee` light / `#1e1e1e` dark; every scene/guide item has `set_dark_mode()` | Hardcoded `#fafaf5` + hardcoded grid/scale-bar/placeholder colors; 3D viewport hardcoded `#fafaf5` |
| Preferences | `framedraft/prefs.py` → `~/.guilddraw/prefs.json` (DEFAULTS-merged); 3-tab SettingsDialog (General / Toolbar / Hotkeys); recent-files list | No prefs file, no settings dialog, no recent files |
| Hardcoded styles | Centralized in the two QSS sheets | Inline `setStyleSheet` hex scattered through `gui/app.py` (toolbar strip `#ffe8a8`, status bar, log `#1a1a1a`/`#ffd580`), `params_panel.py` (grey hint labels), `dxf_canvas.py`, `preview_3d.py` (toolbar strip) |

**Plan (implementation tasks).**

1. **`gui/style/theme.py`**: port GuildDraw's `QSS` / `QSS_DARK` verbatim as
   the base (same hexes, same Inter font stack, same control styling), then
   extend both sheets for widgets GuildCAM has and GuildDraw lacks:
   `QListWidget`, `QTableWidget`/`QHeaderView` (op-summary dialog),
   `QTextEdit` (log), `QScrollArea`, `QDialogButtonBox`. Retire
   `guild.qss` and the League Spartan/Poppins stack. The log keeps its
   monospace amber-on-dark look in both themes (it already matches dark).
2. **De-hardcode**: replace every inline `setStyleSheet` hex in
   `gui/app.py` and the three widgets with theme-driven styling — either
   QSS object-name selectors (`#toolbarStrip`, `#statusBar`) or a small
   palette dataclass exposed by `theme.py` (canvas bg, grid, scale bar,
   placeholder, stock-dash, toolbar strip). One source of truth.
3. **`gui/prefs.py`** modeled line-for-line on `framedraft/prefs.py`
   (DEFAULTS + merge-on-load, silent save) → `~/.guildcam/prefs.json`.
   Initial keys: `dark_mode`, `recent_files`, `preview_resolution_mm`
   (default 0.3), `export_resolution_mm` (default 0.15), `last_output_dir`.
4. **Dark mode toggle**: checkable View ▸ Dark Mode action (mirroring
   GuildDraw's `_act_dark`) that swaps the app stylesheet live and calls
   `set_dark_mode(dark)` on `DxfCanvas` (bg `#faf6ee`/`#1e1e1e`, grid,
   scale bar, placeholder, stock dashes) and `Preview3D`
   (`set_background`). Persisted via prefs; applied at startup.
5. **Preferences dialog** patterned on GuildDraw's `SettingsDialog`
   (tabbed, OK/Cancel): General tab only for now — Appearance (dark mode),
   Preview (preview/export resolution), Paths (default output folder).
   GuildDraw's Toolbar/Hotkeys tabs have no GuildCAM equivalent yet (no
   drawing toolbar); the dialog structure leaves room for them.
6. **Recent files**: File ▸ Open Recent (prefs-backed, most recent first),
   same behaviour as GuildDraw.
7. **Acceptance**: light and dark screenshots of GuildCAM next to GuildDraw
   show the same palette, font, and control styling; toggling dark mode
   restyles every surface (both canvases included) without restart; prefs
   survive an app restart; no `setStyleSheet` call in `gui/` contains a
   hex literal that isn't sourced from `theme.py`.

### Part B — Mesh fidelity: the staircase rim

**Symptom (user report, confirmed).** The 3D preview looks jagged and
pixelated; exported STL is "jagged all over" vs the smooth Fusion reference.
Parameter behaviour is correct — only the surface artifact is wrong.

**Diagnosis (probe: `Demo Project/_probe_m45_mesh.py`, renders
`_m45_overview_flat.png`, `_m45_closeup_*.png`).**

- `build_castle_relief` rasterizes the body/zones/pockets to a square grid
  by pixel-center point-in-polygon tests; `build_castle_mesh` then emits
  only grid cells whose four corners are inside and stitches the rim along
  the mask's boundary edges — which are **axis-aligned grid segments by
  construction**. The true outline/lens splines never enter the mesh.
- Measured on the demo: **98.9 % of sharp silhouette edges are axis-aligned
  at 0.3 mm — and still 98.9 % at 0.15 mm.** Resolution shrinks the steps
  (0.31 → 0.16 mm) but cannot remove the staircase; it is topological, not
  a sampling-density problem. The Fusion reference STL is 1,299 verts /
  2,602 faces with 3.7 mm mean edges — adaptive B-rep tessellation with
  exactly-flat plateaus and smooth curved walls.
- Same mechanism makes the **hinge-pocket walls** blocky (per-pixel carve
  of the HINGE polygons).
- Compounding it, the M4 GUI exports the cached **0.3 mm preview** mesh
  (the `pockets` stage cache) — the coarsest possible variant.
- The **top surfaces are not the problem**: terraces and footing blends are
  analytic per-pixel heights (M2 gate: plateaus exact, band p95 0.045 mm).
  Smooth shading hides this on top but cannot hide the corduroy rim.
- **CAM output is unaffected.** Eyewire/perimeter/pocket toolpaths are
  pyclipper offsets of the *true* polygons, and relief ops ride the smooth
  heightfield (M3 NC gate matched the reference). The staircase exists only
  in the preview/STL artifact — but that artifact is the product's face and
  the M5 inspection record, so it must be fixed before hardware.

**Plan (implementation tasks).**

1. **Boundary-conforming rim (the fix).** After building the masked-grid
   top surface, project every boundary-ring vertex onto the nearest point
   of the true ring it belongs to (outline exterior, each lens interior,
   each hinge-pocket ring) — shapely nearest-point per ring, ring chosen by
   proximity. The Manhattan staircase becomes a chordal approximation of
   the spline with ~`resolution`-length segments (chord error ≈ res²/8R —
   microns). Keep the vertex's z (plateau/blend heights vary ≤ slope·res/2
   across the snap distance). The rim wall quads then sweep a smooth ribbon
   from the snapped top ring to the matching anterior ring.
   - Risks to handle + test: 1-pixel-wide necks and concave corners
     (snapping two adjacent verts to the same curve point → degenerate
     faces — collapse them); rings must not cross after snapping
     (`trimesh` watertight + winding checks); the M2 STL gate must still
     pass unchanged; mesh volume within ~0.5 % of pre-fix.
   - Fallback if snapping proves fragile: constrained triangulation of the
     body polygon with grid interior points (more code, new dep — only if
     needed).
2. **Decouple export from preview.** Export STL rebuilds at
   `export_resolution_mm` (default 0.15, prefs-configurable) in a worker —
   never the preview cache. Progress in the log; file dialog remembers
   `last_output_dir`.
3. **Preview polish.** Per-vertex normals from the heightfield gradient for
   the top surface (instead of `compute_normals` averaging over the rim),
   so footing blends shade smoothly and rim walls stay crisp. Re-check
   whether 0.3 mm preview still needs this after the rim fix; drop if
   redundant.
4. **Acceptance gates** (extend `_probe_m45_mesh.py` into
   `tests/test_castle_m45.py`):
   - axis-aligned fraction of sharp silhouette edges **< 20 %** (from 99 %);
   - max XY deviation of rim vertices from the true outline/lens/pocket
     rings **≤ 0.02 mm**;
   - mesh watertight, M2 STL validation gate unchanged;
   - regenerate the probe renders — closeup visually comparable to the
     reference closeup.

### M4.5 exit criteria

- [x] GuildCAM light/dark themes match GuildDraw's palette, font, and
      control styling; live toggle; prefs persisted (`~/.guildcam`)
- [x] Preferences dialog + recent files
- [x] Rim/pocket walls follow the true curves (silhouette gate < 20 %
      axis-aligned — measured 15.3 %); STL exports at export resolution and
      is visually comparable to the Fusion reference (volume 7825 vs 7826 mm³)
- [x] Full suite green including the new M4.5 gates (64); tag `v0.4.5`

## M4.6 — UI architecture stopover (v0.4.6) · *one sidebar, like the reference; never leave the user guessing*

> **Status: IMPLEMENTED 2026-06-12; tag `v0.4.6` pending commit. M5 stays
> blocked behind it.** All three parts landed (window architecture, progress
> dialogs, icon runtime); the icon SVGs were delivered by Claude Design and
> are consumed by `gui/icons.py` with text fallback. Suite 79 green.

### Part A — Main-window architecture (docks + tabs, the GuildDraw pattern)

**Diagnosis (screenshot + code, confirmed):**

- `ParamsPanel` is `setFixedWidth(290)` with the horizontal scrollbar
  *disabled* — the Footing label + spinbox-pair rows clip at the right edge,
  and six stacked groups force deep vertical scrolling ("doesn't fit").
- Both sidebars are **fixed-width children inside a QSplitter**. A splitter
  pane can be wider than its fixed child; on maximize the extra width lands
  in the right pane and the left-anchored 220 px ActionPanel leaves a dead
  empty band at the window's right edge. Maximization was never the bug —
  fixed widths in a splitter were.
- GuildDraw (the reference) has a different architecture in kind: **one**
  right `QDockWidget` (min 270 px, title bar hidden) holding a `QTabWidget`
  (Properties / Guides / Canvas / History / Library), a top icon `QToolBar`
  (20 × 20), and a status bar. GuildCAM v0.4.5 has two bespoke sidebars and
  no toolbar.
- The "GuildCAM" strip label duplicates the window title and crowds the view
  controls.

**Plan:**

1. **Right dock, tabbed params** — `QDockWidget` (RightDockWidgetArea,
   min width 300, title bar hidden, View-menu toggle action), containing a
   `QTabWidget` with four tabs (castle vocabulary in titles where it earns
   it, anatomical vocabulary in code as ever):
   - **Frame** — file info (name, raw layer summary), layer-visibility
     checks, Boxing read-outs;
   - **Castle** — Towers / Walls / Footing groups + the Zones inspector
     (hover highlight stays);
   - **Stock** — blank + pad block;
   - **CAM** — material, onion skin, hand-finishing allowance, profile
     fallback sub-section.
   `ParamsPanel` becomes the tab container; per-tab `QScrollArea`s, no fixed
   width, no horizontal clipping at the default width.
2. **Left sidebar dissolved** (supersedes the literal swap — a swapped
   220 px column would hold three buttons and a squeezed log; GuildDraw has
   exactly one sidebar and that asymmetry is the look): primary actions move
   to the toolbar (3), the log moves to a **bottom dock** (toggleable,
   default visible, ~140 px, keeps its amber-on-dark monospace in both
   themes), file identity moves to the Frame tab + status bar.
3. **Top icon QToolBar** (GuildDraw QSS already styles it; 20 × 20 icons,
   text-beside-icon fallback until the SVG set lands): Open DXF │ Build 3D
   Model · Generate G-code · Export STL │ 2D Outline / 3D Preview (checkable
   pair) · Fit │ far right: sidebar toggle. Keyboard shortcuts: F5 build,
   Ctrl+G generate, Ctrl+E export (menus updated to match).
4. **Viewport strip slimmed**: drop the `appTitle` label; the strip keeps
   only what is view-contextual — camera presets (Iso/Top/Front/Reset, icons
   later) and the castle stage stepper (**stays text** — Towers/+Walls/
   +Footing/Full are teaching labels, § 2). Zoom readout moves to the status
   bar (GuildDraw keeps transient readouts there).
5. **Window state persistence**: `main_window_geometry` / `main_window_state`
   (base64) in prefs — maximize, dock sizes, and log visibility survive a
   restart.
6. **Acceptance**: maximized light/dark screenshots show no dead band and no
   clipped controls at default sizes; every castle parameter reachable in ≤ 1
   tab click; the old ActionPanel/ParamsPanel splitter is gone; all M4.5
   acceptance still holds (no hex literals outside theme.py, live dark
   toggle restyles toolbar + docks).

### Part B — Long-operation progress feedback

**Diagnosis.** Build 3D (~2 s at 0.3 mm, much longer at fine resolutions),
STL export (0.15 mm rebuild), and G-code generation (0.15 mm relief + five
ops) report only log lines; the user reads stalls as glitches.

**Plan:**

1. **Core progress callback** (core stays headless): optional
   `progress: Callable[[str, float], None]` parameter on
   `build_castle_relief`, `build_castle_mesh`, and
   `generate_castle_program`, called at stage boundaries with a human label
   and 0–1 fraction — zone raster → terraces → footing edge *i*/*N* →
   pockets → mesh grid → rim conform; per-op for CAM (op *k*/5 + write).
   Default `None`; no GUI imports.
2. **Progress dialog**: `QProgressDialog` (window-modal, themed by the app
   QSS) driven by a `progress(str, int)` signal from MeshWorker /
   ExportWorker / GCodeWorker; label = stage text, bar = percent.
   Determinate, since the stage list is known.
3. **Cancellation at stage boundaries**: workers check a cancel flag between
   stages (mid-stage numpy work is atomic by design); Cancel button wired to
   it; cancelled builds leave the previous mesh/state untouched.
4. Status-bar text and log lines stay (the log is the durable record).

### Part C — Icon set (handoff to Claude Design)

1. **`docs/ICON-STYLE-GUIDE.md`** (written this session): GuildDraw's icon
   language captured as a spec — 20 × 20 viewBox, `stroke="currentColor"`,
   width 1.6, round caps/joins, `fill="none"`, monochrome, recolored at
   runtime per theme/state — plus per-icon briefs for the 11 GuildCAM
   drawings and the two reused verbatim from GuildDraw (`op-fit`,
   `view-sidebar`) for cross-app muscle memory.
2. **Runtime**: `gui/icons.py` ports GuildDraw's `_make_icon` (SVG →
   two-state QIcon) and an `apply_toolbar_icons(dark)` hook called from
   `_apply_dark_mode`; icons live in `gui/resources/icons/`. Actions render
   text-only until their SVG exists — drop-in, no code change on delivery.

### M4.6 exit criteria

- [x] Single right tabbed dock (Frame/Castle/Stock/CAM) + bottom log dock;
      old two-sidebar splitter deleted; no clipped controls; no dead band
      when maximized (verified: the params dock now fills to the right edge,
      tab scroll areas have no fixed width)
- [x] Icon toolbar with full keyboard/menu parity (Ctrl+O / F5 / Ctrl+G /
      Ctrl+E / Ctrl+0); viewport strip is view-contextual only (camera
      presets + text stage stepper on the 3D strip; zoom in the status bar)
- [x] Build 3D / Export STL / Generate G-code show a determinate progress
      dialog with stage labels; cancel works at stage boundaries (core hook
      may raise to abort; workers translate to a `cancelled` signal)
- [x] Window geometry/dock state persisted via prefs (base64
      `main_window_geometry` / `main_window_state`)
- [x] `docs/ICON-STYLE-GUIDE.md` delivered; `gui/icons.py` consumes SVGs
      from `gui/resources/icons/` with text fallback
- [x] Full suite green (79); tag `v0.4.6` *(pending commit)*

## M5 — Hardware round-trip (v0.5.0) · *the only gate that cuts acetate*

1. Cut the demo frame front on the Guild CNC from the GuildDraw DXF using
   M1–M4 output: hinge pockets → relief → eyewires → perimeter, onion skin,
   release by hand, compare against the Fusion-cut reference part.
2. Verify: plateau heights (calipers), pocket fit of a catalog hinge, lens
   opening size after the 0.1 mm allowance is hand-finished, skin release
   behaviour, total cycle time vs ~10 min reference.
3. Resolve the asymmetric-lens contract question with real geometry (§3).
4. **This closes GuildDraw's v1.0.0 gate** (its M9 hardware round-trip) —
   tag GuildDraw `v1.0.0` when this milestone passes.
5. Findings feed fixes; milestone ends when a cut part is accepted.

## M6 — Project I/O & two-sided workflow (v0.6.0)

1. `.guildcam` project save/load extended with the castle schema (zones,
   footing, stock, allowances) — full round-trip tests.
2. Back-side program generation for the two-sided cut-and-flip loop using the
   fixture flip axis (the spike's back/front split, now castle-aware), with
   the `M0` single-file option.
3. Export set: STL (watertight), canonical DXF archive, PNG render, archive
   bundle (project + DXF + NC + setup summary).
4. SVG intake npoint bug: fix or formally drop SVG import for v1 (DXF is the
   contract; decide here, not silently).

## M7 — Packaging, docs & release (v1.0.0)

1. PyInstaller → Windows installer (Inno Setup); frozen-build smoke test.
2. User guide: castle ethos chapter (§2 expanded with the stage-stepper
   walkthrough), zone/SCULPT drawing guidance for GuildDraw, parameter
   reference, fixture/stock setup, hand-finishing notes.
3. README, NOTICE refresh, version stamp, tag `v1.0.0`.

### 1.0 release criteria (definition of done)

- [ ] Repo under git with tagged milestones (M1)
- [ ] Demo DXF → relief matches `Model.stl` within the M2 tolerance gate
- [ ] Generated program matches `Demo Program.nc` op envelopes (M3 gate)
- [x] Castle UI: every zone/footing/stock/allowance parameter live-updates
      the preview (M4)
- [x] GuildDraw design parity (theme/dark mode/prefs) and curve-true
      preview/STL meshes (M4.5)
- [x] GuildDraw window architecture (tabbed right dock, icon toolbar,
      bottom log dock), progress dialogs on long ops (M4.6)
- [ ] **A physical frame front has been cut and accepted** (M5 — also
      graduates GuildDraw to v1.0.0)
- [ ] `.guildcam` round-trips the full castle schema; archive bundle exports
      (M6)
- [ ] Packaged Windows build + user guide with the castle chapter (M7)
- [ ] Test suite green and run before every release build

---

# Post-1.0 backlog (do not build in v1)

In rough priority order; the user supplies reference material per item as it
arises:

1. **Temples** — outline + ENGRAVING passes, temple blanks in the fixture.
2. **Base-curve forming holding blocks** — machined fixtures for post-cut
   heat-forming.
3. **Lens patterns** — pattern cutting; OLGA `bevel_flank()` (dormant since
   the spike) likely returns here for lens grooves.
4. BRIDGE angled cutaway (layer reserved in both apps).
5. `.gdraw` direct intake (multi-workspace ZIP → multi-stock project).
6. CHA hinge catalog placement UI (v1 drives pockets from the HINGE layer;
   the catalog machinery in `relief/hinge.py` stays for this).
7. STEP/B-rep export, adaptive strategies, macOS/Linux — unchanged from the
   spike's exclusion list.

---

# Reference

## Module status (as of 2026-06-12, M4.6 complete)

Statuses: ✅ solid · ⚠️ works with known issue · 🔄 to be rewritten in M-series · 🔲 stub / missing

| Module | Status | Notes |
|---|---|---|
| `core/layers.py` | ✅ | Single source of truth for layer names/styles (importers, validator, GUI all import it) |
| `io_import/dxf.py` | ✅ | All 7 layers incl. SCULPT/ENGRAVING; `posterior=True` flip is the default (M1) |
| `io_import/svg.py` | ⚠️ | npoint float-arg bug; decide fix-or-drop in M6 |
| `io_import/normalize.py` `validate.py` | ✅ | close-if-nearly-closed; OUTLINE+2×LENS checks |
| `geometry/boxing.py` | ✅ | ISO 8624 from lens polygons, MRP-based ED |
| `geometry/regions.py` | ✅ | `partition_zones` + auto-label + `ZoneEdge` naming (M1); demo DXF: 9 zones, 10 canonical edges |
| `geometry/symmetry.py` | 🔲 | Stub; needed at latest for the M5 asymmetry question |
| `relief/castle.py` | ✅ | Terraces + order-aware footing + stock + watertight mesh (M2); STL-gate verified; `build_castle_stage()` teaching stepper (M4); boundary-conforming rim — silhouette follows the true curves, volume matches the reference (M4.5); optional `progress` stage hook on relief/stage/mesh builders (M4.6) |
| `relief/builder.py` | — | **Deleted in M4** (spike fallback retired; no-SCULPT DXFs get profile-only G-code, no 3D preview) |
| `relief/groove.py` | ✅ | OLGA `bevel_flank` — dormant until lens patterns (post-1.0) |
| `relief/pocket.py` | ⚠️ | No inward tool-radius offset (caller pre-offsets); M3 hinge op wraps it |
| `relief/hinge.py` | ✅ | CHA catalog machinery — v1 uses HINGE-layer + depth instead; kept for post-1.0 |
| `relief/heightfield.py` | ✅ | Grid container; two-level stock constructor lives in `castle.py` |
| `cam/castle_ops.py` | ✅ | The five-op posterior program (M3); gated against the reference NC; `op_summaries()` setup sheet (M4) |
| `cam/dropcutter.py` | ✅ | grey-dilation ball/flat/toroid; CLS feeds the relief ops |
| `cam/profile.py` `pocketing.py` | ✅ | pyclipper offsets/cascade; castle_ops uses the pocketing cascade |
| `cam/tabs.py` | ✅ | Correct, but **retired for frame fronts** (onion skin instead); stays available |
| `post/grbl.py` | ✅ | `comment()` added; pockets enter via ramped laps (plunge issue closed); contour passes plunge ≤ one stepdown by design |
| `mesh/twosided.py` `stl_export.py` | ⚠️ | Superseded by `build_castle_mesh` for frame fronts; review/retire in M6 |
| `project/schema.py` `save_load.py` | ✅ | `CastleParams` landed (M1); legacy `ReliefRecipe` removed (M4) |
| `config/` | ✅ | fixture (incl. nosepad sub-zone), hinges, `flat_3175` tool, proven acetate feeds (M3) |
| `gui/app.py` + widgets | ✅ | Castle UI (M4); GuildDraw-parity theming, dark mode, Preferences, recent files, export-resolution STL worker (M4.5); right tabbed dock + bottom log dock + icon toolbar, progress dialogs, window-state persistence (M4.6) |
| `gui/icons.py` | ✅ | New in M4.6 — `_make_icon` port (SVG→two-state QIcon, `currentColor` recolor) + `apply_toolbar_icons`; text fallback when an SVG is missing |
| `gui/style/theme.py` `gui/prefs.py` | ✅ | New in M4.5 — GuildDraw QSS port + CanvasPalette; `~/.guildcam/prefs.json` (M4.6 adds window geometry/state keys) |
| `tests/` | ✅ | 79 green (smoke 16 + M1 10 + M2 11 + M3 12 + M4 8 + M4.5 7 + M4.6 15, incl. the STL, NC, silhouette, and progress/icon gates) |

## Dependency list (v1 — unchanged)

`pyside6`, `pyvista`, `pyvistaqt`, `numpy`, `scipy`, `shapely`, `pyclipper`,
`ezdxf`, `svgelements`, `trimesh`, `pydantic`, `pyyaml`, `pytest`,
`pyinstaller`. **Excluded by design:** OpenCASCADE, CadQuery, build123d,
OpenCAMLib.

## Repo structure (target — unchanged from the spike, plus docs/)

```
guildcam/
├── BUILDPLAN.md                # this file
├── DEMO_PROJECT_TEARDOWN.md    # behavioural spec (Fusion reference workflow)
├── OLGA_TEARDOWN_AND_PLAN.md   # OLGA reverse-engineering reference
├── Demo Project/               # ground-truth fixture set + _analyze_*.py
├── docs/
│   └── BUILDPLAN-spike-archive.md
├── src/guildcam/
│   ├── core/                   # io_import, geometry, relief, mesh, cam, post, project
│   ├── config/                 # materials, tools, fixtures/, hinges/
│   └── gui/                    # PySide6 shell (no core→gui imports)
├── tests/
└── packaging/
```

## Working agreements

- One milestone per version bump; commit (and tag milestones) in git.
- Update the **Status snapshot** and milestone checklists in this file as work
  lands; stale detail moves to `docs/`.
- The M2 (STL) and M3 (NC) validation gates run in CI/pytest before every
  milestone tag — the Demo Project fixtures are the regression suite.
- The GuildDraw import contract (§3) is frozen; changes require a
  cross-repo round-trip test.
- Castle vocabulary in the UI/docs; anatomical/boxing vocabulary in the API —
  never mixed in code identifiers (§2).
- Known-issue findings live in this file; session-to-session context lives in
  Claude's project memory.
