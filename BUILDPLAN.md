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

## Status snapshot *(2026-06-11, v0.1.0 — M1 complete: repo under git, posterior flip, castle zone partitioning + schema)*

**M1 landed (same day as the replan):** repo initialized with the full spike
as the baseline commit; `import_dxf(posterior=True)` is the single
anterior→posterior flip point; `geometry/regions.py` partitions the demo DXF
into the 9 auto-labeled castle zones with all 10 step edges canonically named
(verified: `matched=True` on first run against the Demo Project DXF);
`CastleParams` schema (zones / footing / stock / allowances, demo defaults)
round-trips through `.guildcam` save/load. Suite: 26 tests green.
*Snag fixed en route:* the venv's editable install pointed at a stale
`C:\Users\Chad\Documents\...` path from before the repo moved under Google
Drive — reinstalled from the G: location.

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

## M2 — Terraced relief: towers, walls, footing (v0.2.0) · *the castle stands*

1. **Two-level stock heightfield**: blank + centered pad block (defaults
   170 × 85 × 6 + 45 × 45 × 4 mm), the heightfield analogue of the user's
   complex Fusion stock model — both preview and CAM read it, so toolpaths
   never cut air expecting the wrong stock height.
2. **Terraced builder** replacing the distance-based scallop in
   `relief/builder.py`: rasterize zones → assign per-zone Z (towers first,
   then walls) → cut the hinge pockets (HINGE outline at depth).
3. **Footing fillets**: rolling-ball blends along each step edge with the
   per-edge exterior/interior radii (grey morphology, spherical element,
   masked per edge).
4. **Watertight mesh**: stitch the rim wall (closes the spike's open-mesh
   issue); STL export of the preview mesh.
5. **Validation harness (the M2 gate)**: pytest builds the relief from the
   demo DXF + default castle params and diffs against
   `Demo Project/Model.stl` — plateau levels exact (±0.02 mm), blended
   regions within tolerance (define empirically, target ≤0.1 mm at 95th
   percentile over machined surfaces). Legacy `relief/scallop.py` /
   `relief/nosepad.py` deleted once the harness is green.

## M3 — The five-operation CAM recipe (v0.3.0) · *cut the castle, not the air*

1. **Hinge Pockets**: pocket from the HINGE outline at the depth parameter,
   **ramp entry** (closes the `post/grbl.py` straight-plunge issue), cut
   first while the stock is rigid. Stepover 1.2 mm default.
2. **Rough relief**: the fine pattern offset +2.0 mm axial / 0.1 mm radial,
   0.8 mm stepover. **Fine relief**: zero stock to leave, same stepover.
3. **Eyewire + Perimeter contours**: 2.5 mm max stepdown, **0.4 mm onion
   skin** (axial stock above the anterior face — *tabs are retired for frame
   fronts*; `cam/tabs.py` stays available but unused), **hand-finishing
   allowance** 0.1 mm radial on both contour ops.
4. **Tool/material config**: add the 3.175 mm single-flute flat end mill to
   `tools.yaml`; S10000 / F750 cut / F333 ramp into `materials.yaml` acetate.
5. **Fixture safety**: assert no toolpath enters a hold-down screw circle.
6. **Validation (the M3 gate)**: per-op Z envelopes, pass counts, and XY
   extents match `Demo Program.nc` (op-by-op assertions from the teardown
   table); generated program runs through a GRBL syntax lint.

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

## Module status (as of 2026-06-11, M1 complete)

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
| `relief/builder.py` | 🔄 | Distance-scallop preview builder → M2 terraced castle builder |
| `relief/scallop.py` `nosepad.py` | 🔄 | Legacy; deleted when the M2 harness is green |
| `relief/groove.py` | ✅ | OLGA `bevel_flank` — dormant until lens patterns (post-1.0) |
| `relief/pocket.py` | ⚠️ | No inward tool-radius offset (caller pre-offsets); M3 hinge op wraps it |
| `relief/hinge.py` | ✅ | CHA catalog machinery — v1 uses HINGE-layer + depth instead; kept for post-1.0 |
| `relief/heightfield.py` | ✅ | M2 extends with two-level stock constructor |
| `cam/dropcutter.py` | ✅ | grey-dilation ball/flat/toroid |
| `cam/profile.py` `pocketing.py` | ✅ | pyclipper offsets/cascade; M3 re-parameterizes (skin + allowance) |
| `cam/tabs.py` | ✅ | Correct, but **retired for frame fronts** (onion skin instead); stays available |
| `post/grbl.py` | ⚠️ | Straight plunge → M3 ramp entry |
| `mesh/twosided.py` `stl_export.py` | ✅ | M2 stitches the builder rim for watertight preview/STL |
| `project/schema.py` `save_load.py` | ✅ | `CastleParams` landed (M1); legacy `ReliefRecipe` retired in M2/M4 |
| `config/` | ✅ | fixture (incl. nosepad sub-zone), hinges; M3 adds the 1/8" tool + acetate feeds |
| `gui/app.py` + widgets | ✅ | Shell, workers, live-rebuild pattern; M4 reworks the params panel into the castle UI |
| `tests/` | ✅ | 26 green (`test_smoke.py` 16 + `test_castle_m1.py` 10); M2 adds the STL harness |

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
