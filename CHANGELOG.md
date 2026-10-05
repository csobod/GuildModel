# Changelog

Release notes by version, newest first. The README keeps one status paragraph
and the current release's note; everything else lives here.

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
