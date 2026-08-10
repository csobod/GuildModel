# BUILDPLAN-NEW — The Model Kernel, Re-examined

*2026-08-07. Written after the Stage 2 curve work hit a wall: user-visible
breakage (a spike of material off the nosepad, features that corrupt the model)
on a real drawing, with every automated check green. This document is the deep
audit that was asked for: what our chosen method actually is, what the evidence
says about it, what the alternatives are, and what to do. Every number in it was
measured on this machine, this week, on this codebase — the probe scripts are in
`scripts/` and the session history is in BUILDPLAN.md's Stage 2 log.*

---

## 0. First operation — the interface (UI-0). *Added 2026-08-07, runs before everything below.*

The kernel is not the only thing at a wall. The interface is struggling on the
maker's own machine — the primary platform this project exists for — and the
mandate is the same shape as the kernel audit: **an in-depth UI/UX analysis**,
not another spot fix. Two distinct problems, one operation.

### 0.1 Rendering: the scaling has now been wrong in both directions

History, with numbers, because it shows why the next fix must be systemic:

| era | state | why |
| --- | --- | --- |
| before 2026-08-07 | everything ~68% of intended size, splash black | native-Wayland Qt: VTK cannot embed (X11-only renderer), and under XWayland Qt assumed 96 DPI on a 141.6 DPI panel; nobody scaled |
| after the Stage 2 fix | correct on that day's session: `gui/hidpi.py` forces `xcb`, measures the panel, computes **1.475×**, applies it to the app font and to the stylesheet's 139 `px` sizes; splash rebuilt as a `QWidget` (1096 ms → 83 ms, no black flash) | exactly one party scaled: us |
| now | fonts and splash **far too big** | to be verified, but there is one prime suspect |

**The prime suspect: two parties scaling at once.** Our factor is derived from
physical-vs-logical DPI and explicitly divides out `devicePixelRatio` — but
compositor upscaling of XWayland windows is *invisible* to the client (dpr
still reads 1.0). KDE Plasma's Wayland session can scale legacy X11 apps
itself, and that setting (or a Plasma/Qt update flipping its default) stacks
the compositor's ~1.5× on top of our 1.475× ≈ **2.2×** — "REALLY big," which is
what the screen shows. The old too-small state was zero scalers; the current
too-big state is likely two. The bug class is the same one both times:
**scaling by inference, with no authority on who scales.**

> **This suspect was wrong** — see §0.4. The compositor was at scale 1
> throughout; *we* were the only scaler, and the anomaly. The bug class named
> in the last sentence was right, which is why the fix below still stands: the
> deliverable was always the invariant, not the value. Left here as written
> because a plausible, well-argued, incorrect hypothesis is exactly what the
> "evidence first" rule exists to catch.

The fix this operation must land is an invariant, not a value: **exactly one
party applies scale, and the app can prove which one it was.** Concretely:

1. **Evidence first, on this machine.** A `--diag-display` dump (screen
   name, physical/logical DPI, dpr, platform plugin, the env overrides, the
   computed scale, compositor legacy-scaling setting where readable) captured
   under: Plasma Wayland as-is, Plasma with legacy-app-scaling toggled, plain
   X11 session, and `QT_QPA_PLATFORM=wayland` (headless of 3D, but it answers
   what Qt *would* do). No code changes until this table exists — the last fix
   was correct for the session it was measured in, which is precisely the trap.
2. **Detect, don't assume.** If the compositor is scaling XWayland (detectable:
   logical DPI ≈ 96 × compositor scale, or xrdb `Xft.dpi` ≠ 96, or the X
   screen's mm-size versus EDID disagreeing with the pixel size), our factor
   must collapse to 1.0. The one-scaler invariant enforced in code, with the
   decision logged at startup — one line in the app log saying *who* is scaling
   and *why*, so the next report of wrong-size UI is diagnosable from the log
   alone.
3. **The escape hatch is already there and must be surfaced.** The `ui_scale`
   preference (auto / pinned number / 1.0-off) exists in `hidpi.ui_scale()`;
   Preferences should expose it with a live preview, so no future scaling bug
   ever strands the maker in an unusable UI.
4. **The splash follows the same scale source** — it renders through the same
   `(dpr, scale)` pair, so it is fixed by construction, and verified with the
   same diagnostic.
5. **A platform matrix, kept honest by CI where possible**: Plasma/Wayland
   (the maker's — first-class), GNOME/Wayland, plain X11, Windows, macOS (the
   packaging targets). For each: scale correctness at compositor 100% / 125% /
   150%, splash, dark/light toggle re-derivation, and the VTK embed. The
   Wayland rows cannot run in CI honestly — they get a documented manual
   checklist instead of a pretense.

### 0.2 UX: is the app telling the user the truth, and is it pleasant to drive?

The screenshot that triggered this work shows the deeper problem: a visibly
corrupt model — a spike of material off the nosepad — over a status bar reading
**"3D model ready"** and an Inspector reading **"Nothing flagged."** Every
automated gate was green while the user could *see* the failure. The kernel
audit (§3) explains why the checks lied; the UX audit has to fix the parallel
failure: **the interface reported health it had not verified.**

Scope of the walkthrough, as a user would meet it:

- **Honest status.** The readiness dot and Inspector must reflect the *mesh
  oracle* (closed + volume sane — the only check that has ever caught real
  corruption), not the kernel's self-report. "Model ready" should mean
  *verified*, and a failed verification should name the feature it implicates.
- **Stale-state signaling.** After a parameter change, is it unmistakable that
  the preview no longer matches the numbers? (Today: a rebuild button and
  memory.)
- **Long-operation UX.** At today's 21–35 s builds: progress that names the
  stage (exists), cancellation (exists), and no dead UI. This whole category
  is scheduled to *evaporate* with the 39 ms kernel (§5F) — the audit should
  therefore fix cheaply now and design for live-drag later, not invest in
  polishing a waiting room we intend to demolish.
- **Error surfacing.** Build failures currently land in the log pane with a
  dialog pointing at it. The walkthrough asks: can a non-developer read any
  failure the app can produce and know what to *do*?
- **The panel itself.** The dock's parameter groups have grown feature by
  feature (the screenshot shows the strain); an editing pass over grouping,
  labels, units, and defaults against the vocabulary in §2 — with the maker
  driving, since they are the reference user.
- **Structural debt with UX consequences.** MainWindow is 4,183 lines / 192
  methods (2026-08-07 audit); worth splitting only where it blocks the above,
  not as an end in itself.

### 0.4 UI-0 findings — what the evidence actually said *(2026-08-07)*

Run `guildmodel --diag-display` to reproduce any of this.

**Finding 1 — we were the second scaler, and the desktop was never asked.**

| | value |
| --- | --- |
| session | Plasma 6 / Wayland, app forced to XWayland for VTK |
| primary panel `eDP-1` | 1920x1200, 345x215 mm → **141.6 physical DPI** |
| Qt logical DPI / dpr | 96.0 / **1.00** |
| KWin `Xwayland Scale`, `kscreen` output scale | **1**, **1** |
| our computed scale (old policy) | **1.475** |

The compositor was not double-scaling after all — the maker simply runs that
panel at scale 1 on purpose, and *we* were the anomaly. Every other window on
the desktop is at 1.0; ours was 1.475. The prime suspect named in §0.1 was
wrong, and the measurement is why we know.

The fix is the invariant rather than the number (`hidpi._decide`): the maker's
pin wins; a **managed desktop is followed exactly, including its choice not to
scale**; the physical-DPI heuristic fires only where nothing manages the
desktop (no `XDG_CURRENT_DESKTOP`, dpr 1, logical DPI still at Qt's 96
default). `scale_decision()` renders the reasoning as one line, emitted to the
startup log and to the diagnostic — the same code path, so the log cannot drift
from the behaviour.

**Finding 2 — the original "too small" was not a DPI problem at all.**

`/usr/lib/qt6/plugins/platformthemes/KDEPlasmaPlatformTheme6.so` exists, and the
app can never load it: **PySide6 bundles its own Qt** and searches only its own
plugin directory, which ships `libqgtk3` and `libqxdgdesktopportal` and no KDE
theme. So Qt answers with its generic fallback — `"Sans Serif" 9pt` — under both
the `xcb` and `wayland` plugins. On top of that the stylesheet pins **139
`font-size` values in px**, which overrode even that. The app therefore rendered
at one fixed size on Segoe UI 9, Cantarell 11 and Noto Sans 10 alike; "renders
well across platforms" was structurally impossible.

`desktop_font_scale()` makes the authored sizes *ratios* against a stated 13 px
design baseline (`DESIGN_BASE_PX`), so typography tracks the platform with no
DPI arithmetic anywhere. Qt's generic fallback is treated as "no answer" and
replaced with the mainstream Linux default (10 pt) rather than mistaken for a
desktop that wants 9 pt. On this machine: font 9 pt → 10 pt, stylesheet ×1.026.

Also fixed while in there: `apply_ui_scale` multiplied *the current* font, so a
second caller — which Preferences now is — would have squared the factor. It
captures the platform base once and always sets an absolute size.

**Finding 3 — "3D model ready" only ever meant "the builder returned".**

Now `core/mesh_check.verify_mesh` asks the tessellation: closed, consistently
wound, positive volume, one connected body. It drives the status bar
("⚠ 3D model has problems"), **leads** the Inspector list — a broken model makes
every downstream check meaningless, so it must not sit under a tool-reach
warning — and degrades the readiness dot green → red. Verified end to end: a
leaking mesh flips the dot to red and puts *"The surface has gaps, so this is
not a closed solid. It will not export as a valid STL"* at the top of the
Inspector.

It takes triangles, not a kernel handle, so it survives M-N1 unchanged. That is
deliberate: **the check must not inherit the bias of whatever built the mesh.**

*Amended 2026-08-08.* It inherited one anyway. Counting edges by vertex index is
asking whether the producer's own invariant holds, and index-manifold is exactly
what a mesh kernel guarantees — including across a place where the surface
touches itself, which it keeps manifold by duplicating the vertex. The check now
welds by position first (`welded_surface`), which is what an exporter does and
what a slicer sees. It was blind to 157 self-touching edges on the demo frame's
base until then; see risk 0 in §8.

**Escape hatch shipped.** Preferences ▸ Appearance ▸ UI scale (Auto, or
100–200%) with a live sample and immediate apply.

**Still open from §0.1–0.2** (not blocking, carried forward): the platform
matrix beyond this machine (GNOME/Wayland, plain X11, Windows, macOS) needs the
manual checklist actually run; stale-preview signalling; the parameter-dock
editing pass with the maker driving; and MainWindow's 4,183 lines, to be split
only where it blocks the above.

### 0.3 Deliverables and exit

A short **UI-0 findings report** appended to this file (the display-diagnosis
table, the chosen scaling authority, the UX punch list ranked); the one-scaler
invariant + diagnostic landed; the preference surfaced; the splash verified;
the top of the UX punch list fixed — at minimum honest status (§0.2 first
bullet), which also feeds M-N0's mesh-oracle gate directly.

**Exit criteria**: correct rendering on the maker's session at 100/125/150%
compositor scale with the decision visible in the log; no regression on plain
X11; the walkthrough performed with findings written down rather than held in
memory. Then the kernel work (M-N0…) proceeds below.

---

## 1. The one-paragraph verdict

The project's goals are right and most of the codebase is sound. The failure is
localized and structural: **general-purpose B-Rep boolean modeling (OpenCASCADE)
is the wrong tool for this workload**, and no amount of hardening fixes it,
because its failure modes are data-dependent, order-dependent, session-history-
dependent, and — decisively — **invisible to the kernel's own validity checker**.
This was not a mistake of language ("solids within Python"): the kernel is C++;
a C++ rewrite inherits every failure documented below, byte for byte. The
recommendation is a **staged replacement of the construction layer only** —
mesh-domain CSG via the Manifold library, driven by the same exact curves,
parameters, and partition we already have — keeping the intake, the GUI, the
CAM, and the test suite. A feasibility spike already runs the full failing
workload **220× faster with a guaranteed-closed result**. No new codebase. The
foundations were never the problem.

---

## 2. What we are actually building (the requirements, distilled)

Stated plainly, because the choice of tool has to be judged against the actual
job and not against "CAD" in the abstract:

1. **Input**: GuildDraw drawings — closed NURBS outlines, lens curves, straight
   SCULPT cuts, hinge rings — via `.gdraw` (primary) and DXF. This part is
   *done and exact*: both intakes now carry the authored curves with 0.0000 nm
   deviation (BUILDPLAN Stage 2).
2. **A fixed, small vocabulary of parametric features.** Terraces at per-zone
   heights, footing blends, hinge pockets, the lens-groove V (an undercut), the
   eyewire bezel, edge chamfers/fillets, pad splay, bridge relief, engraving.
   There is no user-driven freeform modeling. **We know every face of the
   result analytically before we build it.** This is the single most important
   fact in this document.
3. **Outputs**: a crisp interactive preview with real feature edges; a
   watertight STL; measurements (volume, sections, boxing); and G-code. **The
   CAM does not consume the solid** — it posts from the 2D curves plus the
   parameters. The solid exists for preview, export, and verification.
4. **Qualities**: Fusion-360-like feel — change a number, the model updates,
   *every time*, identically, fast. GPL-3. Linux-first. One person maintains
   this.
5. **Tolerance regime**: machining. The chord tolerance everywhere in the
   pipeline — importer flattening, raster, CAM — is **0.01 mm**. Nothing
   downstream ever consumes surfaces more exactly than that except the B-Rep
   itself.

Point 2 + point 3 together are the indictment of the current approach: we are
using machinery built to intersect *arbitrary analytic surfaces exactly* — a
research-grade problem — to assemble a known family of shapes whose every face
we can already write down, for consumers that need 0.01 mm.

---

## 3. The evidence against the current method

### 3.1 This week's user-visible bugs, reproduced and traced

The reported symptoms — a spike of material off the nosepad, features breaking
the model — were reproduced on the **aviator fixture** (the second real drawing
we own; the demo frame is clean under every probe, which is itself the lesson:
*fixture-based testing cannot protect users from this kernel*).

Measured, same code, same drawing (`scripts/probe_occt_history.py`):

| build | result |
| --- | --- |
| groove, fresh process, cache cleared | watertight ✓ |
| the GUI sequence: bare → splay → bridge → groove, caches warm (i.e. a user clicking checkboxes) | **splay leaks, bridge leaks, groove leaks — and "groove again" still leaks** |
| one-pass cut, tools ordered `groove+hinges` | watertight ✓ |
| the same call with the same tools ordered `hinges+groove` | **leaks** |
| every sequential-cut variant of the same operations | leaks |
| one full-pipeline run produced 2,485 vertices of junk **10.2 mm outside the body**; the same nominal pipeline in a fresh process produced none | the on-screen spike class |

**`BRepCheck_Analyzer` reports `IsValid = True` for every row of that table.**
Volumes agree to 0.001 mm³ between the leaking and non-leaking variants — the
geometry is "right" while the topology is corrupt.

The obvious mechanism — OCCT booleans are destructive by default and our base
cache re-feeds the same mutated shape — was tested: `SetNonDestructive(True)`
**does not fix it** (groove builds watertight once, then the *identical* build
leaks on the next call). There is no switch for this one. We looked; we have
found four off-by-default switches this week alone (`SetRunParallel`,
`SetUseOBB`, `SetToFillHistory`, `SetNonDestructive`) and the fifth does not
exist.

> #### Correction, M-N0 (2026-08-07): the headline defect was ours, not the kernel's
>
> Everything above is left as written, because the way it was wrong matters more
> than the conclusion it reached.
>
> M-N0 set out to apply the two mitigations §7 proposes for this table. Both
> were **measured and both failed** (`scripts/probe_base_reuse.py`), on the same
> aviator sequence:
>
> | mode | corrupt | wall time |
> | --- | --- | --- |
> | shared base (today) | 1 — `bridge` | 42.22 s |
> | deep-copied base (mitigation *a*) | 1 — `bridge` | 41.28 s |
> | no cache at all (mitigation *b*) | 1 — `bridge` | **80.41 s** |
>
> Identical failure, identical volume (8209.238 mm³), from a **cold** build. The
> base cache is exonerated: dropping it doubles build time and fixes nothing.
> The stale-triangulation theory died the same way — `BRepTools.Clean_s` changed
> the result bit for bit not at all (`scripts/probe_stale_mesh.py`).
>
> What the failure actually is: the bridge relief's loft ends exactly on
> `y_base`, the highest body point on the centreline, so its end cap is a plane
> *tangent* to the bridge wall. The cut leaves **one edge of 33,683 carrying
> four faces** — at x = 0.000, y = 21.695, the cutter's own base. Zero boundary
> edges. The model was never leaking; it was **non-manifold**, which is a
> different defect that our own interface was mislabelling as "gaps".
>
> Fix: one prismatic station past the base, so the cutter crosses the wall
> instead of grazing it. Aviator and demo both watertight and manifold; the part
> moves by 0.046 mm³ (0.0006%), which is the sliver the corrupt mesh had been
> mis-measuring. Pinned by `tests/test_bridge_tangency_mn0.py`.
>
> **What this costs the argument in §6, honestly.** One row of the table above —
> the biggest one, the one behind the maker's screenshot — was a bug in our
> geometry that any kernel would have punished, not evidence against OCCT. The
> "order-dependent corruption" framing came from varying the history and reading
> the pattern of failures without ever running the one control that would have
> falsified it: a cold `bridge`. That is a methodology error and it is mine.
>
> **What survives.** The rest of §3.2 is untouched: empty-but-valid,
> `BRepGProp` disagreeing with itself, the silent vertex-tolerance rejection,
> `MakePipeShell`, `MakeChamfer` at 0/30 rim edges. And the deepest point stands
> *reinforced* — `BRepCheck_Analyzer` called this valid, and the tessellation
> caught it. A kernel whose only reliable oracle is the mesh is still a kernel we
> are using as an expensive middleman. But §6 should now be read as an argument
> from **the class of failure**, not from a count of incidents, and the count is
> one lower than it was.
>
> Residual: probe run 1 showed `splay` leaking where runs 2 and 3 show it clean,
> which is unexplained and may be a second, rarer defect. Not chased — it is not
> reproducible on demand, and the mesh oracle now catches it if it recurs.

### 3.2 The season's full catalog

Each of these cost real time this week, each is recorded with numbers in
BUILDPLAN.md, and each was **silent** — no exception, no invalid flag:

| # | failure | detection |
| --- | --- | --- |
| 1 | **Empty-but-valid**: booleans returning zero-volume/zero-face shapes that pass `IsValid()` — four separate occurrences | volume guards we wrote |
| 2 | **`BRepGProp` disagrees with itself**: two *disjoint* prisms whose fused "volume" ≠ the sum, at every `Eps` setting (1550–2413 mm³ for a true 2008) | our mesh oracle |
| 3 | **Silent vertex-tolerance rejection**: `MakeEdge` refusing arc junctions 0.19–0.54 µm off (default tol 1e-7 mm), quietly leaving *two ninths of every frame polygonal* while classification, verification, volume, and watertightness all read correct | counting edges by hand |
| 4 | **`MakePipeShell`**: refuses offset-curve spines outright; 401 s + invalid on a polyline spine; the multi-section bezel sweep yields a beautiful valid 4-face cutter whose *cut* takes 260 s and returns an invalid solid with **negative volume** | trying it |
| 5 | **`BRepFilletAPI_MakeChamfer`**: chamfers a box, chamfers our own extrusions — and 0/30 rim edges on the real part at every width; non-monotonic in width on bare terraces (2.5 mm succeeds where 1.0 mm fails) | trying it |
| 6 | **Order/history dependence** (§3.1) | the user's screenshot |
| 7 | **Cost**: all-features build 20.5 s cold / 15.2 s warm polygonal, 35.0 s / 21.7 s curved — after a week of optimization that already took it down from 82.8 s | benchmark |

The pattern across all seven: the kernel fails *sideways*. Not an error, not an
invalid flag — a wrong shape, a leak, a hang, delivered with a clean bill of
health. **The only oracle that has ever caught any of these is the
tessellation**: watertightness of the mesh and volume of the mesh. Our ground
truth is already the mesh. The kernel is a 264 MB middleman between us and the
representation we actually trust.

### 3.3 What OCCT genuinely delivered (fairness)

The Stage 2 *goals* were correct and most were achieved: exact curve carriage
end-to-end (0.0000 nm), real feature edges instead of dihedral guessing, the
undercut groove as first-class geometry, sectioning and measurement, watertight
export *when it works*. The move from raster to a real model was right. The
error was equating "a real model" with "a general B-Rep kernel."

### 3.4 Why "rewrite it in C++ / another language" is a red herring

Every failure in §3.1–3.2 happens inside compiled C++ (OCCT itself). Python
orchestrates; the GIL costs us thread-level parallelism of *our* calls, but the
82 s → 35 s history shows the time is in the kernel's own algorithms, not in the
interpreter. A C++ port of this codebase would reproduce the catalog exactly,
after a rewrite measured in months. Likewise CadQuery/build123d (same kernel
underneath) change the ergonomics, not the math.

### 3.5 Defects that were ours, not the kernel's *(added 2026-08-08)*

§3.1 already had to be corrected once for blaming OCCT for a cutter we built
tangent to a wall. Since the port started, the parity work has surfaced three
more of ours, and all three have the same shape: **a sentinel value that is also
a legal measurement.** They are recorded here rather than in the §3.2 catalog
because that table is the case against the kernel and these are not evidence for
it. If anything they are evidence for the port itself — every one was found by
making a second kernel answer the same question.

| # | defect | the sentinel | found by |
| --- | --- | --- | --- |
| 1 | Pad splay cut Gabriel's frame **into two halves** — left x[-67.65, -1.38], right x[1.38, 67.65], watertight, `IsValid` true, zero holes | `surface_z_at` returned **0.0** for an anchor ray that missed, which is also "the surface is at the anterior face". The crest stepped out through the nose notch, the ray found nothing, and the chamfer — spanning up to `top` — took the whole thickness | the maker's own drawing, as a third fixture; only the **body count** caught it |
| 2 | Bridge scoop **plunged through the aviator's decorative keyhole** to z=-0.020, removing 19.471 mm³ against 14.577; and did the same on Gabriel, where the run leaves the bottom of the bridge | the same 0.0 | building the feature on the mesh kernel and comparing. On Gabriel the volume gate stayed green the whole time, because those stations are over air — wrong in the same way, cheap in millimetres |
| 3 | `offset_aperture` lost its exact curve on every rim lip, silently falling back to the Shapely buffer | a bare `except Exception` around a `NameError` | moving the function; the exception had always been there |

The fix for 1 and 2 is `geometry.rings.carry_anchors`, shared by both kernels: a
missed ray is NaN, and NaN is filled from the neighbouring station rather than
from any constant. Substituting a constant is what caused the mesh kernel's own
version of this bug — anchoring a grazed station at the anterior clamp took it
from z 5.3 to 1.48 and gouged 21% more than OCCT. **No constant is a height the
surface ever had.** Both `surface_z_at` implementations now default `missing` to
NaN so that forgetting is loud.

The methodology lesson is the one §3.1 already names, now with four instances:
**a gate must be checked against a known-wrong input, not only a known-right
one.** The groove's backwards V, the bezel's part-volume tolerance, the slab
test's convex fixture, and Gabriel's diving scoop all passed while measuring
nothing.

---

## 4. What is sound and must survive any redesign

These are assets, most of them new this week, all of them kernel-neutral:

- **The intake.** `.gdraw` and DXF both deliver exact authored curves
  (`core/geometry/curves.py` — deliberately kernel-free) alongside the same
  0.01 mm flattened points. Verified to 0.0000 nm on both fixtures. *This is
  the "reliable standard of intake file format" the mandate asks for, and it
  already exists.*
- **The 2D layer.** Partition/zones/edges (Shapely), the boxing measurements,
  `OffsetCurve` ("that curve, d inward" — exact by definition).
- **The parameter schema** (`project/schema.py`) — the entire feature
  vocabulary, typed and versioned. This *is* the parametric model; the solid
  was only ever its evaluation.
- **The CAM.** Posts from curves + parameters; never consumed the B-Rep.
  Untouched by any of this.
- **The GUI shell** (PySide6, component workspaces, the dock, the viewer).
- **The test suite as a behavioral spec** — 768 tests, including the oracles
  that actually work: ray-crossing V-profile spec (5 µm), raster-agreement
  gates, watertightness, mesh volume. These tests define what "the castle" is
  independently of who builds it.

Note what this list amounts to: **everything except `core/solid`'s construction
calls.** The seam already exists — `build_castle_solid(partition, castle,
hinges) → solid → tessellate() → mesh` — and the GUI consumes the mesh, not the
solid.

---

## 5. The alternatives, examined

### A. Harden OCCT in place — **rejected**

This week *was* that strategy, executed aggressively: four kernel switches
found, three construction rewrites (segmented arcs, swept groove, junction
tolerances), 60× on the original build time. The reward was a new
data-dependent failure on the second drawing we own, unfixable by the fifth
switch. §3.1 is the measured proof that the next trap is always input-shaped,
which means users find it before tests do. A one-maintainer GPL project cannot
staff a permanent OCCT-pathology department.

### B. Same kernel, different host (C++, CadQuery, build123d) — **rejected**

§3.4. Same math, same catalog, plus a rewrite.

### C. Commercial kernels (Parasolid, ACIS) — **rejected**

License-incompatible with GPL-3 and with the project's premise.

### D. Young Rust B-Rep kernels (Fornjot, truck) — **rejected for now**

Philosophically aligned, years from the maturity this needs; we would trade
documented pathologies for undocumented ones.

### E. Implicit/SDF modeling (libfive et al.) — **rejected as the core**

Robust CSG by construction, but surfacing via marching cubes fights exactly
what we need most: crisp feature edges and exact dimensional control at
machining tolerance. Worth revisiting someday for cosmetic preview effects;
not for the model of record.

### F. Mesh-domain CSG — Manifold — **recommended**

[Manifold](https://github.com/elalish/manifold) (Apache-2.0 → GPL-compatible;
`manifold3d` 3.5.2 on PyPI; the boolean engine OpenSCAD adopted; actively
maintained). Its entire premise is the property we keep discovering we need:
**the output of every operation is guaranteed manifold** — the halfedge
representation cannot *express* a leak — and failures are loud (`status()`
errors), deterministic, and input-side.

**The feasibility spike** (`scripts/spike_manifold.py`), run on the aviator —
the drawing that breaks OCCT — building the same workload from the same
partition at the same 0.01 mm flattening: 8 terraces unioned, 2 hinge pockets
subtracted, and the lens-groove V — *the undercut that justified the solid
rewrite* — swept as 360 per-segment convex hulls per aperture:

| | OCCT (this branch, after all optimization) | Manifold spike |
| --- | --- | --- |
| same build, cold | 8,600 ms | **39 ms** (220×) |
| watertight | **depends on click order** (§3.1) | closed: **0 boundary edges of 33,036**, counted directly |
| topology | `IsValid` regardless of correctness | genus 3 — exactly the aviator's two lenses + keyhole |
| undercut V | works (when the build survives) | present at **40/40** ray stations |
| volume | 9,152.4 mm³ | 9,237.4 mm³ (delta = the footing blends, not yet ported in the spike) |
| determinism | history- and order-dependent | identical every run |

Two honest notes from the spike, both instructive. First, my hand-rolled tube
mesh was initially wound inside-out and then self-intersecting near the
aviator's teardrow corner — **my** input bugs, caught immediately (negative
volume; visible boundary edges), fixed by construction (per-segment hulls).
That is what failure looks like in this domain: *your* bug, *detectable*,
*deterministic*. Second, `trimesh.is_watertight` under-reports on Manifold's
raw output because MeshGL splits vertices along property boundaries and carries
its own weld map (`merge_from_vert`); the direct combinatorial count (every
directed edge paired) is the correct check and comes back perfect. The export
path must apply the weld map — a footnote, now known.

**What about exactness?** The curves stay exact — they remain the source of
truth for CAM (toolpaths follow the NURBS and its offsets, as they already do)
and for measurement of record. The mesh is evaluated *from* those curves at
whatever density the purpose needs: 0.01 mm for display parity with today,
finer for export if ever wanted, coarser for live dragging. One geometry, one
tolerance knob, no second representation fighting the first. This is also
exactly how Fusion actually feels interactive: display meshes over an exact
definition.

**What about feature edges?** Better than today, not worse. We *know* every
edge analytically — ring curves at terrace heights, groove lips, chamfer
boundaries — because we authored them; they can be drawn from the curve data
directly. (Today's B-Rep hands us 23,088 topological edges, most of which are
boolean scars we then have to filter.) Manifold's face provenance
(`originalID`) additionally labels which input produced every output triangle,
for free.

**2D synergy**: `CrossSection.offset` gives robust polygon offsetting inside
the same library (today: Shapely buffer + our `OffsetCurve` + a comparative
guard), and `project`/`slice` cover sectioning.

---

## 6. Recommendation

**Replace the construction layer; keep everything else. In this codebase, not a
new one.**

Concretely: a new `core/model/` package whose public function is the same shape
as today's seam — *(partition, castle params, hinges) → watertight mesh +
feature edges* — built on Manifold primitives:

| feature | construction (all robust primitives) |
| --- | --- |
| terraces | `CrossSection` → `extrude`, one per zone, `batch_boolean` union |
| hinge pockets | extrude → subtract |
| lens groove V | per-segment convex hulls along the ring (spiked, 40/40) |
| bezel / edge chamfers | same station machinery as today, sections → per-segment hulls (no `ThruSections`, no `MakePipeShell`, no chamfer engine) |
| pad splay / bridge relief scoop | ditto — they are swept sections today already |
| footing blends | ditto — the S-profile sections already exist (`_blend_section`); swept as hull chains |
| rim lip | `CrossSection.offset` (with the existing `OffsetCurve` staying the CAM-side truth) |

Anchoring rays (`surface_z_at`) become mesh raycasts (trimesh + rtree are
already dependencies; Manifold has its own ray API).

Nothing about the GUI, intake, schema, CAM, or file formats changes. The raster
path and the OCCT path both eventually retire, taking roughly 4,500 duplicated
lines with them — the codebase *shrinks*.

**Why this is not another bandaid** (the mandate's phrase): it aligns the
construction domain with the verification domain. Every reliability incident
this season reduced to "the construction layer and the truth layer disagreed,
silently." After this change they are the same layer, and the closed-mesh
property is enforced by the data structure, not by hope. That is the structural
fix; everything else in this document is bookkeeping around it.

---

## 7. Migration plan

Staged so that at every point the app still works and the old path can referee.
**UI-0 (§0) runs first** — it is independent of the kernel choice, it unblocks
the maker's daily use, and its honest-status work is the same mesh-oracle gate
M-N0 needs.

**M-N0 — stop the bleeding (immediately, on the current branch).** *Done
2026-08-07, and it did not go the way this paragraph expected — see the
correction in §3.1.*

- ~~(a) copy the cached base (`BRepBuilderAPI_Copy`)~~ — **measured, fixes
  nothing, reverted.**
- ~~(b) failing that, drop `_BASE_CACHE`~~ — **measured, fixes nothing and costs
  2× (80.4 s vs 42.2 s). Not taken.** The warm win is 14 s on a groove rebuild,
  not the 0.6 s guessed here.
- ~~rebuild once from cold on failure~~ — **not shipped.** The cold build fails
  identically, so a retry would double the wait and recover nothing. It was
  written, measured, and deleted rather than kept as a comfort.
- **The actual fix**: the bridge relief cutter was tangent to the bridge wall,
  leaving one non-manifold edge. One extra loft station past the base. Both
  fixtures watertight and manifold.
- **Honest status, completed.** `_show_active_3d` now verifies too — Build 3D
  and every component-tab switch displayed unverified meshes, or worse, left the
  *previous* component's verdict in the status bar and Inspector. Same
  three-worker hole `gui/mesh_build.py` exists to prevent.
- `verify_mesh` now distinguishes holes from self-overlap. It called a model
  with zero gaps "gappy", which cost real investigation time.
- **Still open**: the Gabriel drawing from the screenshot as a third fixture.
  Needs the file from the maker.

**M-N1 — the mesh feature kernel.** `core/model/` with terraces, pockets,
groove, bezel, edge features, splay, scoop. Port the per-feature parity tests
to run against *both* kernels: the ray-crossing V spec (5 µm), the
raster-agreement chamfer gate, mesh volumes to a stated tolerance, watertight
always. The footing blends are the real work item (the S-sections exist; the
sweep is new). ~2–3 sessions. **Kill switch**: if footing parity cannot meet
the existing gates, fall back to hybrid — OCCT builds the (cacheable, rarely
failing) base, Manifold applies every feature to its tessellation; §3.1 shows
the features, not the terraces, are where the kernel dies.

**M-N1 is complete as of 2026-08-08, footing blends included — the risk in §8.1
did not materialise.** Every feature is ported, every gate is live with no
skips, and the whole base agrees with the B-Rep one to **0.00000%** on all three
fixtures while building in 2.4 s against 12.7 s.

The blends needed one idea that is worth carrying forward. The obvious
construction clips each blend band to the zone it acts on and applies it —
`solid - (band & zone)`, `solid + (band & zone)` — but a zone prism's walls *are*
the terraces' walls, so every clipped band arrives with a face lying exactly in a
face of the target. Manifold is exact and answers coplanar input with
zero-thickness shells: ten of them on the demo base, seven of those inverted
(internal voids), in a part that was watertight, one connected body to look at,
and correct to 7927.958 mm³. Only `decompose()` saw it. **The fix is to clip
nothing** — a carve is subtracted from its high zone's own prism, and a raised
zone is extruded full height and cut back down by a slab the band has been
subtracted from first. Exact, one boolean cheaper, and no coplanar tool faces.

That was not the whole of it, and the rest only surfaced under a measurement
nobody had run yet — see risk 0. The bands still *stopped* on the seam wall
rather than crossing it, and two zone prisms were still being asked to cancel a
wall that two separate booleans had computed. `FOOTING_CROSS_MM` and
`ZONE_WELD_MM` fix both, and the base went from 157 / 247 / 232 self-touching
edges to none without moving. The lesson to carry is not any of the three
constructions but the measurement: *watertight, one body, and exact on volume is
not the same as manifold*, and only a position-weld will tell them apart.

`Manifold.simplify` was tried first and rejected on measurement: it collapses
sub-tolerance edges across the whole part and severed a real hair-thin
connection, turning a clean bare frame into two pieces. `drop_degenerate` filters
components instead, which moves no vertex and cannot sever anything.

The port paid for itself before shipping: it found three defects in the B-Rep
path that the B-Rep path's own tests passed, two of which cut through real
frames — see §3.5. Both are fixed on **both** kernels; the shipped aviator scoop
changed by 4.98 mm³, with the maker's agreement that the old geometry was wrong.
Anything kernel-neutral that both paths need now lives in `core/geometry/`
(`rings.py`, `footings.py`) rather than being copied, for exactly the reason §3.5
documents: two copies of a rule become two rules.

*Not yet done, and not blocking M-N2:* the base is 2.4 s where the featureless
spike was 39 ms, and essentially all of it is the blends — 20 bands × 40 profile
segments × 29 stations is ~23,000 convex hulls. `FOOTING_SECTION_POINTS` is 40
only because the B-Rep path uses 40, and the sagitta says 16 would hold the
0.01 mm chord tolerance. That is M-N4's live-slider work, not parity's.

**M-N2 — into the app behind a flag.** `MultiMeshWorker` gains the Manifold
path; readiness dot = Manifold `status()` + our own boundary-edge count (the
direct check from the spike, it costs microseconds). A/B command in the debug
menu: build both, diff volumes and silhouettes. ~1 session.

*Done 2026-08-08.* The `use_solid_model` checkbox becomes a three-way
`model_kernel` choice in Preferences — raster / B-Rep / mesh — carried through
the one `build_component_mesh` choke point all three workers already share, so
there is no second copy for the next option to be forgotten in. A saved
`use_solid_model` migrates to `brep`, because prefs are restored over the schema
defaults on every launch and a new key with a new default would otherwise
silently undo a maker's choice.

The A/B landed as `guildmodel --diag-kernels <drawing>` rather than a debug menu
item, following the `--diag-display` precedent: it runs headless, it is testable,
and it works on the drawing in front of the maker rather than on a fixture. On
Gabriel it reports volume -0.0055%, silhouette -0.3585%, and 2.66 s against
13.06 s. The silhouette sign is the expected one — this path extrudes the
partition's flattened polygons, which are inscribed in the splines the B-Rep
extrudes — and the report says so, because otherwise it reads as a defect.

~~**One shortfall, and it is not cosmetic: the mesh kernel carries no edges**,
so selecting it costs three of the four display modes.~~ **Closed 2026-08-08**;
`core.model.edges` reads them off the surface and all four modes work on both
solid kernels. What had stopped it was measuring through the zero-area triangles
— see §8.2, which now carries the numbers both before and after.

**M-N3 — parity and the flip. Done 2026-08-08**, `test_kernel_flip_mn3`.

Parity is gated over feature **combinations** rather than one feature at a
time — every M13 feature was individually clean when the whole-ring defect in
risk 0 was still there, and only a combination sweep found it. 12 combinations
x 3 drawings, volume and silhouette together because volume is one number and
two very different parts can share it:

* worst **volume** delta **0.0413%** (gabriel, bezel+groove); gate at 0.1%
* worst **silhouette** delta **0.3609%** (gabriel, bridge relief); gate at
  0.75%. Looser on purpose: the mesh path extrudes the partition's flattened
  polygons, which are inscribed in the splines the B-Rep extrudes, so its shadow
  is the smaller of the two — the deficit is a property of the drawing, sitting
  between 0.22% and 0.36% across all 36 pairs and barely moving as features
  are switched on. Its *sign* is pinned too.
* every one of the 36 builds verified clean on both kernels — a real assertion
  now that `verify_mesh` welds by position rather than counting index edges
* mesh **0.23-0.70 s** against the B-Rep's **12.75-37.91 s**: 20-55x

**The default is now `mesh`**, and existing prefs files come with it
(`prefs.PREFS_VERSION`, added for this). It is safe because the setting governs
the 3D model and the edges drawn on it and *nothing a machine cuts* — which is
the real finding behind the "posted G-code byte-equivalence" clause. The clause
is satisfied, but trivially: **the CAM never sees a kernel.** Every G-code path
builds a `CastleRelief` from the partition and posts from that. So the gate that
means something is structural — `core.cam` must not be able to import either
kernel, checked by AST — plus determinism of the posting itself.

OCCT is *not* yet demoted behind a debug flag; it is still a first-class choice
in Preferences and still the third opinion the parity gates are measured
against. That belongs with M-N4, which is where retiring a path belongs.

**The anterior eyewire bezel is ported** *(2026-08-08)*, and it was a blocker:
`model.features.bezel_cutters` returned nothing unless `cuts_posterior()`, so
the mesh kernel modelled `face="anterior"` as a bare frame and `"both"` as
`"posterior"` — flipping the default would have taken the feature away from
anyone using it. Precisely the gap the B-Rep had until UI-0 finding 3, missed
for the same reason: nothing compared the kernels with the bezel anywhere but
its default face. The band now comes from one derivation,
`EyewireBezelParams.as_edge_features`, that all three paths read; the raster and
the B-Rep each had their own copy of it and the mesh had none.

It removes 291 / 353 / 320 mm3 on the three drawings where it removed nothing,
`both` is the exact sum of its halves, and all six builds verify clean. **The
B-Rep does not**, which is worth stating plainly because it inverts the usual
direction: with the anterior band on, OCCT self-touches along **74** edges on
the demo and the gabriel, and on the aviator it leaves 6 boundary edges and
removes **3.1 mm3** where the mesh removes 352.7. There is no B-Rep control for
this feature to hold to.

**M-N4 — the payoff.** Retire the raster relief path and then the OCCT path;
`cadquery-ocp` becomes an optional dev dependency and **264 MB** leaves the
install (measured: 163 MB of `OCP` plus 101 MB of `cadquery_ocp.libs` — the
"70 MB" this line carried for a season was wrong and too kind). Slider dragging
goes live-continuous: the spike's 39 ms full build is faster than one frame of
the current progress dialog. Update BUILDPLAN.md to point here.

**Landed 2026-08-09:** the CAM posts from the chosen kernel (`core.zmap.castle_relief`),
the lens groove no longer needs OCCT (`curves.sample_curve`), both solid kernels
honour `min_thickness_mm`, and `cadquery-ocp` is now an extra. The B-Rep is
demoted rather than deleted — `core.kernels` keeps it out of Preferences unless
`GUILDMODEL_BREP` is set, and `dev` still installs it, because it is the third
opinion every parity gate measures the mesh against and building the same part
two ways is what caught this season's silent defects. Still open: live sliders,
retiring the raster *relief* path, and BUILDPLAN.md.

**Landed 2026-08-10 — the Model and Stock tabs became draggable, and doing it
found three ways to ask for a frame that cannot be made.** Every measurement on
those two tabs is now a `ParamSlider`: a slider over the range the *project*
allows, a spin box over the range the *schema* means. The split is the whole
design. Dragging can never build something impossible; typing is never refused
and — the part that took a second attempt — never silently rewritten, because
`QSlider.setRange` clamps its own value and emits `valueChanged` doing it, which
came back through the sync and quietly shortened a 10 mm nosepad to 6 when the
stock changed. A value that no longer fits is kept, marked, and reported by
`ParamsPanel.out_of_range_paths`.

`core.project.limits` derives the ranges — pure, kernel-free, gated as such.
What sweeping the panel's own spin-box ranges on all three fixtures turned up:

  1. **Stock is invisible to the model.** A 15 mm nosepad out of a 6 + 4 mm
     stack builds a clean, watertight, *verified* solid. Nothing between the
     drawing and the G-code had ever compared a zone height to its material.
     The ceiling is measured per zone footprint, not assumed from the zone's
     name: overlap is worth nothing, because the part hanging off the pad block
     has only blank under it. On all three drawings the bridge and both nosepads
     sit wholly on the default 45x45 block, the eyewires lap over it (18–44% of
     their area) and the endpieces are entirely off.
  2. **A hinge pocket can come out of the front of the frame.** Demo, 5.5 mm
     endpiece: removed volume stops changing at 5.5 mm of depth (7362.9 mm3 at
     5.5, 6.0 and 8.0) because by then it is a through hole. The panel offered
     3.0 mm against an endpiece that could be set to 0.5.
  3. **A lens groove can dissolve the castle** — the rim-lip re-partition stops
     yielding the same zones at 2.30 mm on the demo, **1.55 mm on the gabriel**
     and 1.90 mm on the aviator. Two of those are inside the 0.2–2.0 mm the
     panel offered, so it was reachable by dragging. Drawing-dependent and not
     derivable, so `max_groove_depth` bisects for it (~0.6 s, once per drawing,
     only when the groove is on).

And a bug that had been sitting under (3): `lip_partition`'s guard raised
`BooleanError`, which lives in `solid/occ.py` and was never imported into
`geometry/rings.py` — importing it would pull in the 264 MB that module exists
to avoid. Nothing swallowed this one, so the maker got `NameError: name
'BooleanError' is not defined` instead of the guard's sentence. **This is the
second undefined name to come out of that same move**, after `nurbs_edge` (§3.2);
the class now lives in `rings.py` and `occ` re-exports it, so every
`except BooleanError` in `core/solid` catches the same object it always did.

Cross-platform behaviour is specified in the widget rather than inherited, since
Qt's slider defaults differ by style: a click on the groove jumps there (macOS
does, Fusion pages), the wheel only turns a control that has focus (both
children default to `WheelFocus` inside a scrolling tab — one unlucky scroll
would rewrite whatever was under the pointer), widths come from font metrics,
and `keyboardTracking` is off so typing "12.5" is one edit rather than three.

Cut and Machine keep plain spin boxes on purpose — a feed rate is a decision,
not a shape — as do the footing pairs, which share a row and have no derived
limit to show. The Model tab's content wants 394 px against 391 px before this
work: the spin boxes shrank to font-metric width and the slider took the slack.

`sliding` (live, during a drag) is kept separate from `valueChanged` (settled),
and nothing connects `sliding` yet. That is the seam the live-continuous rebuild
attaches to, which is the part of "live sliders" still open.

**Landed 2026-08-10 — the drag reaches the 3D view, and "39 ms" was wrong by an
order of magnitude.** Two things stood in the way, and only one was about
sliders.

*The window threw rebuild requests away.* `_start_mesh_build` returned early
whenever a build was running, and nothing looked again — `_on_mesh_finished` had
no notion of a pending request. A parameter changed during a build simply never
reached the preview until something else happened to trigger one. Behind a spin
box and a 350 ms debounce that was rare enough to sit unnoticed for a season;
with a handle emitting as it moves it is the normal case. Now one flag, drained
on finish: however many changes arrive during a build, what is owed afterwards
is one build of the current state. Latest-wins, paced at the kernel's own rate,
with no interval to tune and no way to livelock by cancelling faster than a
build completes. Drained on failure too — the state the parameters moved on to
may well build, and leaving the flag set would wedge every later rebuild behind
one bad one — but *dropped* on cancel, the one case where the maker has said no.

*And the debounce is the wrong instrument for a drag*, which wants no wait at
all: 350 ms of stillness before starting means a drag shows nothing until it
stops. `castle_sliding` bypasses it. It also skips the program invalidation and
the readiness refresh, which belong to a settled value — strobing the readiness
light green-to-yellow on every pixel is not information — and silences the
per-build log lines, which would otherwise bury the log under the drag's own
frames. The panel finds its live handles by walking the Model tab rather than
listing them, so a control added later is live without anyone remembering; the
Stock tab is deliberately not walked, since its numbers move the ghost box
around the part rather than the part.

**Measured, demo frame, this machine.** One full rebuild: **224 ms** bare,
**634 ms** with every posterior feature, **753 ms** with the lens groove too —
and it is all `build_castle_model`; `to_trimesh` is 1 ms and edge detection
12–18 ms. Per stage on a bare castle, `build_base` is **284 ms of 296**. So the
buildplan's "39 ms full build" predates most of these features and is not the
number any more.

End to end through the real window and the real kernel, counting redraws during
a drag: **0 before this change** (7.7 s of dragging, nothing), **20 in 9.1 s**
after on a bare castle's nosepad height, **16 in 9.3 s** on a splay angle with
the splay and bezel on. Two redraws a second, not sixty. That is honest "live"
rather than the word doing work it has not earned.

The next lever is measured and named: `build_base` does not change when a
*feature* parameter moves, and `core/solid` already caches exactly that
(`clear_base_cache`) while the mesh path does not. Caching it would take a
feature drag from ~630 ms to ~400 ms. Beyond that is `build.py`'s own note —
features are subtracted one at a time for B-Rep parity, and "the mesh domain
makes a cheaper arrangement possible". Both change behaviour rather than wiring,
so neither belongs in the commit that connects a signal.

*Three corrections from M-N3's measurements (2026-08-08). This milestone is
larger than the paragraph above, and two of its steps change output rather than
delete code.*

1. **"The raster's only remaining role is being the third opinion" is wrong —
   it is the production CAM path.** Every G-code path calls
   `relief.castle.build_castle_relief`; the `model_kernel` preference has never
   touched posting. Retiring it means the CAM posts from a solid-derived
   `Heightfield` instead, and that **changes what a machine cuts**.

   *Re-measured 2026-08-09 against the complete relief, and the "~60% of cells"
   here was wrong — it had no tolerance attached to it.* Featured gabriel,
   65,494 cells inside the body, share differing by more than the stated amount:

   | pair | max | mean | >0.01 mm | >0.05 mm | >0.2 mm | >1 mm |
   |---|---|---|---|---|---|---|
   | mesh vs brep | 8.342 | 0.0025 | 1.6% | **0.3%** | 0.1% | 0.0% |
   | raster vs mesh | 2.066 | 0.0611 | 21.3% | **12.8%** | 6.4% | 2.1% |
   | raster vs brep | 8.348 | 0.0625 | 21.3% | **12.9%** | 6.5% | 2.1% |

   A bare frame agrees far more closely still: 0/17/2 cells over 0.05 mm across
   the three drawings, worst cell 0.037 / 0.154 / 0.058 mm.

   **The claim that justifies the change, as a number.** On the 8,392 cells
   where the raster and the mesh differ by more than 0.05 mm, the two solid
   kernels — written independently, on unrelated geometry libraries — sit
   **0.0045 mm** apart on average, while the raster is **0.4525 mm** from the
   B-Rep. Two orders of magnitude, exactly where it matters. 95.5% of those
   cells lie on the raster's own feature band; the remaining 4.5% are 374 cells
   in the bridge zone, where the scoop feathers to nothing and the raster stops
   carving before the solids do. `test_cam_relief_mn4` pins this rather than
   leaving it in a paragraph. It is still a deliberate step with a maker's eyes
   on it, not a deletion.
2. **The bridge for step 1 exists now**: `core/zmap.py` (kernel-neutral
   rasteriser and relief assembly), `model/zmap.py` (the mesh side),
   `solid/zmap.py` (two lines of tessellation on top). Stage 2 had built the
   OCCT half and never wired it in. Mesh-derived and B-Rep-derived Z-maps agree
   on 99.95% of cells within 5 um on a bare frame, and the mesh is 13-35x faster
   with no chordal tolerance to choose, because it *is* the triangles.
3. ~~**"70 MB leaves the install" is not free.**~~ — **settled 2026-08-09.**
   Every posterior feature now loads **zero** OCP modules in a mesh-kernel
   G-code build, the lens groove included. It used to load **349**, through
   `geometry.rings.offset_aperture`, which samples the rim lip as an exact
   parallel of the authored curve and had no sampler but OCCT's.

   Both ways out were tried, and the cheap one failed for a reason worth
   recording. **Taking the Shapely buffer** it already falls back to measures
   **8 - 10 um** away — and that gap is real rather than a sampling floor,
   since tightening the chord tolerance from 10 um to 0.1 um leaves it flat.
   Against a model whose every other contour is flattened at 10 um and which is
   cut on a 150 um grid, that looked free. It was not: `_swept_groove_cutter`
   rides that exact curve, and on the buffer the B-Rep's grooved build stops
   being watertight on **all three drawings**. Densifying the lip did not help
   and the V section already carries a lead-in, so it is the sweep itself.
   Reverted — it would have removed the third opinion for the one feature whose
   surface is hardest to check, which is precisely the risk correction 4 raises.

   **`curves.sample_curve` is the answer**: de Boor with a hodograph tangent,
   and adaptive bisection to a chord tolerance. The exact lip survives, the
   sweep survives, and the dependency goes. `test_curve_eval_mn4` holds it to
   `Geom_BSplineCurve` and `Geom_OffsetCurve` at **1e-9** — not ceremony: the
   first version had the offset sign backwards and sat `2 * distance` from
   OCCT's answer, which no test on a circle can catch, its offset being a
   circle either way.

   It is also the first piece of the larger prize §8.5 describes. Nothing else
   in the pipeline can yet evaluate a curve; with this, the app could stop
   flattening at 10 um everywhere rather than being exact in one place.
4. **The third opinion has started refusing input the mesh accepts** *(added
   2026-08-09)*. `footings.CUT_LEAD_MM` runs each blend band past the ends of
   its seam. At 2 mm — the length first shipped, on the reasoning that margin
   past convergence is free — **OpenCASCADE stops building the aviator** with
   the lens groove on: zero volume on two feature combinations, 320
   self-overlapping edges on a third. Manifold builds all of them clean. The
   length is now 0.5 mm, which is where the fix actually converges, so nothing
   is owed here today; but the parity gates measure the mesh *against* OCCT,
   and a referee that falls over on valid input is a referee on a clock. It
   argues for doing step 1's measurements while the third opinion still works.

Total estimate: **5–7 working sessions** at this codebase's demonstrated pace,
with the app never broken in between. Compare: staying the course spent one
session this week producing two correct features and one new class of silent
corruption.

---

## 8. Risks, stated plainly

0. **The mesh surface touched itself and the B-Rep's did not. Contacts and open
   edges are now zero everywhere; a handful of degenerate faces remain.**
   *(Found 2026-08-08 chasing §8.2's edge problem, closed the same day.)*

   Welded by position and with degenerate faces removed, the mesh carried
   **157 / 247 / 232** edges with more than two faces on the base, **76 / 94 /
   82** on the lens groove, and the pad splay pinched the surface at **34 / 47 /
   15** more. The B-Rep carries none of it, on any feature or fixture. An STL has
   no index table, so this is what a slicer sees; it is the M-N0 condition, the
   one `mesh_check` describes as "will not export as a valid STL". Everything
   else about the part was right throughout — watertight, one body, volume exact
   to 0.00000% — which is precisely why it needed looking for.

   **One rule accounts for three of the four fixes:** *a tool must cross every
   surface it meets, and no vertex of it may lie in a face of its target.*

   * `model.build.FOOTING_CROSS_MM` — each blend half's profile ended at
     `u = 0`, the vertical wall between two zones. The sample there is *moved*
     across, not added: leaving one on the wall keeps a vertex in a face, which
     is the same defect one dimension down and measured 330 zero-area triangles
     against none.
   * `features.EDGE_CROSS_MM` — the pad splay sweeps *along the body outline*,
     so its first sample sat on the outline itself. Four hypotheses about the
     far end of the profile failed first, and the `open` count did not move for
     any of them; cutting the same tool from staged targets named it in one run
     — clean against a plain box, 102 against the real outline, before any
     terrace or blend was involved.
   * `kernel.sweep_sections` — `hull_chain` unions one convex cell per station
     gap, and consecutive cells **abut** on a shared section rather than
     overlapping; its docstring claimed otherwise and was wrong. Manifold fails
     to cancel that face about 0.65 times per station on a synthetic sweep with
     nothing else in the scene, invariant to circle / off-centre circle /
     ellipse, V / scalene / tapering section, open / closed, and 60 / 120 / 240
     stations. The strip builds the tube directly — exact, no booleans, and its
     volume converges to the hull chain's from below, the difference being the
     bulge the convex cells add.

   The fourth is `ZONE_WELD_MM`: zone polygons tile the body exactly, so two
   plain prisms raise the same wall twice and the union cancels it — until a
   blend band re-nodes that wall and hands it back displaced by up to
   **7.6e-7 mm**. Growing each zone by a micron gives the boolean real geometry
   instead of a coincidence to adjudicate, and the outline clips it back.

   None of the four moves the part; parity is unchanged and the bezel still
   clears its 5 µm raster gate.

   **`to_trimesh` was reading at float32.** `Manifold.to_mesh()` is float32 while
   Manifold keeps float64, and that function is what `verify_mesh`, every volume
   gate, the anchor rays and STL export all read a model through. At a 50 mm
   coordinate the spacing is about 4e-6 mm, and it distorted the counts in
   *both* directions: the bezel read 308 / 400 / 428 zero-area triangles where
   there are 2 / 12 / 12, and the aviator read 2 contacts where there are 6,
   because quantisation both merges distinct vertices and turns faces degenerate
   so the degenerate-face step carries their edges out of the count. Now
   `to_mesh64`.

   **What is left: at most 12 zero-area triangles** per fixture — bezel 2 / 12 /
   12, groove 8 / 0 / 8, splay 6 / 4 / 2. `mesh_check` does not report them and
   slicers generally discard them, so it is a gap against the B-Rep rather than
   a defect. `test_mesh_selftouch` asserts zero contacts and zero open edges and
   ratchets these.

   **The fallback earned its test immediately.** `sweep_sections` keeps
   `hull_chain` for a path turning tighter than its section is deep, and
   `test_the_sweep_never_falls_back_to_the_hull_chain` pins that it is not
   silently carrying the build. Adding ear-clipped caps turned it red at once —
   11 of 26 sweeps had dropped back — for two bugs that were invisible in the
   geometry: projecting each section onto "the two axes it spans most" collapses
   a section standing in a vertical plane (fixed with Newell's normal), and
   orienting the caps from geometry while the sides follow index order agrees
   for one section winding and contradicts the other, so exactly half the blend
   bands were rejected, one per carve/raise pair.

   **Measuring this is easy to get wrong in three ways, all of which I did.**
   Skipping the degenerate-face removal inflates the count about threefold (194
   where 157 is honest), because a zero-area triangle contributes its long edge
   twice. Round-tripping through **binary STL**, which stores float32, quantises
   distinct vertices into false contacts — that route showed 26 and 16 on the
   *B-Rep* and I briefly concluded the shipped path was broken. And the
   per-feature control was for a while comparing the B-Rep at float64 against
   the mesh at float32: the same trap, one level up, after having written it
   down as a lesson.

   **`verify_mesh` could not see any of this, which is UI-0's own complaint one
   layer down.** *(Closed 2026-08-08.)* It counted edges by **vertex index**, and
   index-manifold is exactly the invariant Manifold guarantees and keeps across
   a self-contact by giving the contact two coincident vertices with different
   indices. So the app said "Model verified" over all 157 while a slicer, which
   has no index table, would have seen every one. `mesh_check.welded_surface`
   now welds by position and drops the dead faces before anything is counted,
   and the test measurement calls that same function rather than a copy of it —
   two instruments disagreeing over precisely this is what produced the false
   B-Rep reading above.

   Turning a stricter check on could have lit up the shipped path in
   combinations nobody had measured, so it was measured first: **11
   configurations x 3 drawings x both kernels** — bare, each M13 feature, the
   pairs a real frame uses, all four at once, an M17 brow chamfer, a whole-ring
   fillet, and everything together. The B-Rep is **zero on every column of every
   configuration it can build**. The mesh matches it everywhere except one, and
   the sweep is what found that one:

   **A whole-ring edge feature was broken in both kernels.** An empty `zones`
   means the run covers the ring, `span_intervals` returns one interval spanning
   it, and everything downstream assumes a run with two ends. The last station
   duplicated the first, the run was swept *open*, and its two end caps landed
   on top of each other inside the solid: **19 / 18 / 21** self-touching edges on
   the mesh, and on the B-Rep a `ThruSections` loft that fails
   `BRepCheck_Analyzer` and takes the whole castle build down. The taper feathered
   the cut to nothing at the ring's arbitrary coordinate seam as well.
   `relief.edges.spans_whole_ring` is the exception the mesh path now takes —
   no duplicate station, no taper where there is no end, swept closed. It goes
   to **zero** contacts and zero open edges on all three drawings, at a 1.5 mm
   radius that genuinely folds at the ~0.7 mm endpiece corners and so still
   takes the `hull_chain` fallback: the fallback was never what was wrong.

   **The B-Rep does not get the exception, and trying to give it one is how we
   learned its whole-ring cutter does not cut.** Repeating the first section
   last is the standard way to close a `ThruSections` loft; at 1.5 mm the loft
   still failed `BRepCheck_Analyzer`, and at 0.4 mm — where it does build — it
   turned a clean solid into one with 7 boundary edges. Reverted. But the A/B
   that showed that also showed the *old* path's answer: the demo frame is
   7825.881 mm3 uncut and **7826.841** with a 0.4 mm round-over run all the way
   round, i.e. larger, within tessellation noise of having done nothing at all,
   and reported "Model verified". The mesh removes 11.4 mm3 for the same
   feature. There is no parity to hold here; this is a pre-existing defect in
   the kernel M-N4 retires, recorded rather than fixed.

   **Left open:** a whole-ring *chamfer* keeps **3** self-touching edges on the
   mesh path on the demo and aviator (none on the gabriel). It is now reported
   instead of hidden, which is the improvement; it is not yet fixed.

1. ~~**The footing blends are unproven in the new kernel**~~ — **retired
   2026-08-08 for parity; see risk 0 for what they did break.** They agree to
   0.00000% on volume. The kill switch was not needed and hybrid mode was not
   entered.

   Two things about the guess in this paragraph were wrong, and both are worth
   keeping. It said the blends are "the same per-segment-hull pattern as the
   groove": they are not. Both halves of every fillet in the schedule are
   **non-convex** sections — measured, `z''` from -0.19 to +0.32, with the
   nosepad pair S-shaped inside a single half — so a hull chain would have
   flattened all ten into straight ramps, silently. They need the slab
   decomposition that was built for the round-over. And the real difficulty was
   not the sweep at all but the *clipping*, which is not mentioned here; see the
   M-N1 note in §7.
2. **Mesh density becomes a quality knob.** Chord 0.01 mm matches today's
   contract everywhere, but edge crispness in the *viewer* now depends on our
   analytic edge overlay landing exactly on the mesh — needs one careful test.

   *Resolved as a diagnosis, 2026-08-08 — and it led to risk 0 above, which is
   the more serious finding.* The unexplained lines were **zero-area triangles**:
   Manifold emits them (357 on the demo frame, its own, not something our merge
   map creates — the map comes back empty), their normal is the zero vector, and
   the angle between a zero vector and a real normal computes as exactly 90
   degrees. So the detector was reading creases off faces that have no
   orientation. That accounts for the whole unexplained population, and the
   original criticism of dihedral guessing is not what was wrong here.

   **Resolved, and the detector ships** *(2026-08-08)*. `core.model.edges`
   supplies the mesh kernel's edges and all four display modes work on both
   solid kernels. The whole surplus was the degenerate faces: they were also the
   stitches over the surface's self-contacts, so risk 0 removed both at once,
   and `mesh_check.welded_surface` drops whatever is left. Re-measured on all
   three drawings, bare, matching within 0.15 mm:

   | | demo | aviator | gabriel |
   |---|---|---|---|
   | drawn length that is a real topological edge | **98.6%** | 98.8% | 98.8% |
   | *the B-Rep's own tessellation*, same detector | 98.2% | 98.5% | 98.4% |
   | B-Rep creases this finds | **100.0%** | 99.9% | 100.0% |

   Precision went 43.7% → 98.6% on one change of instrument. It is as good as
   running the same detector on the mesh it replaces, and it misses nothing that
   detector finds. The ~6% it draws that the B-Rep's *mesh* does not is real
   topological edges its coarser tessellation did not resolve as creases.

   **The threshold is 20°, and that is measured too.** `face_adjacency_angles`
   is the angle between face *normals* — coplanar reads 0 — so a 30° chamfer
   against a flat face reads 30, which is how the raster's `feature_angle=40.0`
   came to smooth 30° chamfers away. Length drawn against threshold on the demo
   frame fully featured: 6584 mm at 1°, 3273 at 5, 2639 at 12, then flat — 2527
   at 20, 2517 at 25, 2508 at 28 — before the 30° eyewire bezel drops out at 32
   (2266) and the 45° features at 40 (1744). Below 12° are the facets of the
   curved footing blends, and drawing those lays a contour map over every blend.
   Anywhere in 12–28 behaves identically; 20 has the most room either side.

   **The two thirds it does not draw are not a shortfall.** The topological set
   is ~6,200–6,800 mm against ~1,400–1,700 mm of actual crease: a 180-section
   loft contributes thousands of tangent patch seams between surfaces that meet
   smoothly. That is the "5,878 curves for a part with perhaps a hundred
   features" already on record, quantified — the B-Rep viewer draws them and
   this does not, which is the feature.

   Cost: **15.7 ms** on a fully featured demo frame, 1.0% of the build.

   *The original measurement, for the record*, since it was right about what it
   measured and wrong only about what was in the way. On the demo frame with the
   bezel on — when it carried 308 zero-area triangles — **89.1%** of the length
   the B-Rep's own tessellation calls a crease was found, but only **43.7%** of
   what it would *draw* had a counterpart there (**61.0%** against the full
   topological set), flat at ~60% from 25° through 85°. The surplus was noted as
   "real geometry — exact 90° creases running up to 13.9 mm across a terrace
   top — that the B-Rep does not have, and I could not account for it." Exactly
   90° is what a zero vector makes with a unit one.

   Two things are worth recording about the attempt. `trimesh.graph.traversals`
   returns the order nodes were **visited**, not a walk along adjacent ones, so
   chaining sharp edges with it drew straight lines across the frame at every DFS
   backtrack: 92% accurate as loose segments, 62% once "chained". And the
   comparison against `tessellate().edges` is not a fair target in the other
   direction — that explores every `TopAbs_EDGE`, so a 180-section bezel loft
   contributes thousands of tangent patch seams, and the demo frame hands the
   viewer 5,878 curves for a part with perhaps a hundred features.
3. **A second geometry dependency.** Manifold is small (~MBs vs OCCT's 264),
   Apache-2.0, and load-bearing for OpenSCAD; risk accepted. It was installed
   into the venv for the spike but is *not* yet in `pyproject.toml` — M-N1
   adds it.
4. **Measurement of record.** `mesh_volume` is already the referee (BUILDPLAN,
   GProp table); Manifold's `volume()` agreed with the welded trimesh to the
   third decimal in the spike. Sectioning via `slice` needs porting from the
   OCCT sectioner — small, testable.
5. **Sunk cost, honestly faced.** The exact-curve work is *not* lost — it feeds
   the mesh evaluation and the CAM. The OCCT-specific work (arc segmentation,
   junction tolerances, boolean switches) becomes archaeology. That is the
   price of the week that also produced the evidence in §3; it was not
   knowable in advance, and it is cheaper than the next such week.

---

## 9. The decision being asked for

Approve the direction (§6) with **UI-0 first**, then M-N0/M-N1. The first
visible deliverables, in order: the interface rendering correctly on the
maker's own machine with the scaling decision provable from the log; honest
model status in the UI; the in-session corruption bug mitigated on the current
branch; the Gabriel drawing as a fixture; and the mesh kernel building the bare
castle + groove with the full parity suite green — at which point the 39 ms
number stops being a spike and starts being the product.
