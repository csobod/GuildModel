# GuildModel User Guide (v1.0.0-rc1)

GuildModel turns a GuildDraw drawing into cut-ready CNC programs. It is the
middle of the Guild toolchain: **GuildDraw** (design) → **GuildModel** (CAM) →
**GuildSend** (machine control). You open the drawing, tune how each part is
modeled and cut, verify the result in simulation, and hand the finished job to
GuildSend.

**Where things stand:** the frame-front workflow is hardware-proven end-to-end
(real acetate on a Carbide 3D Nomad). The temple, base-curve-block, and
worktable-nesting paths are fully built and verified in cut simulation but not
yet hardware-validated — air-cut them first, then cut a test piece.

## 1. Opening your design

**File ▸ Open Drawing (Ctrl+Shift+O)** opens a GuildDraw `.gdraw`. The whole
model comes in as one project: a tab per component — **Frame Front**,
**Temple R / L**, and a derived **Base Curve R / L** template per lens — plus a
trailing **Worktable** tab. Empty components (a temple you never drew) show as
disabled tabs. Each tab keeps its own parameters, 3D model, program, and
readiness state; switching tabs never loses anything.

**File ▸ Open DXF (Ctrl+O)** opens a single frame front exported as DXF. The
layers GuildModel reads: `OUTLINE` (the frame profile), `LENS` (two apertures),
`HINGE`, `SCULPT` (the 5-cuts-per-side castle layout), `ENGRAVING`, `BRIDGE`,
and `REF` (display only). A DXF with an outline and no lenses is treated as a
temple. Boxing dimensions (ISO 8624 A / B / DBL / ED) are measured from the
lens polygons on import and shown on the Info tab.

**Projects.** **File ▸ Save Project (Ctrl+S)** writes a `.gmodel` — a single
self-contained file holding the drawing, every component's parameters, the
tagged worktable, and any generated programs with their setup sheets.
Reopening it restores the whole session. Generated programs are folded into an
open project automatically; the title bar shows a `*` while anything is
unsaved, and closing (or opening another file) with unsaved work asks
Save / Discard / Cancel.

## 2. The frame front — building the castle

GuildModel models the posterior relief the way a maker carves it: the
**castle**. Towers (endpieces, bridge, nosepads) stand at their set heights,
the eyewire walls run between them, and rolling-ball footing fillets ease every
wall into the floor.

The sidebar shows what the active component needs: for a frame front —
**Info · Model · Stock · Cut · Machine**.

- **Model** — per-zone tower heights, footing radius, hinge-pocket depth, and
  the optional posterior finishing features: pad-splay chamfer, bezeled
  eyewire, and bridge projection relief (all off by default).
- **Lens Bevel Groove** (off by default) — the drageoir V-groove in each
  eyewire wall that seats the lens bevel. You set the apex height from the
  anterior face and the groove's depth and width (the included angle shows
  read-only — the shipped 5.5 mm *fraise drageoir* form is ≈106°). GuildModel
  handles the geometry automatically: the visible aperture is cut smaller by
  the groove depth so the groove bottom lands exactly on your drawn LENS
  contour (the boxed size stays honest), and the eyewire channel is widened
  so the grooving tool's head can descend and feed sideways into the rim.
  The groove appears in the 3D model and the exported STL, adds a "Lens
  Groove" operation between Eyewires and Perimeter, and needs a groove-type
  form cutter in the tool library.
- **Stock** — blank dimensions and the pad block.
- **Build 3D** builds every loaded component's model in one pass (each tab
  caches its own mesh). The view strip has camera presets (Iso / Top / Front /
  Reset), the castle **stage stepper** (towers → walls → footing → full), a
  **measure** tool (click two snapped points for distance/angle), and a 3D
  section plane. Parameter edits rebuild the mesh live without resetting your
  zoom.

## 3. Temples and base-curve blocks

- **Temple** — the outline extruded on the blank, hinge blind-pockets from the
  `HINGE` layer, and engraving grooves from `ENGRAVING`. The hinge end snaps
  to the 170×30 blank edge; the injected-core bar shown in 3D is a visual
  guide only. Program: Hinge Pockets → Engraving → Profile.
- **Base-curve block** — the heat-forming template: the lens shape cut from a
  70×70 acetal blank with three M4 through-holes (they double as the fixture's
  mounting screws). Program: Drill Holes → Block Profile.

## 4. Cut settings

The **Cut** tab is the everyday surface: pick the **material** (acetate,
acetal, …) and its feeds, speeds, stepover, and stepdown seed automatically. A
**chip-load** read-out shows green / amber / red against the material's window
so you can see a bad feed-rpm-tool combination before cutting. If you tune
values away from the material defaults, GuildModel offers to save them back as
your new defaults.

The **Machine** tab is setup: the machine profile (Guild CNC, Nomad 3,
Shapeoko, generic GRBL), **program zero** (default center/center/bottom — the
datum crosshair shows on the 2D canvas), per-operation tool assignments for
multi-tool jobs, cut strategy, and the no-SCULPT profile fallback.

**Tools** live in Preferences ▸ Tools — an editable library (add, duplicate,
edit, import/export) with a live cross-section preview. Every tool selector in
the app draws from it. GuildModel warns when a cut is deeper than a tool's
flute length.

## 5. Generate and verify

**File ▸ Generate G-code** posts the active component's program. The 2D view
overlays the toolpaths color-coded per operation (dashed = rapids), with a
per-op table — check a row to show/hide it, click to highlight; totals show
cut length and estimated time. Machine limits are linted (envelope, feed,
spindle, arcs) and reach warnings are reported.

The **readiness dot** in the status bar tracks the job: red = design loaded,
amber = model built, green = the program is stored in the saved `.gmodel`.

**Simulation (Ctrl+Shift+S)** machines the program into a virtual blank and
verifies the result against the target: **Uncut** highlights material left
proud, **Gouge** highlights cuts below target, and the badge gives a
✓ / ⚠ / ✕ verdict. The playback scrubber replays the cut op by op — play/pause
(▶), drag to any boundary, and watch the moving tool; playback pauses with a
warning if the tool would foul a hold-down.

**File ▸ Export G-code (Ctrl+Shift+G)** writes a loose `.nc` when you want a
bare file; the program also always lives inside the saved project.

## 6. The worktable — cutting the whole model in one setup

The **Worktable** tab is the machine bed. Import your bed as a DXF (each
closed region becomes a zone), or load the Guild standard bed. Click a region
and tag its role: frame-front, temple R/L, base-curve R/L, or keep-out.

**Nest Components** places every populated component onto a matching zone.
Drag a footprint to nudge it; rotate with the angle spinbox; a live clearance
badge flags collisions with keep-outs and screws (red outline on the bed).
Set the bed's own program zero and hold-down height on the panel.

**Generate Worktable Program** folds the whole nest into ONE `worktable.nc`,
scheduled to minimise tool changes across the bed while respecting each
part's operation order. **Simulate Bed** runs the full-bed cut sim and
composites every placement into one verdict.

## 7. Sending the job

Save the project (Ctrl+S) and open the `.gmodel` from GuildSend's
**File ▸ Open Job** (or double-click it, if GuildSend owns the association on
your machine). Everything travels in the one file — programs, setup sheet,
tools, material, and the tagged worktable — so GuildSend can name the
placements on its bed view and adopt the matching machine profile.

Prefer a bare file? **File ▸ Export G-code** writes a standalone `.nc` that
any sender can run.

## 8. Preferences & customization

**Settings ▸ Preferences… (Ctrl+,)** — the same shortcut across the Guild
apps:

- **General** — log panel on startup, 3D preview / STL export resolution,
  default output folder.
- **Appearance** — dark mode; viewport presets (Parchment, Dimmed, Blueprint,
  Matte Dark, Plain White, or a custom canvas color) that pin the canvas and
  3D backdrop in both UI modes; the 3D light rig (Studio / Directional / Flat
  with direction and intensity); model surface color; toolpath-overlay
  palettes; and the 2D **grid** (visibility, spacing, a heavier major line
  every Nth, colors).
- **Layers** — your own drawing color per design layer, per UI mode.
- **Materials** — the material presets and your overrides.
- **Tools** — the tool library (§4).
- **Hotkeys** — rebind any listed action; conflicts are flagged.
- **Toolbar** — choose and order the toolbar buttons.

Preferences, window layout, and recent files persist in
`~/.guildmodel/prefs.json`; material, tool, and frame-style overrides live
beside it.

## 9. Files & data safety

- **`.gmodel`** is self-contained: the embedded drawing means a project
  reopens identically even if the original `.gdraw` moved.
- **Autosave** snapshots unsaved work every 3 minutes to
  `~/.guildmodel/autosave/`. After a crash or power cut, the next launch
  offers to restore it — recovered work reopens against your original project
  file, marked unsaved. A clean close clears the snapshot.
- Frame-style presets (Preferences and the Info tab) let you recall a house
  style's parameters in one click.

## 10. Fixed shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Open DXF |
| Ctrl+Shift+O | Open Drawing (.gdraw) |
| Ctrl+S | Save Project |
| Ctrl+Shift+G | Export G-code (.nc) |
| Ctrl+Shift+S | Simulate the cut |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit |

Everything else is rebindable in Preferences ▸ Hotkeys.
