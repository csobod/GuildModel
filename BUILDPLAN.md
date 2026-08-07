# BUILDPLAN.md — GuildModel · Road to Version 1.0

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
> roadmap was built against — the maker's manual Fusion 360 workflow (the
> `DEMO_PROJECT_TEARDOWN.md` teardown) and the OLGA behavioural
> reverse-engineering (`OLGA_TEARDOWN_AND_PLAN.md`) — is kept in the maker's
> local working tree and is **not** part of the published repository; the Demo
> Project ground truth itself is vendored under `tests/fixtures/demo/`. The
> GuildDraw-side export contract is `BUILDPLAN.md` §2 in the GuildDraw repo.

---

## Status snapshot *(2026-06-16, **M6 COMPLETE — M6.5 worktable-nesting tagged `v0.6.5`** — File ▸ Generate Worktable Program cuts the frame front + its base-curve block in ONE program, auto-packed onto the fixture zones and scheduled to minimise tool changes across the bed (demo 2-part bed = 1 change). M6 "Expanded CAM operations" all done: ✅ M6.1 multi-tool → ✅ M6.2 stock-box zero → ✅ M6.3 temples+engraving → ✅ M6.4 base-curve blocks → ✅ M6.5 worktable nesting. Suite 197 green. Roadmap (2026-06-18 reorientation replan): **M7 reorientation** — one `.gdraw` → a multi-component project (frame front + both temples + a per-lens base-curve template), per-component 3D workspace tabs, an interactive worktable from a tagged bed DXF, role-matched auto-nesting, and combined-or-per-component G-code (`v0.7.1`–`v0.7.6`) — then hardware round-trip M8 (the only gate that cuts acetate — also graduates GuildDraw to v1.0.0), two-sided M9, rename-decision + packaging/v1.0.0 M10. **M7.1 project model ✅ DONE (`v0.7.1`) + M7.2 `.gdraw` intake ✅ DONE (`v0.7.2`, 233 tests — reader + File ▸ Open Model + the component notebook: a tab per component, tab-switch rebinds the active component) + M7.3 per-component notebook ✅ DONE (`v0.7.3`, 234 tests — component tabs + kind-aware editable param dock (Temple/Base Curve tabs) + per-component param persistence) + M7.4 interactive worktable ✅ DONE (`v0.7.4`, 247 tests — `Worktable`/`WorktableZone`/`BedRole` model in `project/schema.py` (role-tagged zone polygons + keep-out polygons in machine coords; `from_fixture_dict`/`to_fixture_dict` load the Guild `guild_cnc.yaml` as the default bed and bridge back onto the M6.5 layout machinery unchanged); `core/cam/worktable.py` reads a bed DXF → `polygonize`d regions, `default_worktable`, `.bed` YAML I/O; GUI: a trailing **Worktable** tab (peer of the components) with a machine-coords `BedCanvas` — import a bed DXF / load the Guild bed, click a region, tag its role (frame-front / temple R-L / base-curve R-L / keep-out); persisted in the `.gcam`) + M7.5 per-component 3D models ✅ DONE (`v0.7.5`, 258 tests — `core/relief/flat.py` reuses the castle mesher for flat parts: temple = outline extruded 4 mm + HINGE blind pockets + ENGRAVING grooves, snapped hinge-end to the blank + a visual injected-core bar; base-curve block = the lens shape cut from a 70×70×4.7625 acetal blank, 3 M4 through-holes (2026-06-19: CAM simplified to Drill Holes + Block Profile=lens-shape cut, forming scribe + box cut dropped); GUI `FlatMeshWorker` + Build-3D enabled per kind); next: M7.6 role-matched auto-nesting onto the tagged bed (+ polygon keep-outs, bed render/nudge), then M7.7 combined/per-component G-code**)*

> **2026-08-06 — STAGE 1 KERNEL SPIKE RUN AND PASSED; STL WATERTIGHTNESS FIXED.**
> The B-Rep go/no-go has been taken against the Demo Project frame on
> `cadquery-ocp` 7.9.3.1.1 (OCCT 7.9): **the kill criteria are not met, proceed.**
> The tapered partial-span chamfer — the risk the report ranked first — builds
> valid in 0.14 s on a B-spline spine, needing only a 0.02 mm floor on the taper
> (a section that collapses to a true point fails `MakeSolid()`). **The fillet
> question came back the other way, and it corrected the plan rather than killing
> it:** 0 of 16 footing edges accept `BRepFilletAPI_MakeFillet` at the Demo
> Project's scheduled radii, because those radii (4–48 mm) are an order of
> magnitude larger than the steps they blend (0.2–5.8 mm) — they were never edge
> fillets, they are *cross-section* S-blend radii, exactly what `_footing_z`
> already implements. Sweeping that existing profile along the SCULPT cut line
> instead: **10/10 sweeps valid, 10/10 booleans valid, 0.12 s.** Report §9 has the
> numbers and supersedes its own §4.3 and §5.2. Re-derive with
> `DISPLAY= .venv/bin/python scripts/spike_brep.py`. *Still unproven: PyInstaller
> packaging (and there is no Linux CI workflow), determinism across OCC versions,
> the `flat.py` duck-type, preview interactivity.*
>
> **M18 #2 landed (the shipping STL bug).** `build_castle_mesh` produced open
> solids at fine grids. **The M17 attribution to the rim stitch was wrong** — the
> face set is closed as authored (`process=False` gives 0 open edges at every
> resolution). `_snap_to_rings` is not injective: two adjacent boundary vertices
> can project onto the same point of the outline / lens / pocket curve, trimesh's
> `process=True` welds them, and the collapsed rim quad becomes zero-area slivers
> that survive the merge — and a degenerate face's edges read as unpaired. The
> failure was never monotonic in resolution (open at 0.25 and 0.20 mm, closed at
> 0.40 / 0.30 / 0.15 mm), which is why "finer than either figure, so likely open"
> did not hold. Fix drops faces that lost a distinct corner to the weld — a
> topological test, not an area one; trimesh's own `nondegenerate_faces` is
> area-based and at its default strips legitimate thin grid triangles, tearing far
> more than it repairs. Watertight and genus-2 across 0.40 → 0.10 mm. Suite 675 →
> **679**, the four new cases proven to fail without the fix.
>
> **2026-08-06 — FEATURE CRISPNESS: root cause found, architecture decision
> open.** The cutting features read as blended and pitted rather than as a Fusion
> boolean. **Cause: the raster relief has no representation of an *edge*, so every
> fix attempted so far has been a smoothing filter applied to a sampling
> artifact.** Measured on the demo frame: adjacent rim vertices on a curve that
> should be smooth differ by 0.11 mm on average, 0.48 mm worst case, at preview
> resolution (`scripts/probe_rim_error.py`). Direction: a real B-Rep kernel
> (OpenCASCADE), **after V2** — full diagnosis, kernel survey, costs, staged plan
> and kill criteria in **`BREP-REWRITE-REPORT.md`**; milestone entry in the
> **"Feature crispness"** section near the end of this file. Four contained fixes
> worth making first are proposed there as **M18**, two of which are bugs shipping
> today. *Nothing here displaces V2 — the flip fixture is a hardware gate.*

> **2026-07-29 — `v1.1.0`, 586 tests: WHOLE-BED WORKFLOW HARDWARE-PROVEN + the
> safety fix that got it there.** A complete nested worktable — frame front, both
> temples, both base-curve forming blocks — has been **cut on real stock in one
> program** on the Guild CNC (LUNYEE 3020 Nova), running clean at the tuned
> `$120 = 300`. That graduates worktable nesting, temples and base-curve blocks
> out of beta in the README; the lens bevel groove is now the only beta path left
> (plus two-sided, still planned). The bed could not be proven until the defect
> below was fixed.
>
> **The safety fix: the worktable posted preview geometry.** A bed program made both
> axes oscillate hard enough to be E-stopped on the real LUNYEE 3020, while the
> *single-component* export of the same part had air-cut cleanly minutes earlier.
> **Root cause:** `NestWorker` built each component's relief at
> `max(0.4, prefs["preview_resolution_mm"])` — the 3D-preview grid — and
> `build_nest_program` posts those ops **verbatim** as `worktable.nc`. The relief is
> terraces joined by ~1 mm footing blends; a 0.4 mm grid aliases them into a
> staircase, `castle_ops._bilinear_sample` rides it, and the Z axis reverses on
> roughly every other cutting move (the bad file's median XY step is **exactly
> 0.4000 mm** — `_densify_xy(ring, res)` fingerprinting the grid). Measured on the
> demo part: 9.0 → 39.9 Z reversals per 100 mm going 0.15 → 0.4 mm, total Z travel
> doubling. The single-component path was always 0.15, hence one path safe and one
> not. **Fix:** `core/relief/castle.py` gains `CUT_RES_MM = 0.15` — *the* grid for
> anything that becomes G-code — and `NestWorker` / `BedSimWorker` no longer take a
> `resolution` at all, so no call site can hand a posting path a preview grid.
> Second defect from the same report: neither worktable path ever called
> `apply_machine_limits`, so bed programs bypassed the machine + material clamps the
> single-component path applies; `core/post/machine.py` gains `clamp_cam_to_machine`
> and all three posting paths now share it. Also fixed: `BedPlacement.rotate` left
> `dx`/`dy` stale, so the setup sheet mis-reported where a rotated part sat.
> Verified by re-posting the real Benedict bed: rough-relief reversals **55.8 →
> 16.5** per 100 mm and fine **48.3 → 8.2**, matching the known-good standalone
> program (16.5 / 8.3) — and where XY coincides, Z is now bit-identical to it.
> New `tests/test_worktable_cut_parity.py` (10) gates all three properties,
> including a teeth-check that a preview-grade relief still trips the Z-thrash gate.
> **Upgrade note for users:** the fix is in the generator, not the file — any
> `worktable.nc` produced before `v1.1.0` must be re-nested, re-posted and
> re-verified before it is run.

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

The maker's manual Fusion 360 workflow — reconstructed end-to-end in the local
`DEMO_PROJECT_TEARDOWN.md` teardown (kept in the working tree, not published) —
is the acceptance target for M1–M3. Summary:

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

### M7.13 — Measure/inspect & 3D section view (v0.7.13) · *verify before you cut* — ✅ DONE 2026-06-23 (362 tests)

1. **2D measure tools** on `DxfCanvas` ✅ — `core/geometry/measure.py` (pure, tested):
   `distance`, `angle_at`, `snap_to_vertices`. A canvas measure mode: left-click drops
   points snapped to the nearest curve vertex (~10 px), live rubber-band, dimension
   lines + length labels, a corner angle on the third point, a snap box at the cursor;
   Esc clears; status-bar read-out. A checkable **Measure** action (toolbar Views group
   + View menu, hotkey `M`, `measure.svg`, theme `measure` colour), gated to the
   component 2D outline with geometry loaded — leaving that view ends the mode.
2. **3D section plane** on `Viewer3D` ✅ — `core/mesh/section.py` `mesh_section`
   (pure, tested) + a **Section** toggle in the model toolbar: `add_mesh_clip_plane`
   draws a draggable cutting plane (tinted with the measure accent) so the maker reads
   terrace heights + footing depths; cleared entering sim / on clear(); falls back to
   the full mesh if the widget can't be created.
3. **Tests** ✅: distance / angle / snap math (`test_measure_m713`); the section of a
   cube yields the square-perimeter polyline, a miss → empty (`test_section_m713`).
   Tagged `v0.7.13`.

### M7.14 — Job & validation inspector panel (v0.7.14) · *what's blocking green?* — ✅ DONE 2026-06-23 (370 tests)

1. **One dockable panel** ✅ — `core/diagnostics.py` `Issue` + `collect_issues`
   (pure, tested) fold every engine check — tool reach (width + depth), bed /
   worktable clearance, machine lint, cut completeness / gouge, **and the M7.12.3
   hold-down collisions** — into one severity-sorted list. `gui/widgets/inspector.py`
   `InspectorPanel` (dock tabbed with the Log): colour-coded severity rows (✓ when
   clean), a count badge in the dock title, click-to-navigate (highlight the op's
   toolpath / open the Sim / open the Worktable / **scrub to the first collision** via
   `Viewer3D.goto_first_collision`). Tab-aware: component tabs show the component job,
   the Worktable tab shows the bed's clearance + collisions + lint.
2. **Ties to the readiness dot** ✅ — the dot says ready / not-ready, the panel says
   *why*; the `GCodeWorker` stashes reach/clearance/lint, the sim hands over its
   `CutReport`, the bed sim its collisions — each refreshes the dock (inputs persist
   per component via `workspace.diag`).
3. **Tests** ✅ (`test_diagnostics_m714`): every category aggregates from a known-bad
   job, a clean job is empty, severity sort + per-category targets + `severity_counts`.
   Tagged `v0.7.14`.

### M7.15 — Hotkeys & toolbar customization (v0.7.15) · *make it yours* — ✅ DONE 2026-06-23 (378 tests)

`gui/shortcuts.py` (pure, tested): `ActionSpec` + `effective_shortcuts` /
`find_conflicts` / `effective_toolbar`. The main window builds an **action registry**
(key → QAction + label + group + live default shortcut) that drives both features.

1. **Hotkeys tab** ✅ — a per-action `QKeySequenceEdit` table; per-row ↺ + reset-all to
   defaults; a live duplicate-shortcut warning. `_apply_hotkeys` binds each `QAction`
   from prefs (override or default) at startup + on OK; only genuine overrides persist
   to `~/.guildcam/prefs.json` (`"hotkeys"`).
2. **Toolbar tab** ✅ — a checkable, reorderable (▲/▼) list of every action + reset; the
   toolbar is rebuilt by `_rebuild_toolbar` from the effective order with a `ToolSep`
   divider auto-inserted at each group boundary (iconless actions fall back to text).
   Order persists (`"toolbar"`, `[]` = shipped default); rebuilt on OK. Defaults
   reproduce today's toolbar exactly.
3. **Tests** ✅ (`test_shortcuts_m715`): override/default round-trip, conflict detection,
   empty-never-conflicts, default + custom toolbar order, drops unknown keys, reset.
   Tagged `v0.7.15`.

### M7.16 — Frame-style parameter presets (v0.7.16) · *recall a house style in one click* — ✅ DONE 2026-06-24 (388 tests)

1. **`gui/style_store.py`** ✅ — the store pattern's third use (materials M4.9, tools
   M7.8): named `CastleParams` snapshots; shipped **'Guild demo'** computed from the
   schema default (never written) merged with `~/.guildcam/frame_styles.yaml` via
   add / override / `_deleted` tombstone. `style(name)` → `CastleParams`.
2. **Castle-tab control** ✅ — a **Frame style** group: a preset combo (selecting loads
   it into the dock via `set_castle_params`, one live rebuild like material apply) +
   **Save as… / Update / Delete** (Update warns before editing the shipped reference).
   Presets seed a frame; the `.gcam` still owns its actual params.
3. **Tests** ✅ (`test_style_store_m716`): save → list → load round-trips a full nested
   `CastleParams`; shipped baseline never written; delete/reset/tombstone; a panel test
   confirms a loaded preset drives the dock + emits `castle_changed`. Tagged `v0.7.16`.
   **This completes the M7.8–M7.16 "Tooling & control UX" block.**

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
- [x] On-canvas measure + 3D section view (M7.13)
- [x] Job/validation inspector panel consolidating all warnings (M7.14)
- [x] Customizable hotkeys + toolbar (GuildDraw-parity Settings tabs) (M7.15)
- [x] Saveable frame-style parameter presets (M7.16)
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

## M11 — RC1 follow-ups: per-component flexibility & UX (post-`v1.0.0-rc1`)

> Field-driven refinements found cutting real frames. The theme is **per-component
> independence**: each part (front / each temple / each base-curve block / the
> worktable) carries its own setup, and the whole session round-trips in the
> `.gmodel`. Listed in rough build order (tractable → architectural).

**STATUS — all 7 ✅ COMPLETE (2026-06-29), 425 tests green.** Commits: toolbar
toggles + dock side-by-side/wrap (`f84b8c8`), pad-block toggle (`5932…`), engrave
bit + temple hinge tool `3a5221c`, temple stock-side `b08ab85`, per-component zero
`a81a1d4`, bed zero `2e1519c`, centerline engraving `6d7acd4`. Two behaviour changes
to air-cut on the beta temple path: the temple NC now snaps to its blank (matches the
3D) and engraves stroke **centerlines** by default (was outline-trace).

1. **Toolbar toggles for Toolpaths + Inspector.** Add the two panel toggles to the
   toolbar after the Log toggle, each with its own icon in our SVG format. (The
   actions already exist and live in the `util` group; flip them on-default + draw
   `toggle-toolpaths` / `toggle-inspector`.)

2. **Stock pad-block toggle.** Make the nosepad pad-block stock addition optional
   (`StockDefinition.use_pad_block`, default on). Off ⇒ the stock is the single
   blank whose thickness the user sets directly — for parts extruded/milled to the
   blank alone. Relief (`stock_top_heightfield` / rough stock-aware band), sim,
   stock canvas, and program-zero all honour it.

3. **Per-component engraving bit (selectable, with a default).** Expose the engrave
   tool as a per-component setting that defaults to a standard saved engraving bit
   (a `tool_store` default, e.g. `engrave_vbit`). Today it is fixed. Lives on each
   component's params + the kind-aware param dock.

4. **Temple stock-side alignment (L/R).** Temples snap hinge-pocket-up to one end of
   the blank; add a per-temple flip of WHICH side (left/right) they align to — the
   front-alignment transform currently forces one side, but cores are sometimes shot
   from the left. Always hinge-pocket-up. `TempleParams.stock_side` honoured by
   `temple_snap_offset` + the flat relief; flows through per-NC and on-bed export.

5. **Per-component, per-operation tool assignment.** Each component picks its own
   tools per op (a different tool for temple hinge-pockets / outline than the frame
   front). The M6.1 `op_tools` map exists but isn't per-component; carry it on each
   component's params + the op-tool combos in the dock, persisted.

6. **Per-component program zero + a separate worktable-bed zero.** Today the program
   zero is in the shared CAM params, so it persists across tabs — a per-component
   exported NC can't keep its own datum (fronts and temples as separate NC files
   want different zeros). Move the zero per-component (each part's own datum) + give
   the worktable bed its own; persist all in the `.gmodel`.

7. **Engraving toolpath optimisation (efficient + exact) — ✅ DONE (centerline).**
   Confirmed the ENGRAVING layer holds **closed glyph outlines**; user chose the
   fixed-depth centerline. `core/cam/engrave_centerline.py` derives each stroke's
   medial axis (even-odd ink fill → interior Voronoi ridges with boundary-spoke
   rejection → leaf-spur pruning → merged polylines; outline fallback on failure) and
   both `generate_temple_program` and `build_temple_relief` engrave it (gated by
   `TempleParams.engrave_centerline`, default on) so NC/model/sim agree. The V-carve
   variable-width variant (use the V-bit angle for thick/thin) is the natural future
   toggle on the same medial axis.

---

## M12 — Toolpath quality (efficiency & "best-possible" generation)

> From a deep audit of a full frame-front program (container demo, 0.15 mm relief,
> 3.175 mm flat, Nomad profile): 9.58 min total, **cut = 87 %** of it (Fine Relief
> 3.21, Perimeter 2.52, Eyewires 2.29 the heavy ops), 70 plunges, 56 separate paths.
> The parts are small + soft (acetate) on a rigid desktop mill, which favours
> aggressive feeds + continuous, well-ordered paths over conservative pecking. Items
> in priority order (value / risk).

**STATUS — M12.1-.5 all ✅ DONE, demo front 9.58 → 5.27 min (−45%), 435 tests.** Commits:
ordering `d1a11c6`, spiral stitch `ac01a7f`, feed 0.12 mm/tooth `3fc5714`, per-material
DOC `471974d`, climb-consistent `d0ff222`. Two hardware-behaviour changes to AIR-CUT /
test before production: the 1200 mm/min feed (M12.3) and the 4 mm through-cut DOC
(M12.4). Tangential lead-in/out arcs were deferred (the ramped lead-in covers it for
acetate; revisit only if witness marks appear).

1. **Per-op path ordering — HIGH value, LOW risk (DOING FIRST).** Relief paths are
   emitted in contour-ring order, so fragments + the separate regions (each eyewire /
   bridge / nosepads) interleave and the tool jumps across the part between paths. On
   the demo front the Fine Relief travels **1344 mm** of inter-path air where
   nearest-neighbour ordering needs **252 mm** (Rough wastes another 265 mm) — ~1357 mm
   of air + the same number of long hops, removed by reordering each op's `paths`
   greedily (nearest start to the last end). Contours are already ring-major (0 waste),
   so the reorder must respect ops that are intentionally ordered. Cleaner sweeps too.

2. **Spiral / morph-link the relief rings — MEDIUM.** One plunge per ring today (70
   total, at the <½-feed plunge rate). Link concentric rings into a continuous spiral
   (enter once per region, step over to the next ring without lifting) — the natural
   extension of the M11 gap-linking; the endgame for "sweeping like Fusion".

3. **Feeds into the material's upper chip-load window — HIGH time leverage (tuning).**
   Cut is 87 % of the job; acetate runs **0.075 mm/tooth** (window 0.02–0.15) at
   750 mm/min, while the Nomad allows 3000 mm/min / 24 k RPM. Pushing toward the upper
   chip-load ~halves the cutting time. Not a generation change — the M7.10 chip-load
   calculator already guides it; consider raising the preset / a "performance" profile.

4. **Per-material through-cut DOC — MEDIUM, tooling-dependent.** Eyewires + Perimeter
   (4.8 min) cut ~10 mm at a global **2.5 mm** stepdown = 4 passes; the Nomad `max_doc`
   is 4.0 mm (→ 3 passes, ~25 % less contour cutting). Expose stepdown per material.

5. **Climb-consistent finishing — LOW, quality.** Verify the fine pass + contour ring
   winding is uniformly climb for surface finish; add tangential lead-in/out arcs on
   contours to avoid witness marks if needed.

Explicitly **not** worth chasing for this application: adaptive/trochoidal roughing
(rough is only 1.1 min and shallow — overkill for soft acetate) and rest-machining
(single-tool coverage is fine). Keep the wins already in: corner-safe arc smoothing,
low-hop linking, ramped contour entries, relief gap-linking.

---

## M13 — Posterior finishing features (road to `v1.0.0-rc1a`)

> The three posterior features a maker otherwise cuts by hand — each a
> **min-carve into the footed castle surface** (new `core/relief/features.py`,
> hooked into `build_castle_relief` after the footing blends and before the
> `surface_field` snapshot, so the fine relief machines them, the sim verifies
> them, and the mesher shows them with **zero worker changes**). All three are
> **OFF by default** — the M2 STL / M3–M4 NC gates hold by construction and by
> explicit bit-identical tests. Every feature carves from the same pre-carve
> snapshot via `z = min(z, max(target, anterior_clamp))`: order-independent,
> overlaps take the deepest cut, material can never rise. GUI: a **Posterior
> Finishing** group on the Castle tab (pad-block toggle pattern, live 3D
> rebuild); teaching stages show features from the *footing* stage onward.
> RC1b (next) is dual-sided machining.

**STATUS — M13.1–.3 all ✅ DONE (2026-07-02), 460 tests green.** Commits: UX
tooltips split out `955a815`; splay core `3d3a4d2` + GUI `38ec6d5`; bezel
`c52e293`; bridge relief + feature-finish band `9de6d23`; version/tag
`v1.0.0-rc1a` this commit.

**M13 field-fix round (same day, 464 tests; tag `v1.0.0-rc1a` moved here).**
Four user findings, all landed:
- **The 3D camera survives same-part rebuilds** (`4fc9435`) — every Castle
  spinbox tick reset the camera, zooming the maker out mid-fine-tune.
  `Viewer3D._keep_camera` compares each new scene's XY footprint with the
  last: param edits / stage steps / re-sims keep the camera; first show,
  fresh GL context, or a different part still resets. Fit + presets unchanged.
- **Pad splay crest round-over** (`43c13bf`) — the hard chamfer/surface corner
  shaded as a pixellated ridge. `crest_blend_mm` (default 2.0) rolls the crest
  with a convex arc tangent to both faces (C1, footing-style; 0 = sharp).
- **Pad splay default run = the maker's rule** — `default_splay_run_mm`:
  bottom-center to the **lower nosepad SCULPT line + 5 mm** along the outline
  (demo: 28.1 mm), seeded per frame while the splay is untouched.
- **Bridge relief re-geometried to a conic scoop on Y** — the swept OD↔OS
  V-groove was wrong. Now: base (widest, deepest cut of the cone section)
  opens through the top edge over the bridge; sides taper at
  `taper_angle_deg`/side to a rounded tip down the lower bridge; tangent
  cosine-bell cross-section with depth scaling to the local width (a true
  cone imprint, crease-free — flows with the footing). Params width / depth /
  taper; reach warning re-derived from the bell's tightest base curvature.

**Fix round 2 (on-screen review, 466 tests):**
- **Zoom no longer resets** — position survived round 1 but PyVista's
  `clear()`+`add_mesh` still auto-refit the camera distance. The renders now
  snapshot the full camera state (position/focal/up + parallel scale) before
  clearing and restore it after the adds.
- **Splay termination is clean** — three compounding causes of the jagged
  ridge on narrow-rim frames: the per-sample lens-rim clamp / in-body
  bisection notched the crest offsets (now slope-limited, `_slope_limit`,
  0.5 mm/mm); outline-polyline noise rippled the finite-difference normals
  (now wide-baseline + vector-smoothed); and — the deep teeth — crest anchor
  heights bilinear-sampled beside the body boundary blended in the
  outside-body ZEROS (now sampled from an EDT-filled nearest-inside surface,
  lightly smoothed). Regression gates on a synthetic narrow-rim frame + the
  user's steep toric settings.

*M13 follow-ups (planned, not yet built):* **keyhole-bridge / sharp-corner
splay break** — detect a sharp outline corner (turn angle past a threshold)
inside the splay run and break the chamfer cleanly at it instead of wrapping
it; **eyewire-bezel anterior/posterior side selector** once RC1b dual-sided
machining exists (posterior-only today, working as intended).

1. **Pad splay chamfer (M13.1).** `PadSplayParams` — a crest path plotted as an
   inward offset of the OUTLINE around its **bottom-center** (the lowest x=0
   crossing = the nose-arch apex, the bridge underside), running `run_mm` per
   side with the offset interpolated center→ends ("deviation"); the surface
   falls from the crest (anchored on the local relief) to the outline edge at
   the splay angle; **toric** = center/middle/end angles blended
   mirror-symmetrically (PCHIP, no overshoot); `anterior_clamp_mm` floors the
   cut (min edge thickness); cosine **feather** at the run ends. Distance +
   station measured against the **windowed bottom-edge polyline** (whole-ring
   distance truncates the chamfer with a wall past a thin strip's midline).
   Crest guarded off the lens rims (0.8× clearance + in-body bisection).
   Opening a `.gdraw` with a forming bridge angle **seeds** the splay angle
   once (never clobbers user edits).
2. **Bezeled eyewire (M13.2).** `EyewireBezelParams` — a constant-width chamfer
   band around each lens opening's posterior rim (width / angle / clamp),
   anchored to the local pre-carve surface: constant band width + rim depth
   (`width·tan θ`) all the way round, rides the footing swells; composes with
   the splay as an elementwise min (tested).
3. **Bridge projection relief (M13.3).** `BridgeReliefParams` — a groove swept
   OD↔OS across the posterior bridge, lens rim to lens rim: **V flanks + a
   radiused (U) root** (analytic root-arc→flank profile), constant depth below
   the local surface so it daylights into the eyewires at its ends; axis = the
   middle of the centerline bridge strip + a user y-offset; masked to the
   connected strip containing x=0 (**no zone labels** — generic/no-SCULPT
   partitions work).
4. **CAM: the feature-finish band + reach.** On a chamfer the contour rings are
   its level curves — a flat tool leaves `stepover·tan θ` facet ridges
   (0.52 mm at 30°/0.9 mm, over the sim's 0.5 mm gate). `relief_ops` adds fine
   rings **confined to the (dilated) feature band** at a cusp-derived stepover
   (`0.15 / tan(steepest feature angle)`, ring generation depth-capped) — same
   five ops, cost proportional to feature area. `feature_reach_warnings`: the
   groove root needs a **ball ≤ root radius**, and a chamfer toe falling into a
   rim can't be finished by any flat tool (trailing edge rides the slope —
   ~`r·tan θ` proud at the edge); both warn in the generate log and suggest a
   fitting ball. End-to-end gate: demo, all features on, Fine Relief on
   `ball_2mm` → sim verify green (band interior ≤ 0.18 mm past the half-kerf
   rim ring).

---

## 2026-07-09 — Core-safe temples + honest per-component zeros (field-fix round)

Four user findings from the bench workflow (temple blanks carry an injected
metal core to the butt end; blanks slide into the fixture with the core ends
against one stop), all landed — **483 tests green**:

1. **Per-component Program Zero no longer leaks.** A component visited for the
   first time silently inherited whatever G54 datum was on screen
   (`ws.program_zero` seeded `None`, and the switch-away sync then wrote the
   stale panel value into it) — so separately-set zeros smeared into one.
   Every model component now seeds its **own** `ProgramZero` from its schema
   `Component` in `build_workspaces_from_gdraw`. Tab-switch persistence, the
   3D triad, the posted work offset and the `.gmodel` round-trip were verified
   end-to-end (headless repro + new GUI gate).
2. **Blank-end snap is the default and every consumer honours it.**
   `TempleParams.snap_to_blank_end` now defaults **ON** (the workflow cuts
   from the snapped position, always). The whole-bed sim's
   `simulate_component` was regenerating temples **un-snapped** (floor stamped
   off its placement) — fixed. The 2D view now *back-projects* the blank frame
   into the design frame via the new `temple_snap_transform` (`flat.py`): the
   blank box draws where the blank really sits (butt flush on its short edge),
   the **G54 datum marker now draws for flat parts** (was cleared), and the
   M7.11 toolpath overlay is inverse-transformed onto the drawing (blocks:
   overlay shifted back onto the lens; previously both drew displaced).
3. **The profile never cuts the core end.** `clip_op_at_blank_end`
   (`temple_ops.py`): on a snapped temple every Temple Profile pass is clipped
   at the blank-end plane — each closed lap becomes an **open polyline** that
   stops at the blank edge on either side of the butt (crossings interpolated,
   ring seam re-joined), so the cutter never drags across the injected core.
   Open passes post with the plain plunge entry (≤ one stepdown deep). The
   un-snapped path keeps the historical closed laps.
4. **Nesting registers the core end against the zone end.**
   `BedPart.place_by_origin` (set for snapped temples): the placement maps the
   **blank centre → zone centre** instead of centring the ops' bbox, so the
   butt/core end lands registered against the zone's end — exactly how the
   blank slides into its slot. Snapped temples also skip the un-snapped
   `default_nest_rotation` 180° flip (stock_side already faces the core;
   manual bed rotation still available).

New gates in `tests/test_core_safe_temple.py` (11): snap-transform ↔
placement equivalence, ring clipping (right/left/inside/seam-joined), snapped
program never crossing the core end + un-snapped unchanged, blank-frame vs
bbox nesting, per-component zero seeding + the GUI leak repro.

---

## 2026-07-11 — RC1 language/toolbar polish + deep appearance customization

Pre-RC1 user round (relaunch for inspection before the installer builds) —
**498 tests green** (+15 in `tests/test_appearance_rc1.py`):

1. **Component tabs**: "Temple Right"/"Temple Left" → **"Temple R"/"Temple L"**
   (`_COMPONENT_LABELS`) to save tab-bar width.
2. **Viewer strip decluttered**: the "Castle:" caption is gone (the stage
   buttons speak for themselves); **Section got an icon**
   (`view-section.svg` — sectioned square with drafting hatching, style-guide
   format) and joins the themed two-state icon set; all strip buttons slimmed
   30 → 24 px wide (half the old horizontal padding).
3. **Castle language softened in the sidebar**: params tab "Castle" →
   **"Model"**, its group "Castle" → **"Model Properties"**. Towers / Walls /
   Footing keep the teaching vocabulary.
4. **Preferences ▸ Appearance** (new tab; dark-mode moved here from General):
   - **Viewport presets carried over from GuildDraw** (Parchment / Dimmed /
     Blueprint / Matte Dark / Plain White / Custom color + follow-UI "auto"),
     pinned in both UI modes and applied to the 2D canvas, the worktable bed
     canvas AND the 3D viewport background. `theme.apply_viewport` overlays
     the CanvasPalette; supporting colors + layer variants re-pick by the
     preset background's luminance, OUTLINE follows the preset ink.
   - **3D light rig**: Studio (kit + key, the shipped look) / Directional
     (dramatic relief shadows) / Flat (unshaded), with key-light **direction
     (azimuth), height (elevation) and intensity** sliders; defaults reproduce
     the old hardcoded key light exactly. `theme.set_lighting`/`light_position`
     drive `Viewer3D._apply_scene_lights` in model, sim-floor and removal-block
     scenes.
   - **Model surface color** picker (+ reset to the theme amber) via
     `theme.set_mesh_color`.
   - **Toolpath-overlay palettes** (Vivid / Soft / Bold / Monochrome blue,
     swatch previews in the combo); live recolor of the drawn overlay + the
     Toolpaths table (`DxfCanvas.recolor_toolpaths`).
   - Persisted as `viewport` / `render3d` / `toolpath_palette` in prefs.json;
     `Viewer3D.refresh_appearance()` re-renders the active scene in place
     (camera kept) on Preferences-OK or a mode flip.

**Second inspection pass, same day:** (a) the view-strip buttons were still wide —
the app-wide `QPushButton { min-width:54px; padding:4px 10px }` rule overrides a
widget's `setFixedWidth` in Qt's stylesheet box model, so a scoped
`QWidget#toolbarStrip QPushButton { padding:1px; min-width:0px }` was added to
both themes (`theme.py`) — the strip buttons are now true 24×22 squares; (b) a
nested worktable component's label drew on top of its zone's role caption (both
centred on the zone) — `BedCanvas._draw_zones` now skips a zone's caption when a
placement occupies it, so the part label owns that spot instead. 498 tests green
throughout.

**Version stamp — `v1.0.0-rc1`.** With the field-fix + polish round accepted on
inspection, this is the actual public release candidate (not an internal
`-rc1a`/`-rc1b` step): `pyproject.toml` version → `1.0.0rc1`,
`guildmodel.__version__` → `"1.0.0-rc1"`, README status line, and the installer's
`MyAppVersion` fallback all updated to match. Built via
`scripts\build_release.ps1` → `dist\GuildModel-1.0.0-rc1-win64.zip` +
`dist\GuildModel-1.0.0-rc1-setup.exe`. Local artifacts only this round — no
GitHub remote configured yet; publishing is a separate, later step.

---

## V1-prep round 1 — session safety net *(2026-07-16, 511 tests)*

> The 2026-07-16 GuildDraw-parity audit ranked GuildModel's missing **safety
> net** as the top V1 gap: no unsaved-changes guard, no autosave, no splash.
> This round closes all three (GuildDraw's machinery, ported), plus two bugs
> found on the way. Suite 498 → **511** (+13, `tests/test_session_guard.py`).

1. **Unsaved-changes tracking + guard.** `MainWindow._dirty` with a title star
   (`_update_title` replaces the scattered `setWindowTitle` calls), marked by
   real user edits — the three ParamsPanel change signals, worktable mutations
   (role tag / bed import / default bed / zero / hold-down / nest / nudge /
   rotate), and a generated program held in memory (the fold-into-open-project
   path saves instead). Programmatic restores never mark: `_restoring` counter
   held through `__init__`'s prefs restore, `_open_project`, and
   `_activate_workspace` (tab switches push stored params into the dock).
   `_confirm_discard()` (Save / Discard / Cancel) guards `closeEvent` and all
   four open paths (DXF / drawing / project / recent). Save Project, project
   open, and fresh loads reset the clean baseline (`_post_load_baseline`).
2. **Autosave + crash recovery.** 3-minute timer snapshots a dirty session to
   `~/.guildmodel/autosave/recovery.gmodel` (+ `recovery.json` meta: source
   path, timestamp) via the new UI-free `_write_gmodel` (extracted from
   `_save_gmodel_to`); atomic `os.replace`, silent on failure, "Autosaved" in
   the status bar. On startup `_offer_recovery` (400 ms singleShot) offers the
   snapshot: restored work re-binds to the ORIGINAL project path (not the
   recovery file), marks dirty, stays out of recents; declining clears the
   slot, and so does a clean close.
3. **Guild splash + light boot.** `gui/splash.py` — GuildDraw's parchment
   certificate card verbatim (seal, serif, licence; `gasm_seal.svg` copied to
   `assets/`) with the GuildModel name/version. New `gui/boot.py` shows it
   BEFORE the heavy VTK import (the cold-start cost lives in importing
   `gui/app.py`), then imports and builds the window; `guildmodel` entry point
   + `main.py` now boot there (`gui.app:main` delegates for back-compat).
4. **File-association fix.** `main()` ignored argv — double-clicking a
   `.gmodel` launched the app but never opened the file. `boot.main` now opens
   the first file argument via the new `MainWindow.open_path` dispatcher
   (also backs the recent-files menu).
5. **Recents-pollution fix.** Opening a DXF-based `.gmodel` re-imports the
   embedded DXF through a temp file, and `_on_import_finished` added that
   `%TEMP%\gmodel_*.dxf` to the recent-files menu; `_load_dxf` now carries
   `from_project` through the worker round-trip and skips it.

---

## V1-prep round 2 — appearance parity *(2026-07-16, 519 tests)*

> Cluster (b) of the GuildDraw-parity audit: the customization surfaces
> GuildDraw ships that GuildModel lacked — per-layer colour overrides, a
> configurable canvas grid, and the prefs deep-merge. Suite 511 → **519**
> (+8, `tests/test_layers_grid_prefs.py`).

1. **Per-layer colour overrides (Preferences ▸ Layers).** New theme API
   `set_layer_overrides` / `layer_color_for(layer, dark)` — the override for
   the effective mode wins (on a pinned viewport preset the backdrop's
   luminance picks the slot, same rule as `layer_color`), else the shipped
   `LAYER_STYLES` colour. `DxfCanvas._draw_layers` and the params-panel layer
   checkboxes now resolve colours by NAME through it. The new Layers prefs tab
   (after Appearance, GuildDraw's position) gives every design layer
   Light…/Dark… swatch pickers + Reset; only genuine overrides persist
   (`layer_colors` pref).
2. **Configurable 2D grid (Preferences ▸ Appearance ▸ Grid).** Theme-level
   `set_grid`/`grid_config` (clamped, stale-prefs-safe); `DxfCanvas._draw_grid`
   honors show/hide, spacing, a heavier major line every Nth, major width, and
   minor/major colour overrides. Shipped config reproduces the historical
   10 mm dotted grid, now with a subtle major every 5th (50 mm) — GuildDraw's
   convention.
3. **Prefs deep-merge.** `prefs.load()` now deep-merges every nested dict pref
   (`viewport`/`render3d`/`grid`/`layer_colors`/`cam_params`/`hotkeys`) over
   its defaults, GuildDraw's rule, so an old prefs.json can never silently
   clobber keys added later ("toolbar" is a list — excluded).

---

## V1-prep round 3 — ecosystem glue + module decisions *(2026-07-16, 523 tests)*

> Clusters (c) and (d) of the parity audit. Suite 519 → **523** (+4,
> `tests/test_ecosystem_c.py`). Touches all three apps; every repo's changes
> held uncommitted for review.

**Cluster (c) — the three apps as one toolchain:**
1. **Ctrl+, opens Preferences everywhere.** GuildSend set the convention;
   GuildModel and GuildDraw now match (action kept on `self` — a text+slot
   `addAction`'s wrapper is Python-owned in PySide6, and dropping the last
   reference deletes the QAction).
2. **File ▸ Open in GuildSend** (GuildModel): hands the SAVED `.gmodel` to
   GuildSend, whose bundle reader already ingests programs + setup sheet +
   tools + material + tagged worktable natively — saves first when dirty,
   enabled in lockstep with Export G-code (mirrors its `changed` signal).
   `_find_guildsend()` tries the per-user install
   (`%LOCALAPPDATA%\Programs\GuildSend`), PATH, then the sibling source
   checkout's venv (developer fallback).
3. **GuildSend receives:** `_open_job` dialog split from a new
   `open_path(path)` dispatcher; `main()` opens a file passed on the command
   line (double-clicked job or the GuildModel handoff). Its never-wired M0
   splash was replaced with the family's guild-certificate card
   (seal + serif + licence, GuildSend name) and actually shown before the
   window build. Seal asset copied to `guildsend/resources/`.

**Cluster (d) — module ⚠️ decisions from the audit:**
4. **`io_import/svg.py` RETIRED** (git rm): the `npoint` call passed a chord
   tolerance where svgelements expects positions — broken on any use — and
   the M7.2 `.gdraw` reader already ingests plain GuildDraw `.svg` files
   (`read_gdraw`'s non-ZIP branch). Zero callers, zero tests.
5. **`mesh/twosided.py` + `mesh/stl_export.py` RETIRED** (git rm): superseded
   by `build_castle_mesh` + the GUI's trimesh STL path; no consumers outside
   `mesh/__init__`. `mesh/section.py` (M7.13) is the package's one survivor.
6. **`relief/pocket.py` KEPT, footgun documented:** loud docstring — no inward
   tool-radius offset; callers pre-offset (production pockets use
   `castle_ops.hinge_pocket_op`, which offsets). Dormant with
   `relief/hinge.py` for the post-1.0 CHA catalog.
7. **`geometry/symmetry.py` KEPT:** the module table's "stub" label was stale —
   it's small working code (mirror_polygon / apply_symmetry) for the post-1.0
   asymmetry question.
8. **`docs/USER-GUIDE.md` WRITTEN:** the maker's guide (GuildDraw's format) —
   opening designs, the castle, temples/blocks, cut settings, generate +
   verify, the worktable, the GuildSend handoff, preferences, data safety,
   fixed shortcuts.

---

## Toolpath-efficiency re-audit *(2026-07-16, 524 tests)*

> User question: does generation still produce the most efficient path?
> Method: profile a freshly generated demo front at current defaults
> (F1200 / stepdown 4.0, Nomad dynamics), verify each M12 win empirically,
> hypothesis-test the remaining overhead.

**Verified still optimal:** per-op path ordering (a from-scratch greedy
nearest-neighbour reorder matches the emitted order to the mm in every op),
spiral stitching (48 → 26+22 relief entries), arc fitting live (386 G2/G3
lines posted), feeds/DOC at their deliberate ceilings.

**Where the 6.53 min cycle goes:** pure cutting floor 3.69 min + entries/
ramps/links 0.60 + **accel/junction losses ≈ 1.0 min** + rapids 0.56.
The junction loss is physics, not waste: relief is 0.3 mm-fidelity chords
(≈50 % of segments < 0.5 mm) and GRBL can't corner through them at F1200.
Falsified the simplification counter-move — RDP at 0.01 mm merges only
65 / 3991 relief segments (the chords follow real curvature); recovering
that minute would trade surface fidelity. Not taken. M12's rejections
(trochoidal, rest-machining) reconfirmed.

**Gap found + FIXED: engraving stroke order.** `engrave_op` cut strokes in
draw/file order — on a synthetic 40-stroke temple text that is 1352 mm of
inter-stroke air vs 220 mm ordered (6×). Now routed through
`order_paths_for_travel` (pure permutation, geometry/direction untouched;
+1 test in test_path_order_m12.py). M12 missed it because the demo front
has no engraving.

**Declined by user:** a 0.15 mm/tooth "performance" material preset — makers
tune feeds for their own machine; the M7.10 chip-load read-out already guides
them.

---

## M14 — Lens bevel groove / drageoir *(2026-07-17, user-requested V1 feature)*

> Toggleable V-groove in each eyewire wall to seat the lens bevel, cut with a
> side-cutting grooving form tool (the Fraisesoutillages N°2 "fraise
> drageoir", user's Fusion tool library). Off by default — every bare-castle
> gate (M2 STL / M3 NC / multitool) holds bit-for-bit, verified.

**The geometric contract** (the user's "just enough material removed"):
1. The groove BOTTOM lands exactly on the drawn LENS contour — the boxed
   dimension stays honest — so the visible aperture (the rim lip) is cut
   SMALLER by `depth_mm`. One change point: `build_castle_relief` shrinks the
   mask holes (`_undersized_lens_body`) and everything keys off
   `relief.mask_body` (raster mask, conformed mesh wall, eyewire contour);
   the original lens polys ride on `relief.groove_lens_polys`. The lip
   annulus has no zone → the existing orphan nearest-zone fill gives it the
   neighbouring eyewire-wall height.
2. The eyewires cut a TOOL-WIDTH slot around a retained plug — a 6 mm
   drageoir head can't descend into a 3.175 mm channel. With the groove on,
   the Eyewires op interleaves extra inner rings per lens
   (`groove_channel_width_mm` = head + 2×0.3 mm clearance, depth-independent:
   feeding out only ADDS inner clearance).
3. **Lens Groove op** (after Eyewires, before Perimeter): one constant-Z
   climb loop per lens at tool-center = lens ⊖ head_r (the form apex cuts TO
   the lens contour); radial entry/exit inside the cleared channel — never a
   ramp or plunge into material; posted Z = TOOL TIP (touch off the tip),
   apex = tip + form half-width. Constant-Z → arc-fit applies.

**Schema:** `LensGrooveParams` (enabled / anterior_offset 1.5 / depth 0.75 /
width 2.0 / tool) on `CastleParams.lens_groove`. Deliberately NOT in
POSTERIOR_OPS — `tools_in_use()` iterates it and a groove entry would make
every job multi-tool with the groove off; the workers instead force
tool_settings whenever `relief.groove` is set, and the tool resolves
op_tools["Lens Groove"] → `groove.tool` → shipped default.

**Tooling:** `groove_drageoir` shipped in tools.yaml (6 mm head, 2 mm flute,
0.75 form depth, 3.5 neck, 3 flutes, 400/300/18000 from the vendor preset);
`ToolSpec` gains type "groove" + groove_depth/width/neck fields.
`depth_reach_warnings` skips groove tools (the head rides at depth by
design); new `groove_warnings` flags a non-groove tool, params exceeding the
tool's form, and flanks breaking the wall top / anterior face.

**Mesh (STL-printable):** `_groove_rim` replaces the straight aperture-wall
ribbon with a four-band strip through three new vertex rings — flank top,
APEX pushed outward onto the original lens contour (`nearest_points`), flank
bottom — watertight by shared ring vertices; clamped flanks collapse to
zero-area faces that `process=True` removes. Groove-off takes the exact old
code path.

**Sim:** the drageoir cuts SIDEWAYS — a top-down Z-buffer sweep of its loop
would falsely carve the rim lip from above. The grouped path extraction drops
moves tagged with a groove-TYPE tool (exact: a form cutter never shares a
tool slot); the channel it rides in is verified by the eyewire sweep.

**GUI:** "Lens Bevel Groove" group on the Model tab (toggle, apex-from-
anterior, depth, width, derived included-angle read-out ≈106° at the shipped
form, tool combo fed by the tool store); persists per component and through
the `.gmodel`.

Suite 524 → **534** (+10, tests/test_lens_groove.py).

**Same-day view-strip polish (user request on inspection):** the view strip's
divider was a bare `QFrame` VLine — full strip height, and white on the dark
theme. Replaced with `_StripSep` (viewer_3d.py), the main toolbar's ToolSep
look: a crisp cosmetic 1-px line, inset/centered, tinted darker-amber on dark /
charcoal on light via `set_dark_mode` (matches `_style_toolbar_separators`).
The sim playback ▶ button also grew 24×22 → 36×22 with a 14-px glyph — the
strip-scoped QSS (`padding: 1px`) had left it uncomfortably small; final size
matches the camera squares' height, wider for the glyph (user-tuned on
inspection). Sized by a dedicated `#playButton` rule in both theme QSS blocks
(an inline stylesheet / `setFixedSize` both lose to the stylesheet box model);
verified by offscreen grabs of the strip in both modes.

**Known issue (observed 2026-07-16, root cause still open):** two consecutive
desktop sessions each logged ONE paired VTK `FRAMEBUFFER_INCOMPLETE_ATTACHMENT`
error with a 0×0 renderbuffer (~1–2 min in — around first 3D/sim use).
Non-fatal; sessions continued and closed cleanly. A scripted repro (plotter
created on a hidden stack page, AA enabled immediately — the prior code path)
did NOT reproduce it: a hidden widget isn't 0×0, so the zero-size render likely
comes from a minimize or teardown moment instead. Hardening applied anyway
(safe, semantics-preserving, repro-verified clean): `_ensure_plotter` now lays
the interactor out before any rendering call and defers
`enable_anti_aliasing` to the first sized render (`_enable_aa_if_sized`, also
re-checked from `_safe_render`). **Third occurrence (post-hardening, 28 min
into a session — so NOT the AA-at-creation path):** always exactly two renders
~13 ms apart at one instant. A `_FboProbe` logging handler is now installed
(app.py, diagnostic-only, remove once root-caused): when VTK logs the error it
snapshots view/tab/minimized/viewer-size/mode to stderr + the app log — the
next occurrence carries its own repro data.

---

**Version stamp — `v1.0.0-rc2` (2026-07-17).** With the V1-prep rounds
(safety net / appearance / ecosystem glue / module decisions / USER-GUIDE),
the toolpath re-audit fix, and M14 all landed: version → `1.0.0rc2` in
pyproject, `1.0.0-rc2` in `guildmodel.__version__`, the installer fallback,
and the README status. `scripts\build_release.ps1` now bakes in the off-drive
build (the GuildSend pattern): PyInstaller + Inno work in
`%LOCALAPPDATA%\GuildModelBuild` — Google Drive locks the frozen exe
mid-build — and only the finished zip + setup.exe are copied back to `dist\`.
Pre-build gremlin sweep: 534 tests green, `compileall` clean, no stray debug
output, editable import healthy. Tag held until the user test-installs (the
GuildDraw rc2 precedent).

---

**rc2 pre-drop fixes (2026-07-17, user inspection round; artifacts rebuilt).**
1. **"Open in GuildSend" retired from the File menu** (commented, not deleted —
   action/launcher/registry row kept disconnected in case the decision is
   revisited): the three tools stand alone; GuildSend natively opens `.gmodel`
   jobs just as GuildModel natively opens `.gdraw` drawings. USER-GUIDE §7
   rewritten around Save → GuildSend's File ▸ Open Job.
2. **Open hotkeys swapped:** Ctrl+O = Open Drawing (`.gdraw`, the featured
   path — encourages the GuildDraw-native workflow; toolbar button unchanged),
   Ctrl+Shift+O = Open DXF (the bring-your-own-CAD path).
3. **Groove toggle label** "Cut lens bevel groove" — "(drageoir)" dropped
   (descriptions stay English; the supplier's tool NAME keeps the French).
4. **Drageoir dimensions corrected from the supplier's published profile:**
   the cutting diameter is the V APEX Ø5.5 (the 6 mm is the shank) — was
   entered as Ø6, which would have cut the groove bottom 0.25 mm shy of the
   lens contour. tools.yaml now: apex Ø5.5 / root Ø4.0 / 2 mm form / Ø3.5
   neck / Ø6 shank; CAM fallbacks follow. **ToolView renders the true groove
   silhouette** (flat root tip → V apex → root → relieved neck → shank, neck
   ≈3× form width) instead of the generic rectangle; caption shows d×w.
5. **Bottom-row docks fixed:** Toolpaths + Inspector can share the row again —
   `_toggle_toolpath_dock` / `_toggle_inspector_dock` re-assert the canonical
   arrangement (Log+Toolpaths tabbed left, Inspector split right) on every
   show, so a dragged or stale-saved layout can never wedge them into one tab
   group; `_DOCK_STATE_VERSION` 2→3 discards existing stale layouts once;
   the toolpath table wraps + stretches its Op column so both fit side-by-side
   (each alone still spans the whole row).

**Groove-in-sim representation (2026-07-17, user report; the hybrid answer).**
The playback/removal block was carving a Ø5.5 FLAT swath along the groove loop
— `ToolProfile` had no "groove" kind, so the kernel fell through to flat, and
the M14 verify-exclusion only filtered the achieved-floor sweep, not the
removal plan (nor the bed sim). An undercut is unrepresentable in ANY
Z-buffer/heightfield sim (one z per column — CAMotics has the same wall; the
general fix is a dexel/tri-dexel solid, post-V1 at best). The V1 hybrid:
1. **Empty groove kernel** (`toolsim.ToolProfile.kernel`): a groove-type tool
   stamps NOTHING — every Z-buffer consumer (floor verify, playback block,
   whole-bed sim) is honest at the root, and the playback tool marker still
   traces the loop at the right speed.
2. **Exact geometric verification** (`castle_ops.verify_groove_op`): one
   constant-Z loop per lens at the form tip, apex ON the lens contour
   (≤0.08 mm), radial entry pulled clear — STRONGER than a raster sweep for
   this op class. Result feeds the sim summary: pass = an explicit
   "verified geometrically" line; any defect = ⚠ lines.
3. **Visible marker**: `RemovalPlan.groove_rings` → the sim view draws each
   lens contour at apex height as a thin measure-blue ring tube — the groove's
   true bottom, rendered as annotation rather than pretended material.
Suite 534 → 537 (kernel-empty / geometric-verify / plan-field tests).

**Dock-drag crash fix (2026-07-17, user repro: dragging the Inspector out
with both bottom panels shown → native crash, exit 0xC0000005).** The rc2
dock re-arrangement was connected to the actions' `toggled` — but a dock
DRAG makes Qt hide/re-show the widget mid-drag → `visibilityChanged` →
`setChecked` → `toggled` → `splitDockWidget` re-docked the widget from
inside Qt's own drag cascade (use-after-free). Fix: connect `triggered`
(fires only on a real user click, never from programmatic setChecked),
DEFER the re-arrangement via `QTimer.singleShot(0, …)` so it can never run
inside a Qt-internal call stack, and skip it for a floating panel (the
maker's drag-out is respected). Lesson: never mutate dock layout from a
`visibilityChanged`/`toggled` cascade.

## Worktable tab UX round *(2026-07-23; V1 scope: M8 proven on the available CNCs, M9 two-sided deferred to V2)*

> User inspection of the Worktable tab surfaced two gaps + a UX pass. Two decisions
> recorded first: **M8 hardware round-trip is satisfied** (the reoriented flow is
> proven on the available CNC options), and **M9 two-sided machining is deferred to
> V2** (out of V1 scope). This round is Worktable-tab polish.

1. **Load a saved `.bed`.** `load_bed` existed in core but the panel only wired
   **Save Bed…** — there was no way back in. Added a **Load Bed…** button +
   `_on_load_bed` (open-dialog → `load_bed` → set worktable, clear nest, refresh,
   mark dirty), the counterpart of Save Bed.
2. **The bed perimeter is the work envelope (user-chosen behaviour).**
   `build_worktable_from_dxf` now detects an **enclosing outer outline** (`_find_envelope`:
   the one polygon face whose bbox contains every other polygon face) and treats it as
   the **work area** (`work_area` = its bbox) rather than a taggable region — so a
   custom bed no longer yields a confusing whole-bed "matrix" face; only the inner
   loops stay as regions. Disjoint regions with no outline keep every face (guarded by
   `len(poly) ≥ 2` + strict containment, so the M74 disjoint-rects test is unchanged).
   GUI: a **Bed size (work envelope)** W×H spin group edits `work_area_*` live
   (`_on_bed_size_changed` → `BedCanvas.update_work_area`, no refit); clicking the bed
   **perimeter** selects the envelope (`BedCanvas._perimeter_hit` on the work-area
   border → `perimeter_clicked` → `_on_perimeter_selected` highlights the rect solid +
   focuses the size fields).
3. **Extra fixes (all four, user-approved):** (a) **zoom/pan no longer resets on
   resize** — `BedCanvas` fits only when a fit is pending (`_needs_fit`, set by
   `set_worktable`, cleared once the widget is really sized; `fit_to_view` early-returns
   at 0-size); a plain window resize now preserves the maker's view. (b) **Remove
   Region** button (`_on_remove_region`) drops a selected sliver / leftover face. (c) an
   on-canvas **role legend** (`_draw_legend`) keys the colours actually present. (d)
   placeholder + panel help text updated to mention loading a saved `.bed` and the
   work-envelope outline.

Suite 569 → **572** (+2 core envelope tests, +1 guarded GUI test in
`tests/test_worktable_m74.py`; the GUI test is skip-guarded off-platform). Held
uncommitted for the user's on-screen review (perimeter-click highlight + legend).

## Worktable tab UX round 2 *(2026-07-24; on-screen review of round 1)*

> Second Worktable pass after the maker tested round 1. Four asks, all landed.

1. **Undo/redo for bed edits.** A worktable-scoped undo stack (`_wt_undo`/`_wt_redo`,
   deep `model_copy` snapshots, capped at 30) — **↶ Undo / ↷ Redo** buttons under
   Remove Region. `_wt_snapshot()` runs before every structural edit (Remove Region,
   role re-tag, and any bed load/import/default-load — so an accidental "Load Guild
   Bed" that wiped a custom bed is recoverable); `_after_wt_restore` re-binds the
   canvas without a refit (keeps zoom). A project open clears the history.
2. **Incomplete-bed nesting** — already worked at the engine level
   (`nest_components_on_worktable` sends role-unmatched parts to `BedNest.unplaced`,
   Generate enables on any placement); this round **verified + regression-tested** it
   (a front + one-temple bed nests those two, returns temple-left + base-curve
   unplaced, no error) for shops whose bed does one front + one temple at a time, or
   has no base-curve zones.
3. **User default bed.** New core helpers in `worktable.py`
   (`user_default_bed_path` = `~/.guildmodel/default.bed`, `load/save/clear_user_default_bed`,
   `startup_worktable` = user default ⟶ else shipped Guild). `_ensure_worktable` now
   opens with the user's default; **Set as Default** button saves the current bed as
   it; **Load Guild Bed** still force-loads the shipped fixture. On **saving the
   `.gmodel` or generating the nested worktable.nc**, if the bed differs from the
   current default, `_maybe_prompt_default_bed` offers to make it the default — once
   per bed change (`_bed_prompt_answered`), with a **"Don't ask again"** checkbox that
   sets the new `prompt_set_default_bed` pref (default True) off.
4. **Button declutter.** The four stacked file buttons became a 2×2 grid — **Load
   DXF/BED…** (one button; the open dialog dispatches on `.dxf` vs `.bed`) + **Load
   Guild Bed** on row 1, **Save Bed…** + **Set as Default** on row 2. `_on_import_bed`
   / `_on_load_bed` kept as thin menu/test wrappers over `_import_bed_dxf` /
   `_load_bed_file` appliers (both funnel through `_apply_new_worktable`).

Suite 572 → **575** (+2 core: incomplete-bed nest + user-default round-trip; +1
guarded GUI: undo/redo + set-default).
Held uncommitted for on-screen review (undo/redo buttons, the 2×2 layout, and the
default-bed prompt on save/export).

**Round-2 field fixes (2026-07-24, user on-screen review — two bugs, both pre-existing
but surfaced during round-2 testing):**
1. **Nesting failed / no footprints drawn.** `NestWorker.run`'s frame-front branch
   referenced `CASTLE_CONTOUR_OPS` but never imported it (it was imported locally in
   two *other* methods) → `NameError` the instant a frame front was nested → no
   placements → nothing drawn (the Toolpaths panel was showing the front's own
   per-component Generate, not a nest). The nest **tests build `BedPart` directly**, so
   the worker's castle branch was untested. Fixed the import; **added a regression test**
   running `NestWorker.run` on a real demo-DXF castle onto a frame-front-only bed.
2. **Bottom docks couldn't be resized (glitched over the status bar), in every view.**
   The Worktable sidebar panel grew tall this round (bed-size fields, Set-as-Default,
   Undo/Redo) with **no scroll area**, forcing the shared right dock's *minimum height*
   to **678 px** — starving the vertical layout so the bottom docks spilled over the
   status bar. Wrapped the worktable panel in a `QScrollArea` (the params panel's
   pattern); right-dock min dropped **678 → 130 px**. The panel scrolls internally when
   the window is short.

Suite 575 → **576** (+1 nest-worker castle-branch regression test).

## Linux Wayland: "Build 3D Model" segfaults without XWayland *(2026-07-27, field-diagnosed)*

**Root cause:** PyVista/VTK's Linux OpenGL renderer (`vtkXOpenGLRenderWindow`)
is X11-only — it has no native Wayland backend. Under Qt's native `wayland`
platform plugin, embedding the render window into the GUI fails (`BadWindow` /
`X_ConfigureWindow` X errors), and the process segfaults the instant **Build 3D
Model** finishes meshing and tries to display the result. Mesh generation
itself (`core/relief/*`, run off-thread in `MultiMeshWorker`) is unaffected —
it's pure Python/CPU and completes before the crash; this is purely a
display-layer issue, not a geometry bug.

**Repro/fix confirmed headlessly:** booted `MainWindow`, opened the demo DXF,
called `_on_build_3d()` directly. Reliably segfaults (exit 139, `vtkXOpenGLRenderWindow`
+ `X_ConfigureWindow BadWindow` on stderr) under the default Wayland QPA
plugin; completes clean (mesh built, no crash) with `QT_QPA_PLATFORM=xcb`
forcing XWayland.

**Fix:** no code change — this is an environment/library gap (PyVista/VTK vs.
native Wayland), not a GuildModel bug. Documented in the README; any
`.desktop` launcher should set `Exec=env QT_QPA_PLATFORM=xcb …/guildmodel`.

## M15 — Depth-per-pass control on every component (v1.2.0) · *the maker decides how deep it bites* — 2026-08-06

> **Field report:** a temple's G-code tried to take the whole blank in one pass,
> and there was no control anywhere in the UI to change it. Diagnosing that turned
> up three independent causes plus a cluster of neighbouring places where the same
> decision was being made *for* the maker rather than *by* them. V1 scope: nail the
> single-sided feature set down before M9/V2 two-sided.

**Root cause (three things, all required to produce the symptom):**

1. **The default was one pass.** M12.4 raised `contour_stepdown_mm` to 4.0 —
   "cut as deep as the material allows" — on the strength of an acetate
   `max_doc_mm` of 4.0 that its own comment flagged as needing validation. A
   default 4 mm temple blank less a 0.4 mm onion skin is 3.6 mm of cut:
   `contour_passes(4.0, 0.4, 4.0) == [0.4]`. Exactly one full-depth pass.
2. **The control was hidden.** `contour_stepdown` lived in the frame-only "Cut
   Strategy" group, which `set_component_kind` hides for temple and base-curve
   components. The value still reached the generator — the maker simply could not
   see or change it while a temple was active. Same for the ramp angle and the arc
   tolerance, which also apply to every kind.
3. **The clamp seam was still incomplete.** INCIDENT-2026-07-29 routed the
   *worktable* paths through `clamp_cam_to_machine`; `_generate_temple` and
   `_generate_block` were never done. Neither the machine's nor the material's
   depth-of-cut ceiling applied to a temple, and the post was handed
   `cam.arc_tolerance_mm` instead of `clamp.arc_tol_mm`, so a controller declared
   to have no reliable G2/G3 still received arcs. `_generate_block` *looked*
   clamped — it computed a clamped `stepdown` local, but handed it only to
   `write_castle_program` (which sets the lead-in ramp depth) while the contour
   passes had already been generated from the unclamped value.

**Landed:**

1. **Depth per pass is now a universal, everyday control.** New "Depth per pass"
   group on the **Cut** tab (`_build_depth_group`) — through-cut and pocket —
   visible for every component kind, with a live read-out of what the active
   component's blank works out to: *"Temple profile: 3 passes through 3.60 mm
   (deepest 1.50 mm)"*, amber with *"the whole depth in one bite"* when it
   collapses to a single pass. The old strategy group keeps only the frame's
   relief knobs and is renamed **Relief Strategy**; ramp angle + arc tolerance move
   to a universal **Through-cut lead-in & output** group on Machine.
2. **Shipped defaults lowered** (user decision, this round): acetate
   `max_doc_mm` 4.0 → **2.0**, acetate `contour_stepdown_mm` 4.0 → **1.5**,
   `CastleCamParams.contour_stepdown_mm` 4.0 → **1.5**. A stock temple is now
   three passes, a stock frame perimeter more. Raiseable per job as always — but a
   fresh project no longer ships a full-depth cut.
3. **Clamp seam completed.** `_generate_temple`, `_generate_block`,
   `FlatSimWorker` and `BedSimWorker` all run `clamp_cam_to_machine` **before**
   generating ops, and both posts now use `clamp.arc_tol_mm`. The sim and the
   program a tab posts are once again the same program.
4. **Blind pockets are cut in levels.** `hinge_pocket_op` ramped its outer ring
   down and then cleared the floor in ONE cascade at full depth, however deep the
   pocket. New `pocket_levels()` + `pocket_stepdown_mm` (default 1.0) cut the
   pocket level by level, each with its own ramped entry and cascade. A recess no
   deeper than one stepdown posts the historical single-level path unchanged.
5. **Engraving steps down.** `TempleParams.engrave_stepdown_mm` (default 0.5):
   a groove deeper than one stepdown is traced once per level instead of plunging
   a slender V-bit straight to depth. Levels expand *after* travel ordering, so the
   nearest-neighbour permutation is still computed over strokes, not over level
   copies sharing one footprint. The 0.3 mm default groove is one pass either way.
6. **The upgrade actually takes (`prefs._retire_m124_stepdown`).** Caught during
   verification: prefs are restored over the schema defaults on every launch, so
   lowering the shipped default alone changed nothing for anyone who had already
   run GuildModel — this machine's `~/.guildmodel/prefs.json` still pinned
   `contour_stepdown_mm: 4.0`, and a temple still came out as one pass. A stored
   value **at or above** the old 4.0 default is retired on load (a deliberate
   choice would have been *lower*, since 4.0 was already the ceiling acetate
   allowed); anything below it is the maker's own tuning and is left alone.
   Project files are deliberately *not* rewritten — an old `.gmodel` keeps its
   saved request and the read-out warns about it.
7. **The read-out reports the clamped depth, not the request.** The post applies
   the material/machine ceiling, so a read-out echoing the request would mis-state
   an over-set project by a whole pass. It shows what will be cut and says
   *"capped at the 2.00 mm material/machine limit"* when the two differ.
8. **`cam_params()` no longer loses fields (silent data loss).** It rebuilt
   `CastleCamParams` from scratch, so every field with no widget —
   `pocket_stepover_mm`, `ramp_step_mm`, `relief_link_gap_mm`, `relief_min_run_mm`,
   `simplify_tol_mm`, `skim_epsilon_mm`, `link_retracts`, `link_clearance_mm`, the
   screw-keepout pair — reverted to its schema default. `_build_project_schema`
   saves that snapshot back into the project, so **opening a `.gmodel` with any of
   those tuned and pressing Save discarded the tuning.** Now `set_cam_params`
   retains the loaded model as `_cam_base` and `cam_params()` returns
   `base.model_copy(update=…)` over only the fields the panel owns.

**Deliberately NOT landed (reported, not built):**

- **Hold-down tabs on temple / base-curve profiles.** `cam/tabs.py` exists but is
  wired only to the legacy no-SCULPT `profile_cut`. Tabs are an *alternative* to
  the onion skin, not an addition — with a skin the final pass is above the bottom
  face, where a tab means nothing. Wiring them needs a hold-strategy choice
  (skin | tabs) from the maker, which is its own milestone, not a checkbox.
- **Per-op enable / skip.** `cam_params.op_tools` assigns a tool per op but there
  is no way to say "don't cut the perimeter this time". Needs an op matrix in the
  UI + an op-set on the schema.
- **Per-component CAM overrides.** `cam_params` is project-global (only
  `program_zero` went per-component, in M11). Defensible — depth per pass is a
  material/tool property, not a part property — but a project mixing acetate
  temples with an acetal block has one stepdown for both, and only the block path
  re-reads its own material.
- **Climb/conventional and lead-in/out style.** Climb is hardcoded in
  `contour_op` (M12.5); there is no conventional option and no lead-in arc/line
  choice.

Suite 586 → **606** (+20 in `tests/test_depth_control_m15.py`). Three pre-existing
tests hardcoded M12.4's 4 mm pass stack (`test_cam_quality::test_eyewires_ring_major`,
`test_castle_m3::test_contour_ops_passes_and_skin` and `::test_against_reference_nc`);
each now derives its expectation from the shipped stepdown, or asserts the invariant
that matters (same onion-skin floor, same depth reached, no pass deeper than
requested) instead of a pass count that is a tuning decision.

**Cut-time impact — the trade the lowered default buys.** With the shipped
settings the frame perimeter/eyewire stack goes from 3 passes to **7** through
9.6 mm, and a temple profile from 1 to **3**. That is the intended cost of not
taking a full-depth bite; a maker who has proven a deeper cut on their machine
raises the number on the Cut tab and sees the pass count update live.

Held uncommitted for review — **the changed defaults alter every existing
project's pass structure**, so verify on a sacrificial cut before production.

## M16 — Toolpath control (v1.3.0) · *the four decisions the program used to make for you* — 2026-08-06

> The M15 audit listed four control gaps it deliberately did not close. This
> milestone closes them, and in wiring the first one up found two live defects in
> `cam/tabs.py` that had been latent since the module was written — it had only
> ever been driven by the legacy no-SCULPT profile fallback, never by a real
> buffered contour. Still V1 single-sided; M9/V2 two-sided remains out of scope.

1. **Hold-down strategy — onion skin | tabs** (`HoldingParams` on `CastleParams`
   / `TempleParams` / `BaseCurveBlockParams`). They are **alternatives, not
   additions**, which is why the tab machinery sat unused: with a skin the final
   pass is above the bottom face, where a tab means nothing. On `tabs` the stack
   runs to the anterior face (z = 0, *never* below — the fixture's blank zone and
   hold-down screws are under the stock) and the last pass rises over `tab_count`
   bridges. Only the op that **releases the part** takes tabs; inside through-cuts
   (eyewires, decorative holes) keep the skin, because their waste slug is dropping
   into the fixture either way and a tabbed slug is a loose piece for the cutter to
   catch.
   * **Tab height is clamped to the final pass depth** (`tab_height_for`), because
     the pass above has already removed everything higher — a 3 mm tab under a
     1.5 mm final pass is a 1.5 mm tab whatever the G-code says.
     `tab_height_warning` gives the panel the sentence to show instead of letting
     the difference be silent.
2. **Cut direction — climb | conventional** (`CastleCamParams.cut_direction`).
   Climb was hardcoded in `contour_op` since M12.5. Conventional reverses every
   ring, inside and outside together so the two stay opposite: the choice on a
   machine with backlash it cannot take out, where climb pulls the cutter in.
3. **Lead-in — ramp | plunge** (`CastleCamParams.contour_lead_in`). Not a
   duplicate of the ramp angle: `_emit_ramped_loop` reads a non-positive angle as
   *"ramp the whole lap"* — the opposite request — so a straight entry was
   previously unreachable at any setting. The panel greys the angle out on plunge.
   * **Tangential arc lead-in deliberately not built.** On a through-cut's first
     depth pass an arc entry lands in solid material, so it would have to be a
     ramped arc — i.e. the ramp, with extra geometry. And with an onion skin plus
     a hand-finishing allowance the wall is hand-finished anyway, so the witness
     mark an arc lead-in exists to avoid is sanded off. Wrong feature for this part.
4. **Per-operation enable / skip** (`CastleCamParams.op_enabled`, absent = enabled
   so old projects load unchanged). Cut a job in stages — pocket and engrave now,
   release the part after the inserts go in — or re-post one operation after a tool
   change. The panel's list is kind-aware and warns when a *releasing* op is off
   ("the part stays attached to the blank"). Switching everything off used to
   surface as an `IndexError` on `ops[0]`; `require_ops` / `NoOperationsError` now
   report the maker's own setting as a plain sentence.
5. **Per-component CAM overrides** (`ComponentCamOverrides` on `Component`,
   carried on `ComponentWorkspace`, round-tripped through the `.gmodel`). The
   audit's case: the standard job is an acetate frame and temples plus **acetal**
   base-curve blocks, and acetal's depth-of-cut ceiling is half acetate's — but
   `cam_params` was project-global, so only the block's *feeds* re-read its own
   material while its depth per pass came from the frame. `resolve_component_cam`
   is the single seam that layers a component's overrides and re-clamps through
   *its* material; `ParamsPanel.effective_cam_params()` / `effective_material_name()`
   feed every single-component posting and sim path.

**Two live defects found in `cam/tabs.py` while wiring strategy 1** — both
invisible until tabs met a buffered contour, whose rings mix 140 mm straight runs
with 0.2 mm corner steps:

* **Two tabs on one segment merged into one raised run.** The drop back to cutting
  depth between them was only emitted at the *segment's* end, so on a temple
  profile four 3 mm tabs became two ~80 mm uncut stretches — most of the edge
  never cut through.
* **A tab boundary landing exactly on a vertex was dropped, and stalled the
  cursor**, silently deleting every remaining tab (the `dist < ev` lower bound
  could never become true again once `dist` passed it).

`insert_tabs` is rewritten around a distance-indexed Z schedule (`tab_schedule` /
`_height_at`): every original point is re-emitted at the height the schedule gives
it and the schedule's breakpoints are interpolated in, so **tab size no longer
depends on the caller's point spacing**. Ramps have an explicit length from
`TAB_RAMP_ANGLE_DEG` rather than "whatever the gap to the next path point happens
to be", and half-width plus ramp are capped against the tab spacing so tabs cannot
overlap into one continuous rim however extreme the settings.

Suite 606 → **640** (+34 in `tests/test_toolpath_control_m16.py`, including a
regression test for each `insert_tabs` defect and a spacing-independence test).
Held uncommitted for review. **Tabs have not been cut on real stock** — the
strategy is off by default, and its first real cut deserves the usual air-cut and
test piece.

## M17 — Two-sided modelling foundations (v1.4.0) · *the frame has a front* — 2026-08-06

> First instalment of V2. The driving shape: **a chamfer on the anterior brow,
> over each eyewire, on each side, not connecting across the bridge** — a common
> feature of thick modern frames, and one the M13 eyewire bezel cannot express
> because it is a constant band all the way round a ring.
>
> **Scope decision (user, this round): modelling and preview, not machining.**
> Cutting the front needs the flip setup, which stays M9/V2 — an unproven flip
> datum cuts the part in the wrong place, and it deserves its own milestone. The
> posterior program is byte-for-byte unchanged, pinned by a test.

**1. The frame front now exists in the model.** Until now the anterior face was
flat z = 0 *by definition*: one heightfield, and "the model" meant the posterior.
`CastleRelief.anterior` is a second surface on the same grid — height above the
anterior datum, so 0 is untouched and positive is material taken off the front —
with `thickness() = field.z - anterior`. It is `None` unless something actually
cuts the front (`CastleParams.cuts_anterior()`), so every pre-M17 project keeps
the single-surface fast path and reads bit-identically.

**2. `EdgeFeature`: partial-span chamfers and fillets on either face.**
* **The span is named by castle zone, not by a number along the ring.** `zones`
  lists the zones the run covers (empty = the whole ring). That survives a
  re-imported drawing where an arc-length fraction would silently point somewhere
  else, reads the way the maker thinks ("over the brow, not the bridge"), and
  **mirrors by swapping `_od` for `_os`** — so one feature with `mirror` on is the
  pair, not two objects to keep in sync. `trim_start_mm` / `trim_end_mm` then nudge
  each end for the last few millimetres of control.
* **`blend_mm` tapers the cut to nothing** at each end, so a run feathers out
  instead of stopping at full depth against uncut material. The taper is capped at
  half the run, or a blend longer than the span would ramp past the middle and cut
  *deeper* than asked.
* **`width_end_mm` makes it variable** — the chamfer widens or narrows along its
  length. None = constant.
* **Both profiles are exact.** `chamfer_drop` is the M13 ramp with a per-sample
  width; `fillet_drop` is a true round-over whose arc is tangent to the face at
  `d = radius` (no crease where it ends) and has dropped the full radius at the
  edge.
* Posterior features are min-carves into the castle surface; anterior features are
  the mirror image, max-carves raising the front face into the part. `min_thickness_mm`
  is enforced against *the other* surface both ways, so a part cannot be carved
  into nothing from two sides at once.

**3. The eyewire bezel gained a face.** `EyewireBezelParams.face` is
`posterior` (default, unchanged) / `anterior` / `both` — the "instead of or in
addition to" that was asked for — with its own anterior width and angle, since the
posterior band seats the lens and the anterior one is cosmetic. It is built as a
whole-ring `EdgeFeature` rather than a second copy of the chamfer maths.

**4. The 3D model shows it.** `build_castle_mesh`'s bottom vertices ride the
anterior surface instead of sitting on z = 0, so an anterior chamfer appears in
the preview and the exported STL. `_conform_rim` only moves vertices in XY, so a
non-flat anterior needed nothing there; the solid stays watertight.

**5. UI.** An **Edge Features** list on the Model tab (add / duplicate / remove,
with a zone-multiselect span picker that only ever offers the *loaded drawing's*
zones — a stale name from another frame would match nothing and the run would
silently vanish), plus the bezel's face selector, which greys out whichever side's
numbers are not being cut.

**Two bugs the new tests caught, both pre-existing in shape:**

* **An anterior-only bezel still carved the posterior.** `apply_posterior_features`
  gated on `bezel.enabled`, which was the whole story before a face existed; it now
  gates on `cuts_posterior()`.
* **Anterior carving inflated the posterior program.** `feature_band` /
  `feature_max_slope_deg` feed the posterior CAM's feature-finish rings, and the
  edge carver was contributing anterior cells to them — a chamfer on the *front*
  added 74 extra fine-relief passes to the *back* (Fine Relief 24 → 98 paths).
  Only posterior features feed that band now; the anterior band belongs to the flip
  setup.

Suite 640 → **675** (+35 in `tests/test_edge_features_m17.py`), including a test
that the posted posterior program is unchanged by an anterior feature.

**Pre-existing finding, NOT from this round — `build_castle_mesh` is not
watertight at fine resolutions.** Noticed while exporting a two-sided STL. On the
demo frame the solid is watertight at 0.4 mm and **open at 0.25 mm**, and it is
open with a plain `CastleParams()` too — no edge features, no anterior surface —
so M17 neither causes nor worsens it. It matters because the export resolution
pref defaults to **0.15 mm**, finer than either figure, so exported STLs are
likely open today. Untouched here to keep this milestone to its scope; worth its
own look, starting with the rim stitch's assumption that every boundary edge is
used by exactly one face.

**Still to come for V2:** the flip fixture and second work datum, anterior op
generation and posting, a two-setup program, and re-registration checks. The
anterior surface and its feature band are the inputs those will read.

---

## Feature crispness — root cause found, architecture decision open *(2026-08-06)*

**Field report:** the cutting features (pad splay, eyewire bezel, brow chamfer)
do not read as crisp. There is blending, and a pitted quality along the edges
where the cut begins and ends. The wanted result is a Fusion boolean cut —
exact at every edge.

**Root cause: the relief has no representation of an *edge*.** The model is a
raster heightfield, and every feature is a `min`/`max` painted into it. A cell
either got carved or it didn't; where the cut begins is wherever the sampling
flipped, not a curve the model knows about. **Every fix attempted so far has
therefore been a smoothing filter applied to a sampling artifact** — which is
why each one made the features softer rather than sharper. `crest_blend_mm`
defaults to a mandatory 2 mm round-over on the pad splay crest for exactly this
reason (`relief/features.py:145–147`), and the filter stack in
`_splay_crest_tables` is an inventory of the same, all traced to the 2026-07-02
"jagged points where the cut terminates" finding.

**Measured, on the Demo Project frame through the shipping code path** — walking
the conformed rim vertices around a lens aperture in arc-length order:

```
res = 0.30 mm   522 rim vertices   |dz| mean 0.109 mm   max 0.476 mm
res = 0.15 mm  1042 rim vertices   |dz| mean 0.055 mm   max 0.240 mm
```

Adjacent vertices on a curve that should be smooth, differing by 0.11 mm on
average. Reproduce with `DISPLAY= .venv/bin/python scripts/probe_rim_error.py`.

**The specific defect behind the pitting:** `_conform_rim`
(`relief/castle.py:632–634`) projects each silhouette vertex onto the true ring
**in XY only**, keeping the Z carved at the cell centre — which sits a random
0–0.3 mm inside the ring, where a rim-anchored chamfer has not reached full
depth. Correct when the rim was a flat terrace; wrong the moment a chamfer was
anchored to it. Three further causes (unconformed interior feature edges, the
compensating blur, and the viewer's 40° `feature_angle` smoothing 30° chamfers)
are set out in the report below.

### 📄 `BREP-REWRITE-REPORT.md` — full analysis and proposal

**Read that report before doing any work in this area.** It carries the complete
diagnosis, a survey of B-Rep kernels with a recommendation (OpenCASCADE via
`cadquery-ocp`), an honest cost accounting (~200 MB installer, LGPL obligations,
OCC performance and fillet-robustness risk), the module-by-module target
architecture, the hard problems, a staged migration with kill criteria, and a
"resuming cold" section with entry points.

**Direction (user, 2026-08-06):** attracted to the real B-Rep kernel despite the
cost, on future-proofing grounds — **after the V2 release**. Not scheduled. The
decisive arguments are not crispness but the three things a heightfield cannot
deliver at any price: watertight solids, STEP export, and undercuts.

**This must not displace V2.** The flip fixture and second work datum are
hardware gates; an unproven flip datum cuts the part in the wrong place, a
slightly soft chamfer does not. The M17 scope decision stands.

### M18 (proposed, pre-V2) — the four fixes worth making regardless

None of these is wasted by a later rewrite, and two are bugs shipping today.

1. **Fix the rim-Z defect.** When `_conform_rim` snaps a vertex, re-evaluate the
   feature's analytic height at the snapped XY instead of keeping the raster Z.
   Contained, and it removes the moiré from every aperture rim.
2. **Fix the watertightness bug** (the pre-existing M17 finding above). Exported
   STLs are likely open at the default 0.15 mm export resolution *right now* —
   this should not wait on an architecture decision.
3. **Viewer shading.** `viewer_3d.py:498` uses `feature_angle=40.0`, which
   smooths across the 30° chamfers of both the pad splay and the eyewire bezel,
   and splits the 45° brow chamfer inconsistently. Tag feature triangles and
   split explicitly, or drop the angle to ~15°.
4. **Default `crest_blend_mm` to 0** and expose it honestly as an *optional*
   round-over rather than a mandatory one the renderer needs. Accept that the
   crest looks jagged until the rewrite — better to see the real problem than a
   blurred one.

**Not in scope for M18:** the machined part. A ball or toroid rolling over a
convex crest rounds it by the tool radius regardless of model quality. Physical
crispness needs a curve-driven finishing pass along an exact feature edge curve,
which is impossible until such a curve exists — report §6, Stage 4.

### M18 progress *(2026-08-06)*

**#2 watertightness — DONE.** Diagnosis and fix recorded in the status note at
the top of this file; the short version is that the M17 attribution to the rim
stitch was wrong, and the real cause is `_snap_to_rings` not being injective plus
trimesh's vertex weld. `tests/test_castle_m2.py::test_castle_mesh_watertight_at_fine_resolutions`
pins 0.30 / 0.25 / 0.20 / 0.15 mm and was verified to fail at 0.25 and 0.20
without the fix. Suite 675 → 679.

**#1 rim-Z, #3 viewer shading, #4 `crest_blend_mm` — deliberately deferred**
(user decision, this round). With Stage 1 passed and Stage 2 the next milestone,
#1 and #4 are fixes to code Stage 3 deletes; #3 is superseded by the tessellator
emitting real crease edges. They stay on the list only if a release ships before
Stage 2 lands.

## Stage 1 — B-Rep kernel spike (v1.4.0+) · *the go/no-go* — ✅ PASSED 2026-08-06

`scripts/spike_brep.py`, no production code path. Full results in
**`BREP-REWRITE-REPORT.md` §9**, which supersedes that report's §4.3 and §5.2.

| Question | Result |
| --- | --- |
| §5.1 tapered partial-span chamfer (`MakePipeShell`) | **PASS** — valid, 0.14 s, needs a 0.02 mm taper floor; spline spine works, polyline spine does not |
| §5.2 footing fillets (`BRepFilletAPI_MakeFillet`) | **FAIL 0/16** at scheduled radii — but the operation was mis-specified, not the kernel |
| §9.3 footing as a swept `_footing_z` cross-section | **PASS 10/10** sweeps and 10/10 booleans, 0.12 s |
| Castle as extruded + fused terraces | **PASS** — valid solid, 0.81 s, 8004.95 mm³ |
| Performance | sub-second throughout **except** the chamfer boolean at 10.75 s |

**The one architectural correction:** the footing blend is a swept cross-section,
not an edge fillet. `_footing_z` survives the rewrite as the *primary* section
generator rather than as a fallback — so Stage 3 deletes less than planned.

## Stage 2 — the solid becomes the master model · *in progress, 2026-08-06*

> **Sequencing decision (user, 2026-08-06): go straight to Stage 2; Windows and
> macOS packaging waits.** GuildModel is GPL-3 and Linux-first — priority goes to
> the platforms that agree with the project's philosophy and to the maker's own
> workflow, on the reasoning that an open codebase lets the community adapt the
> rest. The risk accepted, explicitly: OCP has not been proven inside a frozen
> bundle, and that can only be tested on CI runners. If it turns out not to
> freeze, the fallback is unchanged (Manifold, report §3.1) but Stage 2 would
> have been spent first. **The licence obligation was not deferred** — OCCT's
> LGPL relinking terms and source offer went into `NOTICE` with the dependency,
> because retrofitting that after distribution is the part that cannot be undone.

**The architecture (report §4.2), restated:** the B-Rep becomes the master
representation and **the heightfield becomes a derived one, for CAM only**. The
drop-cutter is hardware-proven and carries the `INCIDENT-2026-07-29` fix in
`CUT_RES_MM`; nobody touches it. It keeps consuming a `Heightfield` with exactly
today's semantics, produced by ray-casting the solid.

**1. `core/solid/` — the new module.** Castle from `CastlePartition` unchanged:
zone polygons extruded to their heights and fused; footings and features as
boolean sweeps. Proven in Stage 1 at 0.81 s for the terraces and 0.12 s for all
ten footings.

**2. Footings are swept cross-sections, not fillets** — Stage 1's correction.
`_footing_z` is promoted to the primary section generator: the existing analytic
profile, swept along the SCULPT cut line. It is *not* deleted by Stage 3.

**3. The features as sweeps** (report §4.3, with §9's corrections): eyewire bezel
and lens groove swept along the aperture ring; pad splay along the crest curve;
brow chamfer along the trimmed span with a tapering profile — **floored at
0.02 mm, never zero**, or `MakePipeShell.MakeSolid()` fails; hinge pockets
extruded and subtracted.

**4. The CAM adapter.** Solid → Z-map at `CUT_RES_MM` by vertical ray casting.
One new function, and the only thing the CAM ever sees. `dropcutter`,
`castle_ops`, `component`, `sim/bed`, the worktable and the whole posting chain
stay untouched.

**5. The raster path stays alive behind a preference**, for A/B comparison and
for the gating strategy in report §3.5 — the new path is checked against the old
by sampling, excluding a narrow band around each feature boundary, and that band
is asserted separately to have got *sharper*.

### Stage 2 display modes — Fusion-parity viewing *(user requirement, 2026-08-06)*

**Why this belongs to Stage 2 and could never have been done before it.** All of
these are drawings *of the edges*, and the raster model has none. The Stage 1
solid of the demo frame carries **3,850 real edges** — the outline, each lens
ring, each terrace step, each feature boundary. The heightfield mesh at export
resolution carries **263,800 triangles and therefore ~396,000 triangle borders**,
not one of which is an edge of the frame. Wireframe on that is a wall of noise.
The display modes and the crisp chamfer are the same fix.

Four modes, in the Fusion vocabulary makers already have:

| Mode | Surfaces | Edges |
| --- | --- | --- |
| **Wireframe** | none | all, including occluded |
| **Shaded with Hidden Edges** | translucent | all, occluded ones distinguished |
| **Shaded with Visible Edges** | opaque | visible only |
| **Shaded / Render** | opaque, best quality | none |

**The enabler:** the tessellator must emit the topological edge polylines
alongside the triangles — after `BRepMesh_IncrementalMesh`, each `TopoDS_Edge`
carries its own polygon, so the exact edge set comes out at tessellation
fidelity. The viewer draws the triangles as the surface and the edge polylines as
a separate line set. Hidden-edge handling falls out of depth testing rather than
needing a heuristic: visible-only = lines depth-tested against the surface;
hidden-shown = the same lines drawn again with depth testing off.

**This also retires M18 #3.** `viewer_3d.py`'s `feature_angle=40.0` guess exists
only because the mesh has no crease information. With real edges there is nothing
to guess — the tessellator says where the creases are.

**Exit criteria for Stage 2:** the posted G-code for the demo frame is equivalent
to today's within the agreed tolerance; the preview is visibly crisp; all four
display modes work on the demo frame; `BRepCheck_Analyzer` passes before export.

**Deferred out of Stage 2, tracked:** PyInstaller packaging on Windows/macOS
(report §9.5), determinism across OCC versions (§5.4), the `flat.py` duck-type
(§5.3), preview interactivity and incremental rebuild (§5.5). The last one may
force itself into scope — Stage 1 measured a single chamfer boolean at 10.75 s.

### Stage 2 progress *(2026-08-06)*

**Landed:** `core/solid/` — `occ.py` (the Shapely↔OCCT bridge), `build.py`
(terraces + swept footings), `tessellate.py` (triangles + topological edges).
`tests/test_solid_stage2.py`, 9 cases. The demo castle builds valid in ~9 s and
tessellates in 0.21 s to **4,548 triangles, watertight, genus 2** — against
**263,800** for the 0.15 mm raster mesh of the same frame.

**Two defects found and fixed while building it**, both worth remembering
because of *how* they presented:

* **`polygon_to_face` reversed the hole wires.** Holes must wind opposite the
  outer wire and be added as-is. Reversing on top of that makes a face OCCT
  reports invalid *while still returning a shape with a plausible bounding box*,
  so it surfaced not as an error but as a boolean that quietly produced nothing:
  the footing fill intersected the body prism to exactly 0 mm³ and the blend was
  carve-only. Now normalised with `orient(poly, 1.0)` so it does not depend on
  Shapely's incoming winding, and pinned by two tests.
* **The footing fill was silently absent** because of the above — volume sat at
  the carve-only 7774 mm³. Now 7991 mm³, and a test pins that fills contribute.

**KNOWN LIMITATION — the edges are polygonal, not curves.** `ring_wire` builds
each contour from the Shapely coordinate list, so the demo outline's 342
vertices become 342 straight `TopoDS_Edge`s (lens rings 137 and 129). The solid
therefore carries ~3,850 edges that are *real boundaries but one-segment lines*,
not one spline per feature. Consequences, in increasing order of importance:

1. Wireframe display still works and is still vastly better than 396,000
   triangle borders — the lines drawn are genuinely the part's boundary.
2. The silhouette is a chord approximation, so a very close zoom will show it.
3. **It matters most for Stage 4.** Curve-driven CAM wants an exact curve to
   drive the tool along; 342 line segments is a polyline, which is closer to
   today's situation than to the goal.

The obvious fix is to fit B-spline wires instead of polygons. **It was spiked
and it does not work — do not retry it as written.**

### Spline ring wires — spiked, rejected for now *(2026-08-06)*

`scripts/spike_spline_wires.py`. Splitting each ring at genuine corners (turn
> 25 deg) and fitting the smooth runs works beautifully **as geometry**:

* the demo outline is **4 corners → 4 smooth runs**; lens rings have none, so
  each is one closed periodic curve
* deviation from the source polyline: **5.2 um worst, 1.7 um mean**, and the
  straight hinge-end runs come back exact
* edges collapse **3,850 → 244**; display edges **3,549 → 122**

**And then the faces built on those wires misbehave, at every tolerance:**

| fit tol | face tris | prism tris | watertight | GProp volume err |
| --- | --- | --- | --- | --- |
| 5e-3 mm | **0** | 119,229 | no | −105.06 mm³ |
| 1e-3 mm | 991 | 23,184 | yes | −55.59 |
| 1e-4 mm | 1,077 | 103,028 | yes | −79.03 |
| 1e-5 mm | 1,453 | 126,430 | yes | +22.35 |

The polygonal prism does the same shape in **1,360 triangles with an exact
volume**. There is no convergence to chase: the error changes sign between
tolerances. At the natural 5 um fit the planar face tessellates to *zero*
triangles, which is what collapsed the full build to an empty solid.

Note the failure signature — it is becoming this kernel's house style, and it is
the single most useful thing to carry forward: **`BRepCheck_Analyzer.IsValid()`
returned true throughout**, and the same face reported three different areas
depending on whether you asked `SurfaceProperties`, extruded and took the
volume, or meshed it. Validity is necessary, not sufficient. Cross-check area or
volume by a second route whenever a construction changes.

Tried and did not help: `MakeFace(wire)`, `MakeFace(wire, OnlyPlane)`,
`MakeFace(gp_Pln, wire)`, `ShapeFix_Face`, `ShapeFix_Shape`, and building the
boundary as 2D curves on the plane (`Geom2dAPI_PointsToBSpline` /
`Geom2dAPI_Interpolate` + `BRepLib.BuildCurves3d`), which is the principled
route and still tessellated to zero.

**The better plan, and it removes the risk entirely: do not put splines in the
faces.** Nothing actually requires the *modelling* boundary to be a spline. What
needs curves is (a) Stage 4's curve-driven CAM pass and (b) wireframe display —
both of which consume edges at **extraction** time. So build the solid
polygonally, where the booleans are robust and exact, and fit a spline to each
chain of smooth consecutive edges when handing a curve to the CAM or the viewer.
The kernel never sees a spline face, the fit quality above is already proven
adequate, and the two concerns decouple. Do this in Stage 4 for CAM, and
optionally in the tessellator for display.

The spline machinery stays in `occ.py` behind `spline=False` so the experiment
is re-runnable when OCCT moves; `test_solid_stage2.py` pins both the wire's
fit quality and the decision.

### The CAM adapter — `core/solid/zmap.py` *(2026-08-06)*

**The §3.5 gate is met.** `solid_to_relief` returns a `CastleRelief` the
existing CAM consumes unchanged. Measured against `build_castle_relief` on the
demo frame at `CUT_RES_MM`, over 65,949 in-body cells:

```
grid            identical (316, 847), same origin
inside          identical           zone_index  identical
mean            +0.0001 mm          rms         0.0036 mm
within 5 um     99.86%              within 0.1 mm   99.96%
```

Solid build ~9 s, Z-map 0.22 s. Sampling is by rasterising the tessellation with
a max-Z reduction rather than casting a ray per cell — same answer, one
vectorised pass per triangle, and exact within each triangle instead of sampled
at a point. Meshed at 5 um for CAM (`CAM_DEFLECTION_MM`), not the viewer's 20.

**Two bugs found by the comparison, both invisible without it:**

* **Footing bands were not clipped by zone.** The raster applies a blend only
  where `zi == ia` / `zi == ib` — inside the two neighbouring zones. The sweep
  applied its full band to whatever it crossed, and at the scheduled radii a
  band is ~8 mm wide, easily reaching a third zone. Now each half-blend is a
  separate body clipped to its own zone prism.
* **The high/low side probe flipped on some OS edges.** A single probe at the
  cut's midpoint lands outside both neighbours often enough to matter, and
  getting it backwards is silent — the carve is built on the low side, clipping
  it to the high zone leaves nothing, and the step never blends. It showed as
  1,179 cells adrift in `nosepad_os` against 11 in `nosepad_od`; that asymmetry
  was the tell. Now voted across every station.

**The residual 25 cells are a raster artifact, and the solid is right.** All of
them sit **6–7 mm past the *end* of a nosepad SCULPT cut** — the nearest point
on the cut is its endpoint, in all 25. The raster bands its footing by
`distance(point, LineString)`, which wraps **radially around a cut's endpoint**,
so it shaves up to **0.33 mm off the corner of the nosepad tower where there is
no step edge to blend at all**. The swept solid follows the edge and stops.

This is the first place the rewrite has *corrected* the shipping model rather
than merely reproducing it, and it is exactly the class of defect §3.5
anticipated: "where they disagree, the B-Rep is presumed right and the
difference must be explained." The test asserts the divergence is directional —
the solid may only ever keep material the raster wrongly removed.

### Features as boolean bodies — `core/solid/features.py` *(2026-08-06)*

**Hinge pockets: exact.** Extrude the polygon from `endpiece_mm -
hinge_pocket_depth_mm`, subtract. Whole-frame agreement is unchanged by adding
them (rms 3.64 um either way) and the solid's volume lands at 7825.25 mm³
against the raster mesh's 7825.00. `build_castle_solid(..., return_surface=True)`
also hands back the pre-pocket solid — the M8 `surface_field`.

**Eyewire bezel: a real chamfer, and this changes what the feature means.**
Worth stating plainly because it changes shipped geometry.

* The raster carves `pre(cell) - (width - d) * tan(angle)` — the surface pushed
  down by an amount falling off with distance from the rim. That is a **variable
  offset of whatever lies beneath**, not a chamfer. It has no flat face and no
  edge, and is only chamfer-shaped where the surface under it is already flat.
* The solid cuts a **ruled plane** rising inward at `angle` from
  `rim_z - width * tan(angle)`, anchored per station by an exact vertical ray
  fired 0.05 mm inside the rim.

On a flat terrace the two are identical. Measured on the demo frame: **83.6% of
in-body cells within 5 um, 94.7% within 50 um, rms 44 um, worst 0.70 mm.** The
divergence is concentrated in **nosepad and bridge**, where footing blends sweep
through the band — a plane cannot follow a swell and a variable offset must.
That is the feature behaving like the Fusion chamfer it is named after, and it
is what gives it an edge to be crisp at. **Flagged for the maker's judgement**
rather than settled unilaterally: the alternative is anchoring at the band's
inner edge, which tracks the raster more closely (rms 44 um -> and 85% within
5 um) but lets the *rim depth* drift by the surface slope times the band width,
up to 0.7 mm, breaking the band's one advertised promise.

**Three kernel findings from building it:**

* **`MakePipeShell` has a profile-count ceiling on a closed spine.** 40 and 60
  profiles build; 80, 100, 120 and 160 all throw
  `BRepAdaptor_Curve::No geometry`. `BRepOffsetAPI_ThruSections` takes 60, 120
  and 240 without complaint and its volume converges, so the bezel is **lofted,
  not swept**, and the station count can be chosen for fidelity rather than to
  appease the kernel.
* **A closed ring needs a periodic spine.** An open fit through stations that
  wrap around a ring fails the same way — the first and last are neighbours and
  the fitter has no room. `occ.closed_spline_wire` interpolates periodically.
* **`occ.edge_points` was returning None for every edge**, via an inverted
  `hasattr(edge, "Orientation")` guard — every `TopoDS_Shape` has `Orientation`,
  so it never down-cast and `BRepAdaptor_Curve` rejected the shape. Latent;
  nothing shipped depended on it.

**Edge features (M17) — the brow chamfer, as a solid.** The feature the whole
rewrite was argued from, and the one Stage 1 ranked likeliest to force a
fallback. It builds: **valid, watertight, rms 6.9 um, 96.0% of in-body cells
within 5 um and 99.5% within 50 um**, on the M17 driving shape (a 2 mm / 45 deg
chamfer over each brow, `mirror` on, not carried across the bridge). Residual
sits in the two `eyewire_superior` zones — the run itself, where the ruled
chamfer parts company with the raster's variable offset — plus the 40 known
nosepad cells.

Two things carried over intact, which is the good news for the M17 design:

* **The span is still named, not measured.** `edge_feature_cutters` calls the
  same `span_intervals`, so a run named by castle zone covers the same ring
  either way, and `mirror` still produces the pair.
* **`MIN_TAPER_DROP_MM = 0.02`** is Stage 1's finding in production: a section
  that tapers to a true point fails `ThruSections` outright, and a fiftieth of
  the finishing tool's radius is invisible in acetate.

**One thing the solid deletes outright:** an anterior edge feature is just a cut
from the underside — `surface_z_at(..., face="bottom")`. No second heightfield,
no `thickness()` invariant keeping two 2.5D surfaces from eating each other.
That was M17's scaffolding and it is simply gone.

**Pad splay — the smoothing inventory, left out rather than ported.**
`_splay_crest_tables` is the report's §1.4 list in one function: a slope limiter
on the crest offset, `uniform_filter1d` on the tangents and again on the anchor
heights, an EDT-filled surface so cells outside the body cannot crater the
crest, a cosine feather, and `crest_blend_mm` defaulting to a **mandatory 2 mm
round-over**. None of it is carried over — the crest is a real edge here and
wants to be sharp. What is kept is the geometry those filters were protecting:
the crest as an inward offset of the outline, the lens-rim clearance clamp (real
geometry, not a smoothing fix), the toric angle blend, and the end feather as a
depth taper. `crest_blend_mm` returns later as the optional round-over it should
always have been.

Against the raster with its blend also set to 0: **rms 13.2 um, 90.6% of cells
within 5 um, 98.6% within 50 um**, valid and watertight. With the raster's
blend left at its 2 mm default the divergence grows exactly as it should
(954 -> 1,457 cells over 50 um) — that is the blur, measured.

**One bug, and the wrong diagnosis first.** The initial build anchored the
chamfer at the *outline edge*; the splay is defined as falling **from the
crest**, which sits up to 6 mm inboard. Over that distance the surface climbs
out of the bridge footing into the nosepad tower, so the drop was measured from
the wrong datum — 0.11 mm rms shallow, 0.97 mm at worst. It presented as a large
positive bias (the solid keeping material the raster removed), which looked
exactly like the missing crest round-over; setting the raster's blend to 0
changed rms by 0.4 um and disproved that in one run. **Anchor at whatever the
feature's own definition pins it to** — the splay at its crest, the bezel at its
rim, and those are opposite ends of the band.

**Bridge relief — the cone its own docstring claimed.** The raster's
cross-section is a cosine bell, `0.5 + 0.5 cos(pi x / r)`, listed among the
report's compensating blurs: it meets the surface tangentially and so hides the
facets a sampled cone showed. Here it is a genuine elliptical cone lofted along
Y, depth scaling with the local half-width so it feathers to nothing at the tip
— which is what the raster docstring says it builds.

**rms 29.9 um, 98.3% of cells within 5 um**, valid and watertight. The 763
bridge cells that differ are almost all **negative**, and predictably so: at
half the scoop radius an ellipse is at 0.866 of full depth where the bell is at
0.500, so the cone cuts deeper across the middle of the band. The test asserts
that direction, because a sign flip would mean the section was built inverted.

**Lens groove — the undercut, and the clearest justification the rewrite has.**
The drageoir V is cut *radially into the aperture wall*, so it is an undercut: a
heightfield cannot hold it at any resolution. The raster reaches it by shrinking
the aperture mask and then hand-building a notched rim strip **in the mesher**
(`castle._groove_rim`) — geometry the model itself does not contain, and
therefore cannot be measured, sectioned or posted from. Here it is a boolean
like any other.

**rms 2.32 um, 99.85% of cells within 5 um** — the closest agreement of any
feature — masks identical, watertight, genus 2. Proof that the V is really there
is by **ray crossings**, not surface height: a vertical ray through the wall cuts
four surfaces (anterior, groove floor, groove roof, top) at 40/40 stations and
drops back to two past the apex. Taking min/max Z shows nothing at all, which is
exactly the blindness being fixed. The V's half-width tracks
`width_mm/2 * (1 - u/depth_mm)` to **0.1 um** at every depth.

Getting there took three wrong turns, all worth recording:

1. **The annulus was `difference` where it needed `intersection`.** The lip
   annulus is the sliver inside the original lens outline *and* material in the
   lip body; subtracting gave the shrunk hole's interior instead, so every zone
   stayed unchanged and the groove cut thin air.
2. **Buffering zones into the annulus does not survive the kernel.** Even handing
   the annulus out as a strict partition so no two zones claim the same sliver,
   the buffered rings carry enough near-coincident geometry that fusing the
   terrace prisms **collapsed to an empty solid while still reporting
   `IsValid()`**. Re-running the existing partitioner against shrunk lens
   polygons instead gives zones that tile the lip body exactly — same nine names,
   still classified, same ten SCULPT edges — and reuses proven code.
3. **Then the lip got shrunk twice.** `build_castle_solid` now hands
   `apply_lens_groove` the *already-shrunk* partition, and the function shrank it
   again, putting the V a further 0.75 mm inboard — open aperture. The loft
   built, the boolean succeeded, and it removed nothing.

**A guard now sits on the terrace union.** The empty-but-valid failure has
appeared three times (the hole-winding face, the footing fill clip, the buffered
lip zones), so `build_castle_solid` raises if the terraces come back at zero
volume. It is the one stage whose volume is known to be positive, which makes it
the cheapest place to catch the whole class.

**Performance is now the visible problem.** The bare castle builds in ~9 s; with
the bezel it is **~37 s**. Report §5.5 predicted incremental rebuild would move
from "nice" to "required", and this is that point arriving.

## Stage 2 — SESSION HANDOVER, on-screen review *(2026-08-07)*

**Read this first when resuming.** Stage 2's modelling work is done and green
(suite 709 + 1 xfail). What follows is the first on-screen review of it, with
four findings — two are integration defects of mine, one is a genuine
performance wall, one is environmental.

### 1. Build time is the wall — measured, per feature

Demo frame, solid path, each feature alone on top of the bare castle:

| Build | Time |
| --- | --- |
| RASTER, preview 0.3 mm (for scale) | **0.4 s** |
| bare castle + hinge pockets | 10.6 s |
| + bridge relief | 11.7 s |
| + pad splay | 17.4 s |
| + lens groove | 20.3 s |
| + brow chamfer (mirrored pair) | 23.4 s |
| + eyewire bezel (posterior) | **36.4 s** |
| **ALL FEATURES ON** | **81.6 s** |

The solid is ~200x the raster preview, and **the eyewire bezel alone costs
+25.8 s** — 180 lofted sections per ring, two rings, then a boolean against a
progressively heavier solid. Report §5.5 predicted incremental rebuild would go
from "nice" to "required"; at 81.6 s it is required.

Where to look first, in order of expected return:

1. **Cache the unfilleted castle** and re-apply only the feature that changed.
   Terraces + footings are ~10.6 s of every rebuild and change only when zone
   heights or the footing schedule do.
2. **The bezel's section count.** 180 was chosen for fidelity after the volume
   stopped moving (60 -> 120 -> 240 gave 3179.5 / 3188.0 / 3189.9 mm³). 120 is
   within 2 mm³ of 240 and should roughly halve the loft cost — measure it.
3. **Fuse all feature cutters once, cut once.** Each feature currently does its
   own boolean against the whole solid; the cost grows with what came before.
4. **Debounce the params panel** so a slider drag does not queue rebuilds.

**The test suite has the same disease** — 6 min -> **12 min**, because several
Stage 2 tests build their own solid instead of sharing the module fixture. Fold
that into the same work; it is the fastest feedback win available.

### 2. The display-mode dropdown was dead — my integration gap

**Cause: two build paths, only one of them wired for solids.** The toolbar's
**Build 3D** goes `_on_build_3d` -> `_build_all` -> **`MultiMeshWorker`**, which
was never given a solid branch and always returns raster meshes with
`edges=None`. The solid path lives only in `MeshWorker`, reached by
`_start_mesh_build` — stage changes and param-change rebuilds.

So pressing Build 3D produced a raster model, the viewer correctly saw no edges,
disabled the combo and pinned it to "Shaded" — and clicking it did nothing,
exactly as reported. Meanwhile *changing a parameter* triggered a solid rebuild,
which is why builds felt fast until features started stacking.

**Fix:** give `MultiMeshWorker` the same `solid=` branch and edge emission as
`MeshWorker`, or route both through one builder. The second is better — the
split is what caused this.

### 3. Anterior eyewire bezel does nothing on the solid path

Confirmed by volume: `face="anterior"` removes **0.00 mm³**, and `face="both"`
removes **exactly** what `"posterior"` does (474.40 mm³ either way).

`core.solid.features.apply_posterior_features` only handles
`bezel.cuts_posterior()`. The raster implements the anterior side separately, in
`relief.edges.carve_anterior_bezel`, as a whole-ring `EdgeFeature` on the front
face — and that was never ported.

**It is a porting oversight, not a missing capability.** Anterior *edge
features* already work (184.71 mm³ removed), cutting from the underside via
`surface_z_at(..., face="bottom")`. The bezel should be built the same way the
raster builds it: as a whole-ring anterior `EdgeFeature`, reusing
`edge_feature_cutters`. **`tests/test_solid_stage2.py` carries an
`xfail(strict=True)` that flips to passing the moment it works.**

### 4. Small text is XWayland, not the app

`Xft.dpi` is **96**; the panel is **141 DPI** (1920x1200 over 345 mm). Under the
XWayland workaround Qt gets 96 and renders text at **68%** of intended size.
Native Wayland would carry the compositor's fractional scale, but VTK forces the
`xcb` workaround (README "Linux: Wayland crashes Build 3D Model").

Launch with one of:

```
QT_QPA_PLATFORM=xcb QT_FONT_DPI=141   guildmodel     # text only
QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=1.47 guildmodel  # whole UI
```

Documented in the README beside the existing XWayland note. Worth re-testing the
dropdown under correct scaling too — a combo that does open can still look
inert if its popup renders off-scale.

### Resuming: suggested order

1. **Unify the two mesh workers** (finding 2) — small, and it unblocks any
   further on-screen review of the solid path.
2. **Incremental rebuild + share the test fixtures** (finding 1) — the wall.
3. **Anterior bezel** (finding 3) — delete the xfail.
4. Then the rest of Stage 2's exit criteria: posted G-code equivalence on the
   demo frame, and `BRepCheck_Analyzer` in the readiness dot.

Still open from earlier, unchanged: PyInstaller packaging on Windows/macOS
(report §9.5), determinism across OCC versions (§5.4), the `flat.py` duck-type
(§5.3), and refitting smooth edge chains to splines at extraction time for
Stage 4's curve-driven CAM.

## Stage 2 — the build-time wall, measured and taken down *(2026-08-07)*

**82.8 s → 24.7 s cold, 17.2 s warm, and every volume bit-identical to before.**
Target was "under 20 s"; a warm rebuild — a maker dragging a feature slider — is
17.2 s worst case with *every* feature on, and 0.6–5.1 s for the realistic case
of one feature at a time. Reproduce with `scripts/bench_solid.py`, which is the
handover's hand-timed table turned into a committed benchmark.

| Build | was | cold | warm |
| --- | --- | --- | --- |
| bare castle + hinge pockets | 10.6 s | 8.6 s | **0.6 s** |
| + bridge relief | 11.7 s | 9.8 s | 1.9 s |
| + pad splay | 17.4 s | 13.4 s | 5.1 s |
| + lens groove | 20.3 s | 10.6 s | 2.3 s |
| + brow chamfer (mirrored pair) | 23.4 s | 10.9 s | 3.2 s |
| + eyewire bezel (posterior) | 36.4 s | 11.6 s | 4.0 s |
| **ALL FEATURES ON** | **81.6 s** | **24.7 s** | **17.2 s** |

### The handover's diagnosis was wrong in an instructive way

It named the bezel's 180 lofted sections as the thing to attack. **Profiling says
lofting is ~9 s of the 82 s and booleans are 64 s** — `cut` alone was 7 calls and
81% of the build. Every lever that mattered was in the boolean layer:

1. **OCCT's parallel mode was simply off.** `SetRunParallel(True)` in `occ._run`:
   82.0 s → 62.2 s, same volume, same face count. Same algorithm, more cores.
2. **`cut_many` — one BOP pass, N tools** (`occ.py`). The old code cut each
   feature separately, so every result carried the previous cutter's faces and
   the target inflated 1,244 → 6,471 faces across the build; the last cuts paid
   for all the earlier ones. One pass against an un-inflated target did the
   bezel + edge features + groove in **7.5 s instead of 32.9 s**, volume delta
   0.00 mm³.
3. **`castle_base` is cached** (`build.py`). Terraces + ten footing blends are
   ~8 s of every rebuild and depend on no feature parameter. This is the
   incremental rebuild §5.5 predicted would become required.
4. **`surface_z_at` re-loaded the whole shape per ray.** `Init(shape, line, tol)`
   is O(faces) *per point*; `Load` once + `Init(curve)` per ray took the anchor
   casts from 3.8 s to under 1 s. On a 6,000-face castle the anchor rays cost
   more than some of the booleans they fed.

### Three things that looked right and are not — do not retry as written

* **"Fuse all cutters, cut once" (the handover's own #3) is a double loss.**
  Fusing the eight demo cutters costs 23.6 s and the cut that follows 31.8 s —
  worse than the sequential chain it replaces, because boolean cost is
  superlinear in *both* operands. It is also a semantic change: cutters anchor
  with `surface_z_at` on the *current* solid, so building them all against one
  base moves the bridge relief's anchors by up to **2.59 mm**. `cut_many` gets
  the speed without the semantics precisely by *not* fusing, and
  `apply_surface_features` keeps splay→scoop sequential because those two
  genuinely interact. The membership rule is measured, not assumed — the drift
  table is in `independent_cutters`.
* **Smooth (`ruled=False`) cutter lofts.** The obvious way to cut face counts.
  It takes 221 s and returns a solid with **zero faces and zero volume that
  `BRepCheck_Analyzer` calls valid** — the fourth appearance of the
  empty-but-valid failure. `build_castle_solid` now has a closing volume guard
  to match the terrace one; without it that would have reached the Z-map.
* **Lowering `BEZEL_STATIONS` 180 → 120.** Volume converges early and says this
  is free (0.3% change). It is not: the ruled patches inscribe a polygon in the
  ring, and 120 stations is a 7.2 µm sagitta against a **5 µm** raster-agreement
  gate. `test_bezel_is_a_real_chamfer_not_an_offset` fails it at 79.3% vs the
  required 80%. **Chord error pins that constant, not volume** — the old comment
  argued from volume and was misleading. Reverted, with the sagitta table.

**The test suite came along for free**: 12 min → **7.5 min** on the same tests
(8 min with this session's five new ones, at **715 green and no xfails**), and
`tests/test_solid_stage2.py` alone runs in 75 s. The handover proposed sharing
fixtures to fix the 12-minute suite; the tests were slow because the builds were
slow, so most of that need evaporated. Fixture sharing is still available if the
suite creeps back up, but it is no longer the fastest win.

### Finding 2 — one builder, and edges became per-component state

`gui/mesh_build.py` is new: `build_component_mesh(spec, resolution, solid)`
returns `(mesh, edges, core_guide)` for a frame front, a temple or a
base-curve block, and **all three workers now call it**. `MeshWorker`,
`FlatMeshWorker` and `MultiMeshWorker` keep their own signals and threading and
have no build logic left.

The handover offered "give `MultiMeshWorker` the same solid branch, or route both
through one builder" and preferred the second. That was right, and it
understated the case: there were three copies, not two — `MultiMeshWorker` also
carried a duplicate of `FlatMeshWorker`'s temple and block branches. Adding the
solid branch to the third copy would have left the same trap set for the next
feature.

`MultiMeshWorker.built` gained an edges slot, and **`edge_cache` moved onto
`ComponentWorkspace`**. It was the one piece of per-component render state the
main window still owned, so tab-switching swapped `stage_cache` and left the
edges behind. Harmless only while a single frame front was the only thing that
could produce edges — which stopped being true the moment Build 3D started
building solids for every component. Pinned by three tests, including one that
drives `MultiMeshWorker` synchronously and asserts Build 3D emits edges.

Also fixed in passing: `MultiMeshWorker`'s progress closure captured `label` from
the enclosing loop rather than binding it, so every component's progress line
reported the last component's name.

### Finding 3 — the anterior bezel, ported

`face="anterior"` removed **0.00 mm³** and `face="both"` removed *exactly* what
`"posterior"` did. Now:

| face | removes |
| --- | --- |
| posterior | 474.40 mm³ (unchanged) |
| anterior | **291.38 mm³** (was 0.00) |
| both | **765.78 mm³** — exactly the sum, the two bands do not overlap |

Built the way the raster builds it: `anterior_bezel_features()` spells the band
as two whole-ring `EdgeFeature`s and hands them to the existing
`edge_feature_cutters`, which already cut from the underside via
`surface_z_at(..., face="bottom")`. One chamfer implementation, not two. The
strict xfail is deleted and replaced by a test that guards the *specific* old
shape of the bug — `both` being bit-equal to `posterior`, not merely `both`
being non-zero.

### Finding 4 — nothing to do

The XWayland DPI guidance was already written into the README by the handover
commit itself (`82f4f4c`). Verified present.

### Still open

Stage 2's remaining exit criteria: **posted G-code equivalence on the demo
frame**, and **`BRepCheck_Analyzer` in the readiness dot**. Then the long-running
items, unchanged: PyInstaller packaging on Windows/macOS (report §9.5),
determinism across OCC versions (§5.4), the `flat.py` duck-type (§5.3), and
refitting smooth edge chains to splines at extraction time for Stage 4.

Worth knowing for whoever takes the perf work further: after this round the
remaining cold time is ~8.6 s of `castle_base` (cached after the first build) and
~7 s of the single feature BOP pass. There is no large single lever left — the
next gains would come from the footing blends' 20 `common` calls, or from
extending the cache to a second seam after `apply_surface_features`.

## Codebase audit + the road to Fusion parity *(2026-08-07)*

Commissioned as "a deep audit of any useless or junk code" plus "what we can do
to further work toward a Fusion 360 like experience, even if it entails major
re-writes — we don't want to build on bandaids."

### 1. The curve is destroyed on line 81 of the importer

**This is the root cause of the faceting, and it is upstream of everything the
rewrite has been arguing about.**

GuildDraw exports **real NURBS**. The demo DXF carries `SPLINE` entities:

| layer | degree | control points | flattened to |
| --- | --- | --- | --- |
| OUTLINE | 3, closed | **64** | 342 points |
| LENS (OD) | 3, closed | 13 | 137 points |
| LENS (OS) | 3, closed | 7 | 129 points |
| HINGE ×2 | 3, closed | 25 each | 59 each |

134 control points describe the whole frame. `io_import/dxf.py:81` calls
`entity.flattening(chord_tol)` and replaces them with **726 points**, in the
first few lines of the pipeline. Every stage downstream — `regions`, `relief`,
`solid`, the CAM — has only ever seen polygons. The 3,850 one-segment edges the
Stage 2 notes describe as a "KNOWN LIMITATION" of `ring_wire` are not a
limitation of `ring_wire`: it is faithfully building a polygon out of a polygon
it was handed.

**This also explains why the spline spike failed.** `scripts/spike_spline_wires.py`
fitted B-splines *to the flattened points* — reconstructing information that had
already been thrown away two stages earlier. Hence 5.2 µm deviation (a fit
error that should not exist), and faces that misbehaved at every tolerance. The
spike's conclusion "do not retry as written" is right, and the words that matter
are **as written**: re-fitting is the wrong operation.

The right operation is to *not discard*. A DXF `SPLINE` carries exactly what
`Geom_BSplineCurve` needs — control points, knots, multiplicities, degree,
periodic flag, optional weights — so the curve can be handed to OCCT with **no
fitting and no error at all**. That is a different proposition from the spike.

What it buys, using the spike's own measurements of the same frame: edges
**3,850 → ~244**, display edges **3,549 → 122**, an exact silhouette at any
zoom, and — the one that decides Stage 4 — a real curve for curve-driven CAM to
drive the tool along instead of a 342-segment polyline.

It also fixes the sweeps. Every feature cutter lofts sections positioned along
these rings, so a faceted ring makes a faceted band and the two compound.
Chasing it with more stations does not converge (see `BEZEL_STATIONS`, where the
5 µm gate pins the count) because the spine itself is the polygon.

**Cost, honestly:** `partition_zones`, the whole of `relief/`, and the CAM all
consume point lists. The curve has to be carried *alongside* the flattened
representation, not instead of it, or this becomes a rewrite of everything at
once. The natural seam is to keep the flattened points as the CAM/raster input
they already are, and thread the curve through to `occ.ring_wire` only.

### 2. It is not the GPU

Tested on this machine because it was a live suspicion: **AMD Radeon 880M,
radeonsi, Mesa 26.1.6, OpenGL 4.6 core, direct rendering — hardware
acceleration is working.** The "SGI" string in a VTK capability dump is the GLX
*protocol* vendor and says nothing about the renderer. Faceting is geometry, not
rasterisation.

### 3. Dead code: there is almost none

Measured, not eyeballed — a static import graph over `src/`, `tests/`,
`scripts/` and `main.py`, plus `vulture`:

* **Modules with no importer anywhere: one.** `gui/preview/` — an empty package,
  a tracked `__init__.py` and nothing else. Deleted.
* **Modules imported only by tests: one.** `core/relief/hinge.py` (141 lines,
  the CHA hinge-catalog machinery). BUILDPLAN reserves it for post-1.0 and v1
  uses HINGE-layer + depth instead, so it is *reserved*, not junk — flagged, not
  deleted. It is in git either way.
* `vulture --min-confidence 80` over `src/` found **one** real hit, an unused
  import in `cam/engrave_centerline.py`. Fixed. Everything below 80% is pydantic
  model fields and dataclass attributes it cannot see through.

**The Reference module table below is stale and was misleading me**: it still
lists `mesh/twosided.py`, `mesh/stl_export.py` and `io_import/svg.py` as
retire-candidates. All three no longer exist.

So: the codebase is not carrying junk. What it is carrying is *undifferentiated*
code.

### 4. The real structural debt

| Thing | Size | Why it matters |
| --- | --- | --- |
| `MainWindow` | **192 methods, 4,183 lines** | ~50 methods and 1,089 lines of it are CAM/G-code orchestration; 31 are project I/O. None of that is windowing. |
| `gui/app.py` | **7,107 lines, 17 classes** | `PrefsDialog` (1,044 lines) and `GCodeWorker` (819) live here too. |
| `build_castle_relief` call sites | **8** | Each rebuilds the relief with its own resolution/params handling — STL export, CAM, sim, bed sim, preview. Exactly the disease the three mesh workers had. |
| raster vs solid | 2,317 vs 2,187 lines | Two full implementations of every feature. Deliberate during Stage 2 (§3.5 A/B), but it is the largest duplication in the tree and it cannot stay. |

The mesh-worker unification earlier today is the template for the second and
third rows: one builder, workers reduced to threading and signals.

### 5. Recommended order, if this is to be done without bandaids

1. **Carry the curve** (§1). It is the foundation the other three want, it is
   the smallest change of the four, and it retires the `feature_angle=40.0`
   guess, the chord-error ceiling on every sweep, and Stage 4's blocker at once.
2. **Finish the raster→derived demotion.** Stage 2's stated architecture is that
   the heightfield is produced by ray-casting the solid, for CAM only. Until the
   solid path is the default and `relief/`'s feature carving is deleted, every
   feature has to be written twice — which is how the anterior bezel came to
   exist on one side only.
3. **One relief builder, 8 call sites → 1.**
4. **Split `MainWindow`.** CAM orchestration and project I/O are separable today
   without touching behaviour; that is ~1,700 lines out of the god-object.

Only after 1 and 2 does "Fusion-like" become a question about the *UI* — a
feature tree, a timeline, rollback — rather than about whether the model is
made of curves. Building a history tree on a polygon soup would be the bandaid.

## Carrying the curve — step 1 landed *(2026-08-07)*

Audit item §1. The drawing's NURBS now survive the importer and reach the
kernel. **Exact, not fitted** — that is the whole distinction from the rejected
spike, and it is measured rather than asserted.

### What landed

| Piece | What it does |
| --- | --- |
| `core/geometry/curves.py` | `NurbsCurve` — poles, knots, degree, periodic, weights. Kernel-neutral (the importer must never pull in OCP's 70 MB) plus `mirror_x` for the M1.2 posterior flip. |
| `io_import/dxf.py` | `import_curves()` returns `(points, curves)`, index-aligned. `import_dxf()` is unchanged and now delegates to it, so nothing downstream had to move. |
| `solid/occ.py` | `nurbs_edge` / `curve_ring_wire` — the transcription to `Geom_BSplineCurve`; `ring_wire(..., curve=)` and `polygon_to_face(..., curves=)` use it when a ring has one. |
| `geometry/regions.py` | `CastlePartition.source_curves` + `ring_curve(ring)`, and `curves_by_ring()` to build the map. Additive: a drawing of polylines produces an empty map and behaves exactly as before. |

**The exactness claim, measured.** Every point of the DXF's own
`flattening(0.01)` projected onto the rebuilt curve: **worst deviation
< 1e-6 mm**, outline and both lens rings. The re-fitting spike's 5.2 µm was a
fit error against the curve's own approximation; with no fitting step there is
no error term. Pinned by `tests/test_source_curves.py`.

**The outline is now one edge instead of 342.** `curve_ring_wire` on the demo
outline yields a single-edge wire where `polygon_ring_wire` yields 342.

### Three things this turned up

* **`_ring_key` cannot key on a start point.** `outline.difference(lenses)`
  returns the same coordinates rotated to a different start vertex, and
  sometimes reversed. Keying on start-plus-two-samples matched **one ring of
  three**; keying on vertex count plus bounding box matches all three, and still
  correctly *misses* when Shapely genuinely reshapes a ring — a reshaped ring is
  not the authored curve any more.
* **A B-spline carries its own winding**, unrelated to `orient(poly, 1.0)`. A
  curve running against the ring it replaces gives a face OCCT calls invalid.
  `ring_wire` now compares signed areas and reverses.
* **`BRepGProp` without an `Eps` is wrong on spline-bounded faces — by 4%.** The
  demo body face measures **1546.690 mm³ by default against 1483.750
  adaptively**, and the error points the wrong way: it reads as if the curve
  added 63 mm² of material. It did not. The true outline adds **0.649 mm²** over
  the polygon inscribed in it (exactly the chord deficit) and the true apertures
  take **0.889 mm²** back. `occ.volume` now passes `GPROP_EPS`, and `occ.area`
  exists so nobody reaches for the raw call. Verified not to move any existing
  figure — every row of `bench_solid.py` is unchanged to 0.1 mm³.
  **This one nearly cost a day**: the "curve adds material" reading is exactly
  wrong enough to look like a real geometric bug.

### Step 2 — zone-boundary arcs, spiked to 7/9, NOT landed

Making the *model* curved needs more than whole rings, because `build_terraces`
builds from **zone** polygons — pieces of the rings cut by the SCULPT lines — so
each zone boundary is outline/lens arcs joined by straight cuts. Measured on the
demo: **~94% of every zone's vertices lie on an authored curve**, in 2–5 clean
runs (`endpiece_od` is 54 vertices = 2 runs; `bridge` is 84 = 5).

`scripts/` is not carrying this yet; the working spike is in the session
scratchpad. State at handoff, **7 of 9 zones valid with areas matching the
polygon to under 0.5 mm²**, via three fixes found in order:

1. **Seam splitting.** A run passing the curve's start/end point shows as a
   parameter jump; split there or the trim sweeps the complement arc (areas came
   back negative, or 7× too large).
2. **Explicit shared vertices.** Arc endpoints are exact curve points, straight
   endpoints are flattened ring vertices, and they differ by up to the
   flattening tolerance. `BRepBuilderAPI_MakeWire` stitched across that gap
   where it could and silently produced a disordered wire where it could not —
   still reporting `IsDone()`. Building every `TopoDS_Vertex` once and handing
   it to both neighbours took this from 5/9 to 7/9.
3. **Verify each span before trusting it.** Check the arc's midpoint against the
   ring vertex it came from; a wrong-branch arc misses by millimetres. Given
   this kernel's habit of plausible-looking wrong answers, the guard is worth
   keeping regardless of whether span detection is perfect.

**The two remaining failures are not a NURBS problem.** With every arc rejected
by the guard — `arcs=0`, pure polyline — `eyewire_superior_od` and
`eyewire_inferior_os` are *still* wrong (+180 and +225 mm²). The cause is in the
spike's fallback: a rejected span emits **one straight chord across the whole
span** instead of re-emitting the original vertices, cutting the corner off.

### Step 2 resolved — 9/9, and blocked on the mesher instead

The fallback was the whole remaining problem, exactly as predicted: re-emitting
the span's vertices took it straight to **9/9 valid, areas matching the polygons
to +0.059 mm² in total**. Replacing the midpoint check with one that samples the
arc against the span's own polyline (`ARC_VERIFY_TOL_MM`) then restored arcs to
the two zones the crude guard had been rejecting.

`occ.SourceCurves` + `occ.curved_ring_wire` are production code and
`build_terraces` can use them. The whole castle builds **valid** from authored
curves:

| | polygons | authored curves |
| --- | --- | --- |
| edges | 9,942 | **8,237** |
| display edges | 4,971 | **3,952** |
| mesh volume | 7825.25 mm³ | **7825.69 mm³** (+0.44 — the chord deficit, recovered) |
| `BRepCheck_Analyzer` | valid | valid |
| triangles | 6,472 | 23,774 |
| **watertight** | **yes** | **NO** |
| build | 7.8 s | 18.8 s |

**`CURVED_TERRACES` is therefore `False`.** The geometry is right — that +0.44 mm³
is precisely what recovering the true curve should add — but the tessellation is
not closed, and the M2 STL gate and the CAM both require watertight. Flipping
the flag is one line; **fixing `tessellate` to produce a closed mesh across
mixed spline/planar faces is the actual next task.** Build time (2.4×) is a
secondary concern and is dominated by per-vertex curve classification.

### `volume()` cannot be trusted once a face is a spline — and an Eps makes it worse

Recorded because it cost real time and because the natural fix is the wrong one.
Two **disjoint** zone prisms, whose fused volume must be exactly their sum:

| setting | od | os | fused | sum |
| --- | --- | --- | --- | --- |
| default | 985.435 | 1011.400 | 2006.927 | 1996.835 |
| `Eps` 1e-6 | 919.773 | 1038.664 | **1550.374** | 1958.437 |
| `Eps` 1e-9 | 1045.464 | 1051.349 | 2413.023 | 2096.813 |
| **mesh** | **994.498** | **1013.568** | **2008.066** | **2008.066** |

Only the tessellation is self-consistent. This session briefly shipped
`Eps=1e-6` on `occ.volume` — correct for the planar spline-bounded *face* where
it was verified against theory, and **wrong for solids**, where it turned a 0.5%
error into a 23% one. Reverted; `occ.mesh_volume` added as the referee, and the
reasoning is in the docstring so the next person does not re-derive it. The
`area()` adaptive integration stands, on the face evidence.

Chasing that number is also what exposed the false alarm behind it: the 716 mm³
the terrace fuse appeared to "lose" was never lost. Disjoint solids cannot
overlap, so a fuse that reports less than the sum is a measurement bug, not a
geometry bug — worth remembering as a cheap sanity check on this kernel.

### Watertight — it was never the mesher *(2026-08-07)*

The non-watertight curved mesh looked like a tessellation problem and was not.
Stage by stage, with curves on:

| stage | watertight |
| --- | --- |
| terraces | **yes** |
| + footing fills | no |

The terraces mesh closed. The crack arrives with the fills, and the cause is a
**mismatch, not a mesher limitation**: `footing_bodies` clips each swept fill to
its zone with `extrude(polygon_to_face(zone.polygon))`, which was building that
clipping prism from the *flattened polygon* while the terraces followed the
*curve*. The clip therefore sat a chord-width inside the real boundary, the fill
stopped just short of the terrace it blends into, and the near-coincident pair
of faces that produced tessellated with a gap — valid solid, leaking mesh, the
house failure mode.

Threading one `SourceCurves` from `castle_base` through both `build_terraces`
and `footing_bodies` fixes it outright: **watertight at every stage**, valid,
and the mesh volume lands within half a cubic millimetre of the polygon build.
No change to `tessellate` was needed. Welding was investigated first and is a
red herring — the raw per-face vertices are already merged by `to_trimesh`'s
`process=True`, and welding *harder* (1e-6 mm and coarser) breaks watertightness
by merging genuinely distinct points.

**`CURVED_TERRACES` is now `True`, and it is opt-in by data rather than by
flag.** It engages only where a caller has supplied authored curves; a partition
built without them produces an empty `SourceCurves` and the polygonal path,
unchanged. That is why the whole suite is unaffected.

### Both intakes now carry the curve *(2026-08-07)*

`partition_zones` took `source_curves` and the only caller passing it was
`scripts/bench_solid.py`, so nothing a maker could open ever built from a curve.
Both intakes are wired now.

**`.gdraw` had the same hole the DXF importer had.** It stores splines as cubic
Bezier nodes and `_flatten_spline` threw them away. A chain of cubic Beziers *is*
a cubic B-spline — interleave the poles, multiplicity 3 at each interior joint —
so `geometry.curves.cubic_bezier_chain` re-spells one as the other with no
tolerance and no error term. Verified on the aviator fixture: every ring of the
front (outline, bridge opening, both apertures, both hinges) rebuilds with a
worst deviation of **0.0000 nm** from its own flattening, matching the DXF path.

Circles come across as exact rational quadratics. That work also turned up a
real defect next door: `_flatten_circle` divided *circumference* by the chord
tolerance, which is dimensionally wrong and turned a 20 mm hole into ~12,600
points. Sagitta-based now, like `_flatten_arc` — 100 points for the same hole.

The plumbing mirrors the DXF path exactly: `read_workspace_curves` returns
points and curves index-aligned, `GdrawWorkspace` / `GdrawComponent` /
`ComponentWorkspace` carry the pair, and `derive_workspace` folds OUTLINE and
LENS into the partition's `source_curves` — mirroring the curves along with the
points when it reflects a temple. `ImportWorker` uses `import_curves`.

### The cost was the booleans, not the classification

The first diagnosis of the curved build's 8.6 s → 23.5 s was **wrong**.
Per-vertex classification is 0.06 s of it. The profile says booleans: 20 footing
clips at 10.7 s, one cut at 6.3 s, 27 fuses at 4.3 s. Planar faces intersect in
closed form; B-spline extrusions need a numerical solve, and a zone prism with
*three* curved faces costs 0.73 s against a 56-plane prism's 0.25 s.

Three things fixed it, none of them the classifier:

| change | effect |
| --- | --- |
| `_arc_edge` segments the arc off the curve | terraces 0.95 s → 0.40 s, cold 19.96 s → 16.67 s |
| `fuse_all` in one multi-tool pass, not a pairwise fold | 3.2 s → 0.35 s on terraces + ten fills |
| carves via `cut_many` | 6.2 s → 2.1 s |

Every one of them identical in volume, watertight before and after.

The segmentation is the interesting one. `MakeEdge(curve, v0, v1, ua, ub)` trims
in *parameter* but still references all 64 poles of the outline, so an extruded
zone boundary carries the whole surface with a window cut in it — and the
boolean engine and the mesher then both work on the whole surface. Cutting the
arc out first leaves 22 poles for a third of the outline. It does **not** repair
`volume()`: `BRepGProp` still reads ~17 mm³ light on the curved terraces, so
`mesh_volume` remains the referee.

Two traps recorded in the code, because both cost real time:

* OCP exposes no `Geom_BSplineCurve.DownCast_s`, so the obvious
  `Copy()` + `Segment()` route raises `AttributeError` — and `curved_ring_wire`
  falls back on *any* exception, so the first "3.6× speedup" measured was the
  polyline fallback being fast. `GeomConvert.SplitBSplineCurve_s` is the call
  that works.
* A descending parameter span must be handed to `MakeEdge` in its own order.
  Normalising it makes OCCT refuse the edge — silently, via that same fallback.

Rejected: **bounding-box pre-clipping** the zone prism to the sweep. It removes
plane faces but keeps the arcs, which are what cost, so it bought 23% while
re-cutting the very rings whose curve identity the watertight fix depends on.
**Thread-parallelising the 20 clips**: OCP holds the GIL, measured speedup 1.02×.

Demo frame, all features on: **26.7 s → 22.1 s cold, 16.7 s warm.** Bare castle
6.1 s polygonal / 13.9 s curved, 6,772 edges against 9,942.

### The rim lip is a curve too *(2026-08-07)*

With the groove on, `castle_base` builds the terraces against `lip_partition` —
the frame re-partitioned around apertures shrunk by the groove depth — and that
threw every curve away. A grooved build was polygonal however carefully the
frame was drawn, which is the case that matters most: the groove is on in the
ALL-FEATURES row, so the whole finished frame was falling back.

Two halves. The **outline and the decorative holes are untouched** by the
shrink, so their keys still match and they only ever needed passing through;
that alone is 342 of the demo body's flattened vertices against the apertures'
266, and it took the grooved build from 0% to 53% of zone vertices back on
authored curves. The **apertures are genuinely new geometry**, and for those
`geometry.curves.OffsetCurve` says *"the lens curve, 0.6 mm in"* — exact,
because the kernel has a matching `Geom_OffsetCurve`. Writing the offset down as
poles and knots is not an option: the exact offset of a B-spline is not a
B-spline, so that route means fitting, and fitting is the thing this whole
strand exists to avoid. Grooved is now **94% curved, the same as ungrooved.**

Two traps, both recorded in `_offset_aperture`:

* **The sign has to be measured.** OCCT offsets along `Z x tangent`, so which
  sign shrinks depends on the winding — and the demo frame's two lens rings wind
  opposite ways. Assume a sign and one eye grows while the other shrinks.
* **`Geom_OffsetCurve` does not trim.** Offset a 5 mm aperture inward by 9 mm
  and it sails through the centre and returns a 4 mm ring wound the other way:
  valid, simple, closed, smaller in area. Every cheap local check passes it. The
  guard is therefore comparative — the exact offset must agree in area with
  Shapely's buffer of the same ring (1%) — which catches that *and* the
  self-intersecting case without enumerating either.

### The cutters are the next bottleneck, and always were

Making the groove curved cost the demo's ALL-FEATURES build roughly 1.7x cold
and 1.3x warm, and profiling says why: **the tooling dwarfs the part.**

| group | cutters | faces | cut time (curved) |
| --- | --- | --- | --- |
| eyewire bezel | 2 | 1,440 | 4.9 s |
| lens groove | 2 | 1,080 | 5.4 s |
| brow chamfer | 2 | 2,764 | 4.4 s |
| hinge pockets | 2 | 120 | 0.9 s |

against a base solid of **937 faces**. Every one of those cutters is a
`ThruSections` loft over 180 discrete stations, so the cut is expensive *and*
inscribed — `BEZEL_STATIONS = 180` exists precisely to bound the chord error
that discretisation introduces. This is not a curve problem; the polygonal build
pays 10.7 s for the same pass.

The curve work makes the fix available: **sweep the profile along the authored
curve** instead of lofting stations around it. Prototyped on the groove —
`MakePipeShell` with the lens curve as spine and one V profile — and it gives
**3 faces instead of 540, with the cut falling from 4.9 s to 0.5 s**, watertight
and valid. It would also have *no* chord error, retiring the reason
`BEZEL_STATIONS` is 180.

Not shipped: the prototype's profile placement is not right yet (the cut differs
by ~105 mm³, and `_inward` is the wrong tool for locating it — it probes the
body, and the original contour lies *inside* the material once the aperture has
been shrunk, so both probes land in solid and the vote is meaningless). Two
further notes for whoever picks it up: `MakePipeShell` **refuses a
`Geom_OffsetCurve` spine** with `Standard_ConstructionError`, which is why the
spine must be the original lens curve with the profile placed `depth` inboard;
and the bezel cannot use a single-profile sweep at all, because it fires an
anchor ray per station to follow the footing swells.

### Still open on the curve work

1. **Swept cutters** — above. The largest remaining win, and it helps the
   polygonal path equally.
2. **Cold build is 13.9 s curved against 6.1 s polygonal** for the bare castle.
   The gap is boolean cost against B-spline extrusions. Process-level
   parallelism (shapes serialised through `BRepTools`) is the only untried lever
   that does not touch geometry — threads do not work, OCP holds the GIL.
3. **Only splines and circles come across exactly.** Arcs return None because an
   open arc is never a whole ring; if a drawing ever assembles an outline from
   arc segments, that assumption needs revisiting.

# Reference

## Module status (as of 2026-06-16, M6 complete — M6.5)

> ⚠️ **This table is stale and has actively misled at least one session.** The
> 2026-08-07 audit found it still listing `mesh/twosided.py`,
> `mesh/stl_export.py` and `io_import/svg.py` as modules to review or retire;
> all three were deleted long ago. It also predates `core/solid/`,
> `gui/mesh_build.py` and `gui/hidpi.py`. Trust the import graph
> (`vulture` + a static reachability pass) over this table; it is kept for the
> per-milestone provenance notes in the Notes column, which are still accurate
> about *when* things landed.

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
| `gui/app.py` + widgets | ✅ | Castle UI (M4); theming/dark/prefs/recent/STL (M4.5); docks + icon toolbar + progress (M4.6); CAM machine/tool selectors + strategy + feeds, machine-clamp/lint + cut-time report (M4.8); material-driven feeds + write-back prompt + Materials prefs tab (M4.9); Cut Simulation workspace (`SimWorker` + Simulate toolbar button, 3rd view) (M5); **File ▸ Save/Open Project `.gcam` + embedded-DXF retention + `set_castle_params` restore** (M5.1); **readiness traffic-light** — three flags + `_refresh_readiness`/`_invalidate_program`, green only on program-stored-to-`.gcam` (M5.2); **Generate stores the program in the project by default + File ▸ Export G-code (`Ctrl+Shift+G`) for a loose `.nc`** (post-M5.2 refinement); **Per-operation tools group; generate/sim workers wire `tools_cfg` + `tool_settings` + reach warnings + tool-change cut-time** (M6.1); **Program Zero group + `DxfCanvas.set_program_zero` datum crosshair + work-offset into the generate post + setup-sheet datum** (M6.2); **temple detection on import + `GCodeWorker._generate_temple` (engrave + profile, program-zero, temple-zone clearance) + `temple_params()`** (M6.3); **File ▸ Generate Base-Curve Block + `GCodeWorker._generate_block` + `block_params()`** (M6.4); **File ▸ Generate Worktable Program + `GCodeWorker._generate_worktable` (auto-pack frame + block, combined post, bed clearance)** (M6.5); **One mesh builder** — `gui/mesh_build.py`'s `build_component_mesh` replaces the build logic in all three of `MeshWorker` / `FlatMeshWorker` / `MultiMeshWorker`; `MultiMeshWorker` gained `solid=` + an edges slot on `built`, and `edge_cache` moved onto `ComponentWorkspace` (Stage 2 review, 2026-08-07) |
| `gui/widgets/cut_sim_view.py` | ✅ | **New (M5)** — `CutSimView` PyVista viewport: renders the simulated cut piece, Uncut/Gouge overlay toggles, pass/warn/fail badge |
| `gui/widgets/readiness_dot.py` | ✅ | **New (M5.2)** — status-bar `ReadinessDot` (painted ~10 px circle, theme-recolored, exact tooltips) + the pure `state_for(...)` state machine |
| `gui/material_store.py` | ✅ | **New (M4.9)** — shipped + user-override material presets (`~/.guildcam/materials.yaml`); `effective`/`cam_values`/`changed_keys`/`save_override`/`reset_material` |
| `gui/icons.py` | ✅ | M4.6 — `_make_icon` port (SVG→two-state QIcon) + `apply_toolbar_icons`; text fallback; `sim-cut` icon added (M5) |
| `gui/style/theme.py` `gui/prefs.py` | ✅ | M4.5 — GuildDraw QSS + CanvasPalette; `~/.guildcam/prefs.json` (M4.6 window state; M4.8 `cam_params`; M4.9 `material_name`) |
| `gui/mesh_build.py` | ✅ | **New (Stage 2 review, 2026-08-07)** — the single Qt-free `build_component_mesh(spec, resolution, solid)` → `(mesh, edges, core_guide)` every mesh worker delegates to; the solid branch reaching `MultiMeshWorker` is what un-broke the display-mode dropdown |
| `tests/` | ✅ | **715 green** (incl. STL/NC/silhouette/arc/ramp/budget/clamp/completeness gates + the `.gcam` round-trip + the readiness state machine + the M6.1–M6.5 per-op-tool/change-block/reach/datum-offset/temple-engrave/block-drill/bed-schedule gates + **`test_worktable_cut_parity.py`**: the bed program is the single-component program *placed* — one posting grid (`CUT_RES_MM`), one machine clamp, Z untouched by placement, and a bounded Z-reversal density per 100 mm of travel; see the 2026-07-29 safety fix) |

## Dependency list (v1 — unchanged)

`pyside6`, `pyvista`, `pyvistaqt`, `numpy`, `scipy`, `shapely`, `pyclipper`,
`ezdxf`, `svgelements`, `trimesh`, `pydantic`, `pyyaml`, `pytest`,
`pyinstaller`. **Excluded by design:** OpenCASCADE, CadQuery, build123d,
OpenCAMLib.

## Repo structure (target — unchanged from the spike, plus docs/)

```
guildcam/
├── BUILDPLAN.md                # this file
├── DEMO_PROJECT_TEARDOWN.md    # behavioural spec — local only, not published
├── OLGA_TEARDOWN_AND_PLAN.md   # OLGA reverse-engineering — local only, not published
├── Demo Project/               # local ground-truth set (subset vendored in tests/fixtures/demo/)
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
