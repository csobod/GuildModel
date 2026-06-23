# BUILDPLAN.md — GuildCAM · Road to Version 1.0

A focused, open-source CAM application for acetate / horn eyewear manufacture.
Built on Python + PySide6 (Qt 6) over a headless, scriptable `core/`. Single
purpose: take a GuildDraw model (a `.gdraw`, or a per-component DXF), build the
posterior relief of the frame front the way a maker actually models it — together
with its temples and a base-curve forming template per lens — nest them on the
worktable, generate the GRBL program(s) for the Guild CNC, and prove the result on
real stock — and nothing else.

> **This document is the v1.0 roadmap.** The original spike-era build plan
> (Sessions 1–6, M0 pipeline) is archived verbatim at
> **`docs/BUILDPLAN-spike-archive.md`**. The behavioural ground truth this
> roadmap is built against is **`DEMO_PROJECT_TEARDOWN.md`** (the user's manual
> Fusion 360 workflow, fully reconstructed from `Demo Project/`). OLGA
> behavioural reverse-engineering lives in `OLGA_TEARDOWN_AND_PLAN.md`;
> the GuildDraw-side export contract is `BUILDPLAN.md` §2 in the GuildDraw repo.

---

## Status snapshot *(2026-06-16, **M6 COMPLETE — M6.5 worktable-nesting tagged `v0.6.5`** — File ▸ Generate Worktable Program cuts the frame front + its base-curve block in ONE program, auto-packed onto the fixture zones and scheduled to minimise tool changes across the bed (demo 2-part bed = 1 change). M6 "Expanded CAM operations" all done: ✅ M6.1 multi-tool → ✅ M6.2 stock-box zero → ✅ M6.3 temples+engraving → ✅ M6.4 base-curve blocks → ✅ M6.5 worktable nesting. Suite 197 green. Roadmap (2026-06-18 reorientation replan): **M7 reorientation** — one `.gdraw` → a multi-component project (frame front + both temples + a per-lens base-curve template), per-component 3D workspace tabs, an interactive worktable from a tagged bed DXF, role-matched auto-nesting, and combined-or-per-component G-code (`v0.7.1`–`v0.7.6`) — then hardware round-trip M8 (the only gate that cuts acetate — also graduates GuildDraw to v1.0.0), two-sided M9, rename-decision + packaging/v1.0.0 M10. **M7.1 project model ✅ DONE (`v0.7.1`) + M7.2 `.gdraw` intake ✅ DONE (`v0.7.2`, 233 tests — reader + File ▸ Open Model + the component notebook: a tab per component, tab-switch rebinds the active component) + M7.3 per-component notebook ✅ DONE (`v0.7.3`, 234 tests — component tabs + kind-aware editable param dock (Temple/Base Curve tabs) + per-component param persistence) + M7.4 interactive worktable ✅ DONE (`v0.7.4`, 247 tests — `Worktable`/`WorktableZone`/`BedRole` model in `project/schema.py` (role-tagged zone polygons + keep-out polygons in machine coords; `from_fixture_dict`/`to_fixture_dict` load the Guild `guild_cnc.yaml` as the default bed and bridge back onto the M6.5 layout machinery unchanged); `core/cam/worktable.py` reads a bed DXF → `polygonize`d regions, `default_worktable`, `.bed` YAML I/O; GUI: a trailing **Worktable** tab (peer of the components) with a machine-coords `BedCanvas` — import a bed DXF / load the Guild bed, click a region, tag its role (frame-front / temple R-L / base-curve R-L / keep-out); persisted in the `.gcam`) + M7.5 per-component 3D models ✅ DONE (`v0.7.5`, 258 tests — `core/relief/flat.py` reuses the castle mesher for flat parts: temple = outline extruded 4 mm + HINGE blind pockets + ENGRAVING grooves, snapped hinge-end to the blank + a visual injected-core bar; base-curve block = the lens shape cut from a 70×70×4.7625 acetal blank, 3 M4 through-holes (2026-06-19: CAM simplified to Drill Holes + Block Profile=lens-shape cut, forming scribe + box cut dropped); GUI `FlatMeshWorker` + Build-3D enabled per kind); next: M7.6 role-matched auto-nesting onto the tagged bed (+ polygon keep-outs, bed render/nudge), then M7.7 combined/per-component G-code**)*

> **2026-06-22 — M7.12 DONE (`v0.7.12`, 324 tests):** *watch the cut.* The
> twice-deferred cut-sim playback scrubber. New headless `core/sim/playback.py`
> (`simulate_steps` accumulates the tool-profile Z-buffer op by op, snapshotting the
> cumulative achieved floor after each — monotonic by construction, last frame ==
> the full sweep; `steps_from_ops` resolves each op's profile from its own tool).
> `SimWorker`/`FlatSimWorker` emit the per-op snapshots alongside the report;
> `Viewer3D` sim mode gains a **scrubber** (play/pause + timeline slider + a
> `k/n · op` step label) that re-renders the cut building up — neutral floor while
> scrubbed back, the colour-verified report at the final frame — and emits
> `playback_step_changed`, which best-effort selects the matching row in the M7.11
> Toolpaths inspector. Whole-bed playback (the bed sim) stays the static final view
> for now. 10 new headless tests (monotonicity, op-boundary mapping, final ==
> full sweep, profile resolution). **Next (planned, user-approved 2026-06-22):
> M7.12.1–.3** — the *volumetric* revisit: render the stock as a solid block carved
> in-place by a moving tool/holder (not the floor sheet), and a bed sim that flags
> hold-down collisions. Keeps this snapshot core + the M7.11 2D overlay. Then
> **M7.13** measure + 3D section.
>
> **2026-06-21 — M7.11 DONE (`v0.7.11`, 314 tests):** *see what the program cuts.*
> Cluster 2 (control/visibility) opens. `DxfCanvas` gains a per-op **toolpath overlay**
> (colour-coded paths over the 2D design, dashed rapids, per-op visibility +
> highlight); `GCodeWorker` emits an `op_overlay` for castle/temple/block. A new
> **Toolpaths** bottom dock (tabbed with the Log) lists each op (checkbox / tool /
> Z-floor / length / time, totals in the title) — checkbox toggles the overlay,
> selection highlights it. On Generate the overlay draws + the view flips to 2D; a
> CAM/design change or tab switch clears it. Next: **M7.12** cut-sim playback scrubber.

> **2026-06-21 — M7.10 DONE (`v0.7.10`, 311 tests):** the feeds & speeds / chip-load
> calculator. Headless `core/cam/feeds.py` (chip load = feed/(rpm·flutes); surface
> speed = π·D·rpm; the inverse; window status); a per-material chip-load window in
> `materials.yaml`; a CAM-tab **Chip load** read-out (chip load + surface speed + a
> green/amber/red badge vs the window) that re-derives on every CAM change. Ties the
> M7.8 tool library (flutes/Ø) to the material store (feeds/rpm). Next: **M7.11**
> toolpath overlay + per-op inspector.

> **2026-06-21 — M7.9 DONE (`v0.7.9`, 304 tests):** *see the cutter.* (a) A real
> **V-bit** `ToolProfile` (cone drop profile `dz = d/tan(half)`, groove width =
> 2·depth·tan(half)); `engrave_vbit` migrated from a faked 0.5 mm flat to a 0.5 mm 30°
> V-bit (engrave toolpath unchanged). (b) A live **tool visualizer**
> (`gui/widgets/tool_view.py`, QPainter 2D section — flat/ball/toroid/V-bit + shank)
> in the Preferences ▸ Tools editor. (c) **Depth/stickout reach**
> (`depth_reach_warnings`) — warns when an op cuts deeper than its tool's flute
> length, wired into the G-code log beside the width reach. Next: **M7.10** feeds &
> speeds / chip-load calculator.

> **2026-06-21 — M7.8 DONE (`v0.7.8`, 297 tests):** the tool library — first of the
> M7.8–M7.16 Tooling & control UX block. The tool table graduates from a hand-edited
> `config/tools.yaml` to a **managed library**: new headless `core/cam/tooling.py`
> `ToolSpec` (typed, radius derived, +flute-length / shank / number / vbit fields,
> back-compat read) + `gui/tool_store.py` (clones `material_store`: shipped merged
> with `~/.guildcam/tools.yaml`; add/override/delete-tombstone/reset/import/export) +
> a **Preferences ▸ Tools** tab (list + edit form + Add/Duplicate/Delete/Reset/
> Import/Export). Every tool combo sources from the store and refreshes on close;
> `build_tool_settings` honours an explicit spec tool number (stable T-numbers,
> back-compat). Next: **M7.9** tool visualizer + the real V-bit `ToolProfile` +
> depth/stickout reach.

> **2026-06-20 — M7.7 COMPLETE → M7 COMPLETE (`v0.7.7`, 284 tests).** Two parts.
> **(a) Combined worktable program:** `core/cam/layout.py` `build_nest_program(nest)`
> folds an M7.6 `BedNest` (placed on the user-tagged `Worktable`, possibly nudged)
> into **one** scheduled `worktable.nc` — per-placement op-name prefixing + the M6.5
> precedence-aware tool-change minimiser over the whole bed (op copies renamed, so
> the nest render is untouched; `count_tool_changes` shared with `build_bed_program`;
> the M6.5 fixture path unchanged). GUI **Generate Worktable Program** button posts
> it (lint + polygon clearance + cut-time, drill-at-screw exempt), stores
> `worktable.nc` + a `component: worktable` setup sheet, enables Export G-code, folds
> into an open single-DXF `.gcam`. **(b) Whole-bed cut-sim render:** new headless
> `core/sim/bed.py` — `simulate_component(spec)` builds each placed part's relief +
> posted program and sweeps the tools → its achieved floor / target (reusing the M5
> machinery), and `composite_bed_report(comps, work_area)` stamps them onto **one
> machine-coords bed grid** and `verify`s completeness/gouge across the bed (valid
> because nested parts are disjoint and the combined program is the per-component ops
> reordered → an order-independent min). GUI `BedSimWorker` + a **Simulate Bed**
> button render the whole bed in the 3D cut-sim view (Uncut/Gouge overlays). Per-
> component Generate/Simulate unchanged. **M7 reorientation is complete.** Next is the
> planned **M7.8–M7.16** UX block.

> **2026-06-20 UX & control replan (planned, `v0.7.8`–`v0.7.16`):** a new
> **M7.8–M7.16 "Tooling & control UX"** block lands between the reorientation
> (M7) and the hardware gate (M8) — so the maker can *drive* GuildCAM, not just
> generate from it. Cluster one is a Fusion-style **tool library**: a managed,
> visual, validated tool table that supersedes the hand-edited `tools.yaml` — a
> tool store + **Preferences ▸ Tools** tab (M7.8), a live **tool visualizer** +
> a real **V-bit** type + depth/stickout reach (M7.9), and a **feeds & speeds /
> chip-load calculator** tying tools↔materials (M7.10). Cluster two is
> control/visibility: a **toolpath overlay + per-op inspector** (M7.11), the
> twice-deferred **cut-sim playback scrubber** (M7.12), on-canvas **measure +
> 3D section** tools (M7.13), and a **job/validation inspector** panel that says
> what's blocking green (M7.14). Cluster three is workflow personalization:
> customizable **hotkeys & toolbar** (the GuildDraw-parity Settings tabs, M7.15)
> and saveable **frame-style parameter presets** (M7.16). Mostly UI over engines
> that already exist (the material store M4.9, `ToolProfile` M5,
> `op_summaries`/`cuttime` M4.8, the bed toolpath render M7.6). See the M7.8
> head. (M7.7 completes M7 first.)

> **M6.5 — worktable layout & nesting (`v0.6.5`):** `core/cam/layout.py` —
> `build_bed_program` places each part on its fixture zone (`place_ops_at_zone`,
> bbox-centred auto-pack), prefixes op names, and `schedule_bed_ops` orders ops
> across parts to minimise tool changes (front-load special tools, respect each
> part's internal order). `bed_clearance_violations` checks the whole layout
> (drill ops exempt — the block's M4 holes are drilled at the bc-template
> mounting screws on purpose). `BedLayout`/`ComponentPlacement` on
> `ProjectSchema.bed_layout`. File ▸ Generate Worktable Program (`GCodeWorker`
> `is_worktable`) → one `worktable.nc` (frame + block), lint + cut-time over the
> bed, folded into the `.gcam`. Interactive layout editor + bed render deferred.
> Suite **197** (+11). **M6 complete.**

> **M6.4 — base-curve forming blocks (`v0.6.4`):** `core/cam/block_ops.py`
> `generate_block_program` → Drill Holes + Forming Profile + Block Profile from a
> frame LENS interior (centred on a 65×65×6.35 acetal blank). 3 M4 mounting holes
> (in-line/10 mm/Ø4.5, user-confirmed) peck-drilled via new `GRBLPost.peck_drill`
> (G83); `write_castle_program` gained `drill_op_names`/`peck_depth_mm`. One tool
> change drill→bulk (M6.1); `drill_m4_clear` tool + `acetal` material shipped.
> File ▸ Generate Base-Curve Block (`GCodeWorker` `is_block`) → its own
> `base_curve_block.nc` in the `.gcam`. Block flat in v1 (3D base curve still
> metadata); block STL/preview deferred to M6.5. Suite **186** (+11).

> **M6.3 — temples with engraving (`v0.6.3`):** `core/cam/temple_ops.py`
> (`generate_temple_program` → Engraving + Temple Profile ops; `TempleParams` on
> `ProjectSchema.temple`). Engraving traces the ENGRAVING curves at
> `thickness − depth` with the shipped `engrave_vbit`; the profile is the OUTLINE
> through-cut (onion skin, reuses `contour_op`). One tool change between them via
> M6.1; `write_castle_program` gained `contour_op_names` so the temple profile
> ramps. The GUI detects a temple (outline, no lenses) and routes Generate to the
> temple program (program-zero from the temple blank, temple-zone clearance,
> setup sheet `component: temple`). Temple cut-sim deferred to M6.5. Suite
> **175** (+12).

> **M6.2 — program zero from the stock box (`v0.6.2`):** `ProgramZero`
> (`project.schema`) picks G54 zero from the stock blank box — a corner/center in
> X/Y, top/bottom face in Z (default center/center/bottom = the blank center /
> anterior = a zero offset), or `fixture` (the old design-frame zero, identity
> offset). `GRBLPost.work_offset` shifts every posted
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

**M7 (2026-06-18 reorientation replan) re-architects the *product* around the
whole eyewear model.** Where M1–M6 cut one component from one DXF, M7 takes a
single **`.gdraw`** (which already holds the frame front + temple right + temple
left in one file) and builds them — plus a base-curve forming template per lens —
as separate components, each in its own 3D workspace tab, then **auto-nests them
onto a user-defined worktable** (imported as a DXF, its zones tagged by role:
frame-front stock, temple R/L, base-curve R/L, keep-out) and posts **one combined
bed program or separate per-component programs**. This keeps both modes of work the
shop needs: individual models, and a custom bed for a run on the Guild CNC. It is
mostly re-architecture over the M6 engines (§ M7 head); the geometry core and the
non-goals above are unchanged. The product may be **renamed GuildModel** to match
this whole-model framing — decided before release (M10).

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
| `ENGRAVING` | absent (temples only) | **Engrave passes on temples (M6.3)** — traced at depth with a small tool |

### 3.1 `.gdraw` direct intake — the primary multi-component path (M7.2)

From M7 the **primary** project intake is a single GuildDraw **`.gdraw`**: a ZIP of
`manifest.json` + `front.svg` + `temple_r.svg` + `temple_l.svg` + `hinge.svg` (each
an SVG in GuildDraw's metadata dialect). One file yields the whole model:

| Workspace | Layers | GuildCAM component |
|---|---|---|
| `front` | OUTLINE, LENS, SCULPT, HINGE, REF | **frame_front** — the castle pipeline above |
| `temple_r` / `temple_l` | OUTLINE, ENGRAVING, SCULPT, HINGE, REF | **temple_right / temple_left** — profile + engraving (M6.3) |
| `hinge` | HINGE, REF | front hinge-pocket geometry (standalone hinge reserved) |
| *(derived)* | front LENS interiors + `forming.apical_radius_mm` | **base_curve_right / base_curve_left** — one forming template per lens (M6.4 ×2) |

Each workspace also carries `forming` (`apical_radius_mm` = base curve,
`bridge_angle_deg`), the bridge `mirror` axis (the asymmetry signal), and per-layer
visibility. The **same posterior-flip / closure / units rules as the DXF contract
apply**, so both intake paths produce identical downstream geometry (round-trip
gated in M7.2). The DXF contract above remains the per-component and worktable-bed
path; it is frozen and unchanged.

**Open contract question (carried from GuildDraw M9):** asymmetric frames —
two distinct LENS entities vs. symmetric mirror. The `.gdraw` `mirror` axis is the
signal (M7.2); resolved for real during M8 hardware validation.

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
- Fixture / worktable: through M6 the bed is fixed —
  `config/fixtures/guild_cnc.yaml` (six blank zones, 24 hold-down screw circles
  r = 5 mm to avoid, flip axis x = 201.146 mm for two-sided work, nosepad sub-zone
  6 + 4 mm). **M7.4 generalises this to a user-defined worktable** imported from a
  bed DXF, with enclosed regions tagged by role (frame-front / temple R-L /
  base-curve R-L / keep-out); the Guild fixture becomes the built-in **default**
  bed, expressed in the same `Worktable` model so the M6.5 nesting machinery is
  unchanged.
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

Ten milestones (M1–M10), several with lettered sub-milestones. Each sub-milestone
is small enough to finish in one or two sessions, ends in a working app, and gets a
version bump + git commit. Order matters: the geometry core is validated against the
demo STL before any CAM is rewritten, and CAM is validated against the demo NC
before any UI is built, because every later milestone builds on trusting the layer
beneath it.

> **2026-06-11 replan:** the spike's M0–M6 series (archive) is superseded.
> The Demo Project teardown showed the posterior is built as **zones +
> footing fillets** (the castle), not a distance-based scallop, and through-
> cuts use an onion skin, not tabs. The roadmap below rebuilds the relief and
> CAM layers around that ground truth, frame front only.

> **2026-06-18 reorientation replan (M7):** M1–M6 proved a single-component
> engine (one DXF → one program). **M7 re-architects the product around the whole
> eyewear model** — a single `.gdraw` → frame front + both temples + a base-curve
> template per lens, each in its own 3D workspace tab, auto-nested onto a
> user-defined worktable (a tagged bed DXF) and posted as one combined bed program
> *or* separate per-component programs. **Reorient first, then hardware-validate**
> (M8): the reorientation is the road to release. It reuses the M6 engines — see
> the M7 head for the full plan. (`.gdraw` direct intake graduates from post-1.0
> backlog #3 into M7.2; the old M7/M8/M9 — hardware / two-sided / packaging —
> shift to M8/M9/M10; the product may be renamed **GuildModel**, decided in M10.)

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
> is now **M7** (renumbered **M8** by the 2026-06-18 reorientation); this M6 is the block of "real shop" CAM the maker needs before
> a hardware gate is worth running. It deliberately widens the M1–M5 scope
> (single-tool, frame-front-only) — see §1. Sub-milestones ship in order, each a
> version bump; M6.1 (multi-tool) is foundational and the others build on it.
> Hardware validation (M8) then exercises the whole expanded op set in one pass.
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
> simulator are untouched. Default is the stock blank's **center/center, bottom
> (anterior) face** — the blank center, which is the design origin (a zero
> offset); pick a corner + top face to touch off there instead. Suite **163
> green** (+12
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
   current design-frame behaviour, needed for the two-sided flip axis in M9);
   stock-box is the new default for single-setup jobs. Persisted in
   `CastleCamParams.program_zero` and the `.gcam` (round-trip tested).
4. ✅ Tests (`tests/test_program_zero_m62.py`, +12): each datum's offset; the
   post applies it (I/J unchanged, safe-Z offset); the demo lands in the positive
   quadrant and is a pure translation of fixture mode; the sim is unaffected;
   fixture mode is the identity; `.gcam` round-trip; the setup sheet/label name
   the datum.

### M6.3 — Temples with engraving (v0.6.3) — ✅ DONE 2026-06-16

> **Done 2026-06-16 (`v0.6.3`).** A temple is generated as **Engraving →
> Temple Profile** with one tool change between the small engraving bit and the
> bulk profile tool, posted through the same multi-tool machinery (M6.1) and
> program-zero offset (M6.2) as the frame front. The app detects a temple on
> import (an outline with no lenses) and routes Generate G-code to the temple
> program. Suite **175 green** (+12 `tests/test_temple_m63.py`). *Trimmed: the
> temple cut-sim render — `verify`'s completeness is castle-specific (a temple's
> top is meant to stay uncut except where engraved), so a temple verifier is
> built with M6.5's multi-component rendering. The Simulate button stays disabled
> for temples for now.*

Pulled forward from the post-1.0 backlog. A temple is an outline cut **plus
ENGRAVING passes**, and the engraving needs a tool change (depends on M6.1).

1. ✅ **Temple intake**: the ENGRAVING layer (already read by `io_import/dxf.py`)
   + the temple OUTLINE; the GUI caches `_engraving_curves` and flags
   `_is_temple` (outline present, no lenses) on import. Temple blanks already in
   `config/fixtures/guild_cnc.yaml` (`temple_right` / `temple_left`).
2. ✅ **Engrave op** (`core/cam/temple_ops.py` `engrave_op`): traces each
   ENGRAVING polyline at `z = thickness − engrave_depth` (default 0.3 mm) with a
   small tool — the shipped **`engrave_vbit`** (0.5 mm, its own gentle feeds);
   a tool change before the profile via M6.1.
3. ✅ **Temple profile cut** (`temple_profile_op`): the OUTLINE as an outside
   contour with onion skin — reuses `contour_op`; temples are flat (no
   zone/footing machinery). `write_castle_program` gained a `contour_op_names`
   parameter so the profile gets the ramped lead-in (`TEMPLE_CONTOUR_OPS`).
4. ✅ **Generation/UI**: `generate_temple_program` (`TempleParams` on
   `ProjectSchema.temple`); the `GCodeWorker` temple branch builds the program,
   the tool-change blocks, the program-zero offset from the temple blank box, the
   fixture-clearance check against the temple zone, the cut-time (incl. change
   dwell), and the setup sheet (`component: temple`). The profile/bulk tool
   follows the CAM tab's Tool selector; full per-component UI is M6.5.
5. ✅ Tests (`tests/test_temple_m63.py`, +12): engrave depth + tool; profile
   envelope (top → onion skin, ring outside the outline); engrave-then-profile
   order + one posted/linted tool change; engraving emitted at constant depth;
   ENGRAVING-layer DXF intake; `TempleParams` `.gcam` round-trip.

### M6.4 — Base-curve forming blocks (v0.6.4) — ✅ DONE 2026-06-16

> **Done 2026-06-16 (`v0.6.4`).** A base-curve forming block is generated
> straight off the frame's lens interior as **Drill Holes → Forming Profile →
> Block Profile**, with one tool change (drill → bulk) through the shared
> multi-tool post (M6.1) and program-zero (M6.2). File ▸ **Generate Base-Curve
> Block** (enabled once a frame with a LENS is loaded) produces its own
> `base_curve_block.nc`, folded into the `.gcam`. Suite **186 green** (+11
> `tests/test_block_m64.py`). *Hole spec confirmed with the user 2026-06-16:
> **in-line, 10 mm pitch, M4 clearance ≈4.5 mm** (a bolt passes through the block
> into a tapped jig); arrangement + Ø stay parameters. The block is flat in v1 —
> the 3D base-curve surface stays metadata (§5), so the forming feature is a
> contour scribe of the lens footprint; STL/preview of the block is deferred to
> M6.5's component rendering.*

Pulled forward: auto-generate the post-cut heat-forming holding block straight
from the frame DXF.

1. ✅ **Block geometry from the DXF** (`core/cam/block_ops.py`): the LENS interior
   is centred (bbox) on the blank and scribed onto the top face as the
   **Forming Profile** (the forming footprint, at `thickness − forming_depth`).
   Default blank: **acetal, 1/4" (6.35 mm), 65 × 65 mm** (`BaseCurveBlockParams`,
   editable). The blank outline is the **Block Profile** through-cut (onion skin).
2. ✅ **Mounting holes**: `hole_centers()` lays out **three M4 holes, in-line at
   10 mm pitch** (default) or an equilateral triangle; **Ø 4.5 mm (M4 clearance)**.
   Peck-drilled (`GRBLPost.peck_drill`, G83 full-retract — GRBL has no canned
   cycle) from the top face through a `drill_breakthrough_mm` past the bottom.
3. ✅ **CAM**: `generate_block_program` orders Drill (rigid) → Forming scribe →
   Block Profile (release), drilling with **`drill_m4_clear`** (4.5 mm) and the
   bulk tool for the rest — one tool change via M6.1. `write_castle_program`
   gained `drill_op_names` + `peck_depth_mm`. Acetal feeds: a new **`acetal`**
   entry in `materials.yaml`; stepdown clamped to its DOC.
4. ✅ **UI/output**: File ▸ **Generate Base-Curve Block** (`GCodeWorker`
   `is_block` branch) → `base_curve_block.nc` + a `component: base_curve_block`
   setup sheet, folded into the `.gcam`. The forming/profile (bulk) tools follow
   the CAM Tool selector; full per-component UI + the block STL/preview are M6.5.
5. ✅ Tests (`tests/test_block_m64.py`, +11): block outline = blank size; the
   forming profile tracks + centres the lens interior; 3 in-line holes at
   10 mm / Ø4.5 drilled through; the G83 peck cycle + the drill→bulk tool change
   post and lint clean; triangle layout; `.gcam` round-trip.

### M6.5 — Custom worktable layout & multi-part nesting (v0.6.5) — ✅ DONE 2026-06-16

> **Done 2026-06-16 (`v0.6.5`) — M6 complete.** File ▸ **Generate Worktable
> Program** cuts the frame front **and** its base-curve block in **one** program:
> each part is generated in its own design frame, auto-packed onto its fixture
> zone, and the whole bed is scheduled to **minimise tool changes** (the demo
> 2-part bed posts with exactly **one** change — drill front-loaded, then all
> bulk). Suite **197 green** (+11 `tests/test_layout_m65.py`). *Trimmed: the
> interactive layout editor + the 2D bed preview render (a machine-coords
> workspace, distinct from the frame-centric design canvas) — placements are
> auto-packed and reported in the setup sheet + log; the bed sim render is left
> with them. The combined program is gated quantitatively by lint + the
> bed-clearance check + cut-time over the whole bed.*

Cut several components — frame front(s), temples, base-curve block(s) — in **one
CNC program** on the bed. Builds on all of M6.1–M6.4.

1. ✅ **Bed model**: the **fixture is the bed** — `config/fixtures/guild_cnc.yaml`
   already carries the six blank zones + hold-down screws; `zone_center()` reads a
   part's zone, the screws are the keep-outs.
2. ✅ **Layout** (`core/cam/layout.py`): `place_ops_at_zone` rotates (about
   origin) + translates each part so its bbox centre lands on its zone centre
   (simple auto-pack); `transform_ops` is the rigid placement transform.
   `bed_clearance_violations` checks every placed cutting point against the screw
   keep-outs over the whole layout — **drill ops are exempt** (the base-curve
   block's M4 holes are drilled *at* the bc-template screws on purpose — they are
   its mounting bolts; a test asserts the exemption does real work).
3. ✅ **Combined post**: `schedule_bed_ops` orders ops across parts to minimise
   tool changes — greedy stay-on-tool, and on a change pick the ready tool with
   the fewest remaining ops (front-loads drill/engrave, batches the bulk),
   **respecting each part's internal op order** (a part isn't profiled before it's
   drilled). `build_bed_program` places + prefixes op names per part + collects
   the through-cut / drill name sets, and `write_castle_program` posts the
   combined list (one program, fixture clearance over the full bed).
4. ✅ **`.gcam`**: `BedLayout` (+ `ComponentPlacement`) on `ProjectSchema.bed_layout`
   round-trips the bed; the combined `worktable.nc` is stored in the container.
5. ✅ **Cut-time + lint over the bed**: `estimate_program` on the combined `.nc`
   (incl. the change dwell); `lint_program` gates it; the program folds into the
   `.gcam` (the readiness light goes green). *(Full geometric bed sim render
   deferred with the layout editor.)*
6. ✅ Tests (`tests/test_layout_m65.py`, +11): transform + zone placement; the
   scheduler minimises changes **and** preserves precedence (incl. a conflicting
   tool-order case); the demo 2-part bed posts one program with one change, lints
   clean, clears the layout (drills exempt), and cut-time covers the bed;
   `BedLayout` `.gcam` round-trip.

### M6 exit criteria
- [x] Per-operation tool assignment with posted, linted tool-change blocks +
      tool-reach warnings (M6.1) — `v0.6.1`
- [x] Program zero settable from the stock-box datum; fixture mode retained (M6.2)
      — `v0.6.2`
- [x] Temples cut with ENGRAVING passes + the engraving tool change (M6.3)
      — `v0.6.3`
- [x] Base-curve block auto-generated from the DXF (eyewire interior + 3× M4
      holes, acetal blank) (M6.4) — `v0.6.4`
- [x] Multiple components placed on a custom bed and cut in one program (M6.5)
      — `v0.6.5`
- [x] Full suite green; sub-milestones tagged `v0.6.1` … `v0.6.5` (197 tests)

## M7 — Reorientation: the whole-model project & the worktable (v0.7.x) · *one .gdraw in, a nested bed out*

> **2026-06-18 reorientation replan.** M1–M6 built a trustworthy single-component
> engine: one GuildDraw **DXF** in → one frame front (or one temple, or one
> base-curve block) → one program. M7 re-architects the **product** around the way
> the shop actually works — a whole eyewear **model** at once: frame front + temple
> right + temple left + a base-curve forming template per lens, imported in a
> single **`.gdraw`**, each built in its own 3D workspace tab, then auto-nested onto
> a **user-defined worktable** (imported as a DXF, its zones tagged by role) and cut
> either as **one combined bed program** or as **separate per-component programs**.
> That is the flexibility the Guild CNC launch needs: individual models for a
> one-off front or a pair of temples, and a custom bed for a full run.
>
> Almost every *engine* this needs already exists from M6 — multi-tool posting
> (M6.1), program zero (M6.2), the temple (M6.3) and base-curve-block (M6.4)
> generators, and the precedence-aware nesting scheduler (M6.5). M7 is therefore
> mostly **re-architecture, not new geometry**: a multi-component project model, a
> `.gdraw` reader, a per-component tabbed UI, an interactive bed that generalises
> the fixed `guild_cnc.yaml` fixture, and a generalised nest/post over that bed.
> The §6 engineering principles hold throughout (core never imports gui;
> heightfields + polygons; no OpenCASCADE). Sub-milestones ship in order, each a
> version bump; **M7.1 (the project model) is foundational** and the rest build on
> it. The product name stays **GuildCAM** through M7 — the GuildCAM→GuildModel
> decision is resolved before release in **M10**. Hardware validation (M8) then cuts
> the reoriented multi-component bed on real stock.

### M7.1 — The multi-component project model (v0.7.1) — ✅ DONE 2026-06-18

> **Done 2026-06-18 (`v0.7.1`; 216 tests green, +19 `tests/test_project_m71.py`).**
> `ComponentKind` (frame_front / temple_right / temple_left / base_curve_right /
> base_curve_left) + the `Component` model (kind → its `castle` / `temple` /
> `base_curve_block` param, default-built with the kind's fixture zone; `params()`
> / `for_kind()` / `fixture_zone()`) + kind↔label/zone/param-field helpers, all in
> `project/schema.py`. `ProjectSchema.components: list[Component]` with
> `component(kind)` / `components_of_kind` / `frame_front` / `add_component`
> (id-uniquifying) accessors and **`ensure_components()`** — the legacy migration
> (empty → one `frame_front` from the flat `castle` / `forming` / `source_file`);
> `load_gcam` calls it, so an M5.1–M6.5 `.gcam` reopens as a one-component project.
> New **`core/cam/component.py`** `build_component_ops` dispatches a Component + its
> prepared geometry to the M3/M6 generator and returns a `ComponentProgram` (ops +
> contour/drill op-name sets + stock + fixture zone) that maps straight onto M6.5's
> `BedPart` for the bed program (M7.6). The flat single-component fields and all
> M1–M6 paths are byte-unchanged (the 197 prior tests stay green). *Deferred to its
> consumer:* the physical `.gcam` `components/<id>/program/*.nc` tree lands with
> per-component generation (M7.3) / the bed program (M7.6) — until a component
> carries its own program there is nothing to write into the tree; the schema-level
> `components` already round-trips through `project.json`.

The schema spine. Today `ProjectSchema` is one component (`source_file` = one DXF,
one `castle` / `temple` / `base_curve_block`). M7.1 makes a project an **ordered
list of `Component`s**.

1. **`Component` model** (`project/schema.py`): a stable `id` + `label`, a `kind` —
   the shared enum **`frame_front` / `temple_right` / `temple_left` /
   `base_curve_right` / `base_curve_left`** (defined once here, reused by the bed
   roles in M7.4 and the nest match in M7.5) — its layer-keyed source geometry, its
   per-kind params (`CastleParams` for the front, `TempleParams` for temples,
   `BaseCurveBlockParams` for the templates), its `FormingMetadata` (base curve,
   bridge angle), and its generated program / setup / cut-report.
2. **`ProjectSchema.components: list[Component]`** supersedes the flat
   `castle` / `temple` / `base_curve_block` / `source_file` fields (kept as
   deprecated shims that read the first matching component, so nothing downstream
   breaks in one commit). `cam_params` / `machine` / the worktable stay
   project-level.
3. **The generators become per-component**: `generate_castle_program`,
   `generate_temple_program`, `generate_block_program` already take their params +
   geometry — wrap each as "build the program for one `Component`" with no change to
   the geometry/CAM. The M2 (STL) / M3 (NC) / M5 (completeness) gates run **per
   component** and stay green.
4. **`.gcam` grows to N components**: `core/project/gcam.py` gains a
   `components/<id>/` tree (geometry, `program/*.nc`, `setup.json`,
   `cut_report.json`) under the existing manifest + per-file SHA-256; a
   single-component `.gcam` from M5.1–M6.5 **loads as a one-component (frame_front)
   project** (migration tested). `extract_handoff` exports the chosen component(s).
5. **Tests**: a project round-trips N components; the legacy single-DXF / single
   `.gcam` upgrades cleanly; per-component gates green; the kind↔params binding is
   total. Tag `v0.7.1`.

### M7.2 — `.gdraw` direct intake (v0.7.2) — ✅ DONE 2026-06-18

> **Done 2026-06-18 (`v0.7.2`; 233 tests green, +12 `tests/test_gdraw_m72.py`
> reader, +5 `tests/test_components_m73.py` notebook).** `core/io_import/gdraw.py` parses each workspace's
> `<metadata>` JSON (the *authoritative* geometry, not the rendered `<path>`
> d-strings), flattens line / spline (adaptive cubic Bézier) / circle / arc curves
> to the **same layer-keyed point lists `import_dxf` yields**, and applies the
> single net scene→posterior transform **(x, y) → (-x, -y)** (GuildDraw's Y-down
> scene → DXF Y-negate → GuildCAM X-flip — one flip point, like `import_dxf`).
> `read_gdraw` → `GdrawDocument` (the four workspaces + forming + mirror; plain
> `.svg` = a single front; legacy `temple.svg` compat; the entity-expansion guard).
> `build_project_from_gdraw` → `GdrawProject` assembles the multi-component
> `ProjectSchema` — frame front, both temples (`enabled=False` when a workspace has
> no OUTLINE), and **one base-curve template per front LENS** (split right/left by
> centroid x, OD on +x) — each paired with its layer geometry. `FormingMetadata`
> gained `apical_radius_mm` / `bridge_angle_deg` to carry the `.gdraw` forming
> losslessly. **File ▸ Open Model (`Ctrl+Shift+O`) is wired** (with the M7.3
> component notebook): a `.gdraw` loads as a tab per component (Frame Front /
> Temple R / Temple L / Base Curve R / L — empty workspaces shown disabled), and
> switching tabs rebinds the active component. `v0.7.2` bumped.

> Pulls **post-1.0 backlog #3** into the core and makes it the **primary** project
> intake. One `.gdraw` → a fully populated multi-component project.

A `.gdraw` is a ZIP of `manifest.json` + `front.svg` + `temple_r.svg` +
`temple_l.svg` + `hinge.svg`, each an SVG in GuildDraw's metadata dialect carrying
its `curves` (line/spline/circle/arc with cubic nodes), per-layer visibility, the
bridge `mirror` axis, and **`forming` (`apical_radius_mm` = the base curve,
`bridge_angle_deg`)**.

1. **`io_import/gdraw.py`**: read the ZIP and map each workspace + its layers into
   project Components, applying the **same posterior flip, closure, and units rules
   as the frozen DXF contract (§3)** so everything downstream is identical:
   - `front.svg` → a **`frame_front`** Component (OUTLINE→perimeter, LENS→eyewires,
     SCULPT→zone cuts, HINGE→pockets, REF ignored), carrying its `forming`.
   - `temple_r.svg` / `temple_l.svg` → **`temple_right` / `temple_left`**
     (OUTLINE→profile, ENGRAVING→engrave passes, incl. `TextObject` outlines).
   - **Derived**: two **`base_curve_*`** Components from the front's two LENS
     interiors, each formed to the front's base curve (`apical_radius_mm`) —
     generalising M6.4 from one block to **one per lens** (user-confirmed
     2026-06-18); the block carries its lens footprint + per-lens mounting holes.
   - `hinge.svg` → the front's hinge-pocket geometry (standalone hinge workspace
     reserved).
2. **Curve → polygon mapping**: a tested reader for GuildDraw's `Curve`
   serialization (cubic-spline nodes, `data-layer` groups, circle/arc params) → the
   same internal layer-keyed polygons the DXF path yields. The dormant
   `io_import/svg.py` (npoint bug) is either fixed to this dialect or retired for
   the fresh reader (decide in-milestone; the M9 SVG-intake follow-up converges
   here).
3. **Asymmetry**: the front's `mirror` axis tells us whether LENS/HINGE/SCULPT are
   mirrored or two distinct entities — the data that resolves the §3 asymmetric-lens
   contract question (closed for real in M8 hardware).
4. **Round-trip gate**: a `.gdraw` exported from GuildDraw yields the same
   Components (within tol) as importing the per-workspace DXFs GuildDraw would
   export from the same document — the §3 contract is preserved across both paths.
   DXF intake stays for single-component jobs and worktable beds.
5. File ▸ **Open Model** (`.gdraw`) populates every component tab (M7.3). Tag
   `v0.7.2`.

### M7.3 — Per-component 3D workspaces (v0.7.3) — ✅ DONE 2026-06-18

> **Done 2026-06-18 (234 tests; the notebook landed in `v0.7.2`, the kind-aware
> dock in `v0.7.3`).** The component **notebook** is in:
> a `QTabBar` over the existing shared view stack (`gui/app.py` `_build_ui`), one
> tab per component, driven by a new Qt-free `gui/component_workspace.py`
> (`ComponentWorkspace` + `derive_workspace` + `build_workspaces_from_gdraw`, so the
> intake is unit-tested without Qt). On a tab switch `_activate_workspace` persists
> the current component's artifacts and **swaps the `self._*` working set** to the
> selected one (`_sync` / `_load_active_geometry` / `_apply_workspace_to_ui`) — so
> all the M1–M6 build/generate/simulate code operates on the active component
> transparently (one live set of VTK views, not five — the planned trade). Per-kind
> actions enable correctly (castle build/sim only for a matched frame; Generate for
> frame/temple; base-curve block for a lens). A plain DXF is a one-tab project (no
> behaviour change). Verified by an offscreen `MainWindow` smoke test.
> The **kind-aware param dock** (`v0.7.3`) completes it: `ParamsPanel` gained
> editable **Temple** and **Base Curve** tabs and `set_component_kind()` shows only
> the tabs that apply (Castle/Stock for a frame, Temple for a temple, Base Curve for
> a base-curve template; Frame + CAM always). Each component **owns its** `castle` /
> `temple` / `block` params — pulled from the dock on switch-away and pushed back on
> activation (signals blocked so it never spurious-rebuilds), so edits persist
> per-tab (smoke-tested). A plain-DXF frame keeps `None` params so its prefs-restored
> dock is left untouched.

GUI re-architecture, core untouched. The single centre-stack + right dock become a
**component notebook** — one workspace tab per Component, mirroring GuildDraw's
tabbed workspaces.

1. **Component tabs**: **Frame Front · Temple Right · Temple Left · Base Curve R ·
   Base Curve L**, each with its own **2D Outline / 3D Model / Cut Sim** views and
   its own param dock (Castle/Stock/CAM for the front; Temple params for temples;
   Block params for the base-curve templates). The Worktable tab (M7.4) is the final
   peer tab.
2. **Active-component actions**: Build 3D, Simulate, and per-component Generate act
   on the active tab's component; the existing `Preview3D` / `CutSimView` / params
   widgets are re-bound to the active component on tab switch (one live set — keeps
   memory bounded vs. five concurrent VTK views; note the trade in code).
3. **Readiness** aggregates across components (grey→red→yellow→green reflects the
   whole model: imported → all built → all programmed-and-stored).
4. Empty or unedited components (e.g. a `.gdraw` with no temples) show disabled, not
   errored. Tag `v0.7.3`.

### M7.4 — The Worktable workspace: an interactive bed from DXF (v0.7.4) ✅ DONE

> ✅ **DONE (`v0.7.4`, 247 tests).** `Worktable` / `WorktableZone` / `BedRole` model
> in `project/schema.py` (role-tagged zone polygons + keep-out polygons in machine
> coordinates); `from_fixture_dict` / `to_fixture_dict` load `guild_cnc.yaml` as the
> built-in default bed **and bridge back onto the M6.5 layout machinery unchanged**
> (the existing nesting/clearance re-pass through the new model). `core/cam/worktable.py`
> reads a bed DXF → `polygonize`d regions, plus `default_worktable` and `.bed` YAML
> I/O. GUI: a trailing **Worktable** tab (peer of the components) with a machine-coords
> `BedCanvas` — import a bed DXF or load the Guild bed, click a region, tag its role;
> persisted in the `.gcam`. (Deferred to M7.5: role-matched auto-nesting onto the
> tagged zones + polygon keep-out clearance + bed render/nudge.)

> Generalises the fixed `config/fixtures/guild_cnc.yaml` (6 named blank zones + 24
> screw circles) into a **user-defined bed** drawn in CAD. The YAML fixture becomes
> a built-in **default** bed, expressed in the same model so the M6.5 machinery
> keeps working.

A new top-level **Worktable** tab (peer of the component tabs), in machine
coordinates.

1. **Import a bed DXF** and render it on a machine-coords canvas (a sibling of
   `DxfCanvas`). `polygonize` its closed loops into candidate regions (the same
   shapely partition `geometry/regions.py` uses on the frame).
2. **Select & tag zones**: the maker clicks an enclosed region and assigns a
   **role** — **frame-front stock / temple-right / temple-left / base-curve-right /
   base-curve-left / keep-out**. Keep-outs are the hold-downs (circles = screws, but
   any enclosed region qualifies). Multiple zones may share a role (right + left
   temples as their own zones; several fronts for a run).
3. **`Worktable` model** (`project/schema.py`, supersedes the fixture-name coupling
   in `BedLayout`): role-tagged **zone polygons** + **keep-out polygons**, in machine
   coordinates. `config/fixtures/guild_cnc.yaml` loads into this model (its blank
   zones → role zones, its screw circles → keep-out polygons) as the default bed.
4. **Persist** the worktable in the project `.gcam` and optionally as a reusable
   `.bed` (YAML) for a shop's standard fixtures.
5. **Tests**: DXF → polygonized regions; tag/untag round-trips; the Guild fixture
   loads into a `Worktable` equivalent to today's zones/screws (the M6.5 layout
   tests re-pass through the new model). Tag `v0.7.4`.

### M7.5 — Per-component 3D models (v0.7.5) ✅ DONE

> ✅ **DONE (`v0.7.5`, 258 tests).** Each component workspace now builds its own
> watertight solid (a prerequisite the maker called out before nesting: "we need
> the 3D models before we lay them out on the worktable"). The frame had a 3D model;
> temples and base-curve blocks did not. New `core/relief/flat.py` builds the same
> heightfield structure the castle mesher consumes, so `build_castle_mesh` is reused
> verbatim:
>
> * **Temple** — the OUTLINE extruded to the 4 mm blank; HINGE polys carved as blind
>   pockets (floor = thickness − `hinge_pocket_depth_mm`, default 1 mm); ENGRAVING
>   curves (buffered to the engrave tool) as 0.3 mm grooves. Optionally **snapped so
>   the hinge/butt end registers to one end of the 170 × 30 × 4 mm blank** (the
>   injected metal core runs the temple's length); the core is drawn as a 3D
>   **visual reference** (2 mm × ~135 mm bar from the hinge end) — not machined.
> * **Base-curve block** — the **lens shape** (cut from a 70 × 70 × 4.7625 mm /
>   3/16″ acetal blank), centred; the three M4 holes as real **through-holes** (mask
>   exclusions, like the frame's lens openings → genus-3 solid). The block *is* the
>   lens shape — it holds the eyewire on the base-curve press. (2026-06-19: the CAM
>   is just **Drill Holes + Block Profile** — the lens exterior cut free like a frame
>   outline; the earlier forming-scribe + box cut were dropped, "no other cuts.")
>
> GUI: `FlatMeshWorker` + `_start_mesh_build` dispatch by component kind; Build 3D
> enabled for temples (outline) and blocks (lens); the towers/walls/footing stepper
> stays off for flat parts; `Preview3D.show_mesh` guards the (frame-only) pad ghost
> and draws the temple core-guide bar. `BaseCurveBlockParams` → 70 × 70 × 4.7625;
> `TempleParams` gains `hinge_pocket_depth_mm` + `snap_to_blank_end` + core-guide
> dims. (Temple/block STL export + live param-rebuild deferred — Build-on-demand for
> now.)

### M7.6 — Auto-nest the model onto the worktable (v0.7.6) — ✅ DONE 2026-06-20

> ✅ **DONE (`v0.7.6`, 273 tests, +9 `tests/test_nest_m76.py`).** The M6.5 nesting
> machinery is generalised onto the user-tagged `Worktable`: `place_ops_at_polygon_zone`
> + `nest_components_on_worktable` match each built component to a zone whose ROLE
> matches its kind (`frame_front` → a frame-front zone, …), pack several of one kind
> across several same-role zones (bottom-left first), and leave a kind with no free
> matching zone `unplaced`. `worktable_clearance_violations` generalises the circular
> screw check to **arbitrary keep-out polygons** (a screw keeps its exact circle via
> `radius_mm`), retaining the base-curve drill-at-screw exemption. GUI: a **Nest
> Components** button on the Worktable panel runs a background `NestWorker` (reuses the
> per-component generators — frame relief + temple/block ops), `BedCanvas` draws each
> placement's footprint/toolpaths over its zone (red on a keep-out collision), and a
> left-drag **nudges** a footprint with live clearance re-check (no regeneration).
> (.gcam persistence of the nest + the combined post is M7.7.)

1. **Role-matched placement** (`core/cam/layout.py`, generalised): place each built
   Component on a zone whose **role matches its kind** (`frame_front` → a
   frame-front zone, `temple_right` → a temple-right zone, …). Reuse
   `place_ops_at_zone` (bbox-centre auto-pack + optional rotation); zones now come
   from the tagged DXF, not YAML.
2. **Polygon keep-outs**: generalise `bed_clearance_violations` from circular screws
   to **arbitrary keep-out polygons** (circle = a special case) — every placed
   cutting point tested against the tagged regions + tool radius; the drill-at-screw
   exemption (base-curve mounting holes) is retained.
3. **Bed render + manual nudge**: draw each component's footprint/toolpaths on its
   zone in the Worktable tab, shade keep-outs, flag collisions live; allow dragging a
   component within/over zones (the deferred M6.5 editor). Several components of one
   kind nest across several same-role zones.
4. **Tests**: kind↔role nesting; a keep-out *polygon* (not just a circle) catches a
   collision; multi-front batching; the demo bed nests front + two base-curve
   templates + two temples clear. Tag `v0.7.6`.

### M7.7 — Combined & per-component G-code from the bed (v0.7.7) — ✅ DONE 2026-06-20 — **M7 COMPLETE**

> ✅ **DONE (`v0.7.7`, 284 tests, +6 `tests/test_worktable_program_m77.py` +5
> `tests/test_bed_sim_m77.py`).** The output half of the reorientation — "individual
> models **or** a custom bed" — is live, end to end including the whole-bed sim.
> **Combined program:** `core/cam/layout.py` `build_nest_program(nest)` combines an
> M7.6 `BedNest` (already placed on the user-tagged `Worktable`, possibly nudged) into
> **one** scheduled `worktable.nc`: it prefixes each placement's op names, collects the
> through-cut / drill name sets from the prefixed names, and runs the M6.5
> precedence-aware tool-change minimiser (`schedule_bed_ops`) over the whole bed — op
> *copies* are renamed so the nest's own ops (the bed render) are untouched
> (`count_tool_changes` shared with `build_bed_program`; the fixture path unchanged).
> GUI **Generate Worktable Program** posts the nest (`build_tool_settings` →
> `write_castle_program` → `lint_program` + `worktable_clearance_violations`
> drill-exempt + `estimate_program`), stores `worktable.nc` + a `component: worktable`
> setup sheet, enables Export G-code, folds into an open single-DXF `.gcam`.
> **Whole-bed sim:** new headless `core/sim/bed.py` — `simulate_component(spec)` builds
> each placed part's relief + posted program and sweeps the tools → its achieved floor
> / target (reusing the M5 machinery), and `composite_bed_report(comps, work_area)`
> stamps them onto **one machine-coords bed grid** at their placement offsets and
> `verify`s completeness/gouge across the whole bed (geometrically equal to simming the
> combined program: nested parts are disjoint and the achieved floor is an
> order-independent min). GUI `BedSimWorker` + a **Simulate Bed** button render the bed
> in the 3D cut-sim view (Uncut/Gouge overlays). Per-component Generate/Simulate
> unchanged.

1. ✅ **One worktable program** for the whole bed: `build_nest_program` (the
   `Worktable` + multi-component generalisation of `build_bed_program`) places (via
   the M7.6 nest), prefixes, and runs the M6.5 precedence-aware tool-change scheduler
   over every component's ops → one `worktable.nc`, folded into the `.gcam`.
2. ✅ **Per-component programs**: each component tab's **Generate** still emits that
   component alone (front; a temple; a base-curve block) — the existing per-component
   post, byte-unchanged. The Worktable tab adds **Generate Worktable Program**.
3. ✅ **Whole-bed verification**: lint + polygon-bed-clearance + cut-time over the bed
   gate the combined program, readiness greens on the chosen output stored to the
   `.gcam`, **and the cut simulator renders the entire bed** (`core/sim/bed.py`
   `simulate_component` + `composite_bed_report`; GUI `BedSimWorker` + **Simulate
   Bed**) — the multi-component verifier deferred from M6.3/M6.5, now delivered.
4. ✅ **Tests**: the combined bed posts one program (scheduler minimises changes
   across the real demo bed, lints clean, clears the keep-outs with drills exempt,
   cut-time counts the change dwell), names are prefixed/classified, precedence is
   preserved, the nest's own ops are not mutated, and the GUI Generate-Worktable path
   stores `worktable.nc` + the setup sheet; per-component posts stay byte-unchanged;
   the bed sim composites placements onto one grid + reports completeness (uncut cells
   in the right bed region) + a block reaches its flat top + the GUI `BedSimWorker`
   smoke. `v0.7.7` tagged — **M7 complete.**

### M7 exit criteria
- [x] A project is N role-typed components; `.gcam` round-trips them; legacy
      single-component projects upgrade cleanly (M7.1)
- [x] One `.gdraw` imports the whole model — front, both temples, both base-curve
      templates — preserving the §3 contract (M7.2)
- [x] Per-component workspace tabs (incl. separate Temple R / Temple L), each with
      2D/3D/Sim + params (M7.3)
- [x] A worktable imported from DXF with user-tagged role zones + keep-outs; the
      Guild fixture as the default bed (M7.4)
- [x] Each component builds its own watertight 3D solid — temple (extrude + hinge
      pockets + engraving + core guide) and base-curve block (70×70×4.7625, scribe +
      through-holes) (M7.5)
- [x] Components auto-nest by role onto the bed, polygon keep-outs enforced,
      interactive nudge + bed render (M7.6)
- [x] One combined worktable program **or** separate per-component programs, both
      gated by lint + polygon clearance + cut-time, plus the whole-bed geometric
      cut-sim render (M7.7) — **M7 complete**
- [x] Full suite green (284); sub-milestones tagged `v0.7.1` … `v0.7.7`

## M7.8–M7.16 — Tooling & control UX (v0.7.8–v0.7.16) · *the maker's instrument panel*

> **2026-06-20 UX & control replan.** M1–M7 built a trustworthy engine and the
> multi-component product; this themed block — slotted **after the reorientation
> (M7) and before the hardware gate (M8)** — turns GuildCAM into an instrument the
> maker can *drive*, not just a generator. Nine sub-milestones in the `v0.7.x`
> line, each a version bump and a working app, in three clusters:
>
> 1. **A Fusion-style tool library** — the tool table graduates from a
>    hand-edited `tools.yaml` (the one place the UI still tells the maker to "edit
>    the YAML") into a **managed, visual, validated** library: a store + Settings
>    tab (M7.8), a live cross-section **visualizer** + a real **V-bit** type +
>    depth/stickout reach (M7.9), and a **feeds & speeds / chip-load calculator**
>    (M7.10).
> 2. **A control/visibility layer** — **see** the toolpaths (M7.11), **scrub** the
>    cut (M7.12), **measure & section** the model (M7.13), and read every warning in
>    **one place** (M7.14).
> 3. **Workflow personalization** — customizable **hotkeys & toolbar** (the
>    GuildDraw-parity Settings tabs the `PrefsDialog` left room for, M7.15) and
>    saveable **frame-style parameter presets** (recall a house style in one click,
>    M7.16).
>
> It is mostly **UI over a thin tool model**, not new geometry: it reuses the
> material store (M4.9), `ToolProfile` (M5), `op_summaries`/`cuttime` (M4.8), and
> the bed toolpath render (M7.6). The §6 principles hold throughout (core never
> imports gui; the calculators and the tool model are headless). The tool library
> is deliberately placed **before M8** so it is exercised on the real hardware cut.
> M7.7 finishes the reorientation first; the product name stays **GuildCAM**
> through this block (the rename decision is still M10).

### M7.8 — Tool library & the tool model (v0.7.8) · *stop editing YAML* — ✅ DONE 2026-06-21

> ✅ **DONE (`v0.7.8`, 297 tests, +13 `tests/test_tooling_m78.py`).** The tool table
> is now a managed library, not a hand-edited file. New headless **`core/cam/tooling.py`
> `ToolSpec`** (pydantic) — `type` flat/ball/toroid/**vbit**, diameter (radius
> *derived* = dia/2), corner radius, included angle, flutes, **flute length**, shank,
> a stable **tool number**, optional per-tool feeds/DOC, notes — with `from_dict`
> (back-compat read of the shipped YAML) / `to_tool_dict` (the exact dict every
> consumer reads) / `to_yaml`. New **`gui/tool_store.py`** clones `material_store`:
> shipped `config/tools.yaml` merged with a user library in `~/.guildcam/tools.yaml`
> — `effective()` / `spec` / `save_tool` / `delete_tool` (tombstone a shipped tool) /
> `reset_tool` / `import_library` / `export_library` / `replace_user`. **Preferences ▸
> Tools** tab: a tool list + edit form with **Add / Duplicate / Delete / Reset to
> shipped / Import… / Export…**, staged and committed on OK. Every tool combo (the
> global Tool, per-op tools, temple/block tools) now sources from the store via
> `_tool_names()` / `_tools_cfg()` and refreshes when Preferences closes; the "edit
> the YAML" hint is gone. `build_tool_settings` honours an explicit spec `number`
> (stable T-numbers), auto-assigning the rest — shipped tools carry none, so the post
> is byte-unchanged. *(Live visualizer + the real V-bit ToolProfile = M7.9; the
> setup-sheet tool table already emits per-tool numbers via `build_tool_settings`.)*

The CAM tab said *"Add tools by editing config/tools.yaml"* — the only app surface
where the maker dropped to a text editor. The material store (M4.9) is the proven
pattern that fixed it.

1. **Typed tool model** (`core`): promote `tools.yaml` entries to a `ToolSpec`
   (pydantic) — `type` (flat / ball / toroid / **vbit**), diameter, corner radius,
   **flute length / usable depth**, shank diameter, flutes, optional per-tool
   feeds/DOC, a stable **tool number**, display name, notes. Reads the existing
   `tools.yaml` back-compat (every new field optional, defaulted from geometry).
2. **`gui/tool_store.py`** modeled line-for-line on `gui/material_store.py`:
   shipped `config/tools.yaml` merged with user edits + user-added tools in
   `~/.guildcam/tools.yaml`; `effective()` / `add` / `save_override` / `delete` /
   `reset_tool` / `reset_all`; the shipped file is never written.
3. **Preferences ▸ Tools tab** (the Materials tab is the template): a tool list
   with **add / duplicate / edit / delete / reset-to-shipped**. The per-op tool
   combos and the material `recommended_tools` hints source from the store, not the
   raw file; the "edit the YAML" hint is removed.
4. **Stable tool numbering + tool-table emission**: tool numbers come from the
   spec (user-assignable), not first-appearance; the setup sheet + the NC header
   get a **tool list block** (T#, geometry, feeds) the operator reads when loading
   the job.
5. **Import/export** a library file (the `.bed` worktable precedent) so a shop can
   share its standard tools.
6. **Tests**: store merge/override/add/delete/reset round-trips; `tools.yaml`
   back-compat; T-number stability across a job; the setup-sheet tool table; the
   active tool set round-trips through prefs + `.gcam`. Tag `v0.7.8`.

### M7.9 — Tool visualizer, the V-bit type & reach/stickout (v0.7.9) · *see the cutter* — ✅ DONE 2026-06-21

> ✅ **DONE (`v0.7.9`, 304 tests, +7 `tests/test_tool_vis_m79.py`).** Three parts.
> **(a) Real V-bit:** `core/sim/toolsim.py` `ToolProfile` gains a `vbit` kind +
> `included_angle_deg` — a cone drop profile `dz = d / tan(half-angle)`, so a groove
> width = 2·depth·tan(half). `engrave_vbit` migrates from a faked 0.5 mm "flat" to a
> 0.5 mm 30° V-bit (engrave toolpath unchanged — it's a trace — only the sim section
> sharpens). **(b) Visualizer:** new `gui/widgets/tool_view.py` `ToolView` — a QPainter
> 2D cross-section (flat / ball / toroid corner / V-bit cone + shank), theme-aware,
> redrawn live in the Preferences ▸ Tools editor as fields change (a third splitter
> pane beside the form). **(c) Depth/stickout reach:** `castle_ops.depth_reach_warnings`
> + `DepthReachWarning` warn when an op's cut depth (stock top → deepest Z) exceeds the
> tool's `flute_length_mm` — the depth-axis sibling of the width `reach_warnings`;
> wired into the G-code log alongside the reach warnings (shipped tools declare no
> flute length, so nothing new fires until a reach is filled in). *(Deferred niceties:
> the list-thumbnail + combo hover-preview — the editor preview is the headline; the
> V-carving drop-cutter for relief stays post-1.0, the drop-cutter only sees flat/ball/
> toroid.)*

1. **`vbit` tool type**: a real `ToolProfile` variant with an **included angle**
   (tip → diameter), so the engrave bit stops being a faked 0.5 mm "flat"; the
   drop-cutter / sim groove width becomes f(depth, angle). `engrave_vbit` migrates
   to it.
2. **Tool visualizer** (`gui/widgets/tool_view.py`): a QPainter 2D cross-section
   that redraws live from the spec (diameter, corner radius, flute length, V-angle,
   shank) — the Preferences ▸ Tools editor preview, a thumbnail in the tool list,
   and a hover-preview on the per-op tool combos. (A small 3D via the existing
   `Viewer3D` is optional — defer if the 2D section reads clearly.)
3. **Depth reach / stickout**: extend `reach_warnings` / `analyze_program_reach`
   with usable-depth checking — warn when an op's max cut depth exceeds the tool's
   flute length (the depth-axis sibling of the existing width check); surfaced in
   the G-code log and the M7.14 inspector.
4. **Tests**: vbit profile geometry + groove-width sim; the visualizer renders each
   tool type headless (non-empty pixmap / Qt-skip); depth-reach warns when flute <
   depth and stays quiet when it fits. Tag `v0.7.9`.

### M7.10 — Feeds & speeds / chip-load calculator (v0.7.10) · *the material sets the feeds; the maker checks the chip* — ✅ DONE 2026-06-21

> ✅ **DONE (`v0.7.10`, 311 tests, +7 `tests/test_feeds_m710.py`).** New headless
> **`core/cam/feeds.py`**: `chip_load_mm = feed/(rpm·flutes)`,
> `surface_speed_m_per_min = π·D·rpm`, `feed_from_chip_load_mmpm` (the inverse), and
> `chip_load_status` (low / ok / high / unknown vs a window). `materials.yaml` gains a
> per-material **chip-load window** (`chip_load_min_mm` / `chip_load_max_mm`: acetate
> 0.02–0.15, acetal 0.03–0.18, horn 0.01–0.08). The CAM tab gains a **Chip load**
> read-out group (below Feeds & Speeds): the implied chip load + surface speed for the
> active tool (flutes/Ø from the M7.8 store) + feed/spindle + material, with a
> coloured badge (green in-window / amber light-rubbing / red heavy). It re-derives on
> every `cam_changed` (tool / feed / spindle / material) and after the M7.8 tool-list
> refresh. *(Skipped: the optional "set feed from chip load" action — the read-out is
> the surface; the maker adjusts feed/RPM to land in the green.)*

1. **Headless calculator** (`core/cam/feeds.py`): chip load = feed / (rpm ×
   flutes); surface speed = π × d × rpm; the inverse (feed from a target chip
   load). Pure functions, unit-tested — no new persistence.
2. **CAM-tab read-out**: show the implied chip load + surface speed for the active
   op/tool/material, with an **out-of-range badge** (a per-material chip-load window
   added to `materials.yaml`); an optional "set feed from chip load" action.
3. Ties the **tool library** (flutes / diameter) to the **material store** (feeds /
   rpm) — the relationship is surfaced, not duplicated.
4. **Tests**: chip-load / surface-speed math; the inverse; range flagging across
   acetate / acetal / horn. Tag `v0.7.10`.

### M7.11 — Toolpath overlay & per-op inspector (v0.7.11) · *see what the program cuts* — ✅ DONE 2026-06-21

> ✅ **DONE (`v0.7.11`, 314 tests, +3 `tests/test_toolpath_m711.py`).** Generation is
> no longer an opaque "Generate → log text". **`DxfCanvas`** gains a toolpath overlay
> (`set_toolpaths` / `set_toolpath_visible` / `set_toolpath_highlight` /
> `clear_toolpaths` + `_draw_toolpaths`) — each op's cutting paths drawn over the 2D
> design in design mm, colour-coded per op, with faint dashed rapid connectors and a
> thicker highlighted op. `GCodeWorker` attaches an `op_overlay` (per-op `(x, y)`
> paths) in the castle / temple / block branches (`_op_overlay`); the worktable keeps
> its bed render. A new **Toolpaths** bottom dock (tabbed with the Log, View ▸
> Toolpaths toggle) holds a per-op table — Op (checkbox) / Tool / Z-floor / length /
> est. time — built from `op_summaries()`, with the totals in the dock title;
> unchecking an op hides its overlay, selecting a row highlights it. On a per-component
> Generate the overlay draws, the inspector fills, the dock shows, and the view flips
> to 2D; a CAM/design change or a component-tab switch clears it (stale-guard). *(The
> worktable bed already had its M7.6 render; per-component is the new surface.)*

1. **Toolpath overlay** on the per-component `DxfCanvas`: draw each op's cutting
   path, color-coded by op, rapids dashed — reusing the M7.6 bed-render path
   drawing on the design canvas.
2. **Op inspector**: a per-op list from `op_summaries()` + `cuttime` — op, tool,
   strategy, Z-floor, cut length, cut time — with a per-op **visibility toggle** and
   a total; selecting an op highlights its toolpath.
3. **Tests**: the overlay builds from a generated program; the op table matches
   `op_summaries` / `cuttime`; toggles drive visibility. Tag `v0.7.11`.

### M7.12 — Cut-simulation playback scrubber (v0.7.12) · *watch the cut*

> The per-op playback scrubber was trimmed from **M5** (task 4) and again from
> **M7.7**. Built here.

1. **Per-step removal snapshots**: extend `core/sim` to expose the achieved floor
   at op (and optionally move) boundaries — a sequence the GUI can step through.
   Geometric Z-buffer only, no physics.
2. **Scrubber UI** in the Cut Simulation view: a timeline slider + play/pause that
   advances the rendered cut piece op-by-op; the M7.11 op inspector syncs to the
   cursor.
3. Whole-bed playback rides on M7.7's bed sim when a worktable program is loaded.
4. **Tests**: the snapshot sequence is monotonic (material only ever removed); the
   slider maps to op boundaries. Tag `v0.7.12`.

---

## M7.12.1–.3 — Volumetric cut simulation (the M7.12 revisit) · *watch the stock disappear*

> **2026-06-22 — planned (user-approved direction).** M7.12 shipped the headless
> per-op snapshot core (`core/sim/playback.py`) + a scrubber, but it renders the
> **achieved-floor *sheet*** lurching op-by-op — not a solid block of stock being
> eaten by a moving tool. This three-phase arc revisits **only the rendering &
> animation**; the M7.12 headless snapshot core is **retained**, and the M7.11
> **2D DXF toolpath overlay is preserved untouched** (and strengthened with a synced
> cursor). It supersedes the floor-sheet render, not the engine.
>
> **Why this stays in Python / heightfields (no new paradigm):** our parts are
> single-side **2.5D** relief milling — *no undercuts* — so a single-Z-dexel (=
> heightfield with a solid body) is geometrically exact for the cut result, matching
> the project's "heightfields + polygons, no CAD kernel" principle (§6). The
> compute is vectorised numpy; rendering is GPU via VTK with **in-place point-Z
> updates** (fixed grid topology) — so smooth animation is a rendering-strategy
> change, not a language change. Reference model: dexel material-removal sim, as in
> CAMotics (the open-source 3-axis G-code analog). Numbered `.1/.2/.3` (PEP 440
> `0.7.12.1`…) so the downstream M7.13–M7.16 plan is undisturbed.
>
> **Purpose (user, 2026-06-22):** a beautiful, accurate *preview for judgment* — does
> the cut match intent, and will the tool **or its holder** slam into a hold-down? —
> not a substitute for a real air-cut.

### M7.12.1 — The block, carved in place (`v0.7.12.1`) · *solid stock + animated removal* — ✅ DONE 2026-06-22

> **DONE (`v0.7.12.1`, 335 tests).** `core/sim/playback.py` `simulate_removal` carves
> the real stock heightfield at fine move-batch granularity (`RemovalPlayback`,
> monotone, op boundaries aligned to frames; +11 tests). `Viewer3D` renders the
> stock as **one watertight opaque solid** — a two-layer `pv.StructuredGrid` (flat
> bottom + carved top) — animated by updating only the top layer's Z in place
> (fixed topology → GPU-fast), driven by the timeline slider + play/pause. The
> surface is **coloured by elevation** (dark-brown→amber ramp fixed to the stock
> height) so cut depth reads at a glance and a region darkens as it's carved — the
> on-screen win that made the result legible. Two rendering missteps fixed en route
> (a translucent envelope that z-fought; a flat-amber slab with no depth contrast).
> Playback pauses when the viewer is hidden (no incomplete-framebuffer noise).
> **2D-cursor reframe:** the central view is a stacked widget (2D *or* 3D), so a
> marker on the 2D path is invisible during 3D playback; the live 2D↔3D link is the
> M7.11 **op-inspector sync** (the Toolpaths dock, visible beside the 3D view).
> The literal 2D path marker is deferred — it only pays off in a future side-by-side
> layout; the per-frame tool *position* is spent on the M7.12.2 moving tool instead.



1. **Remaining-stock heightfield** (`core/sim`): start from the real two-level stock
   (blank + pad block) as the initial solid top; sweep the densified cutting moves,
   lowering each column under the tool footprint by the existing tool drop profile.
   Generalise the M7.12 `simulate_steps` to **arbitrary cut-fraction checkpoints**
   (fine move-batch granularity), with the op boundaries kept as labelled timeline
   markers. Monotone by construction; final frame == the M7.12 achieved floor.
2. **Closed-solid mesh** (`Viewer3D`): render the stock as a **block** — top
   heightfield + an outer skirt down to the anterior face. Through-cuts (fully
   consumed columns) open as holes via **cell-blanking** (degenerate/masked quads)
   so the mesh **topology is fixed** — the precondition for in-place animation.
   Interior pocket walls are a later fidelity dial (v1 already reads as a carved block).
3. **In-place animated removal**: triangulate the grid **once**; each frame overwrite
   only the points' Z + the blank-cell mask and mark modified — VTK redraws on the
   GPU (the fix for the M7.12 lurch, which rebuilt the whole mesh per op). A real
   continuous timeline (play/pause + slider); the M7.12 op-scrubber becomes the
   coarse op-marker layer on the same timeline.
4. **2D↔3D sync (preserve + strengthen the M7.11 overlay)**: a marker rides the 2D
   toolpath at the same path position as the 3D cut cursor, so the literal path (2D)
   and its physical result (3D) animate together. **The 2D overlay itself is unchanged.**
5. **Tests**: remaining-stock floor monotone + final == M7.12 floor (same min-Z);
   cell-blank mask == the through-cut mask; the point/topology buffer length is
   constant across frames. Tag `v0.7.12.1`.

### M7.12.2 — The cutter you can see (`v0.7.12.2`) · *tool, shank, holder* — ✅ DONE 2026-06-23

> **DONE (`v0.7.12.2`).** The removal core records the tool (x,y,z) at every frame
> (`RemovalPlayback.frame_cursors`) + an optional per-op tool-geometry map; `Viewer3D`
> builds a cutter (flat cylinder / ball / V-cone per `ToolProfile`) + shank +
> collet/holder, moves it to the cut cursor each frame (`SetPosition`), and rebuilds
> the mesh only when the op (tool) changes. `tool_profile_dims` is the shared source
> of truth for the mesh + the M7.12.3 collision envelope. Verified on-screen.



1. **Tool-body mesh** per `ToolProfile` (flat cylinder / ball / V-cone) + **shank** +
   a simple **collet/holder** cylinder, sized from the M7.8/M7.9 stick-out / shank /
   flute-length fields. Parked at the cut cursor and advancing along the densified
   path as the timeline plays.
2. **Reach/holder read-out**: the holder height above the stock makes stick-out and a
   holder-into-stock dive legible at a glance (ties to the M7.9 depth-reach warning).
3. **Tests**: the tool mesh matches the profile section (radius / included angle); the
   cursor maps to path arc-length at a given timeline fraction. Tag `v0.7.12.2`.

### M7.12.3 — Bed simulation & hold-down collision (`v0.7.12.3`) · *will it slam into a clamp?* — ✅ DONE 2026-06-23

> **DONE (`v0.7.12.3`, 345 tests).** The volumetric block on the whole bed +
> hold-down collision + a round of UX work that landed alongside it:
> - **Volumetric bed sim** (`core/sim/bed.py` `simulate_bed_removal`): stamps each
>   placed part's stock onto ONE cropped machine-coord grid and carves the combined
>   steps **in the program's tool-grouped order** (`_schedule_step_order`, matching
>   `schedule_bed_ops` — all same-tool ops at once, not part by part).
> - **Hold-down collision**: keep-outs render as red posts at a settable
>   **hold-down height** (`Worktable.hold_down_height_mm`, a Worktable-panel spinbox);
>   a **Z-aware** check (`bed_collision_frames` + `tool_radius_below`) flags a frame
>   only where the tool is low enough to actually foul a hold-down, so the tool turns
>   red, the badge shows the count, and play **pauses with a pop-up** (deferred via
>   `singleShot` so it reliably presents) + a finish-time summary. The height also
>   raises the worktable program's rapid safe-Z so the post clears the hold-downs.
> - **Unified tab/view model**: the toolbar's **2D / 3D / Simulation** toggles are the
>   single view axis; `_switch_view` always re-renders the active tab's content (no
>   more stale-view flash, content pushed before the page is shown). The Simulation
>   toggle drives the component cut-sim or, on the Worktable tab, the bed sim — the
>   separate "Simulate Bed" / "Worktable" buttons are gone; sims are cached so
>   toggling back is instant.
> - **Context-aware sidebar**: the right dock holds component params on a component
>   tab and the worktable controls on the Worktable tab (available across the bed's
>   2D + Sim views).
> - **Smoother playback**: the carved block updates the top layer's Z **in place**
>   (no per-frame points reassignment / pipeline rebuild), ~18 fps, more frames.
> Whole-bed playback (deferred in M7.7 / M7.12) is delivered here. Some residual
> step-jump remains (discrete frames) — a future polish.



1. **Volumetric bed sim**: composite the per-component remaining-stock heightfields
   onto one machine-coords bed grid (reusing `core/sim/bed.py`), animated with the
   same in-place renderer.
2. **Hold-downs as solids**: render the worktable `KEEP_OUT` zones (screws / clamps)
   as 3D bodies on the bed at their stock height.
3. **Fouling highlight**: as the tool + holder sweep, flag (red) any frame where the
   **tool or holder** enters a keep-out — the 3D companion to the existing
   `worktable_clearance_violations` (tip-only today; this adds the holder body),
   with a per-collision marker + jump-to-frame.
4. **Tests**: a known clamp-fouling job flags ≥1 frame, a clear job flags none; the
   holder-radius check generalises the tip check. Tag `v0.7.12.3`.

### M7.13 — Measure/inspect & 3D section view (v0.7.13) · *verify before you cut*

1. **2D measure tools** on `DxfCanvas`: point-to-point distance, angle, and a
   caliper read-out (verify lens opening, DBL, hinge spacing) — a small measure
   mode that snaps to curve points.
2. **3D section plane** on `Preview3D` / `Viewer3D`: a movable cutting plane that
   slices the model so the maker can inspect terrace heights and footing depths —
   directly serving the castle teaching ethos (§2).
3. **Tests**: distance / angle math; the section produces a valid cross-section
   polyline at a given plane. Tag `v0.7.13`.

### M7.14 — Job & validation inspector panel (v0.7.14) · *what's blocking green?*

1. **One dockable panel** that aggregates every check the engine already produces —
   tool reach (width + depth), bed / worktable clearance, machine lint, cut
   completeness / gouge — each a severity-tagged, navigable row (click → highlight
   on the relevant canvas / view).
2. **Ties to the readiness dot** (M5.2): the dot says ready / not-ready, the panel
   says *why*; generating and simulating refresh it.
3. **Tests**: the panel collects each warning type from a known-bad job and is
   empty on a clean one. Tag `v0.7.14`.

### M7.15 — Hotkeys & toolbar customization (v0.7.15) · *make it yours*

GuildDraw's `SettingsDialog` already has **Toolbar** and **Hotkeys** tabs; GuildCAM's
`PrefsDialog` (M4.5) deliberately left room for them but only ever shipped General.
Close the parity gap — the maker who lives in both apps gets one muscle-memory.

1. **Hotkeys tab**: an editable shortcut table over the existing actions (Open / Build
   3D / Generate / Export / Simulate / view toggles / Worktable / Nest …), persisted in
   `~/.guildcam/prefs.json` (the `prefs.py` DEFAULTS-merge pattern) and applied to the
   `QAction`s at startup; per-binding **reset-to-default** + a conflict warning. Port
   GuildDraw's hotkeys-tab UX where it fits.
2. **Toolbar tab**: choose which actions appear on the left icon toolbar and their
   order (the toolbar is already built from a known action list in `app.py`); persisted
   and rebuilt on apply. Defaults reproduce today's toolbar exactly.
3. **Tests**: a custom binding round-trips through prefs and rebinds the action; a
   conflict is detected; a hidden/reordered toolbar restores from prefs; reset returns
   the shipped defaults. Tag `v0.7.15`.

### M7.16 — Frame-style parameter presets (v0.7.16) · *recall a house style in one click*

The castle params (Towers / Walls / Footing / Stock) define a frame's *style*; a shop
makes many frames in a handful of house styles. Save and recall a whole `CastleParams`
set as a named preset — the third use of the now-familiar store pattern (materials M4.9,
tools M7.8).

1. **`gui/style_store.py`** (the material/tool store pattern): named **frame-style**
   presets — a full `CastleParams` snapshot (zone heights, footing schedule, stock,
   onion skin, allowance) — shipped defaults (at least the Demo reference as "Guild
   demo") merged with user presets in `~/.guildcam/frame_styles.yaml`.
2. **Castle/Stock tab control**: a preset combo + **Save as preset… / Update / Delete**;
   selecting a preset loads it into the dock (one live rebuild, like material apply);
   editing then saving offers to update or fork it. Presets are project-independent
   (they seed a new frame); the `.gcam` still stores the frame's actual params.
3. **Tests**: save → list → load round-trips a full `CastleParams`; shipped presets are
   never written; a loaded preset drives the preview; delete/reset behave. Tag `v0.7.16`.

### M7.8–M7.16 exit criteria
- [x] Managed tool library — add/edit/delete/reset in Settings (shipped + override
      store), no hand-editing `tools.yaml`, stable T-numbers + setup-sheet tool
      table (M7.8)
- [x] Live tool visualizer; real V-bit type; depth/stickout reach warnings (M7.9)
- [x] Feeds & speeds / chip-load calculator tying tools↔materials (M7.10)
- [x] Toolpath overlay + per-op inspector on the design canvas (M7.11)
- [x] Cut-simulation playback scrubber (M7.12)
- [x] Volumetric stock removal — solid block carved in-place, coloured by elevation (M7.12.1)
- [x] Visible tool + shank + holder following the path (M7.12.2)
- [x] Bed sim with hold-down (tool **and holder**) collision highlight + Z-aware height (M7.12.3)
- [x] Unified 2D/3D/Sim view model + context-aware sidebar (M7.12.3)
- [ ] On-canvas measure + 3D section view (M7.13)
- [ ] Job/validation inspector panel consolidating all warnings (M7.14)
- [ ] Customizable hotkeys + toolbar (GuildDraw-parity Settings tabs) (M7.15)
- [ ] Saveable frame-style parameter presets (M7.16)
- [ ] Full suite green; sub-milestones tagged `v0.7.8` … `v0.7.16`

## M8 — Hardware round-trip (v0.8.0) · *the only gate that cuts acetate*

> Was M7 (and M6 before the 2026-06-15 replan); now validates the **reoriented,
> multi-component** flow on real stock — a whole `.gdraw` model nested on the
> worktable — not just a single frame front.

1. Cut the demo model on the Guild CNC **from a single `.gdraw`** through the
   reoriented flow — import → per-component build → worktable nest → combined bed
   program — covering the frame front (hinge pockets → relief → eyewires →
   perimeter, onion skin) plus its temples and base-curve templates; release by
   hand, compare against the Fusion-cut reference part.
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

## M9 — Two-sided workflow & export polish (v0.9.0)

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

## M10 — Rename decision, packaging, docs & release (v1.0.0)

1. **Resolve GuildCAM → GuildModel** (the 2026-06-18 "decide later" gate). If
   GuildModel is chosen, execute the rename in one pass — it is mechanical but
   pervasive: the `guildcam` package + entry points, the `.gcam` extension (decide:
   keep, or rename e.g. `.gmod`), the `~/.guildcam` prefs/materials dir, window
   titles + about box, the installer, README/NOTICE, and these docs. If the name
   stays GuildCAM, record the decision and skip the pass. Do this **before** the
   build so the released artifact carries the final name.
2. PyInstaller → Windows installer (Inno Setup); frozen-build smoke test.
3. User guide: castle ethos chapter (§2 expanded with the stage-stepper
   walkthrough), zone/SCULPT drawing guidance for GuildDraw, parameter reference,
   fixture/stock setup, hand-finishing notes; cut-simulation verification chapter;
   **M6 chapters — multi-tool setup, stock-box zero, temples + engraving,
   base-curve blocks, worktable layout/nesting**; **M7 chapters — `.gdraw` model
   intake, the per-component workspaces, and the interactive worktable (import a bed
   DXF, tag role zones + keep-outs, nest, generate combined or per-component)**;
   **M7.8–M7.16 chapters — the managed tool library + visualizer, the feeds &
   speeds / chip-load calculator, the toolpath & cut-sim inspection tools, the
   on-canvas measure / 3D section tools, and workflow personalization (custom
   hotkeys/toolbar + frame-style presets)**.
4. README, NOTICE refresh, version stamp, tag `v1.0.0`.

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
- [x] Multi-tool jobs (per-op tool change), stock-box zero, temples + engraving,
      auto base-curve blocks, and multi-part worktable layout (M6.1–M6.5)
- [x] **Reoriented around the whole model**: one `.gdraw` → frame front + both
      temples + per-lens base-curve templates as separate components (M7.1–M7.2),
      per-component 3D workspace tabs (M7.3), an interactive worktable from a tagged
      bed DXF (M7.4), per-component 3D solids (M7.5), role-matched auto-nesting with
      polygon keep-outs (M7.6), and one combined bed program *or* separate
      per-component programs + the whole-bed cut sim (M7.7) — **M7 complete**
- [ ] **Tooling & control UX**: a managed tool library + live visualizer + feeds &
      speeds calculator (M7.8–M7.10); toolpath overlay + op inspector, cut-sim
      playback scrubber, measure / 3D section, and the job/validation inspector
      panel (M7.11–M7.14); customizable hotkeys/toolbar + frame-style presets
      (M7.15–M7.16)
- [ ] **A physical model (+ the M6 op set) has been cut and accepted** — the
      reoriented `.gdraw` → worktable flow on real stock (M8 — also graduates
      GuildDraw to v1.0.0)
- [ ] Two-sided back-side program + loose exports (M9)
- [ ] GuildCAM→GuildModel rename decision resolved; packaged Windows build + user
      guide with the castle + M6 + M7 chapters (M10)
- [ ] Test suite green and run before every release build

---

# Post-1.0 backlog (do not build in v1)

In rough priority order; the user supplies reference material per item as it
arises. (**Temples** and **base-curve forming blocks** were moved *into* v1 by the
2026-06-15 M6 replan, and **`.gdraw` direct intake** — formerly item #3 — by the
2026-06-18 M7 reorientation; none are listed here any longer.)

1. **Lens patterns** — pattern cutting; OLGA `bevel_flank()` (dormant since
   the spike) likely returns here for lens grooves.
2. BRIDGE angled cutaway (layer reserved in both apps).
3. CHA hinge catalog placement UI (v1 drives pockets from the HINGE layer;
   the catalog machinery in `relief/hinge.py` stays for this).
4. STEP/B-rep export, adaptive strategies, macOS/Linux — unchanged from the
   spike's exclusion list.

---

# Reference

## Module status (as of 2026-06-16, M6 complete — M6.5)

Statuses: ✅ solid · ⚠️ works with known issue · 🔄 to be rewritten in M-series · 🔲 stub / missing

| Module | Status | Notes |
|---|---|---|
| `core/layers.py` | ✅ | Single source of truth for layer names/styles (importers, validator, GUI all import it) |
| `io_import/dxf.py` | ✅ | All 7 layers incl. SCULPT/ENGRAVING; `posterior=True` flip is the default (M1) |
| `io_import/svg.py` | ⚠️ | npoint float-arg bug; the M7.2 `.gdraw` reader converges here (fix to GuildDraw's SVG dialect or retire); fix-or-drop decision in M9 (export polish) |
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
| `cam/castle_ops.py` | ✅ | The five-op posterior program (M3); gated against the reference NC; `op_summaries()` setup sheet (M4); contour-parallel relief + ring-major eyewires (M4.7); relief stepover 0.9 + ramp-angle param + `CastleCamParams` from schema (M4.8); **rim-band clearing in `relief_ops`** so the finish pass reaches every rim (M5 — uncut 13.7 %→0.05 %); **per-op tools** — `CamOp.tool`, `generate_castle_program(tools_cfg=)`, `relief_ops(fine_tool, rough_tool)`, `reach_warnings`/`analyze_program_reach`, `build_tool_settings`/`count_tool_changes` (M6.1); **`write_castle_program(contour_op_names=)`** so non-castle programs reuse the post (M6.3); **`drill_op_names`/`peck_depth_mm`** for peck-drill ops (M6.4) |
| `cam/temple_ops.py` | ✅ | **New (M6.3)** — temple component CAM: `generate_temple_program` (Engraving at `thickness−depth` + Temple Profile outline through-cut), `engrave_op` / `temple_profile_op`, `TEMPLE_CONTOUR_OPS`; one tool change (engrave bit → bulk) via the M6.1 post |
| `cam/block_ops.py` | ✅ | **New (M6.4)** — base-curve forming block: `generate_block_program` (Drill Holes + Forming Profile scribe + Block Profile), `drill_holes_op` / `forming_profile_op` / `block_profile_op` / `center_on_origin`, `BLOCK_DRILL_OPS` / `BLOCK_CONTOUR_OPS`; drill→bulk tool change |
| `cam/layout.py` | ✅ | **New (M6.5)** — worktable nesting: `build_bed_program` (place parts on fixture zones, prefix names, schedule), `transform_ops` / `place_ops_at_zone` / `zone_center`, `schedule_bed_ops` (precedence-aware tool-change minimiser), `bed_clearance_violations` (drill-exempt); the bed is the fixture |
| `cam/cuttime.py` | ✅ | **New (M4.8)** — GRBL cut-time model: assumption-free cutting-only + accel-aware GRBL-planner cycle estimate; `format_report`; `MachineDynamics.from_profile`; drove the 1.95×→0.87× gap close; **tool-change count + dwell → `total_seconds`** (M6.1) |
| `core/sim/` | ✅ | **New (M5)** — geometric cut simulation: `toolsim.py` (`ToolProfile` flat/ball/toroid + `achieved_floor` Z-buffer), `paths.py` (cutting paths from posted program or CamOps), `report.py` (`verify` → completeness/gouge `CutReport`); the machined-result verifier that caught the relief incompleteness; **multi-tool** `achieved_floor_grouped` + `cutting_paths_from_program_grouped` (per-move tool profiles) (M6.1) |
| `cam/dropcutter.py` | ✅ | grey-dilation ball/flat/toroid; CLS feeds the relief ops |
| `cam/profile.py` `pocketing.py` | ✅ | pyclipper offsets/cascade; castle_ops uses the pocketing cascade |
| `cam/tabs.py` | ✅ | Correct, but **retired for frame fronts** (onion skin instead); stays available |
| `post/grbl.py` | ✅ | ramped pocket laps + `arc()` G2/G3 + arc-fit (M4.7); **partial-lap ramp lead-in** for through-cuts (M4.8); **`ToolSetting` + `apply_tool`/`tool_change`** (M0/M6 change blocks) + multi-tool `write_castle_program` (M6.1); **`work_offset`** — program-zero datum applied to every emitted coordinate, arc I/J untouched (M6.2); **`peck_drill`** (G83 full-retract) (M6.4) |
| `post/arcfit.py` | ✅ | greedy least-squares circle fit, polyline → G2/G3 arcs (constant-Z runs only); GRBL-valid radius agreement (M4.7) |
| `post/machine.py` | ✅ | **New (M4.8)** — load/list `MachineProfile`s, `apply_machine_limits` (clamp feed/plunge/spindle/DOC, linearize arcs), `lint_program` (envelope/feed/spindle/arc checks) |
| `mesh/twosided.py` `stl_export.py` | ⚠️ | Superseded by `build_castle_mesh` for frame fronts; review/retire in M9 (export polish) |
| `project/schema.py` `save_load.py` | ✅ | `CastleParams` (M1); legacy `ReliefRecipe` removed (M4); `CastleCamParams` + `MachineProfile` + `MachineRef` on `ProjectSchema` (M4.8); **`op_tools` per-op map + `POSTERIOR_OPS`; `MachineProfile.tool_change_mode`/`tool_change_seconds`** (M6.1); **`ProgramZero` datum (datum_world/work_offset/label) on `CastleCamParams.program_zero`** (M6.2, default center/center/bottom); **`TempleParams` on `ProjectSchema.temple`** (M6.3); **`BaseCurveBlockParams` (hole_centers/stock) on `ProjectSchema.base_curve_block`** (M6.4); **`BedLayout`/`ComponentPlacement` on `ProjectSchema.bed_layout`** (M6.5) |
| `project/gcam.py` | ✅ | **New (M5.1)** — `.gcam` ZIP project container: `save_gcam`/`load_gcam` (manifest + per-file SHA-256, atomic write), `extract_handoff` (gSender-fork subset); embeds the source DXF for self-contained reopen |
| `config/` | ✅ | fixture (nosepad sub-zone), hinges, `flat_3175` tool, acetate feeds (M3); **`machines/` profiles: guild_cnc, carbide_nomad3, carbide_shapeoko, generic_grbl, grbl_no_arc** (M4.8); **`flat_2mm` pocket tool + optional per-tool feeds/DOC; `tool_change_mode` in machine YAML** (M6.1); **`engrave_vbit` engraving tool; `temple_right`/`temple_left` fixture zones** (M6.3); **`drill_m4_clear` (4.5 mm) drill; `acetal` material** (M6.4) |
| `gui/app.py` + widgets | ✅ | Castle UI (M4); theming/dark/prefs/recent/STL (M4.5); docks + icon toolbar + progress (M4.6); CAM machine/tool selectors + strategy + feeds, machine-clamp/lint + cut-time report (M4.8); material-driven feeds + write-back prompt + Materials prefs tab (M4.9); Cut Simulation workspace (`SimWorker` + Simulate toolbar button, 3rd view) (M5); **File ▸ Save/Open Project `.gcam` + embedded-DXF retention + `set_castle_params` restore** (M5.1); **readiness traffic-light** — three flags + `_refresh_readiness`/`_invalidate_program`, green only on program-stored-to-`.gcam` (M5.2); **Generate stores the program in the project by default + File ▸ Export G-code (`Ctrl+Shift+G`) for a loose `.nc`** (post-M5.2 refinement); **Per-operation tools group; generate/sim workers wire `tools_cfg` + `tool_settings` + reach warnings + tool-change cut-time** (M6.1); **Program Zero group + `DxfCanvas.set_program_zero` datum crosshair + work-offset into the generate post + setup-sheet datum** (M6.2); **temple detection on import + `GCodeWorker._generate_temple` (engrave + profile, program-zero, temple-zone clearance) + `temple_params()`** (M6.3); **File ▸ Generate Base-Curve Block + `GCodeWorker._generate_block` + `block_params()`** (M6.4); **File ▸ Generate Worktable Program + `GCodeWorker._generate_worktable` (auto-pack frame + block, combined post, bed clearance)** (M6.5) |
| `gui/widgets/cut_sim_view.py` | ✅ | **New (M5)** — `CutSimView` PyVista viewport: renders the simulated cut piece, Uncut/Gouge overlay toggles, pass/warn/fail badge |
| `gui/widgets/readiness_dot.py` | ✅ | **New (M5.2)** — status-bar `ReadinessDot` (painted ~10 px circle, theme-recolored, exact tooltips) + the pure `state_for(...)` state machine |
| `gui/material_store.py` | ✅ | **New (M4.9)** — shipped + user-override material presets (`~/.guildcam/materials.yaml`); `effective`/`cam_values`/`changed_keys`/`save_override`/`reset_material` |
| `gui/icons.py` | ✅ | M4.6 — `_make_icon` port (SVG→two-state QIcon) + `apply_toolbar_icons`; text fallback; `sim-cut` icon added (M5) |
| `gui/style/theme.py` `gui/prefs.py` | ✅ | M4.5 — GuildDraw QSS + CanvasPalette; `~/.guildcam/prefs.json` (M4.6 window state; M4.8 `cam_params`; M4.9 `material_name`) |
| `tests/` | ✅ | **197 green** (smoke 16 + M1 10 + M2 11 + M3 12 + M4 8 + M4.5 7 + M4.6 23 + CAM-quality 7 + cuttime 5 + machine 12 + materials 5 + cut-completeness 5 + gcam 6 + readiness 9 + multitool 14 + program-zero 12 + temple 12 + base-curve block 11 + **worktable 11**, incl. STL/NC/silhouette/arc/ramp/budget/clamp/completeness gates + the `.gcam` round-trip + the readiness state machine + the M6.1–M6.5 per-op-tool/change-block/reach/datum-offset/temple-engrave/block-drill/bed-schedule gates) |

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
