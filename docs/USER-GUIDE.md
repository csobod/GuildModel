# GuildModel User Guide (v1.6.0)

GuildModel turns a GuildDraw drawing into cut-ready CNC programs. It is the
middle of the Guild toolchain: **GuildDraw** (design) → **GuildModel** (CAM) →
**GuildSend** (machine control).

You open a drawing, set how each part is modeled and cut, verify the result in
simulation, then hand the finished job to GuildSend.

**Where things stand.** The frame-front workflow is hardware-proven end to end,
in real acetate on a Carbide 3D Nomad. The temple, base-curve-block and
worktable-nesting paths are fully built and verified in cut simulation, but not
yet cut on real stock. Air-cut them first, then cut a test piece.

## 1. Open your drawing

**File ▸ Open Drawing (Ctrl+Shift+O)** opens a GuildDraw `.gdraw`. The whole
model comes in as one project, with one tab per component: **Frame Front**,
**Temple R / L**, and a derived **Base Curve R / L** template per lens. A
**Worktable** tab follows them.

A component you never drew shows as a disabled tab.

Each tab keeps its own parameters, model, program and readiness state. You can
switch tabs freely, because nothing is lost.

**File ▸ Open DXF (Ctrl+O)** opens a single frame front exported as DXF.
GuildModel reads these layers:

| Layer | Contents |
|---|---|
| `OUTLINE` | the frame profile |
| `LENS` | two apertures |
| `HINGE` | hinge pockets |
| `SCULPT` | the castle layout, 5 cuts per side |
| `ENGRAVING` | engraving grooves |
| `BRIDGE` | the bridge |
| `REF` | display only |

A DXF with an outline and no lenses opens as a temple. GuildModel measures the
boxing dimensions (ISO 8624 A / B / DBL / ED) from the lens polygons on import
and shows them on the Info tab.

**Projects.** **File ▸ Save Project (Ctrl+S)** writes a `.gmodel`. This one
file holds the drawing, every component's parameters, the tagged worktable, and
each generated program with its setup sheet. Reopen it to restore the whole
session.

GuildModel folds a generated program into the open project for you. The title
bar shows a `*` while any work is unsaved. If you close the project, or open
another file, with unsaved work, GuildModel asks Save / Discard / Cancel.

## 2. The frame front

GuildModel models the posterior relief the way a maker carves it: as the
**castle**. Towers (endpieces, bridge, nosepads) stand at their set heights.
The eyewire walls run between them. Rolling-ball footing fillets ease every
wall into the floor.

The sidebar shows what the active component needs. A frame front has
**Info · Model · Stock · Cut · Machine**.

### The Model tab

The Model tab sets the per-zone tower heights, the footing radius and the
hinge-pocket depth. Below them are the posterior finishing features, all off by
default: the pad-splay chamfer, the bezeled eyewire and the bridge relief.

**Pad splay ▸ Non-contiguous** is for a **keyhole bridge**. A splay run through
bottom-center planes the keyhole's shape straight off. Tick this box and set
the **Center gap** — the total uncut width, split evenly either side — to start
each half of the cut clear of the keyhole. Both halves keep the same crest,
angles and feathering, and stay mirror images.

**Pad splay ▸ End feather** sets how far the cut runs out to nothing at **every**
end of the run, including the two inner ends that face the keyhole. The chamfer
keeps its angle and lifts out of the surface over this distance, so the cut
narrows away. Set it to 0 and the cut ends in a wall. That is occasionally what
you want, and it is never an accident.

**Bridge relief ▸ Exterior / Interior radius** set the shape of the U, in the
same language as the footing. The exterior radius is the convex round-over
where the scoop leaves the bridge face. The interior radius is the concave
fillet at the bottom of the trough. A straight wall joins them.

A note under the sliders gives the resulting wall angle. It also tells you when
the width and depth you have set cannot carry the radii you asked for, and
reduces both in proportion. An interior radius of 0 is a sharp V. That is
legitimate, but no ball tool can finish it.

### Edge features — a chamfer or a fillet on part of an edge

**Edge Features** is a list on the Model tab. Each entry is one **run**: a
chamfer or a round-over along part of one edge. Use **+ Add**, **Duplicate**
and **Remove** to manage the list. The editor below the list sets the selected
run.

This exists for the shape a constant band cannot make — the **anterior brow
chamfer**, over each eyewire, stopping short of the bridge. The eyewire bezel
runs all the way round a ring, so it cannot stop at the nose.

**Anterior runs are modeled and shown in 3D only.** Machining the front face
needs the flip setup, which is a later release. Posterior runs cut normally.

The controls, in the order they appear:

| Control | What it does |
|---|---|
| **Name** | your own label for the list |
| **Face** | Anterior (front) or Posterior (back) |
| **Edge** | Outline, Lens OD or Lens OS |
| **Spans zones** | the castle zones the run covers. Select none to run the whole edge |
| **Profile** | Chamfer or Fillet (round-over) |
| **Width** | how far in from the edge the chamfer runs |
| **Width at end** | the width at the far end, to taper the run along its length. *(constant)* keeps one width throughout |
| **Angle** | the chamfer angle |
| **Fillet radius** | the radius, for the Fillet profile |
| **Trim start / Trim end** | move each end along the edge. Positive pulls the end in, negative pushes it out |
| **Blend** | the distance over which the cut tapers to nothing at each end |
| **Min thickness** | GuildModel never cuts the frame thinner than this where the run passes |
| **Mirror to the other side** | also cut the matching run on the opposite side (OD ↔ OS) |

**Name the span by zone, not by distance.** The zone list holds the castle's own
names — `endpiece_od`, `eyewire_superior_od`, `bridge`, `nosepad_os` and the
rest. Leave `bridge` out of the selection, and a brow chamfer keeps off the
nose. Zone names survive a re-imported drawing, so a run still covers the brow
after you tweak the shape.

**A run with no zones selected goes all the way round, and has no ends.** Trim
start and Trim end are how you give it two real ends. Each end then gets the
taper set by Blend. This is the way to turn a round-over that circles the whole
edge into one that starts and stops where you want.

**Keep Mirror on for a pair.** The brow chamfer is always a pair, and one
mirrored feature is one edit instead of two.

> **Caution — a sharp corner can fold the cut.** Where a run passes a corner
> that turns tighter than the feature is deep, the swept cut can cross itself.
> The model then does not build, and both the log and the Inspector report that
> the model overlaps itself along N edges. To clear it, trim the run past the
> corner, or ease the corner in the drawing. **Read the log after a rebuild**,
> because a program you have already stored keeps the readiness dot green on
> its own.

### Lens bevel groove

The **Lens Bevel Groove** is off by default. It is the drageoir V-groove in each
eyewire wall that seats the lens bevel. Set the apex height from the anterior
face, and the groove's depth and width. The included angle is read-only: the
shipped 5.5 mm *fraise drageoir* form is ≈106°.

GuildModel handles the geometry for you. It cuts the visible aperture smaller
by the groove depth, so the groove bottom lands exactly on your drawn `LENS`
contour and the boxed size stays honest. It also widens the eyewire channel, so
the grooving tool's head can descend and feed sideways into the rim.

The groove appears in the model and in the exported STL. It adds a **Lens
Groove** operation between Eyewires and Perimeter, and it needs a groove-type
form cutter in the tool library.

### Stock and Build 3D

The **Stock** tab sets the blank dimensions and the pad block.

**Build 3D** builds every loaded component's model in one pass, and each tab
caches its own model. The view strip carries:

- camera presets — Iso / Top / Front / Reset
- the castle **stage stepper** — towers → walls → footing → full
- a **measure** tool — click two snapped points for a distance or an angle
- a 3D section plane

A parameter edit rebuilds the model live and keeps your zoom.

## 3. Temples and base-curve blocks

**Temple.** The outline extruded on the blank, with hinge blind-pockets from
the `HINGE` layer and engraving grooves from `ENGRAVING`. The hinge end snaps
to the 170×30 blank edge. The injected-core bar shown in 3D is a visual guide
only. Program: Hinge Pockets → Engraving → Holes → Temple Profile. The Holes
operation appears only when the drawing has decorative openings in the outline.

**Base-curve block.** The heat-forming template: the lens shape cut from a
70×70 acetal blank, with three M4 through-holes that double as the fixture's
mounting screws. Program: Drill Holes → Block Profile.

## 4. Cut settings

The **Cut** tab is the everyday surface. Pick the **material** — acetate,
acetal and the rest — and its feeds, speeds, stepover and stepdown seed
themselves. A **chip-load** read-out shows green / amber / red against the
material's window, so you can see a bad feed-rpm-tool combination before you
cut. Tune the values away from the defaults, and GuildModel offers to save them
back as your new defaults.

The **Machine** tab is setup. It holds:

- the machine profile — Guild CNC, Nomad 3, Shapeoko or generic GRBL
- **program zero** — center/center/bottom by default. The datum crosshair shows
  on the 2D canvas.
- the per-operation tool assignments, for multi-tool jobs
- the cut strategy
- the no-`SCULPT` profile fallback

**The Features operation.** The posterior finishing features cut in their own
**Features** operation, so they can take their own tool. The everyday job is a
**ball nose** for the chamfers and scoops, and an end mill for everything else —
the hinges, the footing and the posterior sculpting. Left at *(same as Tool)*
it follows Fine Relief, which is what cut these features before they became a
separate operation.

GuildModel warns you when the assigned tool cannot finish a feature, and names
one from your library that fits. A flat leaves a lip at every chamfer toe, and
a ball larger than the bridge relief's interior radius bridges its trough.

**Keep the ball off the terraces.** The reverse assignment — a ball nose on
Rough or Fine Relief — cuts a complete part but a poor program: a ball rolls
down every terrace wall a flat glides over, leaves scallop ridges on the flat
terraces a flat cuts dead flat, and the resulting Z-heavy motion will trip the
Z-profile check on export. GuildModel says so in the Inspector the moment the
assignment is made. Flat tools for the terraces, the ball for Features.

**Tools** live in Preferences ▸ Tools. The library is editable — add,
duplicate, edit, import and export — and shows a live cross-section preview.
Every tool selector in the app draws from it. GuildModel warns you when a cut
is deeper than a tool's flute length.

## 5. Generate and verify

**File ▸ Generate G-code** posts the active component's program. The 2D view
overlays the toolpaths, color-coded per operation, with rapids dashed. The
per-op table beside it shows the totals for cut length and estimated time.
Check a row to show or hide it, and click a row to highlight it. GuildModel
lints the program against the machine limits — envelope, feed, spindle and arcs
— and reports any reach warnings.

The **readiness dot** in the status bar tracks the job:

| Dot | Meaning |
|---|---|
| red | the drawing is loaded |
| amber | the model is built |
| green | the program is stored in the saved `.gmodel` |

**Simulation (Ctrl+Shift+S)** machines the program into a virtual blank and
verifies the result against the target. **Uncut** highlights material left
proud, **Gouge** highlights cuts below target, and the badge gives a ✓ / ⚠ / ✕
verdict.

The playback scrubber replays the cut, operation by operation. Use play/pause
(▶), drag to any boundary, and watch the moving tool. Playback pauses with a
warning if the tool would foul a hold-down.

**File ▸ Export G-code (Ctrl+Shift+G)** writes a loose `.nc` when you want a
bare file. The program also always lives inside the saved project.

**Turntable (Alt+T)** is the record button on the 3D viewer's strip, beside the
camera presets, with a speed slider next to it. It spins the part about **the
view you have set up**, not about a fixed world axis.

Tip the frame the way you want to look at it, then start the turntable. It
turns on that axis, so a surface runs past the light. You no longer have to drag
back and forth over it.

The turntable works in the cut simulation too. It parks itself while you are on
another view, so you do not have to re-arm it when you come back.

## 6. The worktable — cut the whole model in one setup

The **Worktable** tab is the machine bed. Import your bed as a DXF, where each
closed region becomes a zone, or load the Guild standard bed. Click a region
and tag its role: frame-front, temple R/L, base-curve R/L, or keep-out.

**Nest Components** places every populated component onto a matching zone. Drag
a footprint to nudge it, and rotate it with the angle spinbox. A live clearance
badge flags collisions with keep-outs and screws, and outlines them in red on
the bed. Set the bed's own program zero and hold-down height on the panel.

**Generate Worktable Program** folds the whole nest into one `worktable.nc`. It
schedules the bed to minimize tool changes, and respects each part's operation
order. **Simulate Bed** runs the full-bed cut simulation and composites every
placement into one verdict.

## 7. Send the job

Save the project (Ctrl+S), then open the `.gmodel` from GuildSend's
**File ▸ Open Job**. You can also double-click the file, if GuildSend owns the
association on your machine.

Everything travels in the one file — the programs, the setup sheet, the tools,
the material and the tagged worktable. GuildSend can therefore name the
placements on its bed view, and adopt the matching machine profile.

If you prefer a bare file, **File ▸ Export G-code** writes a standalone `.nc`
that any sender can run.

## 8. Preferences and customization

**Settings ▸ Preferences… (Ctrl+,)** — the same shortcut across the Guild apps.

- **General** — the log panel on startup, the 3D preview and STL export
  resolution, and the default output folder.
- **Appearance** — dark mode; the viewport presets (Parchment, Dimmed,
  Blueprint, Matte Dark, Plain White, or a custom canvas color) that pin the
  canvas and 3D backdrop in both UI modes; the 3D light rig (Studio /
  Directional / Flat, with direction and intensity); the model surface color;
  the toolpath-overlay palettes; and the 2D **grid** — visibility, spacing, a
  heavier major line every Nth, and colors.
- **Layers** — your own drawing color per design layer, per UI mode.
- **Materials** — the material presets and your overrides.
- **Tools** — the tool library (§4).
- **Hotkeys** — rebind any listed action. GuildModel flags conflicts.
- **Toolbar** — choose and order the toolbar buttons.

Your preferences, window layout and recent files persist in
`~/.guildmodel/prefs.json`. The material, tool and frame-style overrides live
beside it.

## 9. Files and data safety

- **`.gmodel` is self-contained.** The embedded drawing means a project reopens
  identically, even if the original `.gdraw` moved.
- **Autosave** snapshots unsaved work every 3 minutes to
  `~/.guildmodel/autosave/`. After a crash or a power cut, the next launch
  offers to restore it. Recovered work reopens against your original project
  file, marked unsaved. A clean close clears the snapshot.
- **Frame-style presets** (in Preferences and on the Info tab) recall a house
  style's parameters in one click.

## 10. Fixed shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Open DXF |
| Ctrl+Shift+O | Open Drawing (.gdraw) |
| Ctrl+S | Save Project |
| Ctrl+Shift+G | Export G-code (.nc) |
| Ctrl+Shift+S | Simulate the cut |
| Alt+T | Turntable (3D views) |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit |

Everything else is rebindable in Preferences ▸ Hotkeys.
