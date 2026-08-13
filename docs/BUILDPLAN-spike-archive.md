# GuildCAM Build Plan — Spike Archive (Sessions 1–6, 2026-06)

> **Archived 2026-06-11.** This is the original session-by-session build plan
> from the M0 spike era, preserved verbatim. It was superseded by the
> root `BUILDPLAN.md` (Road to 1.0) after the Fusion 360 Demo Project
> reference set was received and torn down (`DEMO_PROJECT_TEARDOWN.md`) —
> the redevelopment replanned the milestones around the castle pipeline.
> Module-status claims below reflect Session 6 and are superseded by the
> root document.
>
> **Note on referenced files.** The internal reference material this archive
> names — the Fusion 360 Demo Project teardown, the OLGA behavioral analysis,
> and the bed/hinge reference sketches — is kept in the maker's local working
> tree and is not part of the published repository. The Demo Project ground
> truth itself is vendored under `tests/fixtures/demo/`.

Reference: `frame_modeler_project.md` (the full spec). This document tracks the session-by-session build order and current status.

---

## Principles

- **M0 first.** Prove the two-sided cut-and-flip loop on real hardware before writing any UI. If M0 closes, the project is real.
- `core/` must never import from `gui/`. It is a headless, scriptable library. All tests run against `core/` only.
- No OpenCASCADE, CadQuery, build123d, or OpenCAMLib in v1. The geometry is heightfields + polygons by design.
- Boxing-system parameter names are fixed API surface — they must match the Guild Design Brief vocabulary.

---

## Milestone Overview

| Milestone | Scope | Status |
|---|---|---|
| **M0** | Spike: DXF in → scallop heightfield → profile-with-tabs → two GRBL files → cut real part | ✅ Pipeline fully wired in GUI — GuildDraw Phase 13 can now produce real frame DXF; only hardware cut remains |
| **M1** | Geometry core: DXF+SVG import, normalize, validate, boxing parametrics, symmetry | ⚠️ Mostly done — SVG bug deferred; `regions.py` and `symmetry.py` stubs remain; SCULPT layer intake to add |
| **M2** | CAM core: drop-cutter (scipy morphology), pyclipper profile/pocket/groove, GRBL post | ⚠️ Mostly done — straight plunge in GRBL post deferred to M2 |
| **M3** | Export & project I/O: STL, DXF archive, .guildcam save/load, PNG, archive bundle | 🔲 Not started |
| **M4** | GUI shell: PySide6 layout + PyVista preview wired to core, live parameter updates | ✅ Complete — G-code button fully wired, stock thickness param added |
| **M5** | Configs, presets, skin, handoff: material/tool/fixture YAML, guild.qss, Send-to-sender | 🔲 Not started |
| **M6** | Packaging & docs: PyInstaller → Windows installer (Inno Setup), user guide | 🔲 Not started |

---

## Session Log

### Session 1 — Project scaffold

**Goals:**
- [x] Create `pyproject.toml` with Python 3.12 pin and all v1 dependencies
- [x] Create the full `src/guildcam/` directory tree (core + gui stubs)
- [x] Verify deps install cleanly (no binary conflicts)
- [x] Wire up `pytest` with a smoke test
- [x] Create `LICENSE` (GPLv3) and `NOTICE` (third-party)

---

### Session 2 — OLGA teardown + fixture data + bevel algorithm

**Inputs received:**
- `OLGA_TEARDOWN_AND_PLAN.md` — behavioral reverse-engineering of OLGA olgaV5, CHA, BR, OLGA V1, SVGStAlone
- `cnc_bed.dxf` / `cnc_bed.svg` — Fusion 360 sketch of the Guild CNC bed in machine coordinates

**Accomplished:**
- [x] Populated `config/fixtures/guild_cnc.yaml` with real measured data:
  - Work area confirmed 300 × 200 mm (origin lower-left, Y+ up)
  - Six blank zones with exact positions, sizes, and stock thicknesses
  - 24 hold-down screw positions (machine must avoid these circles, r = 5 mm)
  - Flip axis at x = 201.146 mm (center-line of front blank, for two-sided machining)
  - Nosepad sub-zone: 6 mm sheet + 4 mm block = 10 mm total in 45 × 45 mm area
- [x] Upgraded `core/relief/groove.py`: replaced single-ring stub with `bevel_flank()`,
  a full port of OLGA's ruled two-flank bevel algorithm (olgaV5 decal1/decal2).
  Implements: JT_MITER offset, uniform arc-length resampling, CW-force, start-point
  alignment.  Old `lens_groove()` stub kept for smoke-test compatibility.

**Still blocking M0:**
- Real frame DXF from GuildDraw — **now available**: GuildDraw Phase 13 (2026-06-07)
  exports DXF R2000 with SPLINE entities, correct Y-up convention, all five layers
  (OUTLINE, LENS, BRIDGE, HINGE, REF), pre-export validated.  Any saved `.gdraw` /
  `.svg` file can be exported to DXF for intake here.

---

### Session 3 — Hinge module, boxing measurement, tabs bug-fix, integration test (current)

**Accomplished:**
- [x] Fixed `cam/tabs.py`: complete rewrite of `insert_tabs`.  Old code never toggled
  `in_tab` and emitted a single raised midpoint only.  New implementation uses a
  sorted event list (entry/exit per tab) to inject interpolated boundary waypoints;
  exit boundary emits at `z_tab` so the flat top spans the full `tab_width_mm`; the
  ramp-down is a linear motion to the next original path point at `z_cut`.
- [x] Created `core/relief/hinge.py`: full CHA vocabulary (RotationCharniere,
  EncombrementCharniere, ProfondeurPocheCharniere, InclinaisonPocheCharniere,
  InclinaisonPente, RotationPenteCharniere, ProfondeurPenteCharniere).  Exports:
  `HingeSpec`, `HingePlacement`, `hinge_pocket_polygon()`, `ramp_entry_points()`,
  `load_hinge_catalog()`.
- [x] Created `config/hinges/standard.yaml`: three catalog entries (screw_barrel_14x5p5,
  screw_barrel_14x7, spring_hinge_16x5p5 with ramped lead-in).
- [x] Added `measure_from_polygon(lens_od, lens_os)` to `geometry/boxing.py`:
  derives A/B/DBL/ED per ISO 8624 boxing system from Shapely lens polygons.
  ED uses MRP-to-outline distance (correct); DBL is the nasal-edge gap.
- [x] Added `HingeParams` to `project/schema.py` (catalog_file, hinge_name, x/y/
  rotation_deg, face); wired into `ReliefRecipe` as `hinge_od` + `hinge_os`.
- [x] Added 7 new tests (16 total, all pass):
  - tabs: raises Z, width maintained, passthrough when count=0
  - boxing: measure_from_polygon recovers A/B/DBL/ED from synthetic rectangles
  - hinge: catalog loads, pocket polygon has correct area and centroid
  - **integration**: synthetic lens polygon → bevel_flank → GRBLPost → .nc file;
    asserts G1, M3, M30 present.

**Still blocking M0:**
- Real frame DXF — see Session 2 note; GuildDraw now resolves this (Phase 13).

**Remaining known issues (unchanged from Session 2):**
- `io_import/svg.py`: npoint() float argument bug — defer to M1
- `relief/scallop.py`: back_scallop() uses centroid distance not outline distance — defer to M2
- `relief/pocket.py`: no inward tool-radius offset — document constraint, fix M1
- `post/grbl.py`: straight plunge — add ramp/helical entry before real cut (M2)

---

### Session 4 — GUI shell + 3D preview (current)

**Inputs received:**
- `hinge_th-23_front.dxf` — hinge detail drawing (layers: HINGE_POCKET, DISTANCE_TO_ENDPIECE).
  Not a full frame DXF; unrecognized layers are logged in the app.

**Accomplished:**
- [x] Built `gui/widgets/dxf_canvas.py`: custom QPainter 2D DXF viewer.
  - Zoom (mouse wheel), pan (middle/right-drag), per-layer visibility toggles.
  - 10 mm grid, scale bar, fit-to-view, layer color coding.
- [x] Built `gui/widgets/params_panel.py`: scrollable left sidebar.
  - Import group (Open DXF button + layer visibility checkboxes).
  - Boxing group (A/B/DBL/ED read-only fields, auto-populated on import).
  - Relief group (scallop, nosepad, groove — all wired to live 3D rebuild).
  - CAM group (tool, material, stepover/stepdown/tabs).
  - Hinge group (type picker, OD/OS placement — deferred to next session).
- [x] Built `gui/widgets/preview_3d.py`: PyVista Qt interactor embedded in PySide6.
  - Iso/Top/Front/Reset camera presets. Gold-tone lit surface.
  - `pyvistaqt` added to `pyproject.toml`.
- [x] Rewrote `gui/app.py`: three-panel main window (params | canvas/3D stack | actions).
  - 2D ↔ 3D toggle buttons in toolbar.
  - "Build 3D Model" button runs `MeshWorker` in background QThread.
  - Relief param changes auto-trigger rebuild when 3D view is active.
  - DXF import logs raw layer names + warns on unrecognized layers.
  - Boxing auto-computed from ≥2 valid LENS polygons and displayed in panel.
  - Fixed boxing panel rendering bug: `QFormLayout` was double-parented,
    causing A/B/DBL/ED fields to be created but never shown.
  - Fixed auto-load path (`parents[4]` → `parents[3]`).
- [x] Built `core/relief/builder.py`: unified-grid relief mesh builder for preview.
  - Single shared grid (same origin, rows, cols) for front and back — eliminates
    the shape-mismatch bug that made the back surface fall back to flat Z=0.
  - Shapely 2.0 vectorised `contains_xy` masks the grid to the frame outline
    so the mesh is frame-shaped, not a rectangular slab.
  - Numpy-vectorised scallop and nosepad (no Python pixel loops).
  - Shapely 2.0 vectorised groove distance (`shapely.distance` over point arrays).
  - Quad cells where all four corners are inside the mask become two triangles;
    rim (wall between front and back) not yet stitched — mesh is open at edges.
  - Build time ~1.2 s at 0.3 mm/px; ~120 k verts, ~240 k tris for standard front.

**Still blocking M0:**
- Wire the existing `cam/profile.py` + `post/grbl.py` pipeline to the "Generate G-code"
  button in the GUI (the core code is ready; the GUI button shows a placeholder).
- Frame DXF source: resolved by GuildDraw Phase 13.

**Known issues (session 4):**
- `relief/builder.py`: rim (edge wall between front and back) not stitched → mesh is
  not watertight. Acceptable for preview; fix before STL export (M3).
- `preview_3d.py`: PyVista `add_light()` API changed in recent versions; may need
  `pv.Light` constructor args adjusted if lighting looks wrong.
- Hinge pocket visualization not yet wired (hinge panel is UI-only, params captured
  but not passed to builder). Deferred.

---

### Session 5 — G-code generation wired (M0 pipeline complete)

**Accomplished:**
- [x] Added `GCodeWorker(QObject)` to `gui/app.py`: runs the full two-file pipeline
  off the GUI thread.
  - Back relief: `back_scallop()` → cut-depth inversion → `drop_cutter_paths()`
    → `GRBLPost` → `back_relief.nc` (skipped if scallop unchecked).
  - Front profile: `profile_cut()` → `GRBLPost` → `front_profile.nc`.
  - Loads `tools.yaml` and `materials.yaml` for tool geometry and feeds.
  - Emits progress signals wired to the action-panel log.
- [x] Replaced `_on_generate()` placeholder with real implementation:
  - Validates OUTLINE polygon is loaded.
  - Opens directory picker for output folder.
  - Launches GCodeWorker in a QThread; disables button during generation.
  - Shows summary dialog with file paths on success.
- [x] Added `_collect_gcode_params()` helper: snapshots all UI values to a plain
  dict before handing off to the worker (no Qt objects cross thread boundary).
- [x] Added `stock_thickness` spinbox (6 mm default, 2–12 mm range) to CAM
  settings group in `params_panel.py`; wired to `cam_changed` signal.
- [x] End-to-end pipeline verified: synthetic 52×38 mm frame → back_relief.nc
  (26k lines, −4.80…0.00 mm cuts) + front_profile.nc (22k lines, 4 passes).
- [x] 16 smoke tests still all passing.

**M0 status:** The full software pipeline is wired. Remaining blocker is a real
hardware cut to prove the two-sided workflow.

---

### Session 6 — Cleanup + GuildDraw integration prep (current)

**Context:** GuildDraw reached Phase 13 (2026-06-07). With a real frame DXF now
producible by GuildDraw, this session prepares GuildCAM to consume it cleanly
and closes known code-quality issues before the .gdraw validation exercise.

**Accomplished:**
- [x] Created `core/layers.py`: single source of truth for all layer names and
  styles.  Defines `ALL_LAYERS` (frozenset), `MACHINED_LAYERS`, and `LAYER_STYLES`
  (color + width per layer).  Added `SCULPT` (purple) and `ENGRAVING` (teal) for
  GuildDraw Phase 14 workspaces.
- [x] Updated `core/io_import/dxf.py` and `svg.py` to import `ALL_LAYERS` from
  `core.layers`.  `SUPPORTED_LAYERS` is kept as a public alias for backward
  compatibility.  SCULPT and ENGRAVING curves are now imported instead of silently
  discarded.
- [x] Updated `gui/widgets/dxf_canvas.py`: removed hardcoded 5-entry `LAYER_STYLES`
  dict; imports from `core.layers`.  SCULPT and ENGRAVING display correctly in the
  2D canvas.
- [x] Updated `gui/widgets/params_panel.py`: layer-visibility checkboxes now iterate
  `LAYER_STYLES` from `core.layers`.  SCULPT and ENGRAVING checkboxes present
  automatically.
- [x] Fixed `core/relief/builder.py`: added `groove_width_mm: float = 0.8` to
  `ReliefBuildParams`; `_apply_groove` now receives it as a parameter.  Previously
  the UI groove-width spinbox was wired to `relief_changed` but its value was never
  read — the builder always used a hardcoded 0.8 mm regardless.
- [x] Fixed `gui/app.py` (two silent bugs):
  - `_start_mesh_build` was not passing `stock_thickness_mm` to `ReliefBuildParams`;
    the 3D preview always rendered with 6 mm stock regardless of the spinbox value.
  - `groove_width_mm` was never passed to the builder (see above).
  - Updated ImportWorker to import `ALL_LAYERS` from `core.layers` and the
    unrecognized-layer warning to list layer names dynamically.
- [x] Removed `lens_groove()` stub from `core/relief/groove.py` (dead code, no
  callers).  Updated `relief/__init__.py` to export `bevel_flank` in its place.
- [x] Created `.venv` (Python 3.14) and installed project in editable mode with dev
  deps.  All 16 smoke tests pass.

**Next:** Receive `.gdraw` + Fusion 360 STL/NC reference pair for validation
(see GuildDraw Integration Contract section).

---

## Module Status (as of Session 6)

Statuses: ✅ solid · ⚠️ works with known issue · 🐛 bug (do not rely on) · 🔲 stub / missing

### core (top-level)

| File | Status | Notes |
|---|---|---|
| `layers.py` | ✅ | `ALL_LAYERS`, `MACHINED_LAYERS`, `LAYER_STYLES`. Single source of truth — importers, validators, and GUI widgets all import from here. |

### io_import

| File | Status | Notes |
|---|---|---|
| `dxf.py` | ✅ | LWPOLYLINE, LINE, ARC, CIRCLE, SPLINE. Imports from `core.layers`; recognizes SCULPT + ENGRAVING. GuildDraw exports Y-negated (DXF Y-up convention); ezdxf handles correctly. |
| `svg.py` | ⚠️ | `npoint()` float arg bug — defer to M1. Recognizes SCULPT + ENGRAVING via `core.layers`. |
| `normalize.py` | ✅ | close_if_nearly_closed + points_to_polygon. |
| `validate.py` | ✅ | Checks for OUTLINE + 2× LENS; iterates all layers for polygon validity. SCULPT/ENGRAVING pass through as optional layers without warnings. |

### geometry

| File | Status | Notes |
|---|---|---|
| `boxing.py` | ✅ | BoxingDimensions + `measure_from_polygon()` — ISO 8624. MRP-based ED. |
| `regions.py` | 🔲 | Empty stub. |
| `symmetry.py` | 🔲 | Empty stub. |

### relief

| File | Status | Notes |
|---|---|---|
| `heightfield.py` | ✅ | Flat constructor, pixel↔world, width/height properties. |
| `scallop.py` | ⚠️ | `back_scallop()` uses centroid distance, not outline distance. Legacy; `builder.py` has correct vectorised version. |
| `nosepad.py` | ⚠️ | Pure-Python loop — correct but slow. Legacy; `builder.py` has numpy version. |
| `groove.py` | ✅ | `bevel_flank()` only — OLGA ruled two-flank bevel. `lens_groove()` stub removed. Integration-tested. |
| `pocket.py` | ⚠️ | No inward tool-radius offset. Caller must pre-offset. Documented. |
| `hinge.py` | ✅ | HingeSpec + HingePlacement (CHA). `hinge_pocket_polygon()`, `ramp_entry_points()`, `load_hinge_catalog()`. |
| `builder.py` | ⚠️ | Unified-grid preview builder. `groove_width_mm` and `stock_thickness_mm` now properly wired from UI. Rim not stitched — open mesh. Fix before STL export (M3). |

### cam

| File | Status | Notes |
|---|---|---|
| `dropcutter.py` | ✅ | grey_dilation with hemisphere/flat/toroid structuring elements. |
| `profile.py` | ✅ | profile_cut: pyclipper JT_ROUND offset + tabs + depth passes. |
| `tabs.py` | ✅ | Event-driven entry/exit; flat top; trapezoidal ramp. |
| `pocketing.py` | ✅ | Inward offset cascade via pyclipper. |

### post

| File | Status | Notes |
|---|---|---|
| `grbl.py` | ⚠️ | `emit_polyline` straight plunge. Add ramp/helical entry (M2). |

### mesh

| File | Status | Notes |
|---|---|---|
| `twosided.py` | ✅ | Heightfield → trimesh with front/back + stitched wall. |
| `stl_export.py` | 🔲 | Not reviewed; assumed thin trimesh wrapper. |

### project

| File | Status | Notes |
|---|---|---|
| `schema.py` | ✅ | Full Pydantic models including HingeParams. ReliefRecipe carries hinge_od + hinge_os. |
| `save_load.py` | ✅ | JSON roundtrip. |

### config

| File | Status | Notes |
|---|---|---|
| `materials.yaml` | — | Not reviewed; assumed populated with acetate defaults. |
| `tools.yaml` | ✅ | ball_1mm, ball_2mm, flat_3mm, flat_6mm. |
| `fixtures/guild_cnc.yaml` | ✅ | Fully populated from cnc_bed.dxf (Session 2). |
| `hinges/standard.yaml` | ✅ | Three entries: screw_barrel_14x5p5, screw_barrel_14x7, spring_hinge_16x5p5. |

### gui

| File | Status | Notes |
|---|---|---|
| `app.py` | ✅ | Main window. DXF import, boxing, 3D build, G-code generation all wired. `stock_thickness_mm` + `groove_width_mm` bugs fixed (Session 6). |
| `widgets/dxf_canvas.py` | ✅ | QPainter 2D viewer. Zoom, pan, per-layer visibility, scale bar. LAYER_STYLES imported from `core.layers`. |
| `widgets/params_panel.py` | ✅ | All parameter groups rendered and signaling correctly. Layer checkboxes derived from `core.layers`. |
| `widgets/preview_3d.py` | ⚠️ | PyVista Qt viewer. Camera presets. `add_light()` API may need tuning. |

### tests

| File | Status | Notes |
|---|---|---|
| `test_smoke.py` | ✅ | 16 tests, all passing (Session 6). Covers: heightfield, boxing, schema roundtrip, GRBL header, validate, tabs (3), hinge catalog + polygon, integration pipeline. |

---

## Dependency List (v1)

| Package | Role |
|---|---|
| `pyside6` | GUI (Qt for Python, LGPL) |
| `pyvista` | 3D preview (VTK, Qt-embeddable) |
| `pyvistaqt` | PyVista Qt interactor — embeds VTK viewport in PySide6 |
| `numpy` | Heightfield math |
| `scipy` | Drop-cutter via `ndimage.grey_dilation`; smoothing |
| `shapely` | 2D polygon representation and general ops |
| `pyclipper` | Robust CAM-grade offsets, pocketing, profile-with-tabs |
| `ezdxf` | DXF import and canonical archive export |
| `svgelements` | SVG import (handles transforms/units) |
| `trimesh` | Watertight two-sided mesh + STL export |
| `pydantic` | Project file schema, config validation |
| `pyyaml` | Material/tool/fixture config files |
| `pytest` | Headless tests on core/ |
| `pyinstaller` | Windows packaging |

**Explicitly excluded:** OpenCASCADE, CadQuery, build123d, OpenCAMLib (see spec §2).

---

## Repo Structure (target)

```
guildcam/
├── pyproject.toml
├── LICENSE                     # GPLv3
├── NOTICE                      # Third-party licenses
├── README.md
├── BUILDPLAN.md                # this file
├── src/guildcam/
│   ├── core/
│   │   ├── io_import/          # dxf.py, svg.py, normalize.py, validate.py
│   │   ├── geometry/           # boxing.py, regions.py, symmetry.py
│   │   ├── relief/             # scallop.py, nosepad.py, groove.py, pocket.py, heightfield.py
│   │   ├── mesh/               # twosided.py, stl_export.py
│   │   ├── cam/                # dropcutter.py, profile.py, pocketing.py, tabs.py
│   │   ├── post/               # grbl.py
│   │   └── project/            # schema.py (pydantic), save_load.py
│   ├── config/
│   │   ├── materials.yaml
│   │   ├── tools.yaml
│   │   └── fixtures/
│   │       └── guild_cnc.yaml
│   ├── templates/              # template.dxf, template.svg
│   └── gui/                    # PySide6 app (thin shell, no core imports allowed back)
│       ├── app.py
│       ├── widgets/
│       ├── preview/            # PyVista/VTK viewport
│       └── style/
│           └── guild.qss
├── tests/                      # pytest, headless, core/ only
└── packaging/                  # PyInstaller spec, Inno Setup script
```

---

## Key Design Decisions (from spec)

- **Drop-cutter = grayscale morphological dilation.** `scipy.ndimage.grey_dilation` with a hemispherical (ball nose), flat disc (end mill), or composite (toroidal) structuring element. This replaces OpenCAMLib entirely.
- **Two-file GRBL output** is the default (back program / front+profile program). Single-file with `M0` pause is an advanced option.
- **Forming parameters** (base curve, pantoscopic tilt, wrap) are metadata only — not machined in v1. Heat-forming is done after cutting.
- **Fixture is known and fixed.** One bundled preset matching the Guild CNC. Advanced users can add their own via YAML.
- **Left/right symmetry toggle.** Edit one side, mirror to the other; unlock for asymmetric work.

---

## GuildDraw Integration Contract

GuildDraw is the upstream design tool; GuildCAM consumes its DXF exports.
**GuildDraw status at time of writing: Phase 13 complete (2026-06-07).**

### DXF produced by GuildDraw

| Property | Value |
|---|---|
| Format | DXF R2000 (AC1015) via ezdxf |
| Entities | SPLINE (spline/line curves), ARC, CIRCLE (native circle/arc primitives) |
| Units | True mm at 1:1; `$INSUNITS = 4` set by convention |
| Y-axis | **Y negated on export** (`y_dxf = −y_scene`) — DXF Y-up convention; ezdxf reads this correctly |
| Closure | Open endpoints auto-closed on export if within 0.1 mm |
| Mirror | OS half materialized as independent DXF entities at export |

### Layer vocabulary (GuildDraw → GuildCAM)

| Layer | GuildDraw source | GuildCAM treatment |
|---|---|---|
| `OUTLINE` | Frame outer profile (required ×1) | Machined: profile cut |
| `LENS` | Lens openings (required ×2) | Machined: lens pocket |
| `BRIDGE` | Bridge cutaway path (optional) | Machined: angled bridge cutaway |
| `HINGE` | Hinge pocket outline (optional) | Machined: hinge pocket |
| `REF` | Construction reference geometry | Not machined, ignored by CAM |
| `SCULPT` | Back-surface scallop guide curves (Phase 14, optional) | Machined: back scallop path input — add to M1 |
| `ENGRAVING` | Temple arm engraving marks (Phase 14, optional) | Machined: engraving passes — temple support in v2 |

### Upcoming: `.gdraw` project format (GuildDraw Phase 14)

GuildDraw Phase 14 introduces a `.gdraw` ZIP archive containing one SVG per workspace
(front, temple, hinge pocket) plus a `manifest.json`. GuildCAM does not need to parse
`.gdraw` directly in v1 — each workspace still exports its own `.dxf`. In v2 a
single `.gdraw` import could populate a multi-stock GuildCAM project automatically.

### Fusion 360 correlation validation (proposed, pre-M0)

To verify that GuildCAM's heightfield approach produces geometry matching a known-good
3D model, a reference validation can be run:

1. Design a frame in GuildDraw; export DXF.
2. Model the same frame in Fusion 360, generating a real machined-surface 3D body.
3. Export from Fusion 360: **STL** (ground-truth mesh) + **.nc** G-code (reference toolpaths).
4. Feed the same DXF into GuildCAM; compare its heightfield mesh and G-code against the Fusion 360 outputs.

This is brute-force but definitive for validating the scallop, nosepad, and bevel geometry.
Until this validation is done, the heightfield approach is correct by construction but
unverified against physical geometry. A `.gdraw` file + Fusion 360 STL/NC pair is the ideal
test fixture for the M0 hardware session.

---

## v2 Backlog (do not build in v1)

- Temples and temple engraving
- STEP / B-rep solid export (requires OCCT)
- Machining arbitrary imported 3D meshes (would require OpenCAMLib)
- macOS / Linux installers
- Adaptive / roughing CAM strategies
