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

## Status snapshot *(2026-06-15, **M6.2 program-zero-from-stock-box tagged `v0.6.2`** — `ProgramZero` datum (stock-box corner/center + top/bottom, or fixture) as a rigid post-time work offset; design frame & sim unaffected; default lower-left/top. After M6.1 multi-tool (`v0.6.1`). Suite 163 green. Roadmap: M6 = "Expanded CAM operations" (✅ M6.1 multi-tool → ✅ M6.2 stock-box zero → M6.3 temples+engraving → M6.4 base-curve blocks → M6.5 worktable nesting), hardware round-trip M7, two-sided M8, packaging/v1.0.0 M9; next M6.3 temples+engraving)*

> **M6.2 — program zero from the stock box (`v0.6.2`):** `ProgramZero`
> (`project.schema`) picks G54 zero from the stock blank box — a corner/center in
> X/Y, top/bottom face in Z (default lower-left/top), or `fixture` (the old
> design-frame zero, identity offset). `GRBLPost.work_offset` shifts every posted
> coordinate (arc I/J unchanged); geometry/CLS/sim stay in the design frame, so
> M2/M3 + the simulator are untouched. CAM tab **Program Zero** group + a 2D-canvas
> datum crosshair + setup-sheet datum. Suite **163** (+12).

> **M6.1 — multi-tool jobs (`v0.6.1`):** the everyday 2 mm-pocket → 3.175 mm-bulk
> job now posts. `CamOp.tool` + `CastleCamParams.op_tools` (empty = single-tool);
> `generate_castle_program(tools_cfg=)` resolves a tool per op and `relief_ops`
> takes fine/rough tools; `post/grbl.py` `ToolSetting` + `tool_change` emit an
> `M6 Tn` (ATC) or manual-`M0` block (per `MachineProfile.tool_change_mode`) only
> where the tool differs; `build_tool_settings` resolves per-tool feeds (tool
> override or material, machine-clamped). Reach gating (`reach_warnings`) warns +
> suggests a fitting tool; the sim (`achieved_floor_grouped`) and cut-time
> (change-dwell) are tool-aware. CAM tab gains a **Per-operation tools** group.
> Suite **151** (+14).

> **M5.2 — readiness traffic-light (`v0.5.2`):** a subtle ~10 px status-bar dot
> (`gui/widgets/readiness_dot.py`) that walks grey → red → yellow → green across
> the workflow — DXF import, mesh build, and a program *stored into the open
> `.gcam`* — with the exact M5.2 tooltips, recolored per theme. The state
> machine is the pure `state_for(...)` (unit-tested without Qt); a design/CAM
> change drops green back to yellow (stale-program guard). Suite **136** (+9).

> **M5.1 — `.gcam` project container (`v0.5.1`):** `core/project/gcam.py`
> (`save_gcam`/`load_gcam`/`extract_handoff`) — a ZIP holding `project.json`
> (full schema) + the embedded `source.dxf` + `program/*.nc` + `machine.yaml` +
> `setup.json` + `cut_report.json`, with a SHA-256 manifest. Self-contained
> reopen (File ▸ Save/Open Project, `Ctrl+S`), and a documented gSender-fork
> hand-off subset (`docs/GCAM-FORMAT.md`). Generating/simulating folds the
> program/setup/report into the open `.gcam` (the M5.2 green-light hook). Suite
> **127** (+6). The dev-mode demo-DXF auto-load was removed in `v0.5.0`.
> *Workflow refinement (post-`v0.5.2`):* **the generated program lives in the
> `.gcam` by default** — Generate G-code no longer prompts for a folder or writes
> a loose `.nc`; a standalone `.nc` is an opt-in **File ▸ Export G-code**
> (`Ctrl+Shift+G`), the counterpart of Export STL (icon `op-export-gcode`).

> **M5 — cut-simulation workspace & the relief fix (`v0.5.0`):** a CAMotics sim
> showed our posterior relief left the pad-block zone uncut (lower-inner lens
> rims, around the nosepads, the bridge) — the rough pass was confined to the
> body so it never cleared the to-be-removed lens openings, which stayed 10 mm
> tall and the flat drop-cutter rode up on them. The M2/M3 gates missed it (they
> check Z envelopes & the model surface, not whether toolpaths *reach* it). Built
> a real machined-result verifier: headless `core/sim/` (tool-profile Z-buffer
> material-removal → achieved floor → completeness/gouge report), a GUI **Cut
> Simulation** workspace (3rd view + Simulate button), and **fixed the relief**
> (rim-band clearing in `relief_ops`). Demo uncut **13.7 % → 0.05 %** (worst
> 5.8 mm → 1.0 mm corner band), at/above the Fusion control, M2/M3 + cut-time
> budget still green. Suite **121** (+5 cut-completeness). Hardware is now M6.

**M4.8 — cut-time efficiency & machine-portable params (`v0.4.8`):** built a
GRBL cut-time model (`cam/cuttime.py`: assumption-free cutting-only + accel-aware
GRBL-planner cycle estimate) and drove the generated program from **~1.95× the
Fusion control to 0.87× of its cycle time** with the same finish and unchanged
M2/M3 envelopes. Two fixes did it: a **partial-lap ramp lead-in** for through-cuts
(`post/grbl.py`; Eyewires/Perimeter cut ~halved) and **relief stepover 0.8→0.9**
to match Fusion's Scallop coverage (Fine 4179→2252 mm). The rough air-plunge
concern was measured away (stock-aware rough already beats Fusion, 1.09 vs 3.27).
**User control:** `CastleCamParams` is now persisted (schema + `~/.guildcam`),
the CAM tab exposes machine/tool selectors + strategy + feeds, and a
`MachineProfile` system (`core/post/machine.py` + `config/machines/`: Guild,
Carbide Nomad 3, Carbide Shapeoko, generic GRBL, no-arc) clamps feeds/DOC,
linearizes arcs for no-arc controllers, and lints the output. Suite **111 green**
(+5 cuttime, +12 machine). *Open follow-ups:* tool-reach warning + optional
tool-change (single-tool for now), Fine-relief stay-down linking, Carbide spec
confirmation — see M4.8 below.

---

### Earlier same-day snapshot (v0.4.7 — M4.7 CAM-quality)

**M4.7 — CAM-quality pass (`v0.4.7`):** a deep compare of our output vs
`Demo Project/Demo Program.nc` (the Fusion reference) found two
toolpath-strategy defects (the 3D model/heightfield is fine — the CLS the CAM
rides matches the reference STL; only the path *pattern* was wrong). Fixed in
`core/cam/castle_ops.py` + `core/post/`:
- **Eyewires were depth-major** (OD,OS,OD,OS… at each level — 8 long lens-to-
  lens traverses). Now **ring-major** (`contour_op`: finish one ring's full
  depth stack, then the next), matching Fusion. Demo: eyewire long-rapid
  traverse **559 mm → 80 mm** (7 hops → 1).
- **Relief was an axis-aligned raster** (~96 % constant-Y rows, MeshCAM-style).
  Now **contour-parallel** (`relief_ops` + `contour_parallel_rings`): concentric
  boundary-offset rings of the body that follow the outline and eyewires,
  riding the same CLS/stock/rough masks (so the M3 envelopes are unchanged).
  Demo: ~96 % axis-aligned → **0 %**, like Fusion's Scallop.
- **Arc fitting + ramped lead-ins** (`post/arcfit.py`, `post/grbl.py`): curved
  passes emit GRBL-valid **G2/G3** (worst start/end radius mismatch 19 µm ≪
  50 µm tol), and the through-cut contours descend with a ramped lead-in over
  the stepdown instead of a straight slot-plunge.
- Suite: **94 green** (+7 `tests/test_cam_quality.py`). M3 NC gate unchanged.

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
SVG is absent. Suite: 87 tests green (64 + 23 new M4.6 gates). Tagged
`v0.4.6` (commit d8cf26f).

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

**M1–M5 scope was the frame front only**, matching the Demo Project reference.
**M6 (2026-06-15 replan) widens v1 to the whole shop job**: per-operation
tool changes (multi-tool jobs), program zero set from the stock box, **temples**
(with engraving), **auto-generated base-curve forming blocks**, and **multi-part
worktable layouts** that cut several components in one program. Temples and
base-curve blocks therefore graduate from the post-1.0 backlog into v1; only
lens patterns remain deferred. Explicit non-goals (unchanged): machining
arbitrary meshes, B-rep modeling, adaptive/roughing strategies. (Multi-tool was
a spike-era non-goal — **lifted in M6**, since the 2 mm-pocket → 3.175 mm-bulk
job is everyday production.)

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

> **Status: DONE 2026-06-12 — `v0.4.6` tagged (commit d8cf26f). M5 next.**
> All three parts landed (window architecture, progress dialogs, icon
> runtime); the full icon set (toolbar + camera presets + the 4-step castle
> stage storyboard) was delivered by Claude Design and is consumed by
> `gui/icons.py` with text fallback. Suite 87 green.

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
- [x] Full suite green (87); **`v0.4.6` tagged (commit d8cf26f)**

## M4.7 — CAM-quality pass (v0.4.7) · *cut like Fusion, not MeshCAM* — ✅ DONE 2026-06-14

> Triggered by a user review: our `posterior_cut.nc` had "a lot of optimization
> issues" vs the Fusion control `Demo Project/Demo Program.nc`. Deep compare
> (parsed both NCs) isolated the cause to **toolpath strategy, not the 3D
> model** — the heightfield/CLS the CAM rides already matches the reference STL
> (M2/M3 gates). Three fixes:

1. ✅ **Eyewires ring-major** (`contour_op`): finish one ring's full depth
   stack before the next, instead of depth-major OD/OS alternation at every
   level. Demo eyewire long lens-to-lens rapid travel **559 → 80 mm** (7→1
   hops). Perimeter (single ring) unchanged.
2. ✅ **Contour-parallel relief** (`relief_ops` + `contour_parallel_rings`):
   concentric boundary-offset rings (successive `body.buffer(-d)` erosions) that
   follow the outline and eyewires, replacing the axis-aligned Y-raster. Rides
   the **same** cls_fine / stock_cls / reach / cut_rough grids, so the M3 cut
   envelopes are unchanged — only the pattern differs. Demo: **~96 % → 0 %**
   axis-aligned, matching Fusion's Scallop.
3. ✅ **Arc fitting + ramped lead-ins** (`post/arcfit.py`, `post/grbl.py`):
   greedy Kasa circle fit emits GRBL-valid **G2/G3** on constant-Z runs (596
   arcs; worst start/end radius mismatch 19 µm ≪ 50 µm tol); through-cut
   contours descend via a ramped lead-in over the stepdown (feed through cleared
   air to z_cut+stepdown, ramp one lap to depth) — no straight slot-plunge, and
   never a `G0 Z` below safe (lint gate holds).
4. ✅ **Gate**: `tests/test_cam_quality.py` (7) — ring-major order,
   contour-parallel-not-raster, arc circle recovery, GRBL-valid arcs, ramped
   lead-in. Suite 87 → **94 green**; M3 NC gate unchanged.

**Open follow-ups (revisit — likely in M4.8):**
- **Arc aggressiveness.** We fit 596 arcs vs Fusion's 51 (ours fits shorter
  arcs / leaves fewer straight runs). Correct but verbose; tune
  `arcfit.fit_arcs` `max_window` / `tol_mm` for fewer, longer arcs once the
  cut-time harness exists to measure the trade.
- **Ramped lead-in cost.** Each contour depth pass adds one finish lap after
  the ramp lap (gentler entry, more cut time). Consider a partial-lap ramp
  (descend over a fraction, not a full lap) and make it a tunable parameter.

## M4.8 — Cut-time efficiency & machine-portable parameters (v0.4.8) · *measure against the control; let the machine set the rules* — ✅ DONE 2026-06-14

> **Status: DONE 2026-06-14.** M5 (hardware) is next. Goal met: the generated
> program went from **~1.95× slower than Fusion to 0.87× of its cycle time**
> (faster than the control), with the same surface finish and identical M2/M3
> cut envelopes; machine assumptions are no longer hard-coded — feeds/DOC/arc
> behaviour adapt to a selectable machine profile, and every time/finish knob is
> user-editable and persisted.
>
> **Result (production res 0.15 mm, cut-time model in `cam/cuttime.py`):**
>
> | Op | Fusion cycle (min) | GuildCAM cycle (min) |
> |---|---|---|
> | Hinge | 0.86 | 0.42 |
> | Rough | 3.27 | 1.09 |
> | Fine | 3.22 | 3.82 |
> | Eyewires | 1.62 | 2.00 |
> | Perimeter | 2.03 | 2.21 |
> | **Total** | **11.00** | **9.55** (0.87×) |
>
> What moved the needle: **(1) partial-lap ramp lead-in** for through-cuts
> (`post/grbl.py`) — ramp to depth over a short lead-in then one finish lap,
> replacing the full-lap-ramp + full-finish-lap (Eyewires cycle 4.32→2.00,
> Perimeter 6.12→2.21); **(2) relief stepover 0.8→0.9 mm** to match the Fusion
> Scallop's effective coverage (the 0.8 value laid redundant rings in the thin
> frame walls — Fine 4179→2252 mm, ≈ Fusion's 2204). Rough was *already* faster
> than Fusion once measured (stock-aware mask), so the plan's air-plunge concern
> (#3) was a non-issue against the control — settled with numbers, not a rewrite.

### Baseline measurement (2026-06-14, first-order estimate — the starting point)

Quick cut-time estimate of `Demo Project/GuildCAM Generated Cut (improved).nc`
(M4.7 output) vs the Fusion control `Demo Project/Demo Program.nc`. Cutting
moves at their programmed feed; arc length from IJK; rapids at an assumed
3000 mm/min (GRBL `$110/$111` are not in the file, so **cutting-only** is the
assumption-free figure). No accel/decel modeling yet — our many short segments
likely make the real gap slightly *worse*, though arc fitting helps.

| Op | Fusion cut (min) | GuildCAM cut (min) | Fusion len (mm) | GuildCAM len (mm) |
|---|---|---|---|---|
| Hinge | 0.77 | 0.35 | 282 | 238 |
| Rough | 2.99 | 3.63 | 2212 | 1420 |
| Fine | 2.97 | 5.90 | 2203 | 4179 |
| Eyewires | 1.53 | 4.24 | 1038 | 1930 |
| Perimeter | 2.10 | 6.08 | 1521 | 2793 |
| **Total cut** | **10.37** | **20.21** | | |
| Est. cycle (cut+rapid @3000) | 10.84 | 21.34 | | |

Fusion ≈ 10.4 min (matches the ~10 min setup-sheet reference — the model is
sane). **We are ~1.95× slower.** Three named causes, in priority order:

1. **Ramped lead-in double-laps the contours** (Eyewires + Perimeter). Each
   depth pass cuts a ramp lap *and* a finish lap, so our contour length is ~2×
   Fusion's (1930 vs 1038; 2793 vs 1521) — ~6.7 min of the gap. This is M4.7
   follow-up #2: a **partial-lap ramp** (descend over a fraction of the loop,
   then finish) should recover most of it.
2. **Relief path length** — our contour-parallel Fine pass is ~2× Fusion's
   Scallop (4179 vs 2203 mm). Likely 0.8 mm rings over the whole body
   (incl. flat terraces) vs Fusion's constant-scallop spacing — a
   stepover/coverage tuning question (and ties to M4.7 follow-up #1, arc
   aggressiveness).
3. **Air-plunges + extra rapids in Rough** — the stock-aware mask splits the
   rings into 133 short arcs, each retracting to safe Z and re-plunging at F333
   (Rough rapid 0.50 vs Fusion 0.17; cut time > Fusion despite *less* cut
   length). Plunge-from-safe through air is the waste; rapid-to-near + short
   plunge, or chaining adjacent arcs, would help.

The baseline table above is the starting point; the work below closed it.

1. ✅ **Cut-time model + harness** (`cam/cuttime.py`, `tests/test_cuttime.py`).
   Parses a posted GRBL program (ours *or* the Fusion control) into modal moves
   and reports two figures op-by-op: an **assumption-free cutting-only** time
   (length / programmed feed) and an **accel-aware cycle estimate** — a compact
   reimplementation of GRBL's planner (trapezoidal accel, junction-deviation
   cornering `$11`, centripetal arc-speed limiting), so the many-short-segment
   penalty is in the number. `format_report` tables it for the log / setup
   sheet; the GUI prints it after every generate. Budget test asserts our
   cutting-only total stays ≤ 1.30× the control (now ~0.9× at test res 0.3 mm).
2. ✅ **User-controllable CAM parameters.** `CastleCamParams` is now a persisted
   pydantic model (`project.schema`, re-exported from `cam.castle_ops`), on
   `ProjectSchema.cam_params` and saved in `~/.guildcam/prefs.json`
   (`cam_params` key). The CAM tab gained **Machine & Tool** (machine + tool
   selectors), **Cut Strategy** (relief stepover, contour stepdown, rough axial
   stock, ramp angle, arc tolerance) and **Feeds & Speeds** (feed/plunge/spindle
   overrides — 0 = material preset — and safe-Z clearance) groups, all bound via
   `cam_params()` / `set_cam_params()`. Defaults are the Demo reference values.
3. ✅ **GRBL-variant / machine-spec compliance.** `MachineProfile`
   (`project.schema`) + `core/post/machine.py`: `apply_machine_limits` clamps
   feed / plunge / spindle / depth-of-cut (material caps DOC too) and linearizes
   arcs (arc_tol→0) for no-arc controllers, each clamp emitting an actionable
   warning; `lint_program` checks a posted program's part-envelope fit, feed
   ceiling, spindle range and arc support; `MachineDynamics.from_profile` feeds
   the cut-time estimate per machine. Shipped profiles in `config/machines/`:
   **guild_cnc** (default), **carbide_nomad3**, **carbide_shapeoko**,
   **generic_grbl**, **grbl_no_arc** — all user-editable YAML.
4. ✅ **Acceptance**: budget green (0.87× cycle vs control); every time/finish
   knob user-editable + persisted (prefs round-trip + GUI round-trip verified);
   a non-Guild profile produces a compliant program (`grbl_no_arc`: linearized,
   lint-clean; Nomad 3: arcs kept, fits the 203 mm bed); full suite **111 green**
   (+5 cuttime, +12 machine); ready to tag `v0.4.8`.

**Open follow-ups (post-M4.8):**
- **Tool-reach warning + optional tool change** (user request 2026-06-14):
  detect when the selected tool radius is too large to reach a feature (e.g. a
  2 mm-wide hinge pocket with the 3.175 mm tool) and offer the user a tool
  change (or other resolution) for just that op. Deferred deliberately — v1
  stays single-tool; this graduates toward the post-1.0 multi-tool item.
- **Fine-relief stay-down linking.** Fine is the only op still above the control
  (3.82 vs 3.22 cycle), and only on *rapids* (retract-to-safe + replunge between
  ring paths, ~0.45 min). Recoverable with stay-down linking between adjacent
  rings, but that adds gouge risk for a small gain on an op that's already near
  Fusion — left until a hardware cut justifies it.
- **Carbide profile specs are templates** — work area / spindle / DOC vary by
  model and spindle; the shipped Nomad 3 / Shapeoko values want a real-machine
  confirmation pass.

## M4.9 — Material-driven CAM defaults & write-back (v0.4.9) · *the material sets the feeds; the maker tunes them* — ✅ DONE 2026-06-14

> Small follow-on after M4.8, alongside the cut-incompleteness diagnosis that
> re-planned M5. Selecting a material now **populates** the CAM tab's feeds,
> speeds, stepover and stepdown from that material's defaults; if the maker edits
> them and generates, GuildCAM **offers to save the changes back** as that
> material's defaults; and Preferences ▸ Materials edits or **resets to the
> shipped defaults**.

1. ✅ **Material schema + store.** `config/materials.yaml` gained
   `relief_stepover_mm` / `contour_stepdown_mm` / `rough_axial_stock_mm` per
   material (acetate 0.9/2.5/2.0; horn 0.6/0.8/1.0). New `gui/material_store.py`
   merges shipped defaults with per-user overrides in `~/.guildcam/materials.yaml`
   (the prefs DEFAULTS-merge pattern) — `effective()`, `cam_values()`,
   `changed_keys()`, `save_override()`, `reset_material()`/`reset_all()`. The
   shipped file is never written.
2. ✅ **CAM tab.** Material combo is sourced from the store; selecting a material
   loads its feeds/speeds/stepover/stepdown into the spinboxes
   (`apply_material_values`); the feeds group is "from material", not
   "0 = preset". Material + edited values persist (`material_name` pref +
   `cam_params`), restored on startup without clobbering the user's last edits.
3. ✅ **Write-back prompt.** On Generate, if the CAM values differ from the
   selected material's stored defaults, a dialog offers to save them as the new
   defaults for that material (`_maybe_write_back_material`).
4. ✅ **Preferences ▸ Materials.** Per-material editable feeds/speeds/stepover/
   stepdown with a per-material **Reset to shipped** button; OK saves overrides
   that differ from shipped and drops those that match.
5. ✅ Suite **116 green** (+5 `tests/test_materials_m4x.py`); offscreen GUI smoke
   of the populate / write-back / reset flow. (Diagnosis lives in
   `Demo Project/_diagnose_nosepad.py`; the relief fix itself is M5, behind the
   simulator.)

## M5 — Cut-simulation workspace & verification (v0.5.0) · *prove the cut before we waste acetate* — ✅ DONE 2026-06-14

> **Outcome:** built the headless simulator (`core/sim/`), the verification
> report + completeness gate, **fixed the relief incompleteness** (rim-band
> clearing in `relief_ops`), and the GUI **Cut Simulation** workspace. The fix
> took the demo from **13.7 % of the body left uncut (worst 5.8 mm) to 0.05 %
> (worst 1.0 mm = the unavoidable tool-radius corner band)** — at or better than
> the Fusion control — with the M2/M3 gates and the cut-time budget still green
> (cut-time 0.87×→1.20× of control from the extra band clearing, within the
> 1.30× budget). Suite **121 green** (+5 `tests/test_cut_completeness.py`).
> Tag `v0.5.0`. Hardware round-trip is now M6.

> **Why this jumped the queue (2026-06-14):** a CAMotics simulation of our
> program revealed the posterior relief leaves material uncut in the pad-block
> zone — the lower-inner lens rims, around the nosepads, the bridge — that
> Fusion's program clears. A throwaway achieved-floor check
> (`Demo Project/_diagnose_nosepad.py`) quantified it: **ours leaves 11.1 % of
> the body uncut (worst 5.8 mm proud); Fusion 2.3 % (worst 1.1 mm — only the
> tool-radius corner band).** Root cause: our **rough pass is confined to the
> body** (`cut_rough = reach & …`), so it never clears the to-be-removed lens
> openings / pockets; they stay at full 10 mm pad-block height, and the flat
> drop-cutter rides up on them, leaving the rims unfinished. The M3 NC-envelope
> gate and the M2 STL gate **both passed** through this — they check Z
> envelopes and the *model* surface, not whether the *toolpaths actually reach
> the whole surface*. We need a real machined-result verifier, integrated and
> visual, before trusting any cut. It's a big enough build to be its own
> milestone, and hardware (now M6) must wait behind it.

**Goal:** a **Cut Simulation** workspace — a third primary view after *2D
Outline* and *3D Model*, with its own left-toolbar button right after the 3D
Model toggle — that geometrically simulates the machined result from the
generated G-code, renders the cut piece, and flags **uncut** and **gouged**
regions against the intended surface. Geometric material-removal only (no
forces/feeds-physics); CAMotics stays a useful external cross-check.

1. ✅ **Headless simulator core** (`core/sim/`). `toolsim.py`: `ToolProfile`
   (flat = cylinder, ball = sphere, toroid = corner-radius drop profile) +
   `achieved_floor` (vectorised disc/profile Z-buffer stamping). `paths.py`:
   `cutting_paths_from_program` (modal parse, arcs flattened, rapids dropped —
   works on ours *and* the Fusion control) and `cutting_paths_from_ops`.
   Optional `progress` hook. *(Per-op playback snapshots deferred — see task 4.)*
2. ✅ **Verification report** (`report.py`): `Completeness` (uncut cells,
   max/mean excess, per-zone via shapely) + `Gouge` + `CutReport` with a
   pass/warn/fail `status()`. Gouge excludes the tool-radius band around vertical
   target steps (terrace / pocket / rim walls) — a flat tool can't machine a
   sharp concave corner cleaner than its radius, so those are unavoidable, not
   defects. `tests/test_cut_completeness.py` (+5): tool-profile units, program
   parse, and the gate (our uncut % ≤ control + margin). *(cuttime / fixture /
   machine-lint stay their own reports, surfaced on the G-code path, rather than
   merged into CutReport.)*
3. ✅ **Relief incompleteness fixed, gated by the simulator** (`relief_ops`):
   clear a tool-radius **rim band** of the to-be-removed openings/outside down to
   the nearest rim level (nearest-inside via `distance_transform_edt`), and ring
   the body grown by that band, so the finish pass reaches every rim — mirroring
   Fusion's pocket clearing. Demo uncut **13.7 % → 0.05 %**; M2/M3 gates +
   cut-time budget still green.
4. ✅ **GUI workspace.** `gui/widgets/cut_sim_view.py` `CutSimView` (PyVista
   sibling of `Preview3D`) in the stacked centre (index 2); left-toolbar
   **Simulate Cut** button after *3D Model* (new `sim-cut` icon, `Ctrl+Shift+S`);
   renders the simulated cut piece with **Uncut (red) / Gouge (orange)** overlay
   toggles + a pass/warn/fail badge; off-thread `SimWorker` (progress dialog,
   cancellable) simulates the **posted program** (so it catches post defects too);
   themed for dark/light. *(Trimmed from the sketch: the per-op playback scrubber
   and the target-ghost toggle; the cut report goes to the log + badge rather
   than a side panel — revisit if the hardware round-trip wants them.)*
5. ✅ **Acceptance:** the workspace simulates the demo program and the report
   reads "Cut verified" (0.05 % uncut); `test_cut_completeness` green; the relief
   fix keeps the M2/M3 gates and the cut-time budget green; full suite **121
   green**; tag `v0.5.0`.

## M5.1 — `.gcam` project container & gSender hand-off (v0.5.1) · *one file holds the whole job* — ✅ DONE 2026-06-14

> **Done 2026-06-14.** `core/project/gcam.py` (`save_gcam`/`load_gcam`/
> `extract_handoff`, ZIP + manifest with per-file SHA-256, atomic write); the
> layout below; File ▸ **Save Project** / **Open Project** (`.gcam`) with Open
> Recent dispatch; the source DXF is embedded so a `.gcam` reopens with no
> external files; generating G-code (and simulating) folds the program / setup /
> cut-report into the open `.gcam`; `docs/GCAM-FORMAT.md` documents the format +
> the gSender-fork hand-off subset. Suite **127 green** (+6
> `tests/test_gcam_m51.py`). Tag `v0.5.1`.

> **Plan (as built).** A single self-describing project file so a job
> can be re-opened anywhere and handed to the machine. The format is a **ZIP
> container with the `.gcam` extension** (mirroring GuildDraw's `.gdraw`
> multi-workspace ZIP for cross-app consistency) that holds *both* everything
> GuildCAM needs to fully reopen the project *and* the subset a custom **gSender
> fork** (adapted to our two-sided acetate workflow) needs to run it. This
> **supersedes the planned `.guildcam` save/load and archive bundle** (old M7
> tasks 1 + 3, now folded here).

1. ✅ **Container layout** (`core/project/gcam.py`, stdlib `zipfile`):
   - `manifest.json` — format version, GuildCAM version, created/modified, a
     content inventory + per-file SHA-256, and the run mode (two-file vs single
     `M0` program).
   - `project.json` — the full `ProjectSchema` (boxing, castle, `cam_params`,
     machine ref, stock, forming, source name) — independent reopen.
   - `source.dxf` — the imported GuildDraw DXF, so the project is self-contained
     and re-importable with no external file.
   - `program/posterior_cut.nc` (+ `back_cut.nc` once two-sided lands) — the
     generated G-code.
   - `machine.yaml` — a snapshot of the active `MachineProfile` (work area,
     feeds, accel, arc support) so the fork knows the machine's limits.
   - `setup.json` — the setup sheet: tool, feeds/speeds, op order + strategies,
     Z floors, cut lengths, estimated cycle time (`op_summaries` + `cuttime`),
     fixture/stock, onion-skin/allowance, flip axis.
   - `cut_report.json` — the verification result (completeness/gouge + cut-time)
     — evidence the program was simulated before transmission.
   - `model.stl` (optional) + `preview.png` (optional) — inspection record.
2. ✅ **API**: `save_gcam(path, *, project, dxf_bytes, programs, machine, setup,
   report, stl_bytes=None, preview_bytes=None, run_mode)` and `load_gcam(path,
   verify=True) -> GcamBundle` (+ `extract_handoff`); round-trip tests (schema +
   every file survives; SHA-256 verified on load; staged project-only save).
3. ✅ **gSender-fork contract** (`docs/GCAM-FORMAT.md`): the fork consumes
   `program/*.nc` + `machine.yaml` + `setup.json` (+ `manifest.json` for the
   two-file flip / `M0` pause) — `extract_handoff()` writes exactly that subset;
   `source.dxf` / `cut_report.json` / STL are GuildCAM-only.
4. ✅ **GUI**: File ▸ **Save Project** / **Open Project** (`.gcam`, `Ctrl+S`);
   the source DXF is embedded (`_load_dxf` keeps its bytes) so a project reopens
   with no external files; generating G-code (and simulating) folds the program /
   setup / cut-report into the open `.gcam`; Open Recent dispatches `.gcam`;
   `set_castle_params` restores the Castle/Stock tabs on open.
5. ✅ **Acceptance**: a `.gcam` round-trips the full project and reopens with no
   external files; the fork subset is present and validated; suite **127 green**
   (+6 `tests/test_gcam_m51.py`); tag `v0.5.1`.

## M5.2 — Readiness traffic-light (v0.5.2) · *is this job ready to send?* — ✅ DONE 2026-06-14

> **Status: DONE 2026-06-14 (`v0.5.2`).** A subtle ~10 px painted **dot** in
> the status-bar corner (`gui/widgets/readiness_dot.py` — colors from
> `theme.palette`, recolored per theme; tooltip carries the stage). The state
> machine is the pure `state_for(dxf_loaded, mesh_built, program_stored)` so it
> is unit-tested without Qt; `MainWindow` advances three flags — DXF import
> (→ red), any mesh-build finishing (→ yellow), and a program *stored into the
> open `.gcam`* (→ green, via the `_save_gcam_to` choke point that both Save
> Project and the generate-time auto-fold pass through). A castle/stock/CAM
> change calls `_invalidate_program()` (green → yellow, stale-program guard);
> reopening a `.gcam` with a stored program lands green once its DXF imports.
> Suite **136** (+9 `tests/test_readiness_m52.py`).
>
> A small, subtle status **dot** in the corner of the window (status-bar
> corner) that tells the maker at a glance how far the job is from
> transmittable, with the stage named in its tooltip.

1. **States + tooltips** (exact wording):
   - **grey/off** — nothing loaded (no DXF).
   - **red** — DXF imported, nothing built. Tooltip: *"DXF Loaded, Missing 3D
     Model + G-Code"*.
   - **yellow** — 3D model built. Tooltip: *"Model Built, Missing G-Code"*.
   - **green** — G-code generated **and stored to the `.gcam`**. Tooltip:
     *"Ready for Transmission"*.
2. **Widget**: a small painted circle (subtle, ~10 px) docked in the status-bar
   corner — dot only, state in the tooltip; recolored per light/dark theme.
3. **State machine** in `MainWindow`: a `_readiness` enum advanced on DXF
   import (→ red), mesh-build finished (→ yellow), and G-code-saved-to-`.gcam`
   (→ green). A design change that **invalidates the stored program drops the
   light back to yellow** (stale-program guard) so the green never lies.
4. **Acceptance**: the dot walks grey → red → yellow → green across the real
   workflow with the exact tooltips above and reverts on a stale program;
   subtle in both themes; tag `v0.5.2`. ✅ — verified by a headless walk
   (off → red → yellow → green → yellow) and `test_readiness_m52.py` (exact
   tooltip strings, four distinct theme colors per mode, the Qt-skip widget
   check); suite 136 green.

## M6 — Expanded CAM operations (v0.6.x) · *beyond the single-tool frame front*

> **2026-06-15 replan.** The original single-milestone M6 (hardware round-trip)
> is now **M7**; this M6 is the block of "real shop" CAM the maker needs before
> a hardware gate is worth running. It deliberately widens the M1–M5 scope
> (single-tool, frame-front-only) — see §1. Sub-milestones ship in order, each a
> version bump; M6.1 (multi-tool) is foundational and the others build on it.
> Hardware validation (M7) then exercises the whole expanded op set in one pass.
> No standalone `v0.6.0`: the first deliverable is M6.1 / `v0.6.1`.

### M6.1 — Multi-tool jobs & per-operation tool assignment (v0.6.1) — ✅ DONE 2026-06-15

> **Done 2026-06-15 (`v0.6.1`).** Per-op tool binding through the whole stack —
> schema → generation → post → sim → cut-time → GUI — single-tool jobs are byte-
> unchanged (every new path is opt-in behind `op_tools` / `tool_settings`). The
> demo multi-tool job (2 mm `flat_2mm` hinge pockets → 3.175 mm bulk) posts one
> clean `M0` tool-change block, lints clean, and sims at 0.04 % uncut. Suite
> **151 green** (+14 `tests/test_multitool_m61.py`).

The everyday case M1–M5 couldn't post: a **small tool (e.g. 2 mm)** clears the
hinge pockets and any tight internal radius, then a **larger tool (3.175 mm)**
does the bulk relief / eyewires / perimeter. Each op now rides its own tool.

1. ✅ **Per-op tool binding**: `CamOp.tool` (a `tools.yaml` dict + `name`);
   `CastleCamParams.op_tools` maps op → tool (empty = single-tool, the M1–M5
   behaviour) with `tool_for_op` / `tools_in_use` / `is_multi_tool`.
   `generate_castle_program(..., tools_cfg=)` resolves each op's tool and attaches
   it; the drop-cutter CLS keys off the op's tool — `relief_ops` takes
   `fine_tool` + `rough_tool` and computes the surface per distinct tool (shared
   when identical). The CAM tab has a **Per-operation tools** group (one combo
   per op, "(same as Tool)" = the global default). A new **`flat_2mm`** tool ships
   with optional per-tool feeds/DOC in `tools.yaml`.
2. ✅ **Tool-change posting** (`post/grbl.py`): `ToolSetting` + `apply_tool` /
   `tool_change` — spindle stop `M5`, retract to safe Z, then `M6 Tn` (ATC) or a
   manual-change `M0` pause with an operator prompt (per `MachineProfile.
   tool_change_mode`, Guild = `m0`), a re-zero comment, spindle restart at the
   new RPM. `write_castle_program(..., tool_settings=, tool_change_mode=)` emits a
   change only at op boundaries where the tool differs; the fixed order (pockets
   → relief → contours) keeps same-tool ops naturally grouped (one change for the
   demo). Per-tool feeds = the tool's own override or the material, clamped to the
   machine (`build_tool_settings`). Tool numbers assigned by first appearance.
3. ✅ **Tool-reach gating** (closes the M4.8 follow-up): `reach_warnings` /
   `analyze_program_reach` warn when an op's tool can't enter a feature (tool
   radius > the feature's inscribed radius) and suggest the largest fitting tool;
   surfaced in the G-code log + the summary dialog.
4. ✅ **Sim + cut-time multi-tool aware**: `achieved_floor_grouped` +
   `cutting_paths_from_program_grouped` (tool tracked from the post's announce
   comments) sweep each move with its own tool profile; `cuttime.estimate_program`
   counts change blocks and charges `tool_change_seconds` into `total_seconds`
   (kept out of the motion `cycle_seconds`); `lint_program` already checks each
   programmed feed/spindle/DOC against the machine.
5. ✅ Tests (`tests/test_multitool_m61.py`, +14): per-op binding + `.gcam`
   round-trip of `op_tools`; `m0`/`m6` change blocks parse + lint clean; per-tool
   feeds applied; reach warns/suggests (and stays quiet when the tool fits);
   change dwell in the cut-time total; and a 2 mm tool reaching a narrow pocket
   the 3.175 mm bulk tool can't enter. Single-tool post verified unchanged.

### M6.2 — Program zero from the stock box (v0.6.2) — ✅ DONE 2026-06-15

> **Done 2026-06-15 (`v0.6.2`).** A `ProgramZero` datum (stock-box corner/center
> + top/bottom face, or fixture) becomes a rigid post-time work offset — the
> toolpaths stay in the design frame so every M2/M3 envelope and the cut
> simulator are untouched. Default is the stock blank's **lower-left corner, top
> face** (what a maker touches off). Suite **163 green** (+12
> `tests/test_program_zero_m62.py`).

Makers touch off zero on the **stock blank**, not the fixture frame. The program
was implicitly zeroed to the design/fixture frame.

1. ✅ **Stock-box datum selector**: `ProgramZero` (`project.schema`) picks G54
   zero from the `StockDefinition` blank box — a corner or center in X/Y, top or
   bottom (anterior) face in Z — with `datum_world` / `work_offset` / `label`.
   The CAM tab has a **Program Zero** group (mode + X/Y/Z datum combos, X/Y/Z
   disabled in fixture mode); a crosshair **datum marker** on the 2D canvas
   (`DxfCanvas.set_program_zero`, updated on stock/CAM change) and the setup sheet
   (`program_zero` / `work_offset_mm` / `datum_world_mm`) show where zero lands.
2. ✅ **Post-time transform only**: `GRBLPost.work_offset` adds the offset to
   every emitted coordinate (rapid / feed / arc endpoints / header + end safe-Z),
   leaving arc I/J (center-relative) unchanged. Geometry / CLS / sim stay in the
   design frame — the demo cut shape is byte-identical to fixture mode, just
   translated; the simulator posts at offset 0 so completeness is independent of
   where zero is set.
3. ✅ **Fixture mode retained**: `mode="fixture"` is the identity offset (the
   current design-frame behaviour, needed for the two-sided flip axis in M8);
   stock-box is the new default for single-setup jobs. Persisted in
   `CastleCamParams.program_zero` and the `.gcam` (round-trip tested).
4. ✅ Tests (`tests/test_program_zero_m62.py`, +12): each datum's offset; the
   post applies it (I/J unchanged, safe-Z offset); the demo lands in the positive
   quadrant and is a pure translation of fixture mode; the sim is unaffected;
   fixture mode is the identity; `.gcam` round-trip; the setup sheet/label name
   the datum.

### M6.3 — Temples with engraving (v0.6.3)

Pulled forward from the post-1.0 backlog. A temple is an outline cut **plus
ENGRAVING passes**, and the engraving needs a tool change (depends on M6.1).

1. **Temple intake**: the ENGRAVING layer (reserved since M1, "temples only") +
   the temple OUTLINE — both already in the GuildDraw export contract (§3).
   Temple blanks added to `config/fixtures/guild_cnc.yaml`.
2. **Engrave op**: a shallow V-/flat-engrave toolpath following the ENGRAVING
   curves at a set depth with its own (small) tool — a tool change before/after
   via M6.1.
3. **Temple profile cut**: outline contour with onion skin like the perimeter;
   temples are flat (no castle relief), so no zone/footing machinery.
4. UI: temples are a component type alongside the frame front (feeds the M6.5
   layout); the cut-sim renders the engraved result.
5. Tests: ENGRAVING → engrave op at depth with the right tool + change blocks;
   temple profile envelope; demo temple round-trips.

### M6.4 — Base-curve forming blocks (v0.6.4)

Pulled forward: auto-generate the post-cut heat-forming holding block straight
from the frame DXF.

1. **Block geometry from the DXF**: take the **interior shape of the eyewires**
   (the LENS interiors, posterior) as the block's top profile — the surface the
   frame front is formed over. Default blank: **acetal, 1/4" (6.35 mm) thick,
   65 × 65 mm** (editable like the stock model).
2. **Mounting holes**: **three M4 drill holes spaced 10 mm apart** (default).
   Arrangement (in-line vs. triangle) and drill Ø (M4 clearance ≈ 4.5 mm vs.
   tapped ≈ 3.3 mm) are parameters. **OPEN: confirm the canonical arrangement +
   drill spec against a reference block before locking the default.**
3. **CAM**: profile-cut the 65 × 65 outline + the eyewire-interior contour/pocket
   + drill the 3 holes (peck-drill or helical-bore per tool), in acetal feeds
   (add an acetal-block entry to `materials.yaml`). Likely a drill tool change
   (M6.1).
4. UI/output: a "Generate base-curve block" action → its own program (and a
   component for the M6.5 bed); STL/preview of the block.
5. Tests: block outline = blank size; top profile tracks the lens interior;
   3 holes at spec spacing/Ø; program sims clean.

### M6.5 — Custom worktable layout & multi-part nesting (v0.6.5)

Cut several components — frame front(s), temples, base-curve block(s) — in **one
CNC program** on a user-defined bed. Builds on all of M6.1–M6.4.

1. **Bed model**: a configurable worktable (size, origin, keep-out/screw zones —
   generalizes `config/fixtures/guild_cnc.yaml` beyond the single six-zone
   blank), saved as a fixture profile.
2. **Layout workspace**: place component instances on the bed (position/rotate,
   optional simple auto-pack), each carrying its own stock + ops + tools.
   Collision/keep-out + reach checks against the bed.
3. **Combined post**: one program running the placed parts, ordered to
   **minimize tool changes across the whole bed** (group by tool, M6.1), each
   part offset to its bed position (built on the M6.2 transform), with the
   fixture clearance check over the full layout.
4. **`.gcam` extension**: the container holds the bed layout + per-component
   sources/programs (a multi-stock project — anticipates the post-1.0 `.gdraw`
   multi-workspace intake).
5. Sim + cut-time over the whole bed; readiness/lint gate the combined program.
6. Tests: a 2-part bed posts one program with correct per-part offsets + grouped
   tool changes; clearance over the layout; round-trips.

### M6 exit criteria
- [x] Per-operation tool assignment with posted, linted tool-change blocks +
      tool-reach warnings (M6.1) — `v0.6.1`
- [x] Program zero settable from the stock-box datum; fixture mode retained (M6.2)
      — `v0.6.2`
- [ ] Temples cut with ENGRAVING passes + the engraving tool change (M6.3)
- [ ] Base-curve block auto-generated from the DXF (eyewire interior + 3× M4
      holes, acetal blank) (M6.4)
- [ ] Multiple components placed on a custom bed and cut in one program (M6.5)
- [ ] Full suite green; sub-milestones tagged `v0.6.1` … `v0.6.5`

## M7 — Hardware round-trip (v0.7.0) · *the only gate that cuts acetate*

> Was M6; now validates the full M6 op set on real stock, not just the frame front.

1. Cut the demo frame front on the Guild CNC from the GuildDraw DXF using the
   M1–M5 output: hinge pockets → relief → eyewires → perimeter, onion skin,
   release by hand, compare against the Fusion-cut reference part.
2. Verify: plateau heights (calipers), pocket fit of a catalog hinge, lens
   opening size after the 0.1 mm allowance is hand-finished, skin release
   behaviour, total cycle time vs ~10 min reference.
3. **Exercise the M6 additions on real stock**: a multi-tool job (2 mm pocket →
   3.175 mm bulk) with a clean tool change, stock-box zero touch-off, a temple
   with engraving, a base-curve forming block, and a multi-part bed program.
4. Resolve the asymmetric-lens contract question with real geometry (§3).
5. **This closes GuildDraw's v1.0.0 gate** (its M9 hardware round-trip) —
   tag GuildDraw `v1.0.0` when this milestone passes.
6. Findings feed fixes; milestone ends when the cut parts are accepted.

## M8 — Two-sided workflow & export polish (v0.8.0)

> Project save/load + the archive bundle moved to **M5.1** (the `.gcam`
> container). What remains here is the two-sided cut and the leftover exports.

1. **Back-side program** generation for the two-sided cut-and-flip loop using
   the fixture flip axis (the spike's back/front split, now castle-aware, from
   M6.2 fixture mode), with the `M0` single-file option — written into the
   `.gcam` as `program/back_cut.nc`.
2. Export set beyond the `.gcam`: standalone STL (watertight), canonical DXF
   archive, PNG render — for users who want loose files.
3. SVG intake npoint bug: fix or formally drop SVG import for v1 (DXF is the
   contract; decide here, not silently).

## M9 — Packaging, docs & release (v1.0.0)

1. PyInstaller → Windows installer (Inno Setup); frozen-build smoke test.
2. User guide: castle ethos chapter (§2 expanded with the stage-stepper
   walkthrough), zone/SCULPT drawing guidance for GuildDraw, parameter
   reference, fixture/stock setup, hand-finishing notes; cut-simulation
   verification chapter; **M6 chapters — multi-tool setup, stock-box zero,
   temples + engraving, base-curve blocks, worktable layout/nesting**.
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
- [x] Cut-simulation workspace verifies the machined result (completeness +
      gouge); relief reaches the whole surface like the control (M5)
- [x] `.gcam` container round-trips the full project + carries the gSender-fork
      hand-off (M5.1); readiness traffic-light (M5.2)
- [ ] Multi-tool jobs (per-op tool change), stock-box zero, temples + engraving,
      auto base-curve blocks, and multi-part worktable layout (M6.1–M6.5)
- [ ] **A physical frame front (+ the M6 op set) has been cut and accepted**
      (M7 — also graduates GuildDraw to v1.0.0)
- [ ] Two-sided back-side program + loose exports (M8)
- [ ] Packaged Windows build + user guide with the castle + M6 chapters (M9)
- [ ] Test suite green and run before every release build

---

# Post-1.0 backlog (do not build in v1)

In rough priority order; the user supplies reference material per item as it
arises. (**Temples** and **base-curve forming blocks** were moved *into* v1 by
the 2026-06-15 M6 replan and are no longer listed here.)

1. **Lens patterns** — pattern cutting; OLGA `bevel_flank()` (dormant since
   the spike) likely returns here for lens grooves.
2. BRIDGE angled cutaway (layer reserved in both apps).
3. `.gdraw` direct intake (multi-workspace ZIP → multi-stock project) — the M6.5
   bed layout already moves the `.gcam` toward multi-stock, so this is the intake
   half.
4. CHA hinge catalog placement UI (v1 drives pockets from the HINGE layer;
   the catalog machinery in `relief/hinge.py` stays for this).
5. STEP/B-rep export, adaptive strategies, macOS/Linux — unchanged from the
   spike's exclusion list.

---

# Reference

## Module status (as of 2026-06-15, M6.2 complete)

Statuses: ✅ solid · ⚠️ works with known issue · 🔄 to be rewritten in M-series · 🔲 stub / missing

| Module | Status | Notes |
|---|---|---|
| `core/layers.py` | ✅ | Single source of truth for layer names/styles (importers, validator, GUI all import it) |
| `io_import/dxf.py` | ✅ | All 7 layers incl. SCULPT/ENGRAVING; `posterior=True` flip is the default (M1) |
| `io_import/svg.py` | ⚠️ | npoint float-arg bug; decide fix-or-drop in M8 (export polish) |
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
| `cam/castle_ops.py` | ✅ | The five-op posterior program (M3); gated against the reference NC; `op_summaries()` setup sheet (M4); contour-parallel relief + ring-major eyewires (M4.7); relief stepover 0.9 + ramp-angle param + `CastleCamParams` from schema (M4.8); **rim-band clearing in `relief_ops`** so the finish pass reaches every rim (M5 — uncut 13.7 %→0.05 %); **per-op tools** — `CamOp.tool`, `generate_castle_program(tools_cfg=)`, `relief_ops(fine_tool, rough_tool)`, `reach_warnings`/`analyze_program_reach`, `build_tool_settings`/`count_tool_changes` (M6.1) |
| `cam/cuttime.py` | ✅ | **New (M4.8)** — GRBL cut-time model: assumption-free cutting-only + accel-aware GRBL-planner cycle estimate; `format_report`; `MachineDynamics.from_profile`; drove the 1.95×→0.87× gap close; **tool-change count + dwell → `total_seconds`** (M6.1) |
| `core/sim/` | ✅ | **New (M5)** — geometric cut simulation: `toolsim.py` (`ToolProfile` flat/ball/toroid + `achieved_floor` Z-buffer), `paths.py` (cutting paths from posted program or CamOps), `report.py` (`verify` → completeness/gouge `CutReport`); the machined-result verifier that caught the relief incompleteness; **multi-tool** `achieved_floor_grouped` + `cutting_paths_from_program_grouped` (per-move tool profiles) (M6.1) |
| `cam/dropcutter.py` | ✅ | grey-dilation ball/flat/toroid; CLS feeds the relief ops |
| `cam/profile.py` `pocketing.py` | ✅ | pyclipper offsets/cascade; castle_ops uses the pocketing cascade |
| `cam/tabs.py` | ✅ | Correct, but **retired for frame fronts** (onion skin instead); stays available |
| `post/grbl.py` | ✅ | ramped pocket laps + `arc()` G2/G3 + arc-fit (M4.7); **partial-lap ramp lead-in** for through-cuts (M4.8); **`ToolSetting` + `apply_tool`/`tool_change`** (M0/M6 change blocks) + multi-tool `write_castle_program` (M6.1); **`work_offset`** — program-zero datum applied to every emitted coordinate, arc I/J untouched (M6.2) |
| `post/arcfit.py` | ✅ | greedy least-squares circle fit, polyline → G2/G3 arcs (constant-Z runs only); GRBL-valid radius agreement (M4.7) |
| `post/machine.py` | ✅ | **New (M4.8)** — load/list `MachineProfile`s, `apply_machine_limits` (clamp feed/plunge/spindle/DOC, linearize arcs), `lint_program` (envelope/feed/spindle/arc checks) |
| `mesh/twosided.py` `stl_export.py` | ⚠️ | Superseded by `build_castle_mesh` for frame fronts; review/retire in M6 |
| `project/schema.py` `save_load.py` | ✅ | `CastleParams` (M1); legacy `ReliefRecipe` removed (M4); `CastleCamParams` + `MachineProfile` + `MachineRef` on `ProjectSchema` (M4.8); **`op_tools` per-op map + `POSTERIOR_OPS`; `MachineProfile.tool_change_mode`/`tool_change_seconds`** (M6.1); **`ProgramZero` datum (datum_world/work_offset/label) on `CastleCamParams.program_zero`** (M6.2) |
| `project/gcam.py` | ✅ | **New (M5.1)** — `.gcam` ZIP project container: `save_gcam`/`load_gcam` (manifest + per-file SHA-256, atomic write), `extract_handoff` (gSender-fork subset); embeds the source DXF for self-contained reopen |
| `config/` | ✅ | fixture (nosepad sub-zone), hinges, `flat_3175` tool, acetate feeds (M3); **`machines/` profiles: guild_cnc, carbide_nomad3, carbide_shapeoko, generic_grbl, grbl_no_arc** (M4.8); **`flat_2mm` pocket tool + optional per-tool feeds/DOC; `tool_change_mode` in machine YAML** (M6.1) |
| `gui/app.py` + widgets | ✅ | Castle UI (M4); theming/dark/prefs/recent/STL (M4.5); docks + icon toolbar + progress (M4.6); CAM machine/tool selectors + strategy + feeds, machine-clamp/lint + cut-time report (M4.8); material-driven feeds + write-back prompt + Materials prefs tab (M4.9); Cut Simulation workspace (`SimWorker` + Simulate toolbar button, 3rd view) (M5); **File ▸ Save/Open Project `.gcam` + embedded-DXF retention + `set_castle_params` restore** (M5.1); **readiness traffic-light** — three flags + `_refresh_readiness`/`_invalidate_program`, green only on program-stored-to-`.gcam` (M5.2); **Generate stores the program in the project by default + File ▸ Export G-code (`Ctrl+Shift+G`) for a loose `.nc`** (post-M5.2 refinement); **Per-operation tools group; generate/sim workers wire `tools_cfg` + `tool_settings` + reach warnings + tool-change cut-time** (M6.1); **Program Zero group + `DxfCanvas.set_program_zero` datum crosshair + work-offset into the generate post + setup-sheet datum** (M6.2) |
| `gui/widgets/cut_sim_view.py` | ✅ | **New (M5)** — `CutSimView` PyVista viewport: renders the simulated cut piece, Uncut/Gouge overlay toggles, pass/warn/fail badge |
| `gui/widgets/readiness_dot.py` | ✅ | **New (M5.2)** — status-bar `ReadinessDot` (painted ~10 px circle, theme-recolored, exact tooltips) + the pure `state_for(...)` state machine |
| `gui/material_store.py` | ✅ | **New (M4.9)** — shipped + user-override material presets (`~/.guildcam/materials.yaml`); `effective`/`cam_values`/`changed_keys`/`save_override`/`reset_material` |
| `gui/icons.py` | ✅ | M4.6 — `_make_icon` port (SVG→two-state QIcon) + `apply_toolbar_icons`; text fallback; `sim-cut` icon added (M5) |
| `gui/style/theme.py` `gui/prefs.py` | ✅ | M4.5 — GuildDraw QSS + CanvasPalette; `~/.guildcam/prefs.json` (M4.6 window state; M4.8 `cam_params`; M4.9 `material_name`) |
| `tests/` | ✅ | **163 green** (smoke 16 + M1 10 + M2 11 + M3 12 + M4 8 + M4.5 7 + M4.6 23 + CAM-quality 7 + cuttime 5 + machine 12 + materials 5 + cut-completeness 5 + gcam 6 + readiness 9 + multitool 14 + **program-zero 12**, incl. STL/NC/silhouette/arc/ramp/budget/clamp/completeness gates + the `.gcam` round-trip + the readiness state machine + the M6.1 per-op-tool/change-block/reach/tool-aware-sim gates + the M6.2 datum-offset/pure-translation/sim-unaffected gates) |

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
