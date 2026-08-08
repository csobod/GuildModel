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
truth is already the mesh. The kernel is a 70 MB middleman between us and the
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

**One shortfall, and it is not cosmetic: the mesh kernel carries no edges**, so
selecting it costs three of the four display modes. See §8.2 for what was tried
and the numbers that stopped it.

**M-N3 — parity and the flip.** Demo + aviator + Gabriel: volume, silhouette,
V-profile, chamfer gates, **posted G-code byte-equivalence** (it posts from
curves, so this should be exactly equal — any diff is a bug found cheap).
Flip the default. OCCT demoted to an optional cross-check behind a debug flag.
~1 session.

**M-N4 — the payoff.** Retire the raster relief path (its only remaining role
is being the third opinion) and then the OCCT path; `cadquery-ocp` becomes an
optional dev dependency and 70 MB leaves the install. Slider dragging goes
live-continuous: the spike's 39 ms full build is faster than one frame of the
current progress dialog. Update BUILDPLAN.md to point here.

Total estimate: **5–7 working sessions** at this codebase's demonstrated pace,
with the app never broken in between. Compare: staying the course spent one
session this week producing two correct features and one new class of silent
corruption.

---

## 8. Risks, stated plainly

0. **The mesh surface touches itself, and the B-Rep's does not. M-N3 is blocked
   on this.** *(Found 2026-08-08, chasing §8.2's edge problem. **Base fixed the
   same day; three features remain.**)*

   Welded by position and with degenerate faces removed, the mesh base carried
   **157 / 247 / 232** edges with more than two faces on demo / aviator /
   gabriel; the B-Rep carries **0** on all three, with the bezel on. An STL has
   no index table, so this is what a slicer sees. It is the M-N0 condition
   again — the one `mesh_check` describes as "will not export as a valid STL" —
   and `verify_mesh` cannot currently see it, because Manifold keeps its
   index-manifold invariant across a self-contact by duplicating the vertex.

   Everything else about the part is right: watertight, one body, volume exact
   to 0.00000%. That combination is precisely why it needed looking for.

   **The base is now zero, and so is the bare model.** Two causes, both in
   `model/build.py`, both the same rule stated at a surface nobody had counted
   as one:

   * *The blend halves stopped exactly on the seam.* Each half's profile ended
     at `u = 0`, which is the vertical wall between the two zones — a face of
     the tool lying inside a face of its target, which is the very thing the
     unclipped-band construction was adopted to avoid. It also left the band's
     `u = 0` edge a 30-station chord of a seam the prism carries at full
     resolution, so wherever the chord fell inside the zone the subtraction left
     a standing hairline fin. Fixed by `FOOTING_CROSS_MM`, which carries each
     half 0.05 mm past the seam into the zone it does not act on, where that
     zone's own prism clips it away for free.
   * *Two booleans computed the same wall and did not agree.* Zone polygons tile
     the body exactly — neighbours share a seam with the same endpoints,
     collinear, distance 0.0 — so two plain prisms raise the same wall twice and
     the union cancels it. That is why `build_terraces` was always clean. But
     subtracting a blend band re-nodes the wall it crosses and hands it back
     displaced by up to **7.6e-7 mm**, and an exact kernel is right not to
     pretend two walls that differ are one. Fixed by `ZONE_WELD_MM`: grow every
     zone by a micron so neighbours genuinely overlap, and clip the union back
     to the frame outline.

   Neither moves the part — the crossing is clipped off by the zone it reaches
   into, the growth by the outline — and the zero-area triangles went with them,
   56 / 68 / 68 to none. Parity against the B-Rep base is unchanged.

   **What is left is per feature, and none of it is the blend defect:**

   * **lens groove, 76 / 94 / 82.** The V arrives with 60 to 72 *before it meets
     the part*. Root-caused to `kernel.hull_chain`: consecutive cells **abut**
     on a shared section rather than overlapping — the docstring claimed
     otherwise and was wrong — and the union fails to cancel that shared
     triangle at roughly one station in ten, leaving the section standing inside
     the tube. A triangle swept round a plain circle, nothing else in the scene,
     self-touches on 3 edges at 12 stations, 12 at 60 and 33 at 120. Running the
     cells past each other so they genuinely overlap **was tried and rejected**:
     it helped at 12 stations, hurt at 60, and applied to `swept_profile` it took
     the base from 0 to 2,500 by breaking the exact agreement between a blend's
     two halves at the seam.
   * **pad splay.** No contacts, but *open* edges once degenerate faces are
     dropped — 6 / 21 / 12 — which means those faces are load-bearing and the
     surface pinches. The chamfer profile reaches zero drop exactly at the
     anchor, so the tool's inner corner rides along the surface it is cutting
     instead of crossing it: `FOOTING_LEAD_MM`'s problem at the other end of a
     different feature.
   * **eyewire bezel.** 308 / 400 / 428 zero-area triangles, up to 2 contacts.

   Ratcheted by `test_mesh_selftouch`, which now asserts **zero** for the base
   and holds the three features at their current numbers.

   **Measuring this is easy to get wrong in two ways, both of which I did.**
   Skipping the degenerate-face removal inflates the count about threefold (194
   reported where 157 is honest), because a zero-area triangle contributes its
   long edge twice. And round-tripping through **binary STL, which stores
   float32**, quantises distinct vertices into false contacts: that route showed
   26 and 16 on the *B-Rep*, and I briefly concluded the shipped path was broken.
   It is not.

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

   Whether the detector is usable once those faces are excluded is now a smaller
   question, and risk 0 has partly answered it: the degenerate triangles were
   the stitches holding the self-contacts together, and fixing the base removed
   both at once — the bare model now has **none**. So the detector can be
   re-measured on a bare frame without them in the way. The bezel still emits
   308, so a rerun with the features on is still measuring through them.

   *The original M-N2 shortfall, for the record.* The
   viewer's four display modes are drawings **of the edges**, and the B-Rep path
   supplies its real topological ones. Deriving them from dihedral angle instead
   was built, measured, and backed out; the mesh kernel ships with `edges=None`
   and three of the four modes disabled.

   The measurements, so the next attempt starts from them rather than repeating
   them. On the demo frame with the bezel on: **89.1%** of the length the B-Rep's
   own tessellation calls a crease was found, so the detector misses little; but
   only **43.7%** of what it would *draw* had a counterpart there (**61.0%**
   against the full topological set). No threshold separates them — the figure is
   flat at ~60% from 25° through 85°. The surplus is not corruption: the mesh is
   watertight with every edge used exactly twice and zero duplicate faces, and it
   matches on volume and silhouette. It is real geometry — exact 90° creases
   running up to 13.9 mm across a terrace top — that the B-Rep does not have, and
   I could not account for it.

   Two things are worth recording about the attempt. `trimesh.graph.traversals`
   returns the order nodes were **visited**, not a walk along adjacent ones, so
   chaining sharp edges with it drew straight lines across the frame at every DFS
   backtrack: 92% accurate as loose segments, 62% once "chained". And the
   comparison against `tessellate().edges` is not a fair target in the other
   direction — that explores every `TopAbs_EDGE`, so a 180-section bezel loft
   contributes thousands of tangent patch seams, and the demo frame hands the
   viewer 5,878 curves for a part with perhaps a hundred features.
3. **A second geometry dependency.** Manifold is small (~MBs vs OCCT's 70),
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
