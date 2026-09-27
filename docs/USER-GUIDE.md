# GuildModel User Guide (v1.8.0)

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

**File ▸ Open Drawing (Ctrl+O)** opens a GuildDraw `.gdraw`. The whole
model comes in as one project, with one tab per component: **Frame Front**,
**Temple R / L**, and a derived **Base Curve R / L** template per lens. A
**Worktable** tab follows them.

A component you never drew shows as a disabled tab.

Each tab keeps its own parameters, model, program and readiness state. You can
switch tabs freely, because nothing is lost.

**File ▸ Open DXF (Ctrl+Shift+O)** opens a single frame front exported as DXF.
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

**Hinge pocket angle** tilts the floor of the hinge pockets to change the
pantoscopic tilt at the hinge. The superior edge of each pocket stays at the
pocket depth; a positive angle makes the inferior edge deeper, and a negative
angle makes it shallower. At 0° the floor is flat. The slider stops where
either edge would come out of the surface or get closer than 0.5 mm to the
anterior face.

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

### Export STL

**File ▸ Export STL (Ctrl+E)** writes the component you are looking at.
**File ▸ Export All STL (Ctrl+Shift+E)** asks for a folder and writes every
component that can be built — the frame front, both temples and each base-curve
template — one file each, named for the component. A drawing with more than two
lens curves makes more than two templates, and those are numbered.

Export always rebuilds at the **export resolution** in Preferences, never from
what the 3D view happens to be showing. The frame front is written by whichever
model kernel is selected; a temple and a base-curve template are flat parts, so
they are built exactly and the resolution setting does not apply to them.

The log reports each file's triangle count, volume and verdict as it is written,
along with anything wrong with it — including a mounting hole that will not fit
the lens it is drilled into. You get the file either way: a warning tells you
what you are holding, it does not withhold it.

### The formed front — printing a prototype

A front is cut flat and formed afterwards: the **base curve** is molded into
each rim on the press, the **face form** is the angle between the two eyewire
planes at the bridge center line, and the **bridge** is projected at the bench,
where a convex die pressed against the back of the frame, with a V-shaped
plate bracing the front, leaves the classic crease along the plate's edges and
the bulbous bump between them. **View ▸ Forming (F)** shows the front that way,
in the same 3D view, so a prototype can be printed and put on a face before any
acetate is cut.

Press **F** on a built frame front and a panel opens under the view:

- **Press** — *Flat*, the SBT press rows, your own presses, or *Custom*. A row
  sets the base curve and the face form together, because on the press they
  come as a pair. Touching either slider makes the choice *Custom*.
- **Base curve** — the lens base curve in diopters, 0 to 16 in the quarter
  steps a frame is ordered in, the way the forms are tagged. 0 is flat. On a
  press row the die's own radius is used; anywhere else the optical
  convention, 530 / D. The radius in use is shown beside the slider.
- **Face form** — the included angle at the bridge, as the press states it;
  180° is flat and the wrap beside it is 180° minus that.
- **Bridge projection** — how far the die sets the bridge forward, away from
  the face, in millimeters. The die only presses forward; 0 leaves the bridge
  in the curve.
- **Crease gap** — the distance between the two creases at the bridge's top
  edge: the width of the V plate. Seeded from the drawing's own bridge width.
- **Crease angle** — the V's included angle, seen from the front: how fast the
  creases converge toward the nose. 0° keeps them parallel.
- **Bridge offset** — the V's center line left or right of the frame's axis,
  for a bridge that is not drawn centered.
- **Die radius** — the radius of the anvil's convex face that presses the
  posterior bridge. Between the die and each crease the sheet runs straight,
  tangent to the die, so a small die gives a defined bulge with flat flanks
  and a large one a broad bow. *Auto* is the largest die that still reaches
  the projection through the gap — the arc through both creases — and its
  radius is shown beside the slider. A die wider than that rests on the V
  plate before it reaches the projection; the readout says how far it got.
  Where the V narrows toward the nose the die rests on the plate's edges
  and the bump shrinks with it. A die shallower than the projection sets the
  bridge only as deep as its own radius.
- **Crease blend** — *Sharp* leaves the fold the plate's edge makes; a radius
  rounds it into the flat on both sides of each crease, as a softened plate
  edge or a relaxed sheet would.
- **Eyewire groove** — on by default. The formed front is built with the lens
  bevel groove whether or not the Model tab has it on, at the Model tab's
  groove dimensions, because the printed part is the finished piece.
- **Show flat ghost** — the flat part, translucent, under the formed one.

The sliders are live: the handle moves and the front bends, with no progress
dialog. The strip label carries the press and the numbers — **FORMED · SBT
base 4 · 4.00 D · 164° · +4 mm** — and the panel reads out the formed size and
where the bridge lands. Every display mode, camera preset, the section plane
and the turntable work on the formed front, because it is simply another
mesh. The stock ghost and the program zero are hidden while forming is on;
they belong to the flat part on the fixture.

At a steep base curve the two rims, each curved about its own lens center,
force a reverse bend at the bridge; when that bend is tighter than the part is
thick the preview folds through itself there, and the readout and the log say
so rather than draw it as a part. Ease the base curve or the face form.

The creases are cut into the mesh before it is formed, so each is a clean
edge rather than a zigzag between triangles, and the bridge band is meshed
finely (0.5 mm on screen, 0.25 mm in the file) against the rims' 3 mm and
1.5 mm. Dragging the crease gap, angle, offset or blend moves the cut, so
those four handles show the uncut front while they move and re-cut it on
release; the base curve, face form, projection and die stay live throughout.

**Export Formed STL…** (on the panel, and under File) writes
`frame_front_formed.stl`: a fresh build at export resolution with the groove,
refined to 1.5 mm outside the bridge and 0.25 mm in it, cut along the creases,
welded at the file's own float32 precision so a slicer reads one closed body,
formed, and verified by the same check that gates every export. **Export All
STL** adds the formed file whenever the project's forming is not flat, so a
print job is one folder.

Forming is a way of looking at the model, not a change to it. The cut model
does not change, no program is generated for a formed front, the readiness dot
ignores forming entirely, and the forming values are saved with the component
in the `.gmodel` — a drawing that carries none opens flat.

Your own presses go in `~/.guildmodel/presses.yaml`, one row per die, tagged
with its lens base curve; give `radius_mm` when you know the die's own radius:

```yaml
Bench die 6:
  base_curve: 6.0
  radius_mm: 88.0
  face_form_deg: 158.0
```

A row with a shipped label replaces it; `{_deleted: true}` hides one.

## 3. Temples and base-curve blocks

**Temple.** The outline extruded on the blank, with hinge blind-pockets from
the `HINGE` layer and engraving grooves from `ENGRAVING`. The hinge end snaps
to the 170×30 blank edge. The injected-core bar shown in 3D is a visual guide
only. Program: Hinge Pockets → Engraving → Holes → Temple Profile. The Holes
operation appears only when the drawing has decorative openings in the outline.

The Temple tab sets the **Hinge pocket depth** and the **Hinge pocket angle**.
The angle tilts the pocket floor along the temple to offset splay built into
a hinge. The anterior edge, nearer the hinge end, stays at the pocket depth; a
positive angle makes the posterior edge deeper.

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
beside it, and so do your presses (`presses.yaml`, §2).

## 9. Files and data safety

- **`.gmodel` is self-contained.** The embedded drawing means a project reopens
  identically, even if the original `.gdraw` moved.
- **Autosave** snapshots unsaved work every 3 minutes to
  `~/.guildmodel/autosave/`. After a crash or a power cut, the next launch
  offers to restore it. Recovered work reopens against your original project
  file, marked unsaved. A clean close clears the snapshot.
- **Frame-style presets** (in Preferences and on the Info tab) recall a house
  style's parameters in one click.

## 10. Default shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Open Drawing (.gdraw) |
| Ctrl+Shift+O | Open DXF |
| Ctrl+S | Save Project |
| F5 | Build 3D Model |
| Ctrl+G | Generate G-code |
| Ctrl+Shift+G | Export G-code (.nc) |
| Ctrl+E | Export STL |
| Ctrl+Shift+E | Export All STL |
| Ctrl+Shift+S | Simulate the cut |
| M | Measure |
| Ctrl+B | Worktable |
| Ctrl+0 | Fit to View |
| Alt+T | Turntable (3D views) |
| F | Forming (frame front) |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit |

Every row is rebindable in Preferences ▸ Hotkeys except the last two; Ctrl+,
and Ctrl+Q are fixed.
