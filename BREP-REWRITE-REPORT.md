# Report: replacing the heightfield with a B-Rep solid kernel

**Status:** **Stage 1 spike RUN and PASSED — 2026-08-06.** Kill criteria not met;
the recommendation to proceed stands. See **§9** for the measured results, which
**correct §4.3 and §5.2**: the footing blend is not an edge fillet and must not
be built with `BRepFilletAPI_MakeFillet`. Read §9 before acting on §4 or §5.
**Written:** 2026-08-06, against `v1.4.0` (M17 landed, held for review).
**Assumed timing:** *after* the V2 release. Nothing here should displace the flip
fixture, the second work datum, or anterior posting — those are V2's reason to
exist and they are hardware gates, which always outrank modelling gates.

**The question this answers:** the cutting features (pad splay, eyewire bezel,
brow chamfer) do not read as crisp. They read as blended, with a pitted quality
along the edges where the cut begins and ends. Fusion 360 does not do this — a
boolean cut from an extrude/revolve/sweep has an exact edge. Why, and what would
it take to get there?

**The short answer:** the current architecture *cannot* produce a crisp edge,
because it has no representation of an edge. Every fix so far has been a
smoothing filter applied to a sampling artifact, which is why each one made the
features softer rather than sharper. A B-Rep kernel fixes it by construction —
along with a shipped bug it makes structurally impossible — at a cost of roughly
six milestones, ~200 MB of installer, and one genuinely risky dependency.

---

## 1. Why the current model cannot be crisp

### 1.1 There is no edge, only cells

`core/relief/heightfield.py` is a `(rows, cols)` array of Z, sampled at 0.3 mm
for preview and 0.15 mm for anything that becomes G-code. Every cutting feature
is a `z = min(z, target)` painted into that array:

| Feature | Carver | Composition |
| --- | --- | --- |
| Pad splay | `features._carve_pad_splay` | `min` against pre-carve snapshot |
| Eyewire bezel | `features._carve_eyewire_bezel` | `min` against pre-carve snapshot |
| Bridge relief | `features._carve_bridge_relief` | `min` against pre-carve snapshot |
| Brow chamfer / edge features | `edges.carve_edge_feature` | `min` (posterior) / `max` (anterior) |

The composition rule is sound and order-independent. The problem is upstream of
it: **the boundary of the cut is never represented anywhere.** A cell either got
carved or it didn't. Where the cut begins is not a curve in the model — it is
wherever the sampling happened to flip. Fusion, by contrast, computes the exact
intersection curve between the cutting body and the part, and that curve *is* the
edge. Everything downstream — display, STL, STEP — inherits it exactly.

Four consequences stack up, and together they are the entire complaint.

### 1.2 Cause A — rim vertices get the right XY and the wrong Z

This is the pitting, literally.

`castle._conform_rim` (`castle.py:614–643`) exists because the masked-grid
mesher emits a Manhattan staircase along the silhouette. It fixes that by
projecting each boundary vertex onto the true outline / lens ring. But it moves
vertices **in XY only** — `castle.py:632–634` — deliberately, so that "plateaus
and footing blends are untouched and the M2 STL gate is unaffected."

That was correct when the only thing at the rim was a flat terrace. It stopped
being correct the moment a chamfer was anchored *to the rim*. The vertex keeps
the Z it was carved with at the cell centre, and the cell centre sits a random
0–0.3 mm inside the ring, where the chamfer has not yet reached full depth. So
every rim vertex is left proud by `d · tan(angle)`, where `d` varies
quasi-periodically as the ring's curvature beats against the grid.

Both measurements below come from `scripts/probe_rim_error.py`, which is in the
repo. Run it to re-derive them, or to check whether a fix moved them:

```
DISPLAY= .venv/bin/python scripts/probe_rim_error.py
```

**Predicted**, on a synthetic 24 × 17 mm aperture, running the bezel's own
arithmetic (`width_mm = 1.2`, `angle_deg = 45`) with no footing swells or
clamping — isolating the sampling term alone:

```
res = 0.30 mm   rim vertex Z error   mean 0.130   max 0.284   peak-to-peak 0.283 mm
res = 0.15 mm                        mean 0.068   max 0.146   peak-to-peak 0.146 mm
res = 0.05 mm                        mean 0.021   max 0.050   peak-to-peak 0.050 mm
```

**Observed**, on the **Demo Project frame** through the shipping code path —
`build_castle_relief` → `build_castle_mesh(conform=True)` — walking the real
conformed rim vertices around the largest lens aperture in arc-length order and
reporting the step-to-step Z change:

```
res = 0.30 mm   522 rim vertices    |dz| mean 0.1086   max 0.4756 mm
res = 0.15 mm  1042 rim vertices    |dz| mean 0.0545   max 0.2395 mm
```

That is a **0.11 mm average and 0.48 mm worst-case Z step between adjacent
vertices on a rim that should be a smooth curve**, at the default preview
resolution. It is worse than the synthetic prediction because the real frame adds
footing swells and zone boundaries on top of the sampling term. Both halve when
the resolution halves, exactly as the mechanism predicts.

This is a systematic undercut (always proud — material left) *plus* a
quasi-random ripple, which is precisely the visual signature of pitting. Because
it scales linearly with resolution, raising the grid always helps and never
fixes it. That matches the reported experience exactly.

### 1.3 Cause B — interior feature edges get no treatment at all

`_conform_rim` handles the mask boundary and hinge-pocket rings. It does not
handle, because it cannot know about:

- the bezel band's **inner** edge, at `d = width`
- the pad splay **crest** — an inward offset polyline of the outline
- the brow chamfer's inner edge, and both of its **taper-out** ends
- the bridge relief scoop's boundary

Each of those is a slope discontinuity landing wherever it lands between cells.
No vertex lies on it. The crease is reconstructed from whichever axis-aligned
grid quads happen to straddle it: a 0.3 mm staircase following a smooth curve.

### 1.4 Cause C — the code deliberately blurs those creases to hide Cause B

This is the "blending" being felt, and the source says so outright.
`features.py:145–147`:

> Convex round-over at the crest (tangent both sides, footing-style) — the hard
> chamfer/surface corner shaded as a jagged ridge. 0 = sharp crest.

`crest_blend_mm` defaults to **2.0**. A 2 mm round-over replaces the pad splay's
crest, in production, by default. The docstring for `_splay_crest_tables`
(`features.py:150–161`) is an inventory of the same category of fix, all traced
to one field finding — "jagged points where the cut terminates", 2026-07-02:

- wide-baseline smoothed tangents (`uniform_filter1d`)
- slope-limited crest offsets (`_slope_limit`, cap 0.5 mm/mm)
- EDT-filled anchor heights, then smoothed again
- the cosine `feather` over the last 3 mm of each run
- the cosine `bell` cross-section in `_carve_bridge_relief`

Every one of these is real, careful engineering aimed at the wrong target. They
treat the symptom by making the feature *genuinely* not crisp. No amount of
further tuning here can succeed, because the thing being tuned is the blur.

### 1.5 Cause D — the viewer smooths across the sharp edges that survive

`gui/widgets/viewer_3d.py:498`:

```python
pv_mesh = pv_mesh.compute_normals(split_vertices=True, feature_angle=40.0)
```

with `smooth_shading=True` at line 531. VTK treats an edge as sharp only when the
dihedral exceeds `feature_angle`. Against a flat terrace:

| Feature | Default angle | Dihedral | vs. 40° threshold |
| --- | --- | --- | --- |
| Pad splay | 30° | 30° | **smoothed** — shaded as a fillet |
| Eyewire bezel | 30° | 30° | **smoothed** — shaded as a fillet |
| Brow chamfer (`EdgeFeature`) | 45° | 45° | **right on the threshold** |

The first two are Gouraud-shaded across the one edge that is supposed to be
sharp. The third is worse: at 45° against a 40° threshold, the staircase noise
from Cause B pushes the local dihedral either side of the line, so the mesh
splits *inconsistently* from triangle to triangle. That produces mottling — a
second, independent source of the pitted appearance, this one purely in shading.

### 1.6 Cause E — a raster drop-cutter cannot cut a crisp edge either

Even with a perfect model, the fine pass is contour-parallel rings riding a
grey-dilation cutter-location surface (`cam/dropcutter.py`). A ball or toroid
rolling over a convex crest rounds it by the tool radius, unavoidably, and the
CLS is computed on the same raster the model came from. The M13 feature-finish
band (`castle_ops.py:526–529`) adds rings *inside* the band at a chamfer-derived
stepover, which improves the surface finish but does nothing for the edge itself,
because the edge is not what the path is following.

A crisp machined edge needs a **curve-driven** pass: the tool walking the exact
feature curve at an exact offset. That is a CAM change, and it is required
whichever modelling route is chosen. It is the half of the problem that a
modelling rewrite alone does not solve.

### 1.7 The already-shipped bug that belongs to the same root cause

From the M17 notes in `BUILDPLAN.md`, logged and deliberately left alone:

> `build_castle_mesh` is not watertight at fine resolutions. On the demo frame
> the solid is watertight at 0.4 mm and **open at 0.25 mm** … the export
> resolution pref defaults to **0.15 mm**, finer than either figure, so exported
> STLs are likely open today.

The rim stitch (`castle.py:712–718`) assumes every boundary edge is used by
exactly one face. On a masked grid with thin features and diagonal pixel
contacts, that assumption fails. This is not a tuning bug — it is the masked-grid
mesher meeting a shape it cannot represent. **Every STL GuildModel exports at the
default resolution is suspect right now.** Any downstream consumer that expects a
solid (3D printing a fit check, a vendor's inspection software, a lens supplier's
CAD) can reject or mis-handle it.

A B-Rep kernel makes this failure impossible rather than fixed: a valid solid
tessellates to a closed mesh, and validity is checkable (`BRepCheck_Analyzer`)
before export.

---

## 2. What a B-Rep kernel actually buys

Crispness is the request. It is not the largest return.

**1. Exact edges, by construction.** Cuts become boolean subtractions of real
solids. The intersection curve is computed analytically. Causes A, B, C and D all
disappear simultaneously — there is nothing left to conform, nothing to smooth,
and the tessellator emits real crease edges the viewer can shade correctly
without a heuristic angle threshold.

**2. The smoothing filters get deleted, not tuned.** `crest_blend_mm`,
`_slope_limit`, the tangent smoothing, the EDT anchor fill, the cosine feather —
all of it becomes dead code. `crest_blend_mm` survives only as what it should
always have been: an *optional* round-over the maker asks for, not a mandatory
one the renderer needs. Net: `core/relief/features.py` and `core/relief/edges.py`
get substantially smaller and much easier to reason about.

**3. Watertight by definition.** §1.7 stops being a bug class.

**4. The 2.5D ceiling lifts.** This is the future-proofing argument and it is the
strongest one. A heightfield is a function `z = f(x, y)`; it cannot represent an
undercut, ever. M17 worked around this with a *second* heightfield for the
anterior face and a `thickness()` invariant to stop the two eating each other. It
works, but it is two 2.5D surfaces pretending to be a solid, and it will not
stretch to a third direction. A real solid gives, without further architecture:

   - true undercuts — a retentive lens groove with an actual overhang, real
     temple hinge geometry, sculpted pad arms
   - swept temple profiles along a 3D spine instead of an extruded flat
   - a foundation for 4/5-axis output, if a machine ever justifies it

**5. STEP export.** Not a nice-to-have. STEP is the interchange format for
everything outside the hobby CNC world — vendor quoting, injection-mould tooling,
inspection, a lens supplier's CAD. GuildModel currently emits STL, which is a
triangle soup with no edges and no units contract. STEP export from OCCT is one
call.

**6. Measurement that means something.** `core/geometry/measure.py` and the
section view (`core/mesh/section.py`) currently work on a tessellation. Against a
solid you get exact mass properties, exact cross-sections as curves, exact
volumes, and real distance-between-faces.

**7. The footing blends become what they were always imitating.** `castle.py`'s
header says the two-arc S-blend is a "sequential rolling-ball construction
matching Fusion's fillet behaviour, verified against the Demo Project STL to
< 0.01 mm rms". That is a careful analytic reimplementation of a fillet, valid
only because "for the demo's straight SCULPT cuts the cross-section profile
depends only on the signed distance to the cut line." That assumption is already
narrow. In B-Rep it is `BRepFilletAPI_MakeFillet` on the real edge, correct for
curved cuts too.

---

## 3. What it costs

Honestly, and without discounting.

### 3.1 Kernel choice

There is exactly one viable open-source B-Rep kernel with Python bindings:
**OpenCASCADE Technology (OCCT)**. The survey:

| Option | Verdict |
| --- | --- |
| **OCCT via `cadquery-ocp`** | **Recommended.** Thin pybind11 bindings, PyPI wheels for every CI target, Apache-2.0 binding layer. |
| OCCT via `pythonocc-core` | SWIG bindings, **conda-forge only — no PyPI wheels**. A conda dependency in a pip + PyInstaller project is a packaging regression. Reject. |
| `build123d` / `cadquery` | Ergonomic DSLs *on top of* `cadquery-ocp`. Worth using for prototyping the feature maths; not worth taking as a runtime dependency — GuildModel needs the low-level API for edge selection and sweeps anyway. |
| Parasolid / ACIS | Commercial, five figures per year, and license terms incompatible with GPL-3 distribution. Non-starter. |
| Manifold / CGAL | Excellent **mesh** boolean kernels. Robust, fast, guaranteed-manifold, and would give crisp booleans at ~1/10th the cost — but no analytic surfaces, so no STEP, no exact offsets, no exact fillets. This is the honest middle path if the B-Rep route stalls. |
| Fornjot | Rust, pre-alpha. Not a candidate. |

`cadquery-ocp` **7.9.3.1.1**, released 2026-05-28, wraps OCCT 7.9. Wheels for
Python 3.10–3.14 on Windows x86-64, macOS 11+ (x86-64 + arm64), and manylinux
2.31+ (x86-64 + arm64). GuildModel targets `>=3.12` and the working venv is 3.14
— in range, but note 3.14 support is recent, so the CI matrix should pin
explicitly rather than float.

### 3.2 Installer size

Wheels are 46–47 MB (Windows), 62–68 MB (macOS/Linux) compressed. Expect roughly
**150–250 MB added to the frozen bundle** uncompressed. Against current release
artifacts:

```
GuildModel-v1.1.0-windows-x64.zip     364 MB
GuildModel-v1.1.0-macos-arm64.zip     437 MB
GuildModel-v1.1.0-macos-x86_64.zip    489 MB
```

A ~40–60% increase on Windows. Material, but this is already a large bundle —
PySide6 (648 MB installed) and VTK (639 MB installed) dwarf it. It does not
change the distribution story qualitatively. `build_common.py`'s `datas` and the
PyInstaller spec will need OCP-specific collection hooks; these are known-fiddly
and solved by others, budget a day.

### 3.3 Licensing

Clean, but with one shipping obligation worth writing down now.

- OCCT: **LGPL-2.1-only, plus the Open CASCADE Exception 1.0**.
- `cadquery-ocp` binding layer: Apache-2.0.
- GuildModel: GPL-3.0-or-later.

LGPL permits linking from a GPL program directly, and LGPL-2.1 §3 additionally
allows relicensing under a later GPL, so GPL-3 + LGPL-2.1 is a standard,
uncontroversial combination. **The obligation that actually bites** is LGPL's
relinking provision: shipping OCCT inside a frozen bundle requires it stay a
*replaceable shared library* (PyInstaller's default — separate `.so`/`.dll` — is
compliant) and that the license text and a source offer ship with it. Add to
`NOTICE` at the same time as the dependency, not afterwards.

### 3.4 Performance

This is the cost most likely to be underestimated. OCC booleans and fillets on
organic B-spline geometry are **seconds, not milliseconds**. A castle with nine
zones, eighteen footing edges, two lens grooves and four edge features could
plausibly take 10–30 s to rebuild from scratch.

Mitigating: the current raster rebuild is *already* a progress-bar operation with
a cancellation hook (`ProgressFn`, `_report`), and the GUI is already built
around that. So the UX shape exists. But a naive port will feel slower, and the
teaching stepper (`build_castle_stage`) rebuilds from scratch per stage. Feature
caching and incremental rebuild move from "nice" to "required".

### 3.5 The regression-testing problem

The M2 STL gate validates against the Demo Project to < 0.01 mm rms. A B-Rep
rewrite changes every number in the suite. There is no way to keep the existing
gates bit-identical, and pretending otherwise would waste a milestone.

The workable strategy — and this shapes the whole migration — is to **keep the
raster path alive throughout** and gate the new path against it by sampling: ray
cast the B-Rep solid onto the same grid and compare Z-maps feature by feature,
with a tolerance that starts loose and tightens per milestone. Where they
disagree, the B-Rep is presumed right and the difference must be *explained*
before the tolerance moves. Divergence at the feature edges is the expected and
desired result — that is the whole point — so the comparison must exclude a
narrow band around each feature boundary and assert separately that the band got
*sharper* (measured as crease-angle consistency along the edge curve).

---

## 4. The architecture afterwards

### 4.1 The blast radius is smaller than it looks

`CastleRelief` and `Heightfield` appear in **36 places across `src/`**, in nine
files:

```
core/relief/castle.py        core/relief/flat.py       core/relief/heightfield.py
core/relief/__init__.py      core/cam/castle_ops.py    core/cam/component.py
core/cam/dropcutter.py       core/sim/bed.py           gui/app.py
```

Everything else is untouched. The DXF/`.gdraw` import, the zone classifier
(`geometry/regions.py`), boxing, symmetry, the whole CAM posting chain (`arcfit`,
`grbl`, `machine`), the simulator, feeds and speeds, tabs, nesting, the
worktable, the project format, and the entire GUI shell — none of it needs to
know. That is roughly 80% of the codebase.

### 4.2 The key insight: the heightfield does not go away

**The B-Rep becomes the master representation; the raster becomes a derived one,
for CAM only.**

This matters enormously for risk. The drop-cutter (`cam/dropcutter.py`) is
mathematically clean, fast, hardware-proven, and the subject of a costly incident
(`INCIDENT-2026-07-29`) whose fix is encoded in `CUT_RES_MM`. Nobody should touch
it. It keeps consuming a `Heightfield` with exactly today's semantics.

```
  DXF / .gdraw
       │
       ▼
  CastlePartition            (geometry/regions.py — unchanged)
       │
       ▼
  ┌─────────────────────────────────────────┐
  │  NEW: core/solid/                       │
  │    build the castle as a B-Rep solid    │
  │    features = boolean cuts of real      │
  │      swept / extruded / revolved bodies │
  │    footings = BRepFilletAPI on edges    │
  └─────────────────────────────────────────┘
       │                                  │
       │ tessellate (exact edges)          │ ray-cast Z-map @ CUT_RES_MM
       ▼                                  ▼
  3D preview / STL / STEP            Heightfield  ──►  dropcutter, castle_ops,
  (crisp, watertight)                (derived)         sim, worktable
                                                       — ALL UNCHANGED
```

The adapter — solid → Z-map — is one new function, and it is the only thing the
CAM ever sees. Grid of vertical rays against the tessellation (trimesh + `rtree`,
already a dependency) or against the B-Rep directly
(`BRepIntCurveSurface_Inter`). The tessellation route is faster and sufficient at
0.15 mm.

The one CAM change that *is* needed is additive, not a rewrite: a **curve-driven
finishing pass** along each feature edge (§1.6), which the B-Rep can now hand
over as an exact curve. That is where machined crispness comes from, and it is
impossible today because no such curve exists.

### 4.3 The features, restated as solids

| Feature | Today | As a solid |
| --- | --- | --- |
| Castle terraces | per-zone flat fill | extrude each zone polygon to its height, union |
| Footing blends | analytic two-arc S-blend on signed distance | ~~`BRepFilletAPI_MakeFillet`, exterior then interior, on the real step edge~~ **— WRONG, disproved in §9.2. Sweep the `_footing_z` cross-section along the SCULPT cut line and subtract.** |
| Eyewire bezel | `min` over a distance band | revolve/sweep a triangular profile along the aperture ring, subtract |
| Pad splay | crest tables + rounded chamfer drop | sweep a chamfer profile along the crest curve, subtract |
| Brow chamfer (`EdgeFeature`) | per-sample chamfer drop × taper weight | `BRepOffsetAPI_MakePipeShell` along the trimmed span with a profile law, subtract |
| Bridge relief | cosine bell cross-section | revolve a cone, subtract |
| Hinge pockets | `min` inside a polygon | extrude + subtract |
| Lens groove | profiled rim ribbon in the mesher | sweep a V profile along the lens ring, subtract |

Note how many of these become *the exact Fusion operation the maker would use* —
which is the point, and also a strong sign the mapping is natural rather than
forced.

---

## 5. The hard problems

These are the things that will actually consume the schedule. None is a
show-stopper; all deserve a spike before the milestone that depends on them.

### 5.1 Partial-span tapered chamfers (highest design risk)

`BRepFilletAPI_MakeChamfer` chamfers a **whole edge**. The M17 brow chamfer is
explicitly *not* a whole edge — it is a span named by castle zones, with a
`blend_mm` taper feathering the cut to nothing at each end so it does not stop
dead against uncut material. That taper is the feature's reason to exist.

Two routes:

- **Split the edge** at the span ends, chamfer the sub-edge. OCC handles this,
  but the chamfer terminates in a vertical wall at the run end — precisely what
  `blend_mm` was written to avoid.
- **Sweep a solid.** `BRepOffsetAPI_MakePipeShell` along the trimmed span with a
  varying profile: full chamfer triangle in the middle, collapsing to zero at
  each end. Subtract it. This gives the taper, supports `width_end_mm` for free,
  and is genuinely how you would model it in Fusion.

**Take the sweep route.** But `MakePipeShell` with a varying profile on a spline
spine is one of OCC's fussier APIs and can fail to build. *Spike this first* — it
is the single item most likely to force a fallback.

### 5.2 Fillet robustness on organic splines

> **Superseded by §9.2.** Measured: 0 of 16 footing edges accept a fillet at the
> scheduled radii, and the reason is not kernel fragility — it is that the
> footing was never an edge fillet. The section below is kept for the record;
> the mitigations it proposes are not the ones to reach for.

The classic OCC failure mode, and the second-highest risk. The castle is a
stepped solid whose step edges are spline SCULPT cuts meeting an organic outline
at shallow angles, with high curvature at the nosepad and endpiece transitions.
`BRepFilletAPI_MakeFillet` fails on exactly this shape of input. Fusion has
decades of fillet hardening behind it; OCCT does not.

Mitigations, in order of preference: fillet edges in curvature order rather than
all at once; fall back to a smaller radius on failure and surface it in the
readiness dot rather than silently; keep the analytic `_footing_z` blend as an
explicitly-selectable fallback for edges where the kernel gives up. That last one
is unglamorous but it means a fillet failure degrades to today's behaviour
instead of to no model.

### 5.3 The `flat.py` duck-type

`core/relief/flat.py` (`FlatRelief`, temples and blocks) duck-types into
`build_castle_mesh` and `_conform_rim` — see the `getattr` guards at
`castle.py:626` and `castle.py:728`. It has no groove fields and no partition.
Any new mesher must either keep that contract or convert temples to solids in the
same milestone. Converting is cleaner; keeping the duck-type through a transition
is faster. Decide explicitly rather than discovering it.

### 5.4 Determinism and the project format

`.gmodel` stores parameters, not geometry, so the file format does not change —
good. But the rebuilt geometry must be *reproducible* across OCC versions, or a
project saved today will preview differently after a dependency bump. Pin OCP
exactly, and add a fixture test that hashes the tessellation of the demo frame.

### 5.5 Preview interactivity

Every parameter change currently triggers a raster rebuild. At OCC speeds that
becomes unpleasant. The teaching stepper (`build_castle_stage`) is worst — four
full rebuilds. Needs incremental rebuild (cache the unfilleted castle solid;
re-apply only the changed feature) and probably a debounce on the params panel.

---

## 6. Staged migration

Structured so that **every stage ships something usable and nothing is a
throwaway**, and so the project can stop at the end of any stage with a working
application.

### Stage 0 — Interim fixes (do this regardless; ~1 milestone, pre-V2)

None of this is wasted by a later rewrite; all of it improves the product now and
some of it survives verbatim.

1. **Fix the rim-Z bug** (§1.2). When `_conform_rim` snaps a vertex, re-evaluate
   the feature's analytic height at the snapped XY instead of keeping the raster
   Z. Kills the moiré on every aperture rim. Small, contained, high payoff.
2. **Fix the watertightness bug** (§1.7). This is shipping broken STLs today and
   should not wait for an architecture decision.
3. **Viewer shading**: tag feature triangles and split explicitly, or drop
   `feature_angle` to ~15°. One line, immediately visible.
4. **Default `crest_blend_mm` to 0** and expose it honestly as an optional
   round-over. Accept that the crest will look jagged until Stage 2 — it is
   better to see the real problem than a blurred one.

### Stage 1 — Kernel spike (~1 milestone)

No production code path. Prove or disprove the two risks in §5.1 and §5.2 against
the **Demo Project** frame specifically, not a synthetic test shape. Deliverable:
a script that builds the demo castle as a solid, fillets it, applies one brow
chamfer, and reports success/failure and timings. Plus PyInstaller packaging
proven on all three CI targets.

**Kill criteria — decide here, in advance.** If the sweep route cannot build a
tapered partial-span chamfer on the demo outline, or if fillets fail on more than
a small minority of footing edges with no workable fallback, stop and take the
Manifold mesh-boolean route (§3.1) instead. It gets crisp edges and watertight
solids without STEP or exact offsets, at a fraction of the cost.

### Stage 2 — Solid castle, raster CAM (~2 milestones)

Build the castle and all features as a solid. Tessellate for preview and STL.
**Derive the heightfield by ray-casting** and feed the existing CAM unchanged.
Keep the raster path behind a preference for A/B comparison and gating (§3.5).

Exit: the posted G-code for the demo frame is equivalent to today's within the
agreed tolerance, and the preview is visibly crisp.

### Stage 3 — Retire the raster authoring path (~1 milestone)

Delete `_carve_*`, `_conform_rim`, the smoothing filters, `crest_blend_mm`'s
mandatory role. Convert `flat.py`. Re-baseline the test suite against the solid.

### Stage 4 — Curve-driven CAM edge pass (~1 milestone)

The other half of crispness (§1.6). Take the exact feature edge curve from the
solid and drive a chamfer/V/flat tool along it. **This is the milestone where the
physical part gets crisp**, and it is worth stating plainly that Stages 2–3 alone
will make the *preview* beautiful and the *cut* only slightly better.

Gate: hardware. This cuts acetate before it is called done.

### Stage 5 — Collect the winnings (~1 milestone)

STEP export. Exact measurement and section. `BRepCheck_Analyzer` in the readiness
dot. Then the undercut features the 2.5D model could never express.

**Total: ~6 milestones after V2**, plus one before it.

---

## 7. Recommendation

**Proceed, with Stage 0 pulled forward and Stage 1 treated as a real go/no-go.**

The case rests less on crispness than on three things the current architecture
cannot deliver at any price: watertight solids, STEP, and undercuts. Crispness is
the symptom that made the ceiling visible.

Two cautions worth holding onto:

**Do not let this displace V2.** The flip fixture and second work datum are
hardware gates. An unproven flip datum cuts the part in the wrong place; a
slightly soft chamfer does not. The M17 scope decision was right and it is still
right.

**Stage 1 must be allowed to fail.** The kill criteria in §6 are not a formality
— OCC fillet robustness on organic eyewear splines is a genuine unknown, and the
honest fallback (Manifold mesh booleans) delivers most of the crispness for a
fraction of the cost. Committing to B-Rep before the spike would be committing to
a risk that has not been measured.

---

## 8. Resuming this work in a fresh session

Everything needed is in the repository — no conversation context is required.
Read in this order:

1. **This report**, §1 for the diagnosis and §6 for the plan.
2. **`scripts/probe_rim_error.py`** — run it first. It reproduces the §1.2
   numbers in about a minute and is the fastest way to confirm the defect is
   still present and still behaves as described.
3. **`BUILDPLAN.md` § "Feature crispness"** — the milestone entry, which is the
   canonical status. This report is the analysis behind it; BUILDPLAN is the
   record of what is scheduled.

**Where the code is:**

| What | File |
| --- | --- |
| The raster and its resolutions | `core/relief/heightfield.py`, `core/relief/castle.py:43–62` |
| The rim-Z defect | `core/relief/castle.py:614–643` |
| The feature carvers | `core/relief/features.py`, `core/relief/edges.py` |
| The smoothing filters to delete | `core/relief/features.py:117–227` |
| The mesher and its rim stitch | `core/relief/castle.py:646–744` |
| The CAM boundary a solid must feed | `core/cam/dropcutter.py`, `core/cam/castle_ops.py` |
| Demo Project ground truth | `tests/fixtures/demo/` |

**How to verify a change:** the M2 (STL) and M3 (NC) gates are the regression
suite — `tests/test_castle_m2.py` and `tests/test_castle_m3.py`, both keyed to
`tests/fixtures/demo/`. Run the full suite headless:

```
DISPLAY= .venv/bin/python -m pytest
```

`DISPLAY=` matters: with a display set, VTK tries to build a GL context and dies
as soon as a toolpath loads.

**Caveat on the citations.** The `file:line` references throughout this report
were taken against `v1.4.0`. Stage 0 changes several of those exact files, so
after it lands, trust the *names* (`_conform_rim`, `_carve_eyewire_bezel`,
`crest_blend_mm`) over the line numbers.

---

## 9. Stage 1 spike — results *(run 2026-08-06)*

Run with `DISPLAY= .venv/bin/python scripts/spike_brep.py`, against the Demo
Project frame through the real partition (`partition_zones` on the vendored
DXF), on `cadquery-ocp` 7.9.3.1.1 / OCCT 7.9, Python 3.14.6, Linux x86-64.
Re-run it to re-derive every number below.

**Verdict: the kill criteria in §6 are not met. Proceed to Stage 2.** But two of
this report's own design decisions were wrong, and one of them is load-bearing.

### 9.1 §5.1 — the tapered partial-span chamfer: PASSES

The item the report called "the single item most likely to force a fallback"
builds, and it is fast.

```
extrude + fuse 9 zone terraces          0.81 s   valid  8004.95 mm^3, 653 faces
sweep chamfer, spline spine, floor 0.02 0.14 s   valid  run 51.23 mm, 25 profiles
subtract chamfer from castle           10.75 s   valid  removed 90.05 mm^3
```

Two findings that change how it must be built:

* **The taper cannot go to exactly zero.** `MakePipeShell.MakeSolid()` fails
  outright when the end profile collapses to a point. Flooring the chamfer width
  at **0.02 mm** — a fiftieth of the finishing tool's radius, invisible in
  acetate — builds a valid solid every time. M17's `blend_mm` law is otherwise
  reproduced exactly.
* **The spline spine works and the polyline spine does not**, which is the
  opposite of the intuition the report was written on. Fitting a B-spline through
  the span stations (`GeomAPI_PointsToBSpline`) succeeds; feeding the raw
  polyline of ring vertices as the spine fails `MakeSolid()` after 5 s. The
  organic curve is the *easy* case for `MakePipeShell`; the many-segment polyline
  with near-tangent corners is the hard one.

### 9.2 §5.2 — the footing fillets: FAIL, because the operation was wrong

At the Demo Project's scheduled radii, **0 of 16 footing step edges accept a
fillet.** Dropping the radius until it works needs to go absurdly far:

| Radius | Edges filleted | |
| --- | --- | --- |
| scheduled (ext 6–32 mm) | **0 / 16** | all "not done" |
| 1.0 mm | 2 / 16 | |
| 0.5 mm | 5 / 16 | |
| 0.25 mm | 13 / 16 | 1/24th of the smallest scheduled radius |

**This is not kernel fragility, and reading it that way would have taken the
project down the wrong branch.** The scheduled footing radii are
`endpiece_superior=32/48`, `endpiece_inferior=16/32`, `bridge_superior=24/32`,
`nosepad_superior=6/4`, `nosepad_inferior=9/10` mm. The steps they blend are
**0.2 – 5.8 mm**. A 48 mm edge fillet on a 0.7 mm step is not a fillet any kernel
can build, Fusion included — there is nowhere near 48 mm of adjacent face to land
it on.

So these were never 3D edge fillets. They are radii of a **cross-section**
S-blend, which is exactly what `castle.py`'s own header says it implements: *"the
cross-section profile depends only on the signed distance to the cut line."*
§4.3's mapping of footing blends onto `BRepFilletAPI_MakeFillet` was a
mis-reading of the existing code.

### 9.3 The correction — footing as a swept cross-section: PASSES 10/10

Sweeping `_footing_z`'s own profile along each SCULPT cut line and subtracting:

```
sweep + subtract on every named zone edge   0.12 s
  swept   10/10 valid
  booleans 10/10 valid
  result valid, 7774.37 mm^3
```

Ten of ten, in an eighth of a second, using the *existing* analytic profile
function unchanged as the section generator. This is strictly better than the
fillet route would have been even if it had worked: it reproduces the Demo
Project's verified `< 0.01 mm rms` blend by construction rather than hoping a
kernel fillet lands in the same place, and it keeps the Fusion timeline ordering
(`first="interior"` / `"exterior"`) meaningful.

**Consequence for §5.2's mitigations:** none of them are needed. The
"keep `_footing_z` as a fallback for edges the kernel gives up on" plan inverts —
`_footing_z` is the *primary* construction, and no fillet API is involved.

### 9.4 Performance

Better than §3.4 feared, with one exception. Everything is sub-second — terrace
build 0.81 s, all ten footings 0.12 s, the chamfer sweep 0.14 s — **except the
boolean subtracting the swept chamfer from the castle, at 10.75 s.** That single
operation is most of the wall clock. §3.4's warning is real but localised: it is
booleans against the many-profile swept cutter, not the kernel generally. Worth
knowing before Stage 2 designs the rebuild cache, because it says the thing to
cache is boolean results, not sweeps.

### 9.5 What Stage 1 has NOT proven

Being explicit, because §6 lists this and it is not done:

* **PyInstaller packaging on the CI targets.** Not attempted. The OCP collection
  hooks in `build_common.py` are untouched, and note there is **no Linux CI
  workflow** — only `macos-build.yml` and `windows-build.yml` — so "all three CI
  targets" cannot currently be satisfied as written.
* Determinism across OCC versions (§5.4), the `flat.py` duck-type (§5.3), and
  preview interactivity (§5.5) are all untested.
* Nothing here touches the CAM adapter. The solid → Z-map ray-cast is unwritten.

---

## Appendix — evidence index

| Claim | Where |
| --- | --- |
| XY-only rim conform | `core/relief/castle.py:614–643`, esp. 632–634 |
| Rim-Z error, predicted and observed | `scripts/probe_rim_error.py` — §1.2 tables |
| Mandatory crest round-over | `core/relief/features.py:145–147` |
| Smoothing-filter inventory | `core/relief/features.py:150–161` |
| Viewer feature angle | `gui/widgets/viewer_3d.py:498`, `:531` |
| Feature-band CAM rings | `core/cam/castle_ops.py:526–529` |
| Drop-cutter via grey dilation | `core/cam/dropcutter.py:1–75` |
| Cut-resolution incident | `core/relief/castle.py:47–62`, `INCIDENT-2026-07-29-…md` |
| Watertightness bug | `BUILDPLAN.md`, M17 section, "Pre-existing finding" |
| Rim stitch assumption | `core/relief/castle.py:712–718` |
| Blast radius (36 refs, 9 files) | `grep -rn "CastleRelief\|Heightfield" src` |

**External sources**

- [cadquery-ocp on PyPI](https://pypi.org/project/cadquery-ocp/) — versions, wheels, platforms
- [pythonocc-core on conda-forge](https://anaconda.org/conda-forge/pythonocc-core) — conda-only distribution
- [pythonocc-core repository](https://github.com/tpaviot/pythonocc-core)
- [Open CASCADE Exception 1.0 (SPDX)](https://spdx.org/licenses/OCCT-exception-1.0.html) — licensing
- [Open Cascade Technology (Wikipedia)](https://en.wikipedia.org/wiki/Open_Cascade_Technology) — LGPL-2.1 + exception
- [BRepFilletAPI_MakeChamfer reference](https://dev.opencascade.org/doc/refman/html/class_b_rep_fillet_a_p_i___make_chamfer.html) — whole-edge chamfer API
- [build123d documentation](https://build123d.readthedocs.io/en/latest/tips.html) — OCP-based alternatives
