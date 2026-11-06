# Changelog

Release notes by version, newest first. The README keeps one status paragraph
and the current release's note; everything else lives here.

## v2.3.1 — the worktable, sorted; STEPCRAFT on UCCNC *(in progress, not released)*

### STEPCRAFT machines on UCCNC, with the tool changer (2026-11-05)

**STEPCRAFT (UCCNC, tool changer) in the Machine list.** Pick it and every
program GuildModel posts, a part's or the worktable's, is written in UCCNC's
G-code, modeled on Autodesk's certified STEPCRAFT UCCNC post with its tool
changer on: comments in parentheses and plain ASCII; `G64` and the work
offset named at the start and after every tool change; `T<n> M6` for the
changer, then `G43 H<n>` for that tool's length from UCCNC's tool table;
every retract that leaves the work, before a tool change and at the end, to
the top of Z travel with `G90 G53 G0 Z0`, so **home the machine before
running**; `S… M3` followed by a three-second `G4 P3000` (UCCNC reads
milliseconds); arcs no wider than 90 degrees. The toolpaths themselves are
the same as for any other machine, line for line.

**Each tool is called by its pocket.** The number after `T` is the pocket the
changer fetches, so it is the tool's own **Tool number** (Preferences ▸
Tools). *0 = auto* does not do on a changer: a number made up by machining
order fetches whatever sits in that pocket and applies its length. A program
whose tools lack their own number, or share one, is refused before anything
is written, every such tool named in the one message, rather than posted to
fetch the wrong pocket. A program with one tool names it too.

The profile's envelope, feeds and spindle range are a D.600's and a
conservative spindle's; set them to your machine (`stepcraft_uccnc.yaml`).
Re-probe Z after a flip is not carried on UCCNC yet and says so; re-zero at
the flip's pause. The simulations, the Z-profile check, the cut-time
estimate and the program lint all read a UCCNC program, and the Z-profile
summary is written in its comments. When the worktable program is refused,
the dialog now says why instead of "see the log".

### The tool library, and a sweep before the release (2026-11-06)

**An edit on the Tools tab keeps what the form does not show.** The tab
rebuilt the tool from its own fields, and the lens-groove cutter's V and
neck have none there: typing anything into it, its Tool number say, drew
the cutter flattened and, on OK, saved it with no V and no neck, which the
lens groove's toolpath and simulation read. The form now changes only the
fields it shows. **If you edited the groove cutter in an earlier version,**
open Preferences ▸ Tools, pick it, and *Reset to shipped*; then set your
number or feeds again.

**A tool's own number is never taken by another.** A tool without a
number, cutting first, took T1 from a later tool whose number is 1, and that
tool was numbered again. Every tool's own number is now reserved before any
is made up; of two tools claiming one, the first in machining order keeps it.

**A UCCNC program's cut time counts its dwells in milliseconds.** Each
spindle start of a STEPCRAFT program added 50 minutes to the estimate on the
summary and the setup sheet; it adds three seconds. A long op label or tool
name no longer wraps its section marker across two comment lines, which the
simulations read on one. The worktable's dialog quotes the post's own
refusals and keeps every other failure for the log.

### A bed zeroed anywhere but its lower-left (2026-11-05)

Found on a maker's own bed, drawn in Fusion 360 and set up for the first time.

**Simulate Bed cut every part beside its blank.** The worktable program is
posted with the bed zero in its coordinates, and the bed simulation read it
back as if they were bed coordinates. On the default zero, the work area's
lower-left, the two are the same, which is why the Guild bed never showed
it; at any other zero every cut landed that far away. On the maker's bed,
zeroed at the center of a 200 × 200 mm work area, the temples' blanks were
not touched at all and the front's took the temples' paths. The simulation
now takes the zero back out, as the single-part simulation already did, and
both read through one place (`parse_program`'s `work_offset`), so neither
can leave it in again. **The posted G-code was right for the zero chosen;**
only the simulation was wrong. Its hold-down collision check reads the same
cut, and is corrected with it.

**The bed zero is said.** The Bed group shows, under *Bed zero*, the point
the program touches off, in bed coordinates, any shift included: a `.bed`
can carry a shift no item in the list names, and the list read
*Lower-left (bed origin)* over a zero 85 mm away. *Center* is the work
area's center, not a blank's, and the tooltip says so. The worktable's
setup sheet records the zero and its offset, as every part's sheet does, so
GuildSend shows it; the log and the Generate summary say it in the same
words.

**A bed DXF closes the corners its CAD closed.** A region whose outline
met at a corner written two ways (Fusion ended one line at y =
70.784271247399 and began the next at 70.78427124739899) never closed and
was left off the bed; so was a screw hole exported as three arcs. Ends
within 0.01 mm are now one corner. A line that stops short of another's
middle still stays loose, so a reference line drawn across a zone does not
cut it in two.

## v2.3.0 — the draft view and the blueprint; a temple's second side, the temples' link, Embossing, Program Zero's shift

The prepared 2.1.0 was not released: both apps jump to 2.3.0 together, built
on the forming research of 2026-10-29. The 2.1 entries follow the 2.3 ones.

### The draft view and the blueprint (2026-11-04)

**The drawing's forming and tip bend are read.** GuildDraw 2.3 stores the
front's forming under `thermoform` and each temple's tip bend under
`tip_bend`. A front's block seeds the project's forming (the base curve, the
radius in use, the face form, the bridge projection, the press row when it
is one of this installation's, the neutral surface); the project's own
forming wins once it is saved. Each temple's block lands on its params as
`tip_bend`. The library folder a component was placed from
(`component_kind`) is read too, so a bridge placed from *Bridges* is not
taken for a hinge. A file from before carries none of this and opens as it
did.

**View ▸ Draft (D).** The assembled frame after forming, in the 3D view: the
formed front, the temples bent by their tip bend and opened to the **angle
of side** and the **splay** the panel under the view sets, the hinge
filled in. The angle of side is the front's `pantoscopic_tilt_deg`, which
nothing read before. What the hinge alone would give reads beside each
target: the pocket floor's angle, the endpiece's own lean and turn on the
formed front, the hinge's slant and stop. The temples hang at the targets,
and the butt is cut where they would pass the endpiece's back face; the
panto and the splay cut into the butt are the difference, and *Match pocket
angle* sets the front's pocket angle so the hinge agrees. The hinge is marked
rivet, heat-set cleat or spring, with its barrels, screw thread, slant and
stop; the drawn pocket gives its plate and the width along the axis, the
shipped library's datum (the butt face, the REF line's setback) gives the
axis. Seven bench checks run: the angle of side and the splay left against
right, the four-point touch, the tips on a common plane, no X-ing, and each
folded temple crossing the center and clearing the back. The Forming view and
the Draft view share the viewer's one formed slot.

**Export Blueprint… (File, and the panel's button).** Sheet 1 is the
dimensioned assembly after forming, laid out as eyewear sheets are: the
plan, the front view and the side view stacked down a portrait page on the
frame's center line. The plan shows the front from above with the temples
curving in, and carries the front's width, the dowel-to-dowel width, the
tip spread, the front's thickness, the temple's thickness, the front-to-bend
and the base curve; the front view faces the wearer with A and B in the
lens plane, DBL, the boxed-center distance, the joint height and the bridge
width, the folded temples dashed behind the lenses on request; the side view is drawn
in the temple's frame, the temple horizontal and the front tilted by the
angle of side, with the length to bend, the drop, the downward angle and
the temple's heights. Third angle puts the plan above the front; first
angle below, the temples running down. Each dimension is tagged locked,
target, open or reference. Beside the views: the hinge detail, reference
only; the notes with the marking, the rim widths, the forming, the bench
numbers, the hinge's lines, the tolerance table (ISO 12870's rows and the
factory's, editable), the checks and the temples as cut; the ISO 7200 title
block. Sheet 2 is the 1:1 alignment template: the plan with the tips and
ear points in ±2 mm targets, the side view, and a ruler. The scale is the
largest of 2:1, 1:1, 1:1.5, 1:2, 1:2.5 and 1:5 that fits: A3 and tabloid
hold the views at 1:1, letter and A4 at 1:2. PDF, SVG (one file a sheet),
DXF (exploded, layered, for the factory's CAD) or a printer. The settings
(the paper, the projection, the views, the scale, the title block's cells,
the tolerances) are the project's, seeded from **Preferences ▸ Blueprint**,
where *Save these as my defaults* in the dialog writes them back.

**The temple hangs as an acetate temple does.** Its outer face is flush
with the endpiece's end face (the Draft panel's *Inset* tucks it toward the
hinge pocket), the barrel axis a temple's thickness inside the edge on the
endpiece's back face, where the shipped library's front pockets end, the
butt face through the axis (*Butt gap* stands it off).

**The views are edge renderings of the solid.** The front as built is
bent by the forming map (`FormingMesh`, as the Forming view bends it), its
creases and its silhouette from each direction chained into polylines, the
temples' rings added, and every run tested against a depth buffer of the
scene (`core/draft/hidden.py`): what can be seen from that direction is
drawn, what lies behind other material is left out, and the pockets are
dashed where hidden. The blueprint is composed on a worker under the
progress dialog (`BlueprintWorker`), the front built through the kernel
first when it has not been, and Cancel stops it between stages; the file
or the print job follows on the window's thread. The folded temples in the
front view are an option, off; a front without its mesh is drawn from the
drawing's curves.

**The temple bends as a bar.** The drop (GuildDraw's tip bend) and a new
**inward angle**, the turn toward the head seen from above that ISO 8624
names and the temple tab cannot draw, are composed along the temple's core:
the inward bend runs from 40 % of the length to bend to the ear point and the
drop keeps its heading, so the tips sit closer together than the hinges, as
on every worn frame. 15° is assumed until the maker sets it (the trade bends
10 to 20°); *Inward bend from* moves where it begins. The temple's solid in
the 3D view is the flat outline extruded, bent and cut by the endpiece's
back face, so the butt shows its panto and splay cut.

**The Temple tab's Forming section.** *Length to bend* (Auto: the drawn
length less 37 mm), *Downward angle* and *Bend radius*, the names GuildDraw
uses, then *Inward angle* and *Inward bend from*; the readout says where
the ear point lands and how far the tip drops, or why a bend is out of
range. The Draft panel's own fields set both temples at once.

**The Forming panel matches GuildDraw's group.** *Preset*, not *Press*; the
face form is stated per side in low degrees (0 flat, 8 on the SBT base-4
row), the included angle reading beside it; the stored value does not
change. **Preferences ▸ General ▸ Forming** holds the tooling index (1.53 by
default: the radius a base curve names off a press row is (index − 1) ×
1000 / D), the sheet thickness and the neutral surface, as GuildDraw's does;
every design uses them and a drawing's own copy is read for the record. The
neutral surface is applied around the map, never inside it, so the two
apps' maps stay identical.

**The maker's review before publishing (2026-11-05).** Four additions.
*The lettering is the maker's:* the blueprint dialog and Preferences ▸
Blueprint offer every font family the machine has (the default stays
Helvetica, or the nearest sans), the window measures the chosen family's
average glyph width and the sheet lays its texts out by it, the PDF embeds
the font, the SVG names it, the DXF's text style carries it for the CAD to
map. *A dimension's value sits in a break in its line,* centered, as ASME
Y14.5 draws it (**Dimension text**: in a break in the line, or above the
line as ISO 129 draws it); a value wider than its dimension goes outside
the extension lines, past the reading end, or before the start where the
view knows that side is clear (the bridge width reads below its foot, out
of the DBL's way); an angle's value breaks its arc the same way when it
sits on it. *The hinge detail is drawn from the pockets as drawn:* the
front pocket's shape and the temple pocket's shape, each centered on the
barrel axis with its edge nearest the butt face against the barrel column,
the knuckles between them, as the hinge looks opened flat and seen from
behind; the plan beside it is the joint from above at the stop, the
endpiece's section with its pocket sunk in the back face, the barrel at
the axis a temple's thickness inside the end face, and the temple's section
swung to the stop with its pocket sunk in its inner face. *The ink and the
paper are settings:* black on white, the true blueprint (white lines on
Prussian blue, the cyanotype's look), blue on white, or any two colors
picked from the color dialog; the PDF, the SVG and the printer
take them, the DXF keeps its layers' colors.

A gremlin with them: the Preferences dialog opened at the height of its
tallest tab, which the Blueprint tab's tolerance table had made the
screen's, and that size was then saved as the maker's on every close. It
opens at the General tab's height now, a size the maker sets is the only
one saved, and a size saved before is dropped once (prefs version 3). The
note *Inward angle of drop* on the sheet is *Inward angle, seen from above*;
the drop's own curl is still not drawn.

**Not done, and said so.** The curl a bent drop takes toward the head is
not drawn (the drawing's temple tab has no third dimension for it); the
inward angle before the ear point is. The side view shows the far temple
only where it differs. Dimensions in the DXF are lines and text, not
dimension entities.

### The 2.1 bug hunt (2026-11-03)

Three reviews of the two November rounds, before the release.

**Two-sided is each part's own.** The *Two-sided* fold shows for the front
and for a temple and read as the open part's, and was one project-wide
setting: a front switched *Off* took a temple's outer face with it. The
choice and the output are the part's own now (`cam_overrides`), *Auto* as
shipped for both; a 2.0 project's parts carry none and cut as they did.

**A temple's meshes.** *Mirror to the other side* put a twin at the other
end of the same temple, which has no center line to mirror about; the box
is hidden on a temple and a saved mirror is ignored there. The face list
says *Hinge face*, *Outer face* and *Edge* on a temple, and no longer says a
mesh on the front waits for "the flip setup". A deboss removed or switched
off on the 2D page stayed in the 3D model; the temple's records rebuild the
part as the front's do. Linked temples copied a mesh's record without its
file, so the other temple showed the record and built, posted and saved
nothing of it; the bytes travel with the record. The viewer kept the
front's surface as the one a drop or a drag on a temple read, and seated
the mesh on the front's point; each part hands the viewer its own. The
drag's overlay outlived its row when another was selected or the row
removed, taking the clicks over it and dropping the wrong mesh; it is put
away with the row. A source several meshes share was repaired once per
mesh on every rebuild; once. A simplified sculpt took the largest flat face
as its back where the maker had chosen another; it keeps the one that
faces the way the chosen one faced. One plane in pieces whose fitted
normals straddled a rounding boundary came as two backs; facets are grouped
by angle. The repair's record said *inside-out, flipped* for a shell the
turn did not save and reported the coarsest remesh grid as the finest.

**Smaller things.** The temple planner raised out of an empty tool library
instead of posting the temple alone; the viewer's `clear` carried a stray
docstring; British spellings in comments, docstrings and one identifier are
American. The user guide no longer says the flip setup is a later release,
names the controls as the sidebar does, lists the readiness dot's fourth
state and the simulation's key, F6.

### A temple turns over its length; its simulation shows the flip (2026-11-03)

**A temple's two-sided job flips the blank over its length.** The front
turns over about the fixture's vertical line, its X mirrored, the dowel
pins above and below the blank. A temple blank is a long strip: it now
turns over its length, Y mirrored about the blank's center line, the pins
at either end in the waste margin, so the hinge end stays at the end it
was, against the zone's stop. The fixture names the line as `flip_axis_y_mm`
on each temple zone, the zone's horizontal center by default; a temple zone
that names `flip_axis_x_mm` asks for the front's flip instead. The anterior
program is mirrored accordingly, the flip's pause says *hinge face up; flip
about machine Y … mm, over its length*, and the setup sheet carries `part`,
`mirror`, `flip_axis_y_mm` and `mirror_y_mm` beside the fields it had; a
2.0 sheet reads as it was. GuildSend reads the front's form only for now
and describes a temple's flip as the front's.

**The temple's simulation plays both setups.** It simulated the hinge
face's program alone. It now cuts the outer face from the blank turned over,
turns the result back and cuts the temple program from it; the log carries
both verdicts as *Anterior:* and *Posterior:* lines, an anterior that fails
fails the job, and the 3D playback stops at the flip and ▶ turns the blank
over its length and goes on. A temple posted as one file,
`temple_two_sided_cut.nc`, had nothing the simulation would read; it is
split at the pause and simulated like the two files. Two-sided is *Auto*
for the front and the temples alike, as shipped; a test now holds it so.

### Section titles, the temples' link, Embossing, and a temple's second side (2026-11-02)

**The sidebar's titles lose their parentheses.** *Operations (uncheck to
skip)*, *Program Zero (G54 work datum)*, *Holding (how the part stays put)*
and the rest are *Operations*, *Program Zero*, *Holding*; what the title used
to say is on the header's tooltip, and Operations carries the line *Uncheck
to skip an operation* above its boxes, which now stand in the open part's
machining order. *This part only (overrides)* is *Part Overrides*,
*Per-operation tools* is *Tool per Operation*, *Machine & Tool* is *Machine*,
*Through-cut lead-in & output* is *Lead-in & Output*, and the pocket rows are
*Component pocket depth* and *Component pocket angle* on both tabs. A pass
that is off unless ticked is no longer listed as "skipping".

**The temples' link replaces Apply to both temples.** The button at the foot
of the Temple tab copied that tab alone and was easy to miss. A chain switch
now sits at the right end of the sidebar's tab strip while a temple is open,
on every tab. *Linked*, the default, keeps the two temples alike: the open
temple's Temple, Cut and Machine settings, the program zero and the part
overrides included, are copied to the other whenever the sidebar is read
back; each keeps its own seats and fixture zone. *Unlinked*, each temple
keeps its own. Linking again asks first, since the other temple then takes
the open one's settings. The link is saved with the project; a project from
before it opens linked when its temples match.

**Sculpts are Embossing.** A SCULPT is the posterior's scalloping, so the
section of the maker's own meshes is *Embossing*, each record a *mesh*, and
the fine pass over them *Emboss Finish* (a project or a preference saved with
*Sculpt Finish* reads under the new name). The code and the project file keep
the word *sculpt*.

**A temple takes meshes and a second side.** The Temple tab carries its own
*Embossing* section and an *Emboss tool*. A deboss on the hinge face is baked
into the temple's solid and cut into the map the program and the simulation
read, by an *Embossing* operation on the ball nose in the first tier beside
the pockets; a deboss on the outer face goes into the anterior map. An
emboss stands above the blank's face and is modeled only, with a note. The
*Two-sided* section now shows for a temple: its outer face, the seats drawn
there and its debosses, which a one-sided job modeled and never posted, is
cut first as the front's anterior is, mirrored about the blank's center line
in G55 with the flip by hand, then the temple program as a one-sided job
posts it; `temple_anterior_cut.nc` and `temple_cut.nc`, or
`temple_two_sided_cut.nc` with the flip's pause, with the setups on the
sheet GuildSend reads. Preferences ▸ Parts carries the temple's *Emboss
tool* beside its other tools, and the Save offer compares it. The `.gmodel`
records the temple's meshes, the link and the setups' flip; a 2.0.0 file
reads as it was.

### The sidebar comes back from a minimized window; one control per setting (2026-11-02)

**The sidebar survives minimize and restore.** Minimizing the window makes Qt
report every dock not-visible; the Parameters toggle took that as a click and
hid the dock for real, so the restored window had no sidebar until View ▸
Parameters was ticked again. The toggle now answers only to a click, and
reads its state from whether the dock was hidden, as the Log, Toolpaths and
Inspector toggles already did.

**Program Zero loses its dead mode and gains a shift.** *Zero mode ▸ Fixture
(design frame)* posted the same program as *Stock box* at its default datum
and grayed the lists (GitHub issue #1); it is gone from the Machine tab and
from Preferences ▸ Parts, and a project or a preference saved with it reads
as that datum, so the program is byte-identical. The three lists are always
live and say where the point is on the machine: *Bottom of the blank (the
bed)* is the face the blank lies on. **Shift X, Y and Z** move the zero from
the datum, in mm along the blank's own axes, for a touch-off on a stop, a pin
or an edge that is not the blank's corner, a blank larger than the stock box,
or the spoilboard under a spacer; the log, the setup sheet and the 2D marker
say the shift. The Worktable's *Bed zero* keeps *Raw bed coordinates*, which
is a real choice there.

**One onion skin, one allowance, one tool.** The Cut tab's *Onion skin* and
*Hand finishing allowance* were the front's and showed on every part, while
the Temple and Base Curve tabs carried their own, so a temple showed two of
each with one dead. Each is one control now, the open part's: the allowance
under *Material & Allowance*, the onion skin in the *Holding* group beside
the strategy it belongs to, grayed when tabs hold the part. The Machine tab's
default *Tool* is the front's and hides on a temple or a block, which name
their own tools; the two-sided setup is the front's too and is a fold of its
own, *Two-sided*, its tooltip the anterior setup, rather than the foot of *Operations*
on every part. The *Profile fallback (no SCULPT)* group, a hard-coded tool
list with its own tabs that was never saved, is gone: a drawing without
`SCULPT` zones cuts with the default tool, the Cut tab's depth per pass and
the Holding group. The rapid clearances moved from the foot of *Feeds &
Speeds* to *Machine & Tool* (now *Machine*), and *Work-holding height* is *Hold-down height*,
the Worktable's word for it. The per-tool feeds are captioned *Per tool*:
they are the project's by tool, not one part's. The shift is saved with the
project and with Preferences ▸ Parts, and the setup sheet's `program_zero`
carries it.

### Sculpts: placed by hand, flipped, imported whole (2026-11-01)

**A sculpt slides over the frame.** *Move on the part* replaces pyvista's
arrow-and-ring widget, which moved a sculpt along world axes and could not
keep its back on the surface. The sculpt is drawn translucent in the 3D
view; drag it and it follows the surface under the cursor, its flat back
seated to the surface normal there, on the back, the front or the rim as
the surface says; the model rebuilds when you let go. An `.stl` dropped on
the model lands under the cursor. *Size* reads the sculpt's longest side in
mm beside *Scale*, and a sculpt wider than 15 mm is scaled to 15 mm when it
is added. Every snap and drag reads the frame's surface without its
sculpts, so a short move never seats a sculpt on its own old copy.

**Deboss imprints the relief.** A deboss subtracted the sculpt in the same
pose as an emboss, its back sunk 0.05 mm, so it removed a sliver and
nothing of the relief. *Flip* turns the sculpt over, its relief into the
surface, and *Sink* is then the depth of the imprint; choosing Deboss sets
both, halfway into the relief, and the stamp cuts as a seal into wax. *Sink*
ranges to the relief's height. A deboss that touches nothing says so in the
log, with the gap; an emboss lifted clear is reported as the two pieces it
makes.

**The maker's elements import whole, in two seconds.** A 326 mm baroque
panel with 123 small holes and pinched vertices took 38 seconds and came
back as one corner of itself: pymeshfix handed back a mended corner with
NoError. A 16-piece ornament with its backs cut away took 7 seconds and
lost a tenth of its volume. Holes are now capped along the faces' own fans
(a long planar loop ear-clipped, a small one fanned, a pinch walked on its
own side), a shell past capping is rebuilt as a relief over its back plane,
and pymeshfix sits last behind a loss guard. The notes say what each step
did. A large sculpt that is simplified on import is simplified in place
rather than read twice. Facets on one plane (an ornament in pieces, each
capped) are one back, so the whole of it is seated and read for sag.
`core/model/mesh_repair.py` is new; the `.gmodel` records a sculpt's
`height_mm`, `extent_mm` and the mount's `flip`, and a 2.0.0 file reads as
it was.

### The intake agrees with GuildDraw 2.0.1's readiness dot (2026-10-29)

**Two fronts are refused, as GuildDraw 2.0.1 refuses them.** A one-piece
front with both lenses on one eye (a redrawn lens left behind) was
castle-ready, split into an `ou` side, with the other eye solid. Separated
rims with one rim drawn without its lens were built as a monocle, the other
rim dropped, when the two rims were alike and the empty one came second;
when the empty rim was the larger, the partition failed with no word why.
Both now stop the castle, with a line in the log and a reason that says what
to draw. `regions.half_drawn_front` tests a lens against the other lens as
well, and `regions.empty_rims` counts a rim with no lens whether the
assembly made it a body or a stray. The Frame Library's 46 fronts are not
affected.

## v2.0.0 — two-sided cutting, inlays, sculpts, press dies, the stock engine and the Worktable redone

### HINGE becomes COMPONENT (2026-10-17)

**The COMPONENT layer.** The HINGE layer is now COMPONENT. It carries
anything mounted on the back of a part that needs a classic pocket: hinges,
bridges, endpieces and bridge bars. Every drawing, library entry and DXF
made before says HINGE, and GuildModel reads it as COMPONENT for good;
GuildDraw's component tab, its Hinge tab before, is read under either name.
The operation that cuts the pockets is *Component Pockets*. A project or a
CAM preference saved before keeps its per-operation tool and switch under
the new name, a layer color set for HINGE colors COMPONENT, and a program
stored before still has its pockets timed. The pocket depth reads
*Component depth* on the Model and Temple tabs, and the temple's pocket tool
*Component tool*. *Hinge pocket angle* keeps its name: it tilts the pockets
on the endpieces, the hinges.

**Parts carry components.** GuildModel calls its own tabs, the frame front,
the temples and the blocks, parts, as Preferences ▸ Parts and the Worktable
already did: *Export this part's watertight STL mesh*, *Bed verified — every
part reached*.

**A front's anterior seat is cut first.** The Inlays list said an anterior
seat was modeled and not posted; a two-sided job cuts it first, front face
up, and the list says so. A temple's outer-face seat is still modeled and
not posted.

### Two-sided jobs: the anterior first (2026-10-17)

**The anterior is cut first, and only what its features need.** A
two-sided job now cuts the anterior first, with the blank front face up
while it is still a flat slab, and then the posterior after the flip, front
face down on the bed. The posterior program is the one-sided program, byte
for byte: the relief, the hinge pockets, the through-cuts and the onion skin
or the tabs, in G54. The anterior program, in G55, cuts the Fine Relief and
the Features pass over the anterior's chamfers, bezels and round-overs, and
the anterior seats; it cuts the Rough Relief only where the front is cut
deeper than one contour stepdown, and it never cuts a hinge pocket or a
through-cut. All the major removal happens in the posterior program, with
the piece flat on the bed, where it is most secure, and the onion skin holds
the part through all of it. M24 cut the posterior first, less its
through-cuts, and released the part on tabs from the front; that order is
gone, and the *Through-cuts* choice with it. A project that carries the
choice opens without it.

**The anterior finishes at the edge.** When the anterior is cut, the stock
past the part's edge still stands, so a feature that runs to the edge, a
brow chamfer for one, was left uncut there: the relief and the Features
band stopped one tool radius past the part, and the ball never reached the
chamfer's foot. The anterior's relief now reaches two tool radii past the
edge, and the Features pass reaches the ball's radius past its band, so each
feature is finished to the edge and the posterior's perimeter takes the
rest. On a library front with a brow chamfer and anterior seats, the ball
now cuts 0.75 mm deeper, to the chamfer's foot, and the anterior simulates
99.9 percent complete.

**Two files, or one with a pause.** *Output*, under *Two-sided* on the
Cut tab, chooses how a two-sided job is posted. *Two files*, the
default, writes `anterior_cut.nc` and `posterior_cut.nc`; the posterior's
header says what to do after the anterior. *One file, pausing for the flip*
writes `two_sided_cut.nc`: the anterior; then the spindle stopped, the tool
raised and the flip's pause (`M0`); then the posterior in G54, with a tool
change where the tool differs, and one `M30`. One tool table serves both
setups, so a tool keeps its number. On a rotary (M26) the turn is the
program's own, with no pause. The setup sheet lists the setups in the order
they run, and its `run_mode` is `two_file`, `single_file` or
`rotary_indexed`. GuildSend stops at the one file's flip as at any flip; its
guided two-file sequence still looks for M24's `back_cut.nc`, so until it
reads the setups it offers the two programs to choose from, and the anterior
is the one to run first.

**The flip, simulated.** Simulate cuts the anterior from the fresh blank
turned front face up, then turns the result back over and cuts the posterior
from it. The log gives both verdicts, *Anterior* and *Posterior*, and an
anterior that fails or warns carries into the job's verdict. The 3D view
plays both setups as one: the playback stops at the flip and names it, and
▶ turns the block over about the flip line and goes on with the posterior.
The one file is split at its flip for the simulation and gives the same
verdict as the two files. In the Toolpaths inspector the anterior's
operations, listed first as *Anterior · …*, are colored and name their
tools, and the 2D view draws their paths where they fall on the part,
turned back over the flip line; a row's checkbox shows or hides them as it
does the posterior's.

**After the flip.** With *Probe Z after the flip* on, the probe now runs at
the start of the posterior, on the blank's back. Without it, the posterior
of a manual flip says where its Z0 is: the bed, which the flip does not
move, or with a top-face zero the blank's back, to touch off on. A blank
with the pad block lies front face up for the anterior on a spacer as thick
as the pad, the pad in its cut-out; with the default zero, Z0 is the bed
for both setups, and the anterior program says so. On a pressed blank the anterior is cut with the
slab back down over the dome nest, and the posterior with the slab front
down in the cup; the nest's files are named for that, `nest_back_down` and
`nest_front_down`. A one-setup program still leaves an anterior seat out,
and the log says that Two-sided cuts it first.

**What the anterior leaves of the hold.** The posterior's through-cuts stop
an onion skin above the front face, and the anterior, cut first, takes
material off that same face. The log now says where the anterior cuts deeper
than the skin at the edge of a through-cut: along part of a ring, how much of
it, since the rest still holds; all round a ring, with a warning, because a
whole perimeter so cut leaves the part free when the posterior's Perimeter
cuts through, and a whole lens opening frees its core when the Eyewires do.
An anterior bezel is such a ring. On tabs, the perimeter's hold is the tabs'
height. On the library front, the brow chamfer takes the skin off 38 percent
of the perimeter, and the rest holds the part.

### The middle of a pocket, and a narrower Stock tab (2026-10-17)

**A pocket's passes overlap at its middle.** A hinge slot exactly two tool
diameters wide, 4.0 mm for the 2 mm end mill, was cleared by one ring a tool
radius in. The next ring, a stepover further in, did not fit, and the ring's
passes met on the slot's center line with no overlap. That is a fin of no
thickness on paper and a real one under an end mill a hair under size; in
the simulation it was a column of cells standing the pocket's full depth,
in one pocket of the pair, wherever the grid fell. Where the passes would
overlap at a pocket's middle by less than a tenth of the tool's diameter,
the cascade now goes once round the core it leaves: the hinge pockets, the
inlay seats and the filled engraving alike. A pocket whose passes already
overlap posts as before. On the library front both hinge pockets and one
anterior seat take the extra pass, a few seconds each.

**The Stock tab narrows with the rest.** A checkbox does not wrap, and the
pre-formed blank's long label held the Stock tab 100 pixels wider than any
other tab, so a narrowed sidebar scrolled it sideways. The two pressing
options read *Pre-formed blank* and *Apertures and groove first*; their
tooltips say the rest.

### The contours over the pad, the splay's seam, and a dock for each kernel (2026-10-17)

**The contours cut where there is material.** On a blank with the pad block,
every eyewire ring and the perimeter cross the pad, and each ring was cut whole
from the pad's top down; above the blank's top, most of each pass was in air. A
pass above the blank's top now cuts only the stretch of the ring over the pad:
it goes down and comes out in air past the pad's edge. The stock the program
leaves is the same; three corpus fronts on the shipped stock are cut 42 to 67
seconds sooner, and across the corpus the eyewires' feed is down 18 to 20
percent and the perimeter's 18 to 24. On a pressed slab, whose bottom is not
flat, each pass likewise cuts only where it goes deeper than the one before.

**The tabs stand where the floor is reached early.** On a stock whose bottom
is not flat, the tab height was the last pass's least depth along the ring,
which is nothing where the passes reach the floor early, and the part was
released with no tabs at all. The passes before the last now stop over the
tabs' tops, and the last pass rises over each tab. A tab is at most one
depth per pass tall.

**The pad splay is cut the way it is finished by hand.** The angle cut comes
first, from the crest toward the frame's edge at the splay angle; then the seam
nearest the front, where that cut meets the edge, is rounded over. **Seam
blend** sets its radius: 1 mm by default, at most the minimum edge thickness. The
crest, the most posterior seam, is left sharp for tumbling on every kernel. The
raster kernel's 2 mm crest round-over, which only kept its grid from shading the
crest as a jagged ridge, is gone with its Crest blend control; a project that
carries it opens without it. The three kernels now cut one section. Where the
angle cut would pass below the minimum edge thickness, it keeps its angle and
is floored there; the mesh and B-Rep kernels made the angle shallower until
the cut fit. The raster kernel holds the crest inside the body as the others
do, walking it back where it would step into the nose notch; it halved it.

**The dock shows what the kernel builds.** Sculpts are built and cut by the
mesh kernel alone, so the Sculpts section and the Sculpt Finish operation are
hidden on the B-Rep and raster kernels. A front's sculpts are kept for the mesh
kernel, and the log says when a build or a program leaves them off.

### The 2.0 bug hunt (2026-10-16)

Seven reviews before the release, each fixed and pinned by a test the same
day (`tests/test_bug_hunt_v200.py`, `tests/test_bug_hunt_v200_gui.py`).

**At the machine.** The rotary turns the blank from the top of Z travel
(`G53 G0 Z0`), both for the flip and for the unwind at the end; it turned
with the tool parked a few millimeters over the stock, inside the blank's
swing. A flip whose swing the profile cannot show clears the tool is
refused. A blank with the pad block is turned over onto a spacer as thick
as the pad, its cut-out holding the pad: the whole stack turns, Z0 is the
stock's bottom on the bed on both sides, and side two's through-cuts follow
the stock's bottom down through the pad and stop on the spacer elsewhere.
They stopped at the sheet, the part still held by the pad, and the program
says to set the spacer under the blank. With Two-sided On and nothing
cut on the front, side two on the rotary is turned as the blank is; it was mirrored as for a flip by hand,
and its perimeter ran where the part is not. Side two's probe runs down
from where the tool is left (`G91`),
and the touch sets the stock top's height plus the plate's in the
program's own frame; it set the plate's top as Z0, and the program's Z0 is
the blank's bottom by default. The plate's thickness is a new field beside
*Probe Z after the flip*, and without the probe the note names the value
to set. Side two and the hybrid's flat program are clamped to the machine
and checked like side one; they posted the feeds as asked. The low hops
between passes keep clear of the fixture's own screws, sized for the
widest tool in the program; they knew only the blank's corners and the
lens centers, and passed over the inner screws on five of the eight corpus
fronts. A profile may give the spindle's spin-up time, and each M3 that
starts it is followed by a dwell; 0, the default, writes none.

**The cut.** A pocket or a seat whose offsets split, or that holds an
island, is cut without crossing a wall: each loop is entered by ramping
down from the level above. A mount under the pad block starts above the
pad, not inside it. An op with nothing to cut posts nothing; hinge pockets
too small for their tool led the program and paused for a tool change.
A contour ring that keeps clear of the pad block starts at the blank's
top, not the pad's; on a pressed blank each pocket starts over its own
part of the slab, not over the slab's highest point. Generate Base-Curve
Block from the Front tab posts the block on its own tab, at its own
program zero; it replaced the front's program. The Features op cuts with
the 2 mm ball by default: the flat end mill left up to a millimeter on
chamfers, bezels, the pad splay and round-overs, and the ball leaves about
a tenth of a percent of them. A job with a Features op therefore changes
tools for it. On a pressed blank the finishing passes reach two tool
radii past the part, so a flat tool finishes an edge that the tilted
surface falls away from; one radius left half a millimeter or more along
the lens openings. Side two of a pressed blank cuts its anterior features:
the front's cut depth, carried onto the formed grid, missed cells along a
chamfer's foot, and they held the tools up off the chamfer.

**The simulation.** A stored program is simulated from its program zero;
a corner or a top-face zero failed every verdict. Simulate in an unsaved
session generated the program and then generated it again, forever.
Side two is simulated whenever there is a back program, and side one's
warning is carried into the job's verdict. The lens groove cutter's shank
starts above its neck, so a grooved front no longer fails for the neck in
the rim; the shank's real reach to tall nosepads is still reported.

**The verdict.** The verdict's stock starts as the stock is; it stood a
millimeter over the stack and read the nosepads' tops as uncut on every
front. The largest piece left standing in one place is judged by its
volume, and the verdict says where it stands: over 0.5 mm³ it warns, and
over 2 mm³ it fails. The fractions alone passed a hinge pocket left uncut,
which is a fraction of a percent of the body. A gouge deeper than a
millimeter counts from two cells out of a step; the band kept for the grid
hid a perimeter cut into a wall. On a pressed blank the two cells widen by
the walls' lean, and material the blank never had is short, not gouged. The
verdict also asks whether the part is released: above the skin or the
tabs, the body may join neither the blank round it nor the core of a lens
opening, on the side that makes those cuts. On side two of a pressed blank
the part's own underside is no longer counted as left standing.

**Forming.** The pressed blank the CAM cuts is the one the dies press: the
bridge projection and the face form only when the dies carry them. The
bridge punch's nose stands the projection proud of its shoulders; it went a
sheet's thickness further. Pre-cut dies are sized to the blank they press,
with no zone cutaways. A grooved pressed front is cut round its front edge.
The punch's Auto radius is the forming's own die, and a saved press row's
radius is carried only when this machine lacks the row. A monocle forms to
its base curve alone: it has no second eye to wrap toward, so its face form
is off, and the press's wrap no longer creases it.

**The project file.** A program saved after the design moved on comes back
stale, not current, and Export G-code asks before writing one. A DXF
project keeps its part's own settings through a reopen. A damaged file is
an error the window reports; a damaged file opened from the desktop closed
the app. A project whose drawing does not parse leaves the window as it
was. A file from before two-sided machining opens one-sided, as it was cut.
Opening a project no longer rewrites the CAM preferences the next drawing
starts from. The libraries and the default bed are written so an
interruption leaves the old file. A save clears the crash-recovery
snapshot. The dock keeps the pad block's offset, the footings' order, the
bezel's minimum thickness and the overrides it has no widget for. A tool or
a material the library lacks is named in the log. A value out of range (a
number that is not one, an infinity, or a negative where none is possible)
is set to its default when the file opens, and the log names each one; it
reached the post.

**The window.** Each job's progress dialog is its own, and a program or a
simulation that lands after a tab or a drawing changed is kept on its own
part or dropped; a quiet rebuild closed Generate's dialog. Reload Drawing
keeps the sculpts and gives a part drawn since the last open its new
switch. Generate refuses a lens outside the body, as Build did. A sculpt
with no flat face is reported. Each part keeps its own mesh verdict, and a
tab switch no longer checks a mesh again. The pad splay's crest blend is a
raster kernel setting, and it is disabled on the other kernels. The
anterior bezel's width answers to the groove's front flank, and the groove's
anterior offset to the bezel's cut; the shipped bezel took most of the
flank.

**The drawing.** A front is classified about its own axis, so one drawn
off the drawing's origin is named as it would be on it. A closed spline of
two nodes is both of its arcs. A curve that crosses itself keeps its area,
and one the file describes wrongly is skipped and logged instead of
stopping the drawing. One lens in an outline drawn for two, a third lens,
and a lens that crosses its rim are each refused with a warning. Seats
keep their settings when the front moves on its blank. The rim lip
re-partitions at any groove depth the drawing allows, so the groove's
range is the drawing's. The raster kernel leaves decorative openings
square, carves against the rim lip with the groove on, and cuts an edge
feature that runs the whole ring at full depth all the way round. Its lens
groove stays within the rim wall's height; on a short wall the groove's
edges stood above the wall's top or below its bottom.

### Separated rims, the monocle and the guide sizes (2026-10-16)

A combination frame's front, acetate rims on a metal bridge, is drawn in
GuildDraw as two closed OUTLINE curves, each holding its lens, and is now one
Frame Front with a body per rim, cut from one front blank. Of the OUTLINE
curves inside no other, the largest is a body and so is any that holds a
lens, as GuildDraw's validator sorts them; a curve that holds no lens is a
stray, as before. Each rim partitions as a standard half: endpiece, eyewire
superior and inferior, nosepad, and over the nosepad the rim's end of the
bridge, at the bridge's height; no zone spans the gap, and the per-kind
heights apply. The three kernels build a body per rim and the verdict expects
one; the program cuts both apertures, a perimeter around each rim (one ring
around both, with a note, where the gap is narrower than the tool needs) and
both sides of a two-sided job; the keep-outs sit at both lens centers.

The bridge mount is one shape across the gap, on HINGE or on INLAY, and is
cut into each rim's end. A HINGE pocket that reaches no endpiece is a mount:
its depth is taken from the terrace it is cut into, its floor is flat, and
the depth's range answers to that terrace; a pocket on an endpiece keeps the
endpiece rule. Separated rims form to the base curve and the face form; the
bridge projection is off, and so are its controls and the dies' bridge
tooling. The pad splay and the bridge relief need a one-piece front's bridge
and stay off. A lens that lies in no body stops the castle and is named in
the log, as is an OUTLINE curve drawn open.

GuildDraw's Ghost is a drawing aid, and GuildModel reads the curves drawn and
never applies it. A front with one rim and one lens, a monocle, is one rim:
it partitions as a standard half and builds, cuts and forms as either rim of
a pair does. A new project sizes the front's blank and pad block, and each
temple's blank, from the guides the drawing carries; without them the shop's
defaults stand.

### The fourth axis: the indexed flip (BUILDPLAN M26, 2026-10-15)

A machine profile may now carry a fourth axis, off by default: the
controller, the axes, the rotary (letter, what it turns about, its sign,
its centerline, its rate and travel), inverse-time support, and the
spindle-nose-to-table height a swing must fit under. *Guild CNC (fourth
axis)* ships as a profile of placeholders for the bench; the fixture file
says how the blank is mounted. On a rotary bar, a two-sided job flips by
the machine: side two is side one with Y and Z negated about the
centerline, and the back program begins with `G0 A180` and the side's
offset, with no pause. The post writes A words to three decimals, runs a
move in which the rotary and the feed arrive together in inverse time and
never as an arc, refuses an A word on a three-axis profile or past the
travel, and unwinds the rotary at the end; the lint names an A word the
profile cannot run; the cut-time estimate charges a turn at the rotary's
rate; the simulation turns the stock about the centerline and cuts side
two from it. The guide's §5 says what a rotary does for a curved front and
what it does not: the groove waits for five axes.

### The pre-formed blank: cut after pressing (BUILDPLAN M25, 2026-10-15)

*Pre-formed blank* on the Stock tab cuts the front after it is pressed to
the Forming view's curve: the stock is the slab pressed by the same map
that makes the pre-cut dies, the target the formed model, and the masks,
the hinge pockets and the seats are taken at the back's footprint while
the eyewires and the perimeter are taken at the front's, where a
three-axis cut makes the walls vertical. Each through-cut pass sits a
stepdown below the local top and stops a skin above the local bottom,
the skin measured along the surface's normal; the tabs ride the local
floor; the hinge pocket floors follow the curve at their depth. The 3D
view shows the pressed slab; the simulation starts from its mesh, and its
verdict allows the walls' lean in the rim band and says how much it is.
The lens groove is left out with a sentence, or cut flat first by the
hybrid, *Apertures and groove first*, which posts the apertures and the
groove in a program of their own before pressing. A flat project is
byte-identical. A pre-formed front is cut in its nest, not on the bed.
*Export Nest…* on the Forming panel writes the nest: the pre-cut dies' cup
for side one and the post-cut dome for side two, on the dowels; a
two-sided job on the pressed blank turns the slab over in it, and the
simulation cuts side two from side one's result upside down.

### Two-sided jobs: the flip (BUILDPLAN M24, 2026-10-15)

A front that takes material off the front, a brow chamfer, an anterior
bezel, a seat or a sculpt there, posts two setups. Side one is the
posterior program as always, in G54, less the through-cuts; side two cuts
the anterior in G55 after the blank is flipped about the fixture's flip
line onto its dowel pins: the anterior Z-map becomes a relief of its own,
mirrored and re-zeroed on the fixture plane, so the relief, the Features
pass, the seats and the sculpts are cut by the same generators, and the
eyewires, the holes and the perimeter go last with the part released on
tabs. A front that takes nothing off the front posts one setup, byte for
byte as before. `back_cut.nc` begins with G55, the flip pause GuildSend
parses extended with the flip line and the work offset, and a G38.2 probe
block when asked; the setup sheet carries the setups; Export G-code writes
both files. The simulation reads both programs: side two is cut from the
stock side one left, flipped bit for bit, and the log carries both verdicts.
The Cut tab's Operations group chooses Two-sided (Auto, Off, On),
Through-cuts (side two or side one) and the probe; the Guild bed's fixture
file names the two pins on the flip line. The guide's §5 has the bench test.

### Press dies: the molds for the formed front (BUILDPLAN M23, 2026-10-15)

*Export Dies…* on the Forming panel writes the press's molds, cut to the
forming you set: a posterior die, a convex dome under a flange; an anterior
die, a cup in a block; and, post-cut, a bridge punch and a V anvil for the
bench. The dies are made from the forming map and the silhouette, never
from the modeled front: hinge pockets, seats, chamfers and sculpts play no
part in a mold. The dome follows the eyewire terrace and is cut away under
every taller zone, the nosepads first; the anterior die is the plain
negative set back by the silicone mat rolled over the dome and by the
clearance. The closed gap is terrace + mat + clearance over the whole face,
and the dies close flange to flange on two dowels. Post-cut dies relieve
the inside of each eyewire so only the rim band is supported; pre-cut dies
cover the blank and carry no eyewire geometry. The panel and the log report
the gap, the cutaways, the outer size, and the formed DBL, lens width,
frame PD and overall width against the flat ones. The parameters live
with the forming in the project file; a file from before opens with the
defaults. The guide's §2 says how to press.

### Sculpts: your own meshes on the frame (BUILDPLAN M22, 2026-10-15)

Drop an `.stl` on the 3D view and it is on the frame: repaired, its flat
back found, snapped to the posterior at the center and sunk so the union is
one body. Emboss adds it, Deboss cuts it; Mirror derives the twin; a handle
in the 3D view moves and turns it, and the model rebuilds when you let go.

* **Import that survives real files.** The soup is welded, an inside-out
  shell turned, an open shell mended by pymeshfix, overlapping shells
  unioned rather than summed, and a shell nothing can mend offered as its
  hull, labeled. A scanned back with no exact facet is grown from the
  mesh: ten microns of noise on every vertex still recovers the mounting
  normal to a few parts in ten thousand.
* **A sculpt on the back is cut.** It lands in the surface the posterior
  program posts, its footprint joins the feature band, and a *Sculpt
  Finish* operation, off unless ticked, runs a ball over the footprint at a
  stepover from a 15 micron cusp. A sculpt on the front changes nothing the
  posterior program cuts, byte for byte.
* **What a tool cannot reach is said.** After each build the log reports
  the area that faces down between the part's two envelopes.
* The project file (`.gmodel`, format 2) carries each sculpt's bytes under
  `features/`; a file from before loads as it did. The mesh kernel builds
  sculpts; the raster and B-Rep kernels do not, and the panel says so.

### Inlays: the INLAY layer, modeled and cut (BUILDPLAN §8a, 2026-10-15)

A closed curve on GuildDraw's new `INLAY` layer, on the front or a temple, is
a **seat for a plaque, a laminate or a plate**. The drawing carries the shape
and nothing else; GuildModel keeps one inlay per curve, with what the drawing
does not say, and cuts it.

* **One row per seat**, in an *Inlays* group on the Model tab and on the
  Temple tab: enabled, a name, the face it is cut into, the depth (the
  insert's thickness), a flush offset for a seat cut shallower or deeper
  than that, step or island, the tool and the depth per pass, and the
  minimum thickness it must leave. A seat starts at the part's **Inlay
  depth** (1.0 mm; beside the hinge pocket depth on each tab, and a shop
  default in Preferences ▸ Parts) and on the **visible face**: the front of a
  frame, the outer side of a temple. Each seat then keeps its own.
* **What a seat is relative to is read off the drawing**, never typed. A seat
  drawn inside another seat is a step down from the parent's floor and takes
  the parent's face. A seat drawn inside a HINGE curve is a step in the hinge
  pocket's floor: it inherits the pocket's plane, tilt included, and sits on
  the hinge's face. The panel shows the floor each seat measures from, and
  the 2D canvas draws a nested seat darker.
* **An island is left standing.** Switch a seat drawn inside another to
  *Island* and its parent is pocketed around it: a raised monogram on a
  plaque. The island's own depth sinks its top; 0 leaves it at the surface.
* **All three kernels cut the same seats** from one list made of the
  parameters (`core/geometry/inlays.py`), the way the anterior bezel's band is
  made once and read three times: the raster carves them after its surface
  snapshot, so the relief passes sail over them; the mesh kernel and the B-Rep
  subtract them as prisms, trimmed by a tilted hinge floor where one is
  inherited. The three agree to the cell on every fixture.
* **The program.** Posterior seats are pocketed by a new **Inlays** operation
  with the same ramped lap entry as the hinge pockets, parents first, after
  the relief has finished the surface each seat is measured from and before
  the eyewires open the apertures; on a temple it rides beside the hinge
  pockets while the blank is rigid. Each seat's levels begin just above its
  own reference plane rather than at the stock top. The hinge tool cuts them
  unless a seat names its own tool, which posts as its own operation. The
  operation can be skipped on the Cut tab like any other, has a row in the
  per-operation tools, and is billed on its own in the cut-time estimate.
* **An anterior seat is modeled and previewed, not posted.** It shows in 3D
  on every kernel and the panel's row says *not posted*; the posted program
  is byte for byte the one without it, as the anterior eyewire bezel has been
  since M17. M24's flip setup cuts it on side two.
* **Two checks.** A seat its tool cannot enter is left out and named in the
  log and the Inspector, with a tool that fits. A seat whose floor leaves
  less than its minimum thickness against the other face — a plaque seat on
  the front under a hinge pocket on the back, say — is named too, in the
  log, the Inspector and the generate summary; the setup sheet lists every
  seat with its face, depth, floor, whether it posts and whether it keeps
  its thickness.
* **A re-imported drawing keeps every seat's settings.** Seats are matched
  by their place in the containment tree and by centroid, so Reload Drawing
  and a reopened project pair each saved inlay with its redrawn curve; a seat
  that moved far is paired in order, a new one starts from the defaults, a
  deleted one is dropped. *Apply to both temples* copies the inlay depth and
  leaves the other temple's own seats alone.
* **What does not change.** A drawing without the layer models, posts and
  simulates exactly as before: the tests pin the posted programs
  byte-identical. A project from 1.8 opens with no seats and the defaults.

### The stock engine, under the hood (BUILDPLAN M21, 2026-10-15)

The cut simulation's floor is becoming a **stock**: a grid whose every column
holds a list of solid intervals instead of one height, so a side-cutting form
can take a slot out of a wall and leave the material above it, a tool can cut
from below, and a half-finished blank can be carried from one setup to the
next. Nothing on screen changes yet; this release carries the engine and its
proofs.

* `core/stock/`: the dexel grid, the tool shapes (the drageoir's V form among
  them), the cutter, the posted program read once into runs, and the report
  that compares a stock to a target cast from the model mesh, with the
  volumes left standing and taken.
* A C++ kernel, `guildmodel_stock`, built by the release workflows and
  installed from `ext/`; without it the NumPy reference answers, bit for bit
  the same and several times slower, and the log says so once.
* The gabriel front's program sweeps in 0.045 s where it took 0.66 s, at a
  third of the memory, and the floor is the same array. A rapid through
  stock, or a shank entering it, is found and reported rather than stamped.

And on screen, the same night:

* **Simulate reads the stored program.** The simulation is of the program the
  machine will run, the one stored on the tab, read at the cutting grid; it
  generates the program first when none is fresh, as Simulate Bed has since
  M20.
  The verdict is today's, cell for cell, with the volumes left standing and
  taken added to the log and the Simulation page; a rapid through stock or a
  shank in it fails the verdict, with the operation named.
* **The bed is cut once.** `worktable.nc` goes into the placed blanks on the
  posting grid, and that one result is the verdict and the playback: no
  second build, no compositing of floors, the rotation right by construction.
* **The block is a closed solid in one piece**, its top rewritten in place as
  the playhead moves, which renders at about twice the old rate. A column
  holding an undercut is tinted, and **Solid**, offered when the cut has one,
  shows the stock through Flying Edges at a pause and at the end: the lens
  groove's slot in the eyewire wall, which the top surface could not show.
* `core/sim` keeps its names as a facade over the engine: the parsers are one
  walk of the program, and the floor sweep every test and tool reads is the
  stock engine's, so the whole suite verifies the new path.

### The sidebar folds (2026-10-15)

Every section of the parameter dock — Model Properties, Posterior Finishing,
Edge Features, Inlays, Zones, and the sections of every other tab — now folds
under its header with a click, the way the Worktable panel's sections have
since M20. GuildModel remembers which sections you folded, with the rest of
the window layout, and opens a section it has not seen before. The Inlays
section lost its paragraph to the header's tooltip and keeps only what a seat
needs every time in view — enabled and its name, what it is relative to, the
face, the depth, step or island — with the flush, the tool, the depth per
pass and the minimum thickness under a *Cut details* fold.


### The Worktable, redone (BUILDPLAN M20, 2026-10-14)

The nest was not saved; nesting rebuilt every program behind a modal; a nest
went stale without saying so; there were two commands named Generate
Worktable Program; there was no Simulate Bed button; the canvas had no
keyboard, no snapping and no context menu; the summary was a message box.
And a worktable program generated on the Worktable tab was written onto
whichever component sat behind that tab, on save and on the next tab switch,
and came back on reopen as that component's program.

* **Placements are saved with the project** and reopen where they were,
  nudges and turns included. A part whose zone no longer exists is reported
  unplaced. A project from 1.7 with the old bed layout is converted.
* **Placing is not generating.** A part's footprint — its blank and the
  outline it cuts — is placed on the bed with no program in hand.
  *Auto-place* fills the zones by role at once and leaves the placed parts
  alone; *Re-place all* starts over, behind a confirmation. The programs are
  made at *Generate*, once per part, and a part whose settings did not change
  is not rebuilt.
* **Staleness shows.** Each part's row carries its state: placed, unplaced,
  needs Generate, collision. Any edit that would change the program — on any
  tab, a zone's role, the hold-down, the bed zero, a move on the bed — marks
  the part; the Program line says whether the bed program is current, on
  reopen too.
* **One Generate, and Simulate Bed on the panel.** The File menu's Generate
  Worktable Program of the fixed fixture is gone; the panel's Generate is the
  one. Simulate Bed sits beside it and generates first when the program is
  stale. The summary is the setup sheet, in the same dialog the component tabs
  show, bounded to half the screen; the default-bed offer no longer stacks
  behind it, and is made on Save.
* **The canvas.** Drag with snapping to the zone's center within 3 mm (Shift
  disables it); arrow-key nudges of 0.1 mm (Shift: 1 mm); R and Shift+R turn
  the part; a right-click menu to rotate, send to another zone or remove;
  hover highlight; the blank drawn dashed under the cut. The live clearance
  check grows what the program sweeps by the largest tool: a front's body less
  its lens openings, a temple's body, a block's outline ring, since a block's
  mounting holes are drilled at the fixture's screws on purpose. The exact
  check, operation by operation, runs at Generate and goes on the setup sheet.
* **The panel in four groups** — Bed, Zones, Parts, Program — each folding
  away under its heading; the selected part's zone, rotation and offset are
  controls on the Parts group.
* **The worktable program has a slot of its own** in the project, and is the
  job GuildSend streams when the project has one. A 1.8.x project whose
  worktable program had been written onto a component is healed on open.
* **Flows.** File ▸ Reload Drawing (Ctrl+R) re-reads the drawing and keeps
  every part's settings and placement; a watcher on the file lights a
  status-bar chip, *drawing changed · reload*, rather than interrupting. A
  drawing, project or DXF dropped on the window opens. A drawing builds its
  frame front on open and shows it in 3D (Preferences ▸ General turns it
  off). The front's 2D view is captioned *Back view (posterior), mirrored
  from the drawing*. A stored program over a model that failed verification
  drops the readiness dot to yellow, *Program stored · model has problems*;
  the green now reads *Ready for GuildSend*. Save As takes Ctrl+Shift+S and
  Simulation moves to F6, a saved override of the old chord dropped. The
  window title carries the version. Open in GuildSend knows a Linux
  checkout's launcher venv. The Windows installer offers GuildModel under
  Open with for `.gdraw`, never as the default.

### Session two of M20, from the maker's first drive (2026-10-14)

* **The simulations carve the blank as listed**, its full size, the pad
  block on the front's, not the relief grid cropped to the cut; on the bed,
  each blank sits placed among the hold-downs, so the playback shows the
  stock on the bench.
* **The bed verdict is read from the posted program.** The whole-bed
  simulation used to rebuild every relief and every program a second time;
  it now reads `worktable.nc` itself onto one bed grid, takes the front's
  relief from Generate's cache and builds only the flat parts' targets, and
  runs the playback on the preview grid. Faster by what it no longer does;
  the stock engine of M21 is the real answer.
* **The Worktable panel**: icon buttons with their words in the tooltips for
  the bed files, Remove / Undo / Redo, Auto-place, Re-place all and the setup
  sheet; the regions as a tree with the hold-downs folded away; no field
  takes the mouse wheel until clicked; the group headers read as headings in
  dark mode, not as lit buttons.
* **A walk through the tabs stays in 3D.** The view chosen on a component is
  kept across a visit to the Worktable, and a tab visited in 3D whose model is
  not built yet is built quietly rather than falling back to 2D.
* **The sidebar's tabs after a visit to the bed.** Coming from the Worktable
  to a temple, the Temple tab was missing from the sidebar until another tab
  was visited: Qt marks a tab visible on a hidden bar without laying it out,
  and a later no-op clears the mark. The panel lays its tabs out again
  whenever it is shown.
* **Snapping to the pocket's ends.** A dragged blank pushed past its zone's
  wall comes back flush to it, and one dropped within 3 mm of an end, the
  center or the stop snaps there; Shift drops it where it is. The new Snap
  action (the button beside the turns, S on the canvas, the menu) pushes the
  part flush to the end it is nearer, keeping its orientation: a 160 mm temple blank in a 170 mm zone, flipped 180°, sits
  flush to either end the other way round. A zone can also carry the
  fixture's **stop**, the edge the stock registers against, on either axis,
  saved with the bed: Auto-place and Snap then register against it.

### Parts on the bed, on and off (BUILDPLAN M19, 2026-10-14)

Batch production cuts the base-curve templates once. Until now every
populated component went onto the worktable, with no way to leave one off
short of taking it out of the drawing, and the Worktable panel had no list of
parts.

* **A Parts list on the Worktable panel**, one row per component with a
  checkbox: on the bed, or not. Unchecking leaves the part out of the
  worktable program, its setup sheet and the bed simulation without a
  re-nest; its placement is kept, hidden, and checking it again puts it back
  where it was, nudged and rotated as it was. Delete on a selected footprint,
  or *Remove from bed* on its right-click menu, unchecks the same box. Picking
  a row selects the footprint and a click on the bed picks the row. A part
  off the bed keeps its tab, builds, exports and posts on its own; its own
  program does not change. The setup sheet lists the parts left off as *not
  on this bed*, so the operator knows the program is partial on purpose. The
  switch is saved with the project; a project from before opens with every
  part on the bed.
* **A default per kind of part.** Preferences ▸ Parts gains *On the worktable
  by default* for the front, the temples and the base-curve blocks, so a shop
  in batch production opens every new drawing with the blocks off. It is shop
  policy, not a project departure, so Save never offers it; *Reset to shipped*
  restores on.
* **The bed simulation composites a rotated part correctly.** The nest seeds
  an unsnapped left temple at 180°, and a maker spins any part on the bed;
  the bed program cuts it so, but the whole-bed verification and the removal
  playback laid its floor, target and stock down by translation alone, on the
  strength of a comment that rotation defaulted to zero in the nest. They now
  apply the placement's rotation: exactly for a quarter turn, by resampling
  for any other angle, within one cell of a direct stamp of the rotated
  toolpaths. No program changed.

### A part is placed by the drawing's origin (2026-10-14)

A maker draws against GuildDraw's grid: the temple core on the zero line, the
stock blank guide centered on the origin, several drawings of one design laid
out against the same origin so every cut registers alike. GuildModel's blank is
centered on the design origin too, and the import keeps the origin, so the
drawing's zero is the blank's center. The temple snap centered the outline's
bounding box across the blank anyway, which put an asymmetric temple (a
dropped tip) off the core and drew the core guide through the middle of the box
rather than down the core.

* **Origin from drawing**, a checkbox on the Temple tab and on the Stock tab,
  on by default. For a snapped temple it keeps the drawing's zero line on the
  blank's center line; the snap along the blank (hinge end, stock side) is as
  it was, and a temple spun to the other end spins about the origin, so the
  core line holds. Off centers the temple's width on the blank, as before.
  For the frame front, on is what every project already did; off centers the
  drawing on the blank at intake, for a drawing that was never drawn on its
  blank, and toggling back restores it exactly. A base-curve block is always
  centered and has no switch.
* **The core guide runs down the blank's center line**, where the wire is,
  whatever the placement. Its width and length, long in the saved project,
  are now on the Temple tab.
* **Shop defaults.** Preferences ▸ Parts offers the switch for the front and
  the temples, and Save offers a project's departure from it.

A saved project whose temple was not drawn on the origin will show it placed
differently on reopen: the blank box in the 2D view shows where, and
unchecking the box restores the old placement.

### Fixes (2026-10-15)

* **The largest front in the library builds on the B-Rep kernel.** On one
  drawing, 165 mm across, the footing carve's multi-tool cut reported that it
  did not complete, and the build stopped there with an error; the raster
  and the default mesh kernel built the same front without remark. The flat
  rebuild that already rescues a curved base that does not close now also
  covers a curved base whose boolean fails: the front builds flat, closes,
  and agrees with the raster within 0.02%. Found by the new corpus sweep
  (`tests/test_frame_corpus.py`), which reads a local folder of the maker's
  designs when one is there and ships none of them.

### What posts the same, and what to re-post

The release check (`scripts/probe_release_compare.py`, which now drives the
Worktable as 1.8.2 does: Auto-place, then Generate) against v1.8.1 on the
gabriel fixture: the frame front and the base-curve block post byte-identical
on their own tabs. **Re-post a temple.** With *Origin from drawing* on, a
temple drawn off the zero line is placed on its blank by the drawing's origin;
on the fixture every move shifts 0.585 mm across the blank, and a temple drawn
on the origin is unchanged. **Re-post the worktable program.** The temples
carry that shift, and every part now sits in its pocket by its blank, not by
the bounding box of its cuts, as a blank-end-snapped temple already did; the
fixture's front moves 0.24 mm on the bed for it, and the blocks less than a
thousandth.

### No app launches another (2026-10-15)

The *Open in GuildSend* action, its launcher and its finder, retired from the
menu in rc2 and kept disconnected since, are removed, and nothing in the
application starts another program. The three apps never find or launch each
other: GuildSend opens the saved `.gmodel`, as GuildModel opens a `.gdraw`,
and the handoff is always a file you open.

## v1.8.1 — a drawn logo is engraved as a filled shape

A maker drew a six-armed logo on a temple's ENGRAVING layer as one closed
spline, beside the hinge pocket and a line of text. GuildModel showed the logo
as a forked stick figure with a cluster of spurs, in the 3D model, the cut
simulation and the posted program alike (2026-10-05).

### The finding

Every closed ENGRAVING curve went through the text-stroke centerline (M11 #7:
the medial axis built for glyph outlines, so an "O" is cut once down the
middle of its ring rather than twice along its edges). A `.gdraw` keeps its
engraving text as text objects, and the GUI outlines them into glyph contours
when the file opens; those contours were merged into the same list as the
curves the maker drew, so by the time the relief and the CAM saw them a drawn
logo and an outlined "G" looked alike, and both were skeletonized. The
skeleton of a stroke is its center line. The skeleton of a logo is a stick
figure.

A second, smaller finding on the same file: the drawn spline's seam crossed
itself. The logo had been traced from a DXF whose closed polyline repeated its
first vertex, with the vertex before it a few microns short of the start;
GuildDraw's Rebuild fitted that hairline as a node sitting on its neighbor.
The centerline's even-odd fill had papered over the self-intersection with a
`buffer(0)`, and the as-drawn trace does not care. GuildDraw 1.3.1 closes the
hairline at its source, in DXF import, in Rebuild and in the new SVG import.

### What changed

- `ComponentWorkspace.engraving_text` holds the glyph contours outlined from
  the drawing's text objects; `engraving_curves` stays what sits on the layer.
  `engraving_split()` hands every build `(text, graphics)`: for a `.gdraw`, the
  outlined text and the drawn curves; for a DXF, which cannot tell the two
  apart (GuildDraw outlines its text into plain closed splines at export),
  everything as text and no graphics, so a DXF temple's program is unchanged.
  `display_layers()` gives the 2D canvas both; the authored layer stays as
  read, so a re-derive cannot mistake a glyph for a drawn curve.
- `build_temple_relief` and `generate_temple_program` take `graphic_curves`,
  cut with the same bit at the same depth in the one Engraving op. A drawn
  **open** curve is a stroke, traced as drawn. A drawn **closed** curve is a
  filled shape: the closed curves combine even-odd into regions
  (`engrave_centerline.even_odd_regions`, the rule that already gave an "O"
  its counter), so a closed curve inside another is an island — an "O" is two
  circles, a disc is one — and each region is cleared with inward rings a tool
  radius in from its edge and 40 % of the bit's diameter apart
  (`pocketing.fill_rings`, hole-aware; `temple_ops.graphic_engraving_curves`).
  The relief carves the same regions flat, so the model, the simulation and
  the program agree; a region the bit cannot enter is left, as a hinge pocket
  too small for its end mill is, and the simulation reports it as uncut.
  `place_temple_curves` carries the graphics through the blank snap with the
  outline; the nest and the bed simulation pass them too.
- The Temple tab's option reads *Engrave text as stroke centerlines*, and its
  tooltip states the drawn-curve rule and the DXF exception.
- Programs: a temple whose ENGRAVING layer carries only text, or open strokes
  beside its text, posts byte-identically to 1.8.0 (the drawn curves keep
  their place at the head of the op). One with a drawn closed curve now fills
  it; re-post that temple.

## v1.8.0 — the front as it will be worn (M18)

The most-requested feature of the season: the frame front as it will be
**after forming** — base curve, face form, bridge projection — viewable in the
app and exportable as an STL with the eyewire groove in it, so a prototype can
be printed in SLA and worn.

**No program changes.** Forming is after cutting. The CAM cannot import the
forming code (gated by AST, like the kernels), the posted program is
byte-identical with forming on and off and with the groove override on and
off, and the readiness dot reads the same three job facts it always did.

### What a maker will notice

- **View ▸ Forming (F)**, a checkable view state of the one 3D viewer, on the
  Frame Front tab once a model exists. It opens a panel under the viewport —
  press, base curve, face form, bridge projection, eyewire groove, flat ghost,
  a readout, and Export Formed STL — and swaps the formed front in. Off
  restores the flat model from cache.
- **Live sliders**, the first in the app that are genuinely live: no debounce,
  no worker, no pending-rebuild flag. Measured on the gabriel drawing through
  the real window, a drag of the projection or the die handle redraws at
  about 110 ms a tick, nine times a second, on a bridge band meshed at 0.5
  mm; the warp and the normals are about 20 ms of it and the rest is VTK. The
  four handles that move the crease layout (gap, angle, offset, blend) show
  the uncut front while they move and re-cut it on release.
- **Base curve in diopters**, 0 to 16 in the quarter steps a frame is ordered
  in, the way the SBT forms are tagged. On a press row the die's own radius is
  what the model bends to (the SBT dies are R259 / R181 / R144 for base 2 / 3 /
  4, which are not 530 / D); off a row the optical convention is the only
  radius there is, and the radius in use is shown beside the slider.
- **The bridge is formed the way the bench forms it**: a convex die against
  the posterior, a V plate bracing the anterior, the classic crease along the
  plate's two edges and the bulbous bump between them. Three controls beside
  the projection: the **crease gap** (the distance between the creases at the
  bridge's top edge, seeded from the drawing's bridge width), the **crease
  angle** (how fast the creases converge toward the nose, seen from the
  front) and a **bridge offset** for a bridge that is not drawn centered. The
  bump shrinks with the V's width toward the nose and carries an aviator's
  brow bar forward with it.
- **The die has its own radius.** The bump across the gap is the anvil's
  section: an arc of the die's radius on the center line and a straight
  flank tangent to it down to each crease. *Auto* is the largest die that
  still reaches the projection through the gap (the arc through both
  creases); a smaller die gives a defined bulge with flat flanks, a wider one
  rests on the V plate before it reaches the projection and the readout says
  how far it got. A **crease blend** rounds the fold at each crease into the
  flat with a fillet of the given radius; *Sharp* is the plate's own edge.
- **The projection is forward only.** The die only ever presses the bridge
  away from the face, so the slider runs from 0 to 8 mm and a negative value
  in a file is read as none.
- **Clean creases, no streaks.** The first build refined the whole part to
  one edge length and let VTK derive the shading from the formed triangles,
  and in use that showed two things: a ragged crease, because a triangle
  straddling a fold shows it as a zigzag, and streaks across the rims, from
  slivers in the castle's own tessellation that the warp turned edge-on.
  Now the flat model is simplified before it is refined (84 % of the
  streak-making slivers gone, no dimension moved), the mesh is cut along the
  crease planes so each fold is a chain of edges, the bridge band is refined
  to 0.5 mm on screen and 0.25 mm in the file against 3 / 1.5 mm elsewhere,
  and the vertex normals are computed by the forming code — area-weighted,
  split at the part's edges and at every live crease — so a crease is drawn
  sharp at any angle and a blended one smooth. A sliver thinner than the
  simplification's own tolerance takes the normal of the smooth side it lies
  on instead of being read as a fold, which is what drew wedge-shaped facets
  with a hairline between them along the posterior outline of the Paula.
  `core.forming.tessellate` carries it; the map moved no differently.
- **Presses.** The maker's SBT base-curve press rows ship as presets
  (`config/presses.yaml`): base 2 / 3 / 4 with lens curve 4, and base 2 with
  lens curve 2. A maker's own presses go in `~/.guildmodel/presses.yaml`,
  merged the way tools and materials are. Picking a row sets the base curve
  and the face form together; touching a slider makes the choice Custom.
- **Export Formed STL…** writes `frame_front_formed.stl`: a fresh build at
  export resolution with the groove override applied, refined to 1.5 mm
  outside the bridge and 0.25 mm in it, cut along the creases, formed,
  welded at float32 (an STL's own precision, so a slicer that merges by
  position finds one closed body rather than edges shared by four faces),
  verified, written. **Export All STL** adds it whenever the project's
  forming is not flat. The file is one closed body in millimeters.
- **The strip label** carries the mode instead of the triangle count while
  forming is on: `FORMED · SBT base 4 · 4.00 D · 164° · +4 mm`.
- The forming values are saved with the frame front in the `.gmodel`. Every
  earlier project opens flat. Two comments that called GuildDraw's *Apical
  radius* "the base curve" are corrected: it is the crest of the bridge in
  the frontal plane, and nothing crosses the seam from GuildDraw.

### How it is modeled

One smooth map from the flat model to the formed part, in the maker's own
vocabulary: every eyewire a spherical cap of the press's radius apexed at its
lens center; the face form an included angle at the bridge center line, spread
over the bridge zone's width; the bridge a displacement forward between two
creases — the die's own section pressed into the V plate's gap: its arc on
the center line, a flank tangent to it down to each crease, the same die
resting on the plate's edges as the V narrows toward the nose, and a fillet
at the crease when a blend is asked for. Thickness rides the local normal, so
the castle keeps its depth everywhere; volume is not preserved (the posterior
is on the concave side and is compressed a few percent), and that is stated
so nobody measures a formed volume and calls it a defect. The map is applied
to the mesh kernel's own triangles — simplify, refine, cut the creases in,
refine the band, then move every vertex — so nothing is rebuilt and nothing
is re-booleaned.

### The finding

The spike bent the projection as a smooth S over the bridge zone's own
half-width. At 4 mm of set that S-bend has a tightest radius of 5 mm, and a
10 mm castle offset along the normal at a 5 mm radius folds through itself.
The fold is neither a gap nor a self-touching edge, so the closure check called
the part "Model verified" while it carried **7 % more volume** than the flat
one. The V-crease bump replaced it the next day for a different reason — it is
what the bench actually does — and it cannot fold: a displacement along z is
monotone in z whatever the gap or the angle. What can still bend too tightly
is the reverse bend between two rims apexed at their own lens centers, at a
steep base curve; the map reports its tightest radius, the tests hold it above
the fixtures' thickness at every press row and across the panel's projection
range, and at 16 diopters the readout and the log say when it drops under.

### Hinge pocket angle

A new **Hinge pocket angle** tilts the floor of each hinge pocket. The default
is 0°, which is the flat floor of every earlier release; a project saved before
this version loads at 0° and posts the same program, byte for byte.

- **Frame front** (Model tab, under Hinge pocket depth). The superior edge of
  the pocket keeps the set depth; a positive angle sinks the inferior edge and a
  negative angle raises it. This changes the pantoscopic angle at which the
  temple leaves the endpiece.
- **Temple** (Temple tab). The anterior edge, nearer the hinge end, keeps the
  set depth; the posterior edge moves. This offsets splay that is built into a
  hinge. The Temple tab also has a **Hinge pocket depth** control now. Before
  this, a temple always cut at 1.0 mm, because the tab did not keep the depth
  a project had saved.
- **Range.** The slider travels only as far as the drawing allows: both edges
  of the longest pocket stay between the surface and 0.5 mm above the anterior
  face. The depth's own range narrows to match when the angle is not 0°.
- **One floor everywhere.** The preview, the mesh and B-Rep solids, the
  simulation and the Hinge Pockets operation read the same floor plane, so
  they agree on the tilt.

This is the one exception to "no program changes" above. A tilted pocket is cut
with the same ramped levels, and each point is held at the height where the
uphill edge of the flat end touches the floor, so the tool never cuts below the
plane. After the levels, a tilted pocket gets a **finishing pass** in the same
operation and with the same tool: level lines along the floor's contours,
0.25 mm apart, zigzagging down the slope. A flat pocket gets no finishing pass,
so its program does not change. Simulated at 5°, the pass takes the worst ridge
on the floor from 0.08 to 0.105 mm down to 0.022 mm (`0.25 × tan(angle)`) with
either the 2 mm or the 3.175 mm cutter. A pocket narrower than two tool
diameters had few ridges to begin with; the demo hinge with the 3.175 mm cutter
was at 0.007 mm before the pass. The line spacing is
`pocket_finish_stepover_mm` in the project's cut settings.

A strip of up to `2 × r × tan(angle)` remains against the downhill wall: 0.27
mm at 5° with the 3.175 mm cutter, and 0.17 mm with the 2 mm cutter. A flat
end cannot reach it without cutting below the floor elsewhere, so clean it up
by hand or leave it for the hinge leaf's edge radius.

### Part defaults, and offers that can be silenced (2026-09-27)

Added before the tag, from the maker's own bench. A shop that cuts components
one at a time at macroed zero positions on its bed — the Small Batch Tools
bed; the maker's earlier setup — touches off every part at the same corner of
its blank, job after job, and until now every drawing opened at the schema's
center/center/bottom for every part, with the temples' blank-end snap and
stock side likewise re-set per project.

- **Preferences ▸ Parts.** The defaults a newly opened drawing or DXF starts
  from, per kind of part — Frame Front, Temples, Base-curve blocks: the
  **program zero**, the temples' **snap to blank end** and **stock side**, the
  blank sizes and the pad block, the block's mounting-hole pattern (it is the
  jig's) and each part's tools, with *Reset to shipped* on each group. A
  project keeps its own values: changing a default does not touch an open
  project, and a reopened project shows what it saved.
- **The offer on Save.** Save a project whose program zero or stock, or whose
  temples' snap or stock side, differs from the defaults and GuildModel asks
  once whether to make them the defaults — only where every enabled part of
  that kind agrees, since two temples zeroed differently are the project's
  business. The stock is one line per kind of part (the blank, and on the
  front the pad block) and is adopted whole; a maker standardizes their own
  blanks as surely as their zeros. Each line has its own checkbox, all
  checked to start, so a new zero can be taken while a one-off job's blank is
  left; Yes adopts the checked lines. Each line is asked about once: saving
  again asks nothing more, and a further change asks about that change alone.
  Not asked on autosave or on the silent save after a worktable program. The hole pattern and the tools
  are set in Preferences and never asked about: those vary per job often
  enough that an offer on every save would be noise.
- **Don't ask again, where it belongs.** The four offers GuildModel makes —
  the default bed, the part defaults, saving tuned cut settings back to the
  material, saving a project's per-tool feeds to the tool library — each carry
  a *Don't ask again*, and **Preferences ▸ General ▸ Prompts** turns any of
  them back on. The warnings do not: the Z-profile hold
  before an export or a handoff, the hold-down collision that pauses a
  simulation, the unsaved-changes and file-overwrite confirmations and the
  failure boxes ask every time, because each stands between the maker and a
  machine or a lost file.
- Stored sparsely in `prefs.json` under `part_defaults`: only what differs
  from the shipped default, so a shipped default that moves in a later release
  still reaches a maker who never set that field.
- **The briefest tool first.** Within what the cut allows, a component's
  program now runs the tool with the least work first, and the longest-running
  tool last, the order the worktable program has used since M6.5. On a temple
  the hinge pockets and the engraving both want the blank rigid and do not
  depend on each other, so with the pockets and the profile on one end mill
  and the engraving on its bit, the bit runs first: the operator loads it,
  starts the program, and swaps once. Holes still follow, and the profile
  still releases the part last. The front's relief is a chain, so its program
  is unchanged. **Temple programs change order**; re-post them.
- **Feeds and speeds per tool.** The Cut tab's Feeds & Speeds group is now
  the material row — the program's own feeds, as before — followed by one row
  per tool the open component's program uses, each showing what that tool
  will cut at and where the number comes from: the material row, the tool's
  own library feeds (the shipped engraving bit runs at 300 mm/min and
  14000 RPM, which its tip needs), or this project. Until now a tool's library
  feeds won silently over the tab, which read 1200 while the bit cut at 300.
  Type into a row to set a feed, plunge or spindle for this project; *Reset*
  gives the tool back to the library or the material; a chip-load read-out sits
  on every row. The rows follow the tool choices on the Temple, Base Curve and
  Machine tabs. Stored in the project as `cam_params.tool_feeds` (empty in
  every earlier project, which posts unchanged) and carried to the next
  project like the rest of the Cut tab. One resolver serves the tab and every
  posting path — a part, the bed, the simulation — and the setup sheet now
  times each operation at its own tool's feed. Generate a program whose
  per-tool feeds differ from the tool library and GuildModel offers, once, to
  save them to the library, the way the material write-back works; the project
  keeps its own values either way. The temple and block programs
  also now take the Cut tab's material row for tools without their own feeds,
  as the front always did, instead of the preset behind it.
- **A typed number settles when you are done typing.** Every spin box now
  applies on Enter, Tab or a click away — the feed rows, the spindle fields,
  the hole and tab counts, the worktable's size, hold-down and rotation.
  Typing 1500 into a feed used to post 1, 15 and 150 first, each one a CAM
  change, a preferences write and, on a temple, a preview rebuild, which is
  the lag the maker felt. The sliders still render live while they move.
- **Tooltips wrap, and they can be switched off.** A tooltip is laid out at
  about fifty characters a line, in the widget's own font, instead of one
  ribbon across the screen. A **?** button at the far end of the toolbar
  turns tooltips off everywhere and back on; the setting is remembered, and
  the button's own tooltip still shows so you can find your way back.
- Showing the Toolpaths or Inspector panel queues a deferred arrangement of
  the docks; if the window closed in the same tick, that call ran on a dead
  window. It checks first now, as the Log panel's already did.
- **Pop-up windows fit the screen.** The Preferences window opened at Qt's
  fallback, two thirds of the screen's width, and its height was whatever its
  one non-scrolling tab demanded — on a panel with the UI scale up, that put
  the OK button below the screen's edge; two tabs' one-line hints also fixed
  its width at over 900 px. Every tab scrolls now, the hints wrap, the window
  opens at the size of its content within the screen it is on, and it
  remembers the size you leave it at. The operation summary's table is bounded
  to half the screen, so a long bed program scrolls instead of pushing its OK
  button off the bottom.
- Five group titles on the Model, Cut and Machine tabs — *Material & Allowances*,
  *Feeds & Speeds*, *Machine & Tool*, *Edge Features (chamfers & fillets)*,
  *Through-cut lead-in & output* — drew their ampersand as a keyboard mnemonic,
  underlining the space after it. They read as written now.
- **Apply to both temples**, at the foot of the Temple tab: copies the tab —
  blank, snap and stock side, hinge pocket depth and angle, engraving, tools,
  onion skin, hand allowance, holding — onto the other temple, so both cut
  with the same tools and depths. Each temple keeps its own fixture zone,
  program zero and cut settings. The copied-to temple's model and stored
  program are marked stale, as an edit on its own tab would; the button is off
  when the project has one temple.

### Fixed in the second pass (2026-09-28)

Five more read-only reviews over the 2026-09-27 additions, before the tag.

- **A typed number reaches the action.** A spin box applies on Enter, Tab or
  a click away; a toolbar button takes no focus and a shortcut moves none, so
  typing 1500 into a feed and clicking Generate on the toolbar, or pressing
  Ctrl+G, posted the old feed while the field read 1500, and Ctrl+S saved the
  old one. Every action that reads the panel — Generate, Build, Save, Export,
  the handoff — now applies the field it finds being typed in first. Autosave
  does not; it must never touch what is being typed.
- **A single-tool front posts at its tool's feeds.** A front whose hinge
  pockets share the bulk tool is a single-tool program, and that path posted
  the material row, timed the setup sheet at it and simulated at it while the
  Cut tab's row for that tool read *this project* or *tool library*. Every
  program now resolves its tools' feeds the same way, with or without a tool
  block.
- **The Feeds & Speeds rows follow the component.** Switching to a component
  restores its cut overrides with signals blocked, and the rows kept the
  previous component's feeds against the new one's material row; a reopened
  front's lens-groove row was missing until the next edit. The rows are
  recomputed on both paths, and a temple whose outline holes are pinned to a
  tool on the Machine tab has a row for it.
- **A front's program is a chain in every tool setup.** With the hinge tool
  also on the fine relief, that tool outweighed the rough one and the pockets
  moved after the roughing, which the notes above promise does not happen;
  each of the front's operations now holds its own tier.
- **Adopted defaults stay sparse.** Saying Yes to the Save offer wrote the
  project's value verbatim, so a project that had gone back to the schema's
  value stored that value rather than no entry, and a shipped default that
  moves later would not have reached that maker. It is stored as the page
  stores it.
- **A default naming a deleted tool is dropped**, so the schema's tool applies
  and shows; left in, the dock kept whatever it last showed, an inactive part
  fell back to the library's first entry, and the page kept the dead name.
- **The Preferences window on a short screen.** Its minimum height stood
  above a small panel's usable height, so the OK row was under the edge again;
  the floor is bounded by the screen. Its editors' spin boxes also apply on
  commit now, as the dock's do, so the tool editor stops redrawing per digit.
- **Simulations run at the Cut tab's material row**, as the posted programs
  do, not at the preset behind it; the bed simulation takes the project's
  per-tool feeds as well. The bed's setup sheet times each part's operations
  at that part's own feeds, and the fixture worktable no longer logs each
  clamp warning twice.
- The tool-feeds write-back offer is fresh per opened project, like the part
  defaults offer.

### Found at release (2026-09-29)

Posting the Gabriel drawing's front, block, temple and worktable through
v1.7.0's code and this release's found two faults with one cause: the Cut
tab's feed, plunge and spindle are filled from the project material, and a
part cut from another material was given them anyway.

- **A lone base-curve block cut at the front's feeds.** The per-tool feeds
  made the Cut tab's row the default of the block's program, so the acetal
  block posted at acetate's feed, plunge and spindle, twice acetal's feed,
  with its header still saying acetal. Never released. The block's program is
  again byte-identical with v1.7.0's, and its Feeds & Speeds rows show acetal.
- **The worktable cut its block as acetate.** The bed read a block's material
  only from a Cut-tab override, which a block does not carry by default, and a
  block with one still got the row. The block now cuts at its own material's
  feeds on the bed as on its own program; the rest of the worktable program is
  unchanged. Worktable programs change; re-post them.
- The rule is one function, `feeds.for_material`: a part cut from another
  material than the project's gets the row unset, so its material's preset
  fills it, and its own override still wins. The panel, the bed and the core
  seam all read it; a temple given its own material follows it too.

### Checkboxes you can see (2026-09-29)

- An unchecked checkbox all but vanished on the dark chrome: the platform
  style drew its outline from the background color. The stylesheet now draws
  every checkbox, in the dialogs and in the list views, in both modes: a light
  outline on the dark chrome, and, when checked, filled with the ink and
  ticked, like a checked toolbar button. It scales with the UI. GuildDraw 1.3
  carries the same rules.

### The cut simulation's memory (2026-09-30)

- **Simulating a cut no longer needs memory in proportion to the path.** The
  simulation stamps the tool's footprint at every position along a path, and
  it built the whole (positions x footprint cells) table for a path in one
  piece: about fifty bytes an element. A 1 mm tool on a 0.02 mm grid has a
  footprint of 7,854 cells, and one 50,000-position pocket path asked for
  15 GB. That is the hinge pocket finishing test, and on 2026-09-29 it took
  the maker's machine down in the middle of the suite. The stamping now runs
  in batches of two million elements, about 100 MB. A minimum is the same
  taken in parts, so the simulated floor is identical bit for bit
  (`tests/test_toolsim_memory.py` checks it against a position-at-a-time
  reference for every tool type). That test now peaks at 0.2 GB and runs in
  half the time.
- The suite collects garbage after every test. The meshes and solids the tests
  build sit in reference cycles, and the run held about 6 GB by its end; the
  24 forming fixture tests alone went from 3.4 GB to 0.45 GB.
- Checked before the tag, again: the gabriel front, block and temple post
  byte-identical with v1.7.0, and the worktable differs only in the block's
  feeds and its spindle line, as noted under *Found at release*.

### Fixed after publication (2026-09-30)

- **A slider clicked into place stayed "down".** A click on a slider's
  groove jumps the handle there on every platform. The jump handled the press
  itself and never passed it to Qt, and Qt follows a drag, and takes the
  release, only for a press it saw land on the handle; so the release of a
  groove click was ignored, the slider never reported the value as settled,
  and every later change to it (an arrow key, a wheel notch, the next click on
  the groove) was reported as a drag still in progress. In the Forming view, a
  crease-layout handle clicked into place left the drag's uncut base on
  screen, streaked at the bridge with its creases missing, until the castle
  was rebuilt, and a project saved afterward carried the handle's previous
  value. On the Model tab, a slider clicked into place rebuilt the mesh but
  never invalidated the stored program, marked the project changed or logged
  the build. Dragging the handle recovered it. Since 1.5.0; the Forming view
  made it visible. The jump now hands Qt the press at the handle, and the
  release settles the value once, as a drag's does
  (`tests/test_param_slider_mn4.py`). The 1.8.0 downloads were rebuilt with
  this fix on 2026-09-30.

### Fixed in the pre-release bug hunt (2026-09-26)

Seven read-only reviews over the whole program, one slice each, before the
release workflows were turned on. What a maker will notice:

- **A reopened project keeps its program.** Opening a `.gmodel` restored the
  stored program to the window and then wiped it when the first component tab
  was activated: the readiness dot came up red, Export G-code was disabled, and
  the next save (including the silent one after a simulation) dropped the
  program from the file. It had done this in every release since 1.0.
- **Every component's program is saved.** A whole-model project wrote only the
  active tab's program and stamped `has_program` on the others. Each
  component's program set now rides in the file under `components/<id>/`; the
  top-level `program/` set stays the active component's, which is the job
  GuildSend streams, and a v1.7.0 file opens as before.
- **Cancel works.** The Cancel button on every progress dialog (Build 3D,
  Export STL, G-code, Simulation, Nest) reached the worker only after its job
  had finished. It now stops the job at its next checkpoint.
- **The bed program's safe height is the parts' own.** The nested worktable
  program took its rapid height from the fixture's nominal stock thickness; an
  8 mm blank on a 6 mm pad block put every rapid 1 mm inside the block. It is
  now the tallest placed part's stock top, plus the hold-downs, plus the
  clearance; and the post refuses any program whose rapid plane is not above
  every cut, since the simulation cannot see a rapid.
- **Found at release, fixed before it.** Closing the pocketing helper's rings
  (for the profile fallback's sibling, `pocket_paths`) doubled the seam point of
  every hinge pocket and relief ring, which changed every front's program from
  v1.7.0's while the whole suite passed. Reverted there, closed in the wrapper,
  and a test now fails on a zero-length move. Posted against v1.7.0: the default
  front, a temple and a block are byte-identical; the front on tabs differs only
  in its release pass's entry.
- **The profile-only fallback cuts the whole ring.** The perimeter, the tabbed
  release pass and each decorative hole were posted open: the closing segment
  (1.3 mm on the aviator; a whole side of a rectangular hole) was never cut.
- **The guide's shortcuts.** The guide had Ctrl+O and Ctrl+Shift+O the wrong
  way round; its table now lists every default and says which two are fixed.
- **Forming view.** A saved forming keeps its die radius when its press row is
  not installed on this machine (the preview and the export bent to different
  radii, and the first slider touch rewrote the project); a base-curve drag
  off a press row moves the part at once; a layout drag that ends where it
  began puts the cut front back; F on a teaching stage steps to the pockets
  stage; the groove-override base is built once per state, not once per
  landing during a drag, and a failed build is not retried per tick; the
  export progress bar no longer runs backwards, and Cancel is heard during the
  forming step; the fold readout reads the sign of the bend, so a safe 16 D
  aviator no longer warns and a bridge set that the reverse bend between the
  rims cannot carry now does.
- **Hinge pocket angle.** The Model tab's ranges are computed for the reopened
  values; the last tilted level ends where the tool can reach, so it is not
  posted twice; the finishing pass reaches the corners of a non-convex pocket.
- **Smaller.** A live rebuild that finished after another file was opened no
  longer lands under the new file's name; a change made during a build runs
  after it instead of being forgotten; closing the window during a build no
  longer aborts the process on exit; prefs are written atomically; a fold-in
  save that fails marks the project dirty; a hand-edited clearance of 0, a NaN
  in the forming block, a pocket angle past the slider, a feed rate of 0 and a
  press row named Flat or Custom are refused with a reason; a corrupt default
  bed or machine profile is logged rather than silently replaced; the B-Rep
  closure check reports its own failure as "open", not "closed"; the suite's
  two trimesh warnings are gone; the macOS Intel test gate has a budget that
  fits the suite.

### Fixed the same day, at the maker's word

The bug hunt's deferred list went back to the maker, who took five of its
seven items and the spin-box note:

- **Each component on the bed cuts under its own settings.** Both worktable
  paths clamped the project's cut settings once against the project material
  and posted every nested part at them, so a base-curve block in acetal cut
  at acetate's feeds and depth per pass. Now every op carries its
  component's own context: its overrides layered on the project's settings,
  its material's feeds and depth per pass, clamped to the machine, with a
  tool's own feeds from the tool library still winning as they do for a
  single part. The post adopts it as each op begins and re-issues the
  spindle speed when it differs; the bed simulation re-derives each part
  under the same settings. The log names each part's material and feeds as
  it nests. (Holding is per part already: the front's Model tab chooses
  tabs or the onion skin; a temple or a block is always skinned.)
- **An opening the tool cannot enter is said.** A decorative hole narrower
  than the tool plus its allowance offset away to nothing and was skipped in
  silence; the Holes op now notes it, with the size and the tool, and every
  posting path logs the note with a ⚠.
- **A tabbed release pass ramps in.** The pass rises over its tabs, so it
  was not constant-Z, and the ramped lead-in refused it: a straight
  slot-plunge to the floor instead. The ramp is an offset above the path's
  own z now, falling to nothing over the lead-in, and the lap keeps its tabs.
- **A rebind onto Quit or Preferences is refused.** Ctrl+Q and Ctrl+, are
  bound outside the hotkey registry, so a maker could put Build 3D on Ctrl+Q
  and Qt, seeing two actions on one key, fired neither. Preferences ▸ Hotkeys
  now reports them as conflicts, holds OK until they are resolved, and a
  prefs file from before falls back to the default with a log line.
- **A failure is said to the maker.** A build, G-code, export, simulation,
  nest or bed-simulation failure landed in the log with a status-bar pointer,
  and the log panel is hidden by default. A non-modal dialog now names the
  failure with the exception's own last line, and its Show Log button opens
  the panel; one dialog, updated, never a stack of them.
- **The Cut tab settles a typed number once.** Typing 1500 into a feed fired
  1, 15, 150 and 1500, and each one invalidated the program, dropped the cut
  simulation and the toolpath overlay, wrote the prefs file and re-read four
  YAML files; the spin boxes commit on Enter, Tab or a click away now, and
  the tool, material and style stores re-read their files only when the
  files change.

### Still deferred

- The forming tick spends ~20 ms of 73 warping the edges a second time and
  hashing the normals; the layout cache entry is 6.6 MB, now capped at four.

### Carried, not fixed

- The crease is a real fold, so a 1.5 mm export edge that straddles it sits
  up to ~0.3 mm off the surface along the crease line; a gate holds it under
  0.5 mm. Refining finer would cost triangles everywhere for a line.
- A grooved export — flat or formed — carries eight coincident edges from the
  groove sweep that a slicer's vertex merge turns into four-face edges. It is
  one body and passes the app's own verification; it did in v1.7.0 too.
- The Forming panel sits *under* the viewport rather than floating over its
  lower-left corner: the viewport is a native GL window, and a Qt widget
  floated over one is the class of XWayland embedding trouble the app has
  already had once.
