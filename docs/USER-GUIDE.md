# GuildModel User Guide (v2.0.0)

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
model comes in as one project, with one tab per part: **Frame Front**,
**Temple R / L**, and a derived **Base Curve R / L** template per lens. A
**Worktable** tab follows them.

A part you never drew shows as a disabled tab.

**The Ghost.** GuildDraw's Ghost is a drawing aid, and GuildModel reads only
the curves you drew. Bake the mirror (Mirror (bake)) before you open a front
drawn as a half; a front left with one rim and one lens is a monocle.

**The guides.** A new project sizes each blank from the stock guide the
drawing was made against: the front's blank and pad block, and each temple's
blank. The thickness stays your default. A drawing without guides uses your
defaults (Preferences ▸ Parts), and a reopened or reloaded project keeps its
own sizes.

Each tab keeps its own parameters, model, program and readiness state. You can
switch tabs freely, because nothing is lost.

A drawing, project or DXF dragged from the file manager onto the window opens
as the menu would. When a drawing opens, GuildModel builds the frame front and
shows it in 3D; the temples and blocks are built the first time you visit
their tab in the 3D view, so a walk through the tabs stays in 3D. Preferences
▸ General turns the build on open off. The view you chose on a part is
kept across a visit to the Worktable. The 2D view of the front is the back of
the frame, mirrored from the drawing, and its caption says so.

**File ▸ Reload Drawing (Ctrl+R)** re-reads the open drawing from disk after
you save it again in GuildDraw. Every part keeps its parameters, cut settings,
program zero, forming values, worktable switch and placement; the geometry is
re-derived, and the models and programs, which described the old drawing, are
dropped. While a drawing is open GuildModel watches the file: when it changes,
a chip in the status bar reads *drawing changed · reload*, and clicking it
reloads. Nothing interrupts you.

**File ▸ Open DXF (Ctrl+Shift+O)** opens a single frame front exported as DXF.
GuildModel reads these layers:

| Layer | Contents |
|---|---|
| `OUTLINE` | the frame profile |
| `LENS` | two apertures |
| `COMPONENT` | pockets for what mounts on the back: hinges, bridges, endpieces, bridge bars |
| `SCULPT` | the castle layout, 5 cuts per side |
| `ENGRAVING` | engraving grooves |
| `INLAY` | seats for plaques and plates (§2, *Seats and plaques*) |
| `BRIDGE` | the bridge |
| `REF` | display only |

A drawing made before 2.0 says `HINGE` for the `COMPONENT` layer, and
GuildModel reads it as `COMPONENT`. GuildDraw's component tab was its Hinge
tab, and that is read too.

A DXF with an outline and no lenses opens as a temple. GuildModel measures the
boxing dimensions (ISO 8624 A / B / DBL / ED) from the lens polygons on import
and shows them on the Info tab.

**Projects.** **File ▸ Save Project (Ctrl+S)** writes a `.gmodel`. This one
file holds the drawing, every part's parameters, the tagged worktable, and
each generated program with its setup sheet. Reopen it to restore the whole
session. A value in the file that is out of range (a number that is not one,
an infinity, or a negative where none is possible) is set to its default as
the file opens, and the log names each value it set.

GuildModel folds a generated program into the open project for you. The title
bar shows a `*` while any work is unsaved. If you close the project, or open
another file, with unsaved work, GuildModel asks Save / Discard / Cancel.

## 2. The frame front

GuildModel models the posterior relief the way a maker carves it: as the
**castle**. Towers (endpieces, bridge, nosepads) stand at their set heights.
The eyewire walls run between them. Rolling-ball footing fillets ease every
wall into the floor.

The sidebar shows what the active part needs. A frame front has
**Info · Model · Stock · Cut · Machine**. Every section on every tab folds
under its header with a click; GuildModel remembers which you folded.

### The Model tab

The Model tab sets the per-zone tower heights, the footing radius and the
**Component depth**, the depth of the component pockets. Below them are the
posterior finishing features, all off by default: the pad-splay chamfer, the
bezeled eyewire and the bridge relief.

**Hinge pocket angle** tilts the floor of the component pockets on the
endpieces, the hinges, to change the pantoscopic tilt at the hinge. The superior edge of each pocket stays at the
pocket depth; a positive angle makes the inferior edge deeper, and a negative
angle makes it shallower. At 0° the floor is flat. The slider stops where
either edge would come out of the surface or get closer than 0.5 mm to the
anterior face.

**Pad splay** is cut the way it is finished by hand. The angle cut comes first,
from the crest down toward the frame's edge at the splay angle, and never
leaves the edge thinner than **Min edge thickness**. Then **Seam blend** rounds
over the seam nearest the front, where that cut meets the edge: 1 mm by
default, at most the minimum edge thickness, and 0 leaves it sharp. The crest,
the most posterior seam, is left sharp for tumbling. Every kernel cuts the same
section.

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

### Separated rims — a combination frame

A combination frame's acetate rims sit on a metal bridge and temples. Draw
both rims in GuildDraw, each a closed OUTLINE curve holding its lens, and bake
the mirror. GuildModel builds one Frame Front with a body per rim, both cut
from one front blank.

Each rim partitions as a standard half: endpiece, eyewire superior and
inferior, and nosepad, with the rim's end of the bridge over the nosepad when
you draw the fifth section cut. The bridge end takes the bridge's height, as
on a one-piece front. No zone spans the gap, and the zone list on the Model
tab reads *a standard half per rim*. A LENS curve that lies in no rim is never
cut: GuildModel says so in the log, and the castle does not build until the
lens is inside its rim. A rim drawn in pieces is named in the log too:
GuildModel closes each piece with a straight line, so join the pieces in
GuildDraw.

The program cuts both apertures and a perimeter around each rim. Where the
rims are closer together than the perimeter tool and its allowance need, one
ring goes around both, and a note on the Perimeter op says that the stock
between them stays; cut the gap with a smaller tool.

The bridge's mount is one shape across the gap: on COMPONENT for a bridge that
mounts from behind, and on INLAY, cut on the visible face, for one that mounts
from the front. Each rim takes its own end of the shape, and the rest of the
toolpath runs in the waste between the rims. A COMPONENT pocket that reaches no
endpiece is a mount: the component depth is measured from the terrace it
is cut into, the rims' bridge ends, and its floor stays flat whatever the
hinge pocket angle. A pocket on an endpiece is a hinge pocket, as always.

The pad splay and the bridge relief are cut under and into a one-piece
front's bridge. Separated rims have no such bridge, so both stay off. On the
Forming panel the rims take the base curve and the face form; the bridge
projection and its controls are off, and the dies carry no bridge tooling.

**A monocle** is one rim and one lens, drawn on the front. It partitions as a
standard half, like either rim of a pair, and builds and cuts the same way.
It forms to its base curve alone: with no second eye to wrap toward, its
face form and the dies' face form are off, and the projection with them. The
curve is apexed at the lens, or on the center line when the rim is drawn
across it.

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

### Sculpts — your own meshes, embossed or debossed

A sculpt is a mesh you made elsewhere: a crest, a rivet head, a plaque, a
channel. Drop an `.stl` on the 3D view, or use **+ Add STL…** in the
**Sculpts** section of the Model tab. GuildModel repairs the mesh (a
duplicated-vertex soup is welded, an inside-out shell is turned, an open
shell is mended, two overlapping shells become one), finds its flat back,
and snaps it to the back of the frame at the center, sunk 0.05 mm so the
two are one body; where the back spans a terrace step the sink grows by the
step. The log names what the repair did. A sculpt over 250,000 triangles is
offered a simplification, and the tolerance is recorded with it.

Each row has a name, the face it snaps to (back, front or the rim), the
operation (**Emboss** adds the mesh, **Deboss** cuts it as a tool), a scale
about the back, a spin about the surface, the overlap, **Flush** for a
coplanar seat on a flat terrace, and **Mirror** for the twin across the
center line. **Re-snap** reads the frame again under the sculpt. **Move in
3D** puts a handle on it in the 3D view: arrows to move, rings to turn; the
model rebuilds when you let go, and a scale or spin edit afterward keeps the
place you moved it to. A sculpt lifted clear of the frame is refused with
the gap named: the union would be two bodies.

After each build the log reports any undercut: a face that points down
between the top and the bottom of the part, which a three-axis tool cannot
reach. The program cuts the envelope over it. A sculpt on the back is
machined by the posterior program: its footprint joins the feature band, so
the Features pass finishes it at its cusp stepover, and the **Sculpt
Finish** operation on the Cut tab, off unless you tick it, runs a ball over
the footprint at a finer one. A sculpt on the front or the rim is modeled
and exported, and not posted until the flip setup. The project file carries
the mesh bytes, so a saved project reopens with its sculpts and no external
files. The mesh kernel builds them, and the raster and B-Rep kernels do not:
with either of those chosen in Preferences, the Sculpts section and the
Sculpt Finish operation are hidden, the sculpts are kept for the mesh kernel,
and the log says when a build or a program leaves them off.

### Seats and plaques — the INLAY layer

A closed curve drawn on GuildDraw's `INLAY` layer, on the front or on a
temple, is a **seat**: a flat-bottomed pocket for a plaque, a laminate or a
plate. The drawing carries the shape; GuildModel holds the rest, one row per
seat in the **Inlays** section on the Model tab (and on the Temple tab for a
temple's seats). There is no Add here — draw the seat in GuildDraw and it
arrives. The flush, the tool, the depth per pass and the minimum thickness
sit under the section's **Cut details** fold.

| Control | What it does |
|---|---|
| **Enabled** | off leaves the seat uncut, and anything drawn inside it |
| **Name** | your own label for the list, the log and the setup sheet |
| **Relative to** | read off the drawing: the face, the parent seat's floor, or the component pocket's floor |
| **Face** | which side the seat is cut into. Anterior is the visible side — the front of a frame, the outer side of a temple |
| **Depth** | the insert's thickness, below what the seat is relative to |
| **Flush** | cut the seat shallower (+, the insert sits proud) or deeper (−, sunk) than the insert |
| **Mode** | Step, a pocket; or Island, left standing while its parent is pocketed around it |
| **Tool** | the end mill that pockets the seat; the part's pocket tool by default |
| **Depth per pass** | this seat's own, or the Cut tab's pocket setting |
| **Min thickness** | the material the floor must leave against the other face |

**Draw nesting to say what a seat is relative to.** A seat on its own is cut
into a face. A seat drawn inside another seat is a step down from the
parent's floor, on the parent's face. A seat drawn inside a `COMPONENT`
curve is a step in that pocket's floor and takes the pocket's tilt with it, so
a hinge with a plate under it seats true. The canvas draws a nested seat
darker. GuildDraw refuses a seat that leaves the outline, crosses a lens,
drill or component curve, or half-overlaps another seat.

**An island is a raised shape inside a plaque.** Draw the monogram inside the
seat and set it to *Island*: the seat is pocketed around it and the monogram
stands. Its own depth sinks its top; 0 leaves it at the surface.

**Inlay depth**, beside the hinge pocket depth, is what a new seat starts
at — a plaque's usual 1.0 mm. Each seat then keeps its own depth. The shop
default is in Preferences ▸ Parts (§8).

**A seat on the visible face is modeled and shown in 3D, and not posted.**
Machining the front of a frame or the outer side of a temple needs the flip
setup, which is a later release; the row says *not posted*, and the program
is exactly the one you would post without the seat. A seat on the back of
the frame, or on a temple's hinge side, is cut by the **Inlays** operation:
after the relief has finished the surface the seat is measured from and
before the eyewires, with the hinge tool unless the seat names another. A
seat the tool cannot enter is left out and named in the Inspector with a
tool that fits.

**The thickness check.** When you generate, GuildModel measures each seat's
floor against the other face at the same spot — a seat on the front under a
hinge pocket on the back, two seats back to back — and names any seat that
leaves less than its minimum, in the log, the Inspector and the setup sheet.

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

The **Stock** tab sets the blank dimensions and the pad block. They start
from your defaults in Preferences ▸ Parts (§8); save a project on a different
stock and GuildModel offers, once, to make it the default. The blank is
centered on the drawing's origin, which is where GuildDraw draws its stock
blank guide, so with **Origin from drawing** on (the default) the front is cut
exactly where it was drawn and several drawings laid out against one origin
register alike. Turn it off for a drawing that was never drawn on its blank:
the outline is centered on the blank, and the 2D view shows the drawing moved
there. Turning it back on restores the drawing exactly.

The pad block stands over the blank across the nose, and the eyewires and
the perimeter cross it. Above the blank's top only the pad has material, so
each pass there cuts the stretch of the ring over the pad, going down and
coming out in air past its edge; below it, the rings are cut whole.

**Build 3D** builds every loaded part's model in one pass, and each tab
caches its own model. The view strip carries:

- camera presets — Iso / Top / Front / Reset
- the castle **stage stepper** — towers → walls → footing → full
- a **measure** tool — click two snapped points for a distance or an angle
- a 3D section plane

A parameter edit rebuilds the model live and keeps your zoom.

### The pre-formed blank — cut after pressing

**Pre-formed blank** on the Stock tab cuts the front after it is pressed:
the blank is the slab pressed to the Forming view's base curve and face
form (the press's pre-cut dies make it), the target is the formed model,
and the eyewires, the holes and the perimeter follow the curve, so nothing
ovalizes and the bridge does not draw in. The 3D view shows the pressed
slab in place of the stock box. A pressed sheet carries no pad block. The
hinge pockets follow the curve at their depth; each pass of a through-cut
sits a stepdown below the local top and stops an onion skin above the local
bottom, the skin measured along the surface's normal; the tabs ride the
local floor.

A formed part's walls lean with the curve, and a three-axis cut makes them
vertical at the front's edge, where the lens seats and the visible edge
are. The back's rim therefore loses the lean, up to a few millimeters at
the temporal ends of a steep front; the simulation says how much and
allows it in its verdict; the fourth axis (2.0) cuts the walls as formed.
The lens groove cannot follow a curved rim in three axes: the program
leaves it out and says so. **Apertures and groove first** is the hybrid:
the eyewires, the holes and the groove are cut flat first, in a program of
their own, the part is pressed in the post-cut dies, and the pressed blank
is nested for the rest. It trades the bridge's draw-in for a correct
groove. A pre-formed front is cut in its nest, not on the worktable; take
it off the bed.

**Export Nest…** on the Forming panel writes the nest fixture: the cup
that holds the pressed slab front down for the posterior, and the dome,
cut away under the taller zones, that the slab lies on back down while a
two-sided job cuts the anterior first, both on the dowels of the flip
line. The simulation cuts the anterior from the pressed slab turned over,
then the posterior from its result. The dome was shaped for a carved back,
and it bears on the slab's uncut back only where it is not cut away; work
on pressed blanks is paused, and the dome is to be reshaped before a
two-sided pressed part is cut. What is documented here is the
geometry and the programs; the pressing of a blank for cutting, the nest
and the flip on a curved blank are the maker's own tests, and the first
parts should be measured before a batch.

### Export STL

**File ▸ Export STL (Ctrl+E)** writes the part you are looking at.
**File ▸ Export All STL (Ctrl+Shift+E)** asks for a folder and writes every
part that can be built — the frame front, both temples and each base-curve
template — one file each, named for the part. A drawing with more than two
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
ignores forming entirely, and the forming values are saved with the part
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

### Press dies — the molds for the formed front

**Export Dies…** on the Forming panel writes the molds for the press, cut
to the forming you have set, as STL files to print or to machine: the
**posterior die**, a convex dome under a flange, and the **anterior die**, a
cup in a block; in post-cut mode also a **bridge punch** and a **V anvil**
for setting the bridge at the bench. **Dies with Export All** adds them to
Export All STL.

The dies are made from the forming map and the silhouette, never from the
modeled front: hinge pockets, seats, chamfers and sculpts play no part in a
mold, and the less a die carries the better it presses. The dome follows
the eyewire terrace, the surface most of the back rests on, and is cut away
under every zone that stands taller than it, the nosepads first, by the
zone's extra height plus a clearance and out past the footing blend's
reach onto the terrace, so the die holds the frame on its rims and never
presses the pads. The anterior die is the plain negative at
the base curve and face form, set back by the **silicone mat** you roll
over the dome and by the **clearance**; the mat gives the compliance and
the die gives the curve. The closed gap between the faces is the terrace's
height plus the mat plus the clearance, and the dies close flange to
flange, two 6 mm dowels on the diagonal locating them. The log and the
panel report the gap, the cutaways, the outer size, and the formed sizes
against the flat ones: the DBL, the lens width, the frame PD and the
overall width, which the curve and the bridge both shorten.

- **Mode** — *Post-cut* trims the faces to the outline plus a margin and
  relieves the inside of each eyewire so only a rim band is supported and
  the aperture edge is not marked. *Pre-cut* covers the blank plus a
  margin and carries no eyewire geometry; the formed blank it makes is the
  stock the pre-curved program (2.0) machines.
- **Mat thickness** and **Clearance** — what sets the closed gap. Hot
  acetate grows about 0.08 mm on a 6 mm front, and the mat is yours.
- **Over-bend** — a radius multiplier for the springback, 0.97 to 1.00. No
  eyewear source quantifies it; press the first part and move it if the
  curve opens.
- **Face form in die** — off leaves the wrap to the bench.
- **Bridge in die** — the projection as a ridge in the dome and a valley
  in the cup, for a pre-cut blank; post-cut, the punch and anvil set it.
- **Cutaways** and their clearance; **Relief depth** and the **rim band**
  for post-cut; **Trim** and **Margin**; the **flange**, its thickness and
  draft; the **dowel** and its fit; the **vent**; the **mounting pattern**,
  the three M4 holes the base-curve blocks use, so a die bolts to the same
  jig; the **punch radius** and the **V angle**, both following the forming
  view unless you set them.

Heat the front to 110 °C for standard and M49 acetate, 125 to 130 °C for
HX; below 110 °C the curve relaxes. Hold 10 to 30 s under closure and
quench. A printed die in Rigid 10K, post-cured and used with silicone
release, lasts dozens of pressings when the contact stress is low, which
is what the large faces and the mat are for; FDM only in annealed
PAHT/PPA-CF, PC or PEEK. Condition the sheet two days at 45 to 55 % RH and
pre-bake fresh stock. Check the first part's curve and face form before
the batch and move the over-bend if it opens. The pre-cut route is the
less documented one; you are the test case.

## 3. Temples and base-curve blocks

**Temple.** The outline extruded on the blank, with blind pockets from the
`COMPONENT` layer, the hinge's, and engraving grooves from `ENGRAVING`. Two kinds of
engraving share the layer and are told apart when a `.gdraw` opens: text,
which is engraved as one line down each stroke while *Engrave text as stroke
centerlines* (Temple tab) is on, and a curve you drew on the layer. A drawn
closed curve is a filled shape, cleared to the engraving depth with the
engrave tool; a closed curve drawn inside another is an island and keeps its
material, so an O is two circles and a filled disc is one. A drawn open curve
is a stroke, traced as drawn. A shape too small for the bit to enter is left
and the simulation reports it; a small flat end mill set as the engrave tool
fills a logo more cleanly than a V-bit. Over a DXF, which cannot tell text
from drawing, the option applies to every closed curve; turn it off for a
DXF temple that carries a logo. The hinge end snaps
to the 170×30 blank edge; the snap, the stock side and the blank size start
from your defaults in Preferences ▸ Parts (§8). Across the blank, **Origin
from drawing** (on by default) keeps the drawing's zero line on the blank's
center line, where the injected core runs: draw the temple with the core on
GuildDraw's horizontal zero and it is cut there, a dropped tip and all. Turn
it off to center the temple's width on the blank instead. The injected-core
bar shown in 3D runs down the blank's center line and is a visual guide only;
**Core guide width** and **Core guide length** size it. Program: the hinge
pockets, the engraving and the inlay seats while
the blank is rigid — whichever tool has the least work first, so the operator
loads it, starts, and swaps once — then Holes, then the Temple Profile that
releases the part. The Holes operation appears only when the drawing has
decorative openings in the outline.

The Temple tab sets the **Component depth** and the **Hinge pocket angle**.
The angle tilts the pocket floor along the temple to offset splay built into
a hinge. The anterior edge, nearer the hinge end, stays at the pocket depth; a
positive angle makes the posterior edge deeper.

A temple's `INLAY` curves are its seats for plates and plaques, one row each
in the **Inlays** group under the Temple tab; the controls are those of §2,
*Seats and plaques*. The outer face is the visible one and the default, and
a seat there is modeled and not posted until the flip setup; a seat on the
hinge side is pocketed by the Inlays operation beside the hinge pockets, and
one drawn inside the hinge curve steps the pocket's floor.

**Apply to both temples**, at the foot of the Temple tab, copies the tab onto
the other temple — blank, snap, stock side and origin, hinge pocket depth and
angle, inlay depth, engraving, tools, onion skin, hand allowance and holding —
so both cut with the same tools and depths; the other temple keeps its own
seats, which are its drawing's. Each temple keeps its own program zero (Machine
tab) and cut settings (Cut tab). The copied-to temple needs a rebuild and a
new program, and its tab shows the copied values on the next visit.

**Base-curve block.** The heat-forming template: the lens shape cut from a
70×70 acetal blank, with three M4 through-holes that double as the fixture's
mounting screws. The blank size and the hole pattern start from Preferences ▸
Parts. Program: Drill Holes → Block Profile.

## 4. Cut settings

The **Cut** tab is the everyday surface. Pick the **material** — acetate,
acetal and the rest — and its feeds, speeds, stepover and stepdown seed
themselves. Tune the material row away from the defaults, and GuildModel
offers to save them back as your new defaults; *Don't ask again* on that box
silences the offer, and Preferences ▸ General turns it back on.

**Feeds & Speeds, per tool.** Under the material row, one row per tool the
open part's program uses — a temple with engraving shows the engraving
bit, the component pocket end mill and the profile tool. Each row shows what that
tool will actually cut at and where the numbers come from: *material* (the row
above), *tool library* (the tool's own feeds in Preferences ▸ Tools — the
shipped engraving bit runs at 300 mm/min and 14000 RPM, which its slender tip
needs) or *this project* (a value you typed here). Type into a row to set it
for this project; *Reset* gives the tool back to its library feeds or the
material's. A **chip-load** read-out on every row shows green / amber / red
against the material's window, so a bad feed-rpm-tool combination is visible
before you cut. The rows follow the tool choices on the Temple, Base Curve and
Machine tabs, and everything is clamped to the machine profile at post time.
Generate a program whose per-tool feeds differ from the tool library and
GuildModel offers, once, to save them to the library; the project keeps its
own values either way.

The **Machine** tab is setup. It holds:

- the machine profile — Guild CNC, Nomad 3, Shapeoko or generic GRBL
- **program zero** — each part keeps its own, starting from the default for
  its kind of part in Preferences ▸ Parts (shipped as center/center/bottom).
  The datum crosshair shows on the 2D canvas. Save a project whose zero differs
  from the default and GuildModel offers, once, to adopt it.
- the per-operation tool assignments, for multi-tool jobs
- the cut strategy
- the no-`SCULPT` profile fallback

**The Features operation.** The posterior finishing features cut in their own
**Features** operation, so they can take their own tool. It is the **2 mm ball**
by default, for the chamfers, bezels, splays and scoops; an end mill cuts
everything else, such as the hinges, the footing and the posterior sculpting.
A flat end mill left up to a millimeter on these slopes. To cut the features
with another tool, pick the tool by name; as for the Component Pockets, *(same as
Tool)* keeps the default. A job with features therefore changes tools for
them.

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
Check a row to show or hide it, and click a row to highlight it. A pocket, a
hinge pocket or a seat, is cleared in rings a tool radius in from its wall
and a stepover apart; where the last rings' passes would overlap at the
middle by less than a tenth of the tool's diameter, one more pass goes round
the middle, so no fin stands there. GuildModel
lints the program against the machine limits — envelope, feed, spindle and arcs
— and reports any reach warnings. A machine profile may give
`spindle_spinup_s`, the seconds its spindle takes to reach speed: GRBL does not
wait for it, so each M3 that starts the spindle is followed by a `G4` dwell
that long. The shipped profiles leave it at 0, which writes none; set it at the
bench.

The **readiness dot** in the status bar tracks the job:

| Dot | Meaning |
|---|---|
| red | the drawing is loaded |
| amber | the model is built |
| green | the program is stored in the saved `.gmodel` |

**Simulation (Ctrl+Shift+S)** machines the stored program into a virtual
blank and verifies the result against the target. It simulates the program
the machine will run: the one stored on the tab, read at the cutting grid.
With no fresh program stored, GuildModel generates it first and the
simulation follows. **Uncut** highlights material left proud, **Gouge**
highlights cuts below target, and the badge gives a ✓ / ⚠ / ✕ verdict; the
log and the Simulation page add the volumes left standing and taken, in
cubic millimeters.

The verdict fails a cut that reaches less than 90% of the body, or gouges it
deeper than half a millimeter; it warns below 96%, or on a shallower gouge.
It also judges the
largest piece left standing in one place by its volume, and says where it
stands: over 0.5 mm³ it warns, and over 2 mm³ it fails. A hinge pocket left
uncut is a fraction of a percent of the body, so the fractions alone pass
it. A gouge deeper than a millimeter counts even beside a step, where a
shallower one is the grid's. Last, the verdict asks whether the part is
released: above the skin or the tabs, the body may join neither the blank
round it nor the core of a lens opening. On a two-sided job it asks this of
the posterior, which makes the through-cuts, and a cut you switched off is
not asked for.

The stock is a true solid, not a surface: every column of the blank keeps
the intervals of material it still holds, so a side-cutting form such as the
lens groove's drageoir takes its slot out of the eyewire wall and leaves the
rim above it standing. A column holding such an undercut is tinted blue on
the block, and **Solid**, offered when the cut has one, shows the stock as a
solid at a pause and at the end, slot and all; playing and scrubbing draw the
top surface, which keeps them quick. A rapid that would pass through stock,
or a tool's shank entering it, is never cut: the verdict fails, and the log
names the operation and counts the positions.

The playback scrubber replays the cut, operation by operation. Use play/pause
(▶), drag to any boundary, and watch the moving tool. Playback pauses with a
warning if the tool would foul a hold-down.

**File ▸ Export G-code (Ctrl+Shift+G)** writes a loose `.nc` when you want a
bare file. The program also always lives inside the saved project. A program
generated before the design or its CAM settings last changed does not cut
what the tabs show: Export G-code asks before writing it, and a project saved
with it brings it back marked stale, so Simulate generates the program again
first.

**Turntable (Alt+T)** is the record button on the 3D viewer's strip, beside the
camera presets, with a speed slider next to it. It spins the part about **the
view you have set up**, not about a fixed world axis.

Tip the frame the way you want to look at it, then start the turntable. It
turns on that axis, so a surface runs past the light. You no longer have to drag
back and forth over it.

The turntable works in the cut simulation too. It parks itself while you are on
another view, so you do not have to re-arm it when you come back.

### Two-sided jobs — the flip

A front that takes material off the front, a brow chamfer, an anterior
bezel, a round-over or a seat on the front, is cut in two setups, and the
anterior always comes first. **The anterior** is cut with the blank front
face up, in G55, while the blank is still a flat slab: the Fine Relief and
the Features pass over the anterior's features, and the anterior seats, and
nothing more. It cuts the Rough Relief only where the front is cut deeper
than one contour stepdown, and never a hinge pocket or a through-cut. Then
the blank is flipped about the fixture's flip line, the station's vertical
center line, onto its two dowel pins, front face down on the bed, and
**the posterior** is cut in G54 exactly as a one-sided job cuts it: the
relief, the hinge pockets, the eyewires, the holes and the perimeter, with
the onion skin or the tabs you chose. All the major removal happens there,
with the piece flat on the bed, where it is most secure, and the onion skin
holds the part through all of it. A front that takes nothing off the front
posts the posterior alone, byte for byte as before.

When the anterior is cut, the stock past the part's edge still stands, so
the anterior reaches past the edge: the relief by two tool radii, the
Features pass by the ball's radius past its band. A feature that runs to
the edge, as a brow chamfer does, is finished to the edge, and the
posterior's perimeter takes the rest away. The onion skin is the layer next
to the front face, so where the anterior cuts deeper than the skin at the
edge of a through-cut, the skin there holds nothing. The log says how much of
each ring the anterior takes the skin off, and warns when it takes it off a
whole ring: an anterior bezel all round a lens opening frees the opening's
core when the posterior's eyewires cut through, and a brow chamfer along part
of the perimeter leaves the part held by the rest. On tabs, the perimeter's
hold is the tabs' height.

The Cut tab's **Operations** group has the choices. **Two-sided** *Auto*
cuts the anterior first when the front is cut or carries a seat, *Off*
never, *On* always. **Output** writes *Two files*, `anterior_cut.nc` and
`posterior_cut.nc`, or *One file, pausing for the flip*,
`two_sided_cut.nc`: the anterior; then the spindle stopped, the tool raised
and the flip's pause, `M0`; then the posterior, with a tool change where
the tool differs. **Probe Z after the flip** begins the posterior with a
G38.2 touch-off on the blank's back, for a machine with a probe plate: the
probe runs down from where the tool is left, and the touch sets G54's Z to
the back's height plus the plate's, in the program's own frame. Give the
plate's thickness in **Plate**; 0 is a probe that touches the stock itself.
Without the probe, the posterior says where its Z0 is: the bed, which the
flip does not move, with the default zero on the blank's bottom; the
blank's back, to touch off on after the flip, with a top-face zero. With
the default zero both setups are cut from the bed up, so give the sheet's
measured thickness on the Stock tab: a sheet thicker than the tab says puts
the difference into the depth of the anterior's chamfers and seats.

A blank with the pad block lies front face up for the anterior on a
**spacer** as thick as the pad block, with a cut-out for it: the pad goes
into the cut-out and stands on the bed, and the sheet stands on the spacer.
Z0 is the bed for both setups: the pad block's back for the anterior, the
front's face for the posterior. The anterior makes no through-cut, so the
cut-out needs only to hold the pad. The anterior program and the setup
sheet name the spacer.

The project holds the programs, and Export G-code writes them to a folder;
the setup sheet lists the two setups in the order they run, the flip line
and what to re-probe. The simulation runs the whole job: it cuts the
anterior from the fresh blank turned front face up, turns the result back
over and cuts the posterior from it, and the log carries both verdicts; an
anterior that fails fails the job. In the 3D view the playback stops at the
flip and names it; ▶ turns the block over about the flip line and goes on
with the posterior. The per-op table lists the anterior's operations first,
as *Anterior · …*, each with its tool and color, and the 2D view, which
shows the design from the back, draws their paths where they fall on the
part. GuildSend stops at the one file's flip as at any flip;
its guided two-file sequence still looks for M24's names, so until it reads
the setups it offers the two programs to choose from. Run `anterior_cut.nc`
first.

Registration on this class of machine is 0.05 to 0.1 mm, and every error is
doubled in a two-sided cut: press-fit pins in the wasteboard, a slip fit in
the stock, and the flip the way the program assumes. The bench test is a
counterbore pattern from the anterior and a matching through-hole pattern
from the posterior in a scrap blank, measured at four corners under a loupe.

### The fourth axis — what a rotary does and does not do

A rotary on the Guild CNC is for the **indexed flip**: with the blank
centered on the rotary's centerline on a bar fixture, the anterior setup
of a two-sided job is the posterior's with Y and Z negated about that line.
The anterior program begins with the turn to A180, then its work offset,
and turns back to A0 at its end, so the posterior runs as it would alone,
with no pause to re-fixture by hand. The machine profile says whether the
machine has the axis (**Guild CNC (fourth axis)** is the shipped
four-axis profile, its figures placeholders for the bench), what it is
called, what it turns about, which way (the sign has flipped in a shipped
firmware; a chamfer on one corner tells you), its centerline, its rate and
its travel; the fixture file says the blank is on the rotary bar and where
its centerline lies on the bed. GRBL 1.1 has no fourth axis: grblHAL or
FluidNC carries it, and the first bench session decides which. A program
with A words is refused by the post on a three-axis profile, and the lint
says so if one reaches it; the cut-time estimate charges a turn at the
rotary's rate; a move in which the rotary and the feed arrive together
runs in inverse time, G93, and never as an arc.

What a rotary does not do is the lens groove on a curved front. The rim's
normal tilts in two directions and one rotary compensates one: about the
frame's horizontal the residual yaws the disc into the walls and widens a
2 mm groove by half a millimeter or more; about the vertical the residual
is smaller but the swing needs a height this class of machine does not
have. A correct groove on a curved front is a five-axis feature, and it
waits for the experiments of 2.5. Before the rotary is mounted, measure
the spindle nose to the table at Z max; the swing of the blank and its
fixture must fit under it, and the profile holds both numbers.

The bench test is the flip test of a two-sided job with the flip done by
the rotary: a counterbore pattern from the anterior and a matching
through-hole pattern from the posterior, concentric at four corners within
0.1 mm, and the rotary
back at zero within 0.05 degrees over ten turns. GuildSend's side, the
A axis in its status, jog and settings, is its own work.

## 6. The worktable — cut the whole model in one setup

The **Worktable** tab is the machine bed. Its panel has four groups, each of
which folds away under its heading.

**Bed.** Four buttons, their words in the tooltips: import your bed as a DXF,
where each closed region becomes a zone, or load a saved `.bed`; load the
Guild standard bed; save the bed; make it the default that loads with every
session. Set the bed's size, its program zero and the hold-down height here.
No field on this panel takes the mouse wheel until you click into it, so
scrolling the sidebar never changes a value.

**Zones.** The regions are listed in two groups, the zones and the
hold-downs, the hold-downs folded away. Click a region on the bed, or a row in
the list, and tag its role: frame-front, temple R/L, base-curve R/L, or
keep-out; picking a screw on the bed unfolds its group. A zone can carry the
fixture's **stop**, the edge the stock registers against, on either axis: a
temple zone cut for 170 mm blanks with a stop at its left end takes a 160 mm
blank flush left. *Centered* places the blank in the middle of the zone on
that axis. The stop is saved with the bed. Remove, Undo and Redo sit beside
the count; Undo and Redo cover every bed edit.

**Parts.** One row per part, with a checkbox: on the bed, or not. A part
left unchecked keeps its tab, builds and posts on its own, and is left out of
the worktable program, its setup sheet and the bed simulation; its placement
is kept, so checking it again puts it back where it was. Each row names the
zone the part sits on and its state: *placed*, *unplaced*, *needs Generate*
or *collision*. Pick a row and the part's controls follow: the zone to send
it to, the rotation buttons and angle, and its X and Y offset on the bed.
Which parts a new drawing starts with on the bed is set per kind of part in
Preferences ▸ Parts (§8); a batch shop that cuts its base-curve blocks once
leaves them off there.

On the bed itself, drag a footprint to move it. A blank pushed past the
pocket's wall comes back flush to it, and one dropped within 3 mm of an end,
the center or the stop snaps there; Shift drops it exactly where it is.
**Snap** (the button beside the turns, or S) pushes the selected part flush to
its zone's stop, or, with no stop, to whichever end it is nearer, keeping its
orientation: flip a temple 180°, drag it toward the
other end and snap, and it sits flush there the other way round. The arrow keys nudge the selected part 0.1 mm, or 1 mm
with Shift; R turns it 90°, Shift+R the other way; Delete takes it off the
bed. The right-click menu snaps it, rotates it, sends it to another free zone
of its role, or removes it. Each footprint shows the blank, dashed, and the
outline the program cuts; a part whose cut would reach a keep-out draws in
red.

**Program.** **Auto-place** (the grid with an arrow) puts every part without
a placement on a free zone of its role, against the zone's stop where it has
one, at once, and leaves the placed ones where they are; **Re-place all** (the circling arrows) forgets every
placement, nudges and turns included, and places every part again; the sheet
button shows the last setup sheet. Placements are saved with the project and
reopen where they were.
Placing needs no program: **Generate** makes the programs, once per part, and
posts the parts on the bed as one `worktable.nc`, scheduled to minimize tool
changes while keeping each part's operation order. A part whose settings did
not change since the last Generate is not rebuilt. Any edit that would change
the program, on any tab or on the bed, marks the part *needs Generate*; the
Program line says whether the bed program is current. The setup sheet names
the parts left off as *not on this bed* and lists the keep-outs any
operation reaches. **Simulate Bed** runs the whole-bed cut simulation over
the same parts, generating the program first when it is stale. The posted
`worktable.nc` is cut once into the placed blanks, rotation included, and
that one result is both the verdict and the playback: each part's blank as
listed, placed on the bed among the hold-downs, so what you see is the stock
on the bench.

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

- **General** — the log panel on startup, whether a drawing builds its frame
  front on open, the 3D preview and STL export
  resolution, the default output folder, and the **Prompts**: the four offers
  GuildModel makes — the default bed, the part defaults, the material
  write-back, the tool-library write-back — each of which has a *Don't ask
  again* on the box and a switch here to turn it back on.
- **Parts** — what a newly opened drawing or DXF starts from, for each kind of
  part: the program zero, whether the part is on the worktable to begin with
  (§6), the temples' snap to blank end and stock side, each part's origin
  from drawing, the blank sizes and pad block, the base-curve block's
  mounting-hole pattern, each part's tools, and the inlay depth a new seat
  starts at on the front and on a temple. A project keeps its own
  values. Save one whose program zero, stock or temple alignment differs and
  GuildModel offers to make that the default, provided every part of that
  kind agrees. Each difference is a line with its own checkbox; clear the ones
  that belong to this job only, and Yes adopts the rest. The stock is one line
  per kind of part and is adopted whole. GuildModel asks about each line once;
  a further change asks about that change alone. The hole pattern, the tools
  and the worktable switch are set here only.
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

The **?** button at the far end of the toolbar turns tooltips off everywhere,
and back on; GuildModel remembers the choice. Tooltips wrap to a readable
width. A number you type into any field applies when you press Enter, Tab or
click away; the sliders update live while they move.

The Preferences window opens sized to its content within your screen and
remembers the size you leave it at. Your preferences, window layout, folded
sidebar sections and recent files persist in `~/.guildmodel/prefs.json`. The material, tool and frame-style overrides live
beside it, and so do your presses (`presses.yaml`, §2).

## 9. Files and data safety

- **`.gmodel` is self-contained.** The embedded drawing means a project reopens
  identically, even if the original `.gdraw` moved; the sculpts' meshes ride
  in the file too.
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
| Ctrl+R | Reload Drawing |
| Ctrl+S | Save Project |
| Ctrl+Shift+S | Save Project As |
| F5 | Build 3D Model |
| Ctrl+G | Generate G-code |
| Ctrl+Shift+G | Export G-code (.nc) |
| Ctrl+E | Export STL |
| Ctrl+Shift+E | Export All STL |
| F6 | Simulate the cut |
| M | Measure |
| Ctrl+B | Worktable |
| Ctrl+0 | Fit to View |
| Alt+T | Turntable (3D views) |
| F | Forming (frame front) |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit |

Every row is rebindable in Preferences ▸ Hotkeys except the last two; Ctrl+,
and Ctrl+Q are fixed.
