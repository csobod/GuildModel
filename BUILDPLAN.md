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

## Status snapshot *(2026-06-11, v0.3.0 — M3 complete: the five-operation program generates and matches the reference)*

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

## M4 — Parametric castle UI (v0.4.0) · *immediate parametric feedback*

1. **Castle panel** (replaces the relief group): **Towers** (endpiece /
   bridge / nosepad thickness, hinge-pocket depth), **Walls** (superior /
   inferior eyewire thickness), **Footing** (the five exterior/interior
   fillet radius pairs). Every spinbox triggers the live 3D rebuild
   (≤ ~2 s at preview resolution).
2. **Stock panel**: blank L × W × T + pad block L × W × T (defaults above);
   redraws the stock outline in the 2D canvas and the preview.
3. **CAM panel additions**: onion-skin thickness; **"Hand finishing
   allowance"** spinbox (default 0.1 mm) with the tooltip *"places radial
   leave-behind stock on contour operations"*.
4. **Castle stage stepper** in the 3D preview: towers only → +walls →
   +footing → +pockets — the teaching visualization of §2.
5. **Zone inspector**: hovering a zone row highlights the region on the 2D
   canvas; unmatched/generic zones flagged.
6. G-code action produces the five-op program with an op-summary dialog
   (op, strategy, Z floor, est. length — the in-app setup sheet).

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
- [ ] Castle UI: every zone/footing/stock/allowance parameter live-updates
      the preview (M4)
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

## Module status (as of 2026-06-11, M3 complete)

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
| `relief/castle.py` | ✅ | Terraces + order-aware footing + stock + watertight mesh (M2); STL-gate verified |
| `relief/builder.py` | ⚠️ | No-SCULPT preview fallback only; retire in M4 with the castle UI |
| `relief/groove.py` | ✅ | OLGA `bevel_flank` — dormant until lens patterns (post-1.0) |
| `relief/pocket.py` | ⚠️ | No inward tool-radius offset (caller pre-offsets); M3 hinge op wraps it |
| `relief/hinge.py` | ✅ | CHA catalog machinery — v1 uses HINGE-layer + depth instead; kept for post-1.0 |
| `relief/heightfield.py` | ✅ | Grid container; two-level stock constructor lives in `castle.py` |
| `cam/castle_ops.py` | ✅ | The five-op posterior program (M3); gated against the reference NC |
| `cam/dropcutter.py` | ✅ | grey-dilation ball/flat/toroid; CLS feeds the relief ops |
| `cam/profile.py` `pocketing.py` | ✅ | pyclipper offsets/cascade; castle_ops uses the pocketing cascade |
| `cam/tabs.py` | ✅ | Correct, but **retired for frame fronts** (onion skin instead); stays available |
| `post/grbl.py` | ✅ | `comment()` added; pockets enter via ramped laps (plunge issue closed); contour passes plunge ≤ one stepdown by design |
| `mesh/twosided.py` `stl_export.py` | ⚠️ | Superseded by `build_castle_mesh` for frame fronts; review/retire in M6 |
| `project/schema.py` `save_load.py` | ✅ | `CastleParams` landed (M1); legacy `ReliefRecipe` retired in M2/M4 |
| `config/` | ✅ | fixture (incl. nosepad sub-zone), hinges, `flat_3175` tool, proven acetate feeds (M3) |
| `gui/app.py` + widgets | ✅ | Shell, workers, live-rebuild pattern; M4 reworks the params panel into the castle UI |
| `tests/` | ✅ | 49 green (smoke 16 + M1 10 + M2 11 + M3 12, incl. the STL and NC gates) |

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
