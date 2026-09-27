# Changelog

Release notes by version, newest first. The README keeps one status paragraph
and the current release's note; everything else lives here.

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

### How it is modelled

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
