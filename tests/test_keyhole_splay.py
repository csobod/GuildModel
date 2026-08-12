"""The non-contiguous pad splay — the keyhole bridge's splay (2026-08-11).

**The report.** A keyhole bridge carries its own shape across the centreline,
and a pad splay run through bottom-centre planes that shape straight off. What
the maker wants is the two halves of the splay with the middle left alone, so
the splay gained a `non_contiguous` flag and a `gap_mm` spacing adjuster.

**What has to hold, and why each of these is here rather than eyeballed:**

* the gap is genuinely uncut — this is the whole request, and the failure mode
  it replaces is a cut that is merely *shallow* in the middle rather than absent
  (a single swept strip with a zero-weight midsection still has sections
  standing over the gap, and their drop is floored at `MIN_TAPER_DROP_MM`);
* the two halves are still there, still symmetric, and still the same surface
  they were as part of one run — the toric angle blend measures from
  bottom-centre either way;
* the inner ends feather like the outer ones. They are the ends the maker looks
  at across the keyhole, and a cut that stops dead there is a wall;
* the contiguous case still cuts the splay everyone already has. `splay_weight`
  replaced a hand-written cosine that had exactly one span, and the curve is
  identical — pinned below against the old formula. The *selection* did move, by
  three cells in 191,694 on the aviator and only ever toward leaving material:
  the old carve selected every station with `|u| <= run`, including the two where
  the feather has already reached zero, and at those the target was the crest
  anchor height with no drop subtracted. Where the surface stood above that, the
  cut terminated in a 0.077 mm step. That is one more of the "jagged points where
  the cut terminates" family (2026-07-02) and it is gone;
* all three kernels agree, because all three now build the spans from one
  function.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def aviator(tmp_path_factory):
    """The keyhole frame — its decorative bridge opening is the motivating case."""
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / "aviator.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "aviator").iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


def _castle(**splay):
    from guildmodel.core.project.schema import CastleParams

    c = CastleParams()
    c.pad_splay.enabled = True
    for k, v in splay.items():
        setattr(c.pad_splay, k, v)
    return c


def _relief(front, castle, res=0.2):
    from guildmodel.core.relief.castle import build_castle_relief

    return build_castle_relief(front.partition, castle, front.hinge_polys,
                               resolution=res)


# ------------------------------------------------------------------ the spans

def test_spans_split_evenly_about_bottom_centre():
    from guildmodel.core.project.schema import PadSplayParams

    p = PadSplayParams(run_mm=18.0, non_contiguous=True, gap_mm=8.0)
    assert p.spans() == [(-18.0, -4.0), (4.0, 18.0)]
    # Contiguous is one interval through the centre, as it always was.
    assert PadSplayParams(run_mm=18.0).spans() == [(-18.0, 18.0)]


def test_a_gap_wider_than_the_run_cuts_nothing():
    """A splay switched off by the back door, not an error: the maker has
    pushed the halves past the ends of their own run."""
    from guildmodel.core.project.schema import PadSplayParams

    assert PadSplayParams(run_mm=6.0, non_contiguous=True, gap_mm=20.0).spans() == []


def test_spans_are_re_derived_against_the_achievable_run():
    """`PadSplayParams.spans` works from the *requested* run; the carvers clip
    that to a fraction of the outline first. `splay_spans` re-applies the gap
    against the run actually in use, or a small frame would put the halves in
    the wrong place."""
    from guildmodel.core.project.schema import PadSplayParams
    from guildmodel.core.relief.features import splay_spans

    p = PadSplayParams(run_mm=60.0, non_contiguous=True, gap_mm=8.0)
    assert splay_spans(p, 10.0) == [(-10.0, -4.0), (4.0, 10.0)]


# ------------------------------------------------------------------ the weight

def test_every_span_end_feathers_including_the_inner_ones():
    from guildmodel.core.relief.features import splay_weight

    u = np.linspace(-18.0, 18.0, 3601)
    w = splay_weight(u, [(-18.0, -4.0), (4.0, 18.0)], 3.0)

    assert np.all(w[np.abs(u) < 4.0 - 1e-9] == 0.0)     # the gap is untouched
    for end in (-18.0, -4.0, 4.0, 18.0):                # all four run out to 0
        assert w[np.argmin(np.abs(u - end))] == pytest.approx(0.0, abs=1e-9)
    assert w.max() == pytest.approx(1.0)                # and reach full depth
    # Mirror-symmetric about bottom-centre.
    assert np.allclose(w, w[::-1], atol=1e-12)


def test_contiguous_weight_is_the_cosine_it_replaced():
    """`splay_weight` generalised a hand-written single-span cosine. Same curve."""
    from guildmodel.core.relief.features import splay_weight

    run, feather = 18.0, 3.0
    u = np.linspace(-run, run, 1001)
    au = np.abs(u)
    want = np.where(au <= run - feather, 1.0,
                    0.5 * (1.0 + np.cos(np.pi * (au - (run - feather)) / feather)))
    assert np.allclose(splay_weight(u, [(-run, run)], feather), want, atol=1e-12)


# ------------------------------------------------------------------ the raster

def test_the_gap_is_uncut_and_the_halves_are_not(aviator):
    """The motivating gate. Measured against the same frame with the splay off,
    so this is material removed, not a height compared to a guess."""
    bare = _relief(aviator, _castle(enabled=False))
    whole = _relief(aviator, _castle())
    split = _relief(aviator, _castle(non_contiguous=True, gap_mm=12.0))

    assert whole.feature_band is not None and whole.feature_band.any()
    assert split.feature_band is not None and split.feature_band.any()

    cut_whole = bare.field.z - whole.field.z
    cut_split = bare.field.z - split.field.z

    # The contiguous splay cuts across the centreline; the split one does not.
    res, (ox, _oy) = whole.field.resolution, whole.field.origin
    cols = np.arange(whole.field.z.shape[1])
    centre = np.abs(ox + cols * res) < 2.0
    assert cut_whole[:, centre].max() > 0.2
    assert cut_split[:, centre].max() == pytest.approx(0.0, abs=1e-9)

    # Both halves still cut, and by a substantial fraction of the whole run —
    # but well under the third of the *length* the gap takes, because the length
    # it takes is the deepest third: the crest offset peaks at bottom-centre.
    # Measured 0.38 on this frame at a 12 mm gap in a 36 mm run.
    assert 0.25 < cut_split.sum() / cut_whole.sum() < 0.55

    # Where both cut, they cut the *same surface*: the split is the whole run
    # with its middle removed, not a shallower chamfer. Compared only outside
    # the feathered ends, which the gap moves by construction.
    outer = cut_whole > 0.05
    inner = np.abs(ox + cols * res) > 12.0
    both = outer & cut_split.astype(bool) & inner[None, :]
    assert both.any()
    assert np.abs(cut_split[both] - cut_whole[both]).max() < 0.05

    # The whole run is deeper overall, and necessarily so: its deepest station
    # is bottom-centre, where the crest offset is largest — which is precisely
    # the material the gap is there to leave alone.
    assert cut_split.max() < cut_whole.max()


def test_split_splay_is_no_less_symmetric_than_the_whole_run(aviator):
    """One flag, two halves, and the halves stay each other's mirror.

    Measured **against the contiguous splay rather than against zero**. The
    raster splay is already ~3.9% left/right uneven on this frame — its stations
    are arc-length samples of a flattened outline and its crest bisection is
    per-sample — on a body that is 0.13% uneven. That is a pre-existing raster
    artifact, not the gap's doing, and asserting perfect symmetry here would be
    asserting something the feature has never had. What the gap must not do is
    make it worse than the tails it leaves behind already are.
    """
    bare = _relief(aviator, _castle(enabled=False))
    res, (ox, _oy) = bare.field.resolution, bare.field.origin
    xs = ox + np.arange(bare.field.z.shape[1]) * res

    def imbalance(castle):
        cut = bare.field.z - _relief(aviator, castle).field.z
        left, right = cut[:, xs < 0].sum(), cut[:, xs > 0].sum()
        return abs(left - right) / max(left, right)

    whole = imbalance(_castle())
    split = imbalance(_castle(non_contiguous=True, gap_mm=12.0))
    assert whole < 0.05
    # The split keeps only the outer tails, where the artifact is concentrated,
    # so a modest rise is expected; a genuinely lop-sided split would not be
    # modest. The exact spans and weights are pinned above and are symmetric.
    assert split < 0.10


def test_zero_weight_stations_are_not_carved(aviator):
    """A station whose feather has reached zero must not be a carve target.

    The old selection was `|u| <= run`, which includes the two stations where the
    weight is already 0; there the target was the crest anchor height with no
    drop subtracted, so wherever the surface stood above it the cut ended in a
    step. Three cells on the aviator, up to 0.077 mm. The selection is now
    `weight > 0`, and this pins the consequence: **nothing outside a span is ever
    below the un-splayed surface.**
    """
    bare = _relief(aviator, _castle(enabled=False))
    whole = _relief(aviator, _castle())
    cut = bare.field.z - whole.field.z
    band = whole.feature_band
    assert band is not None
    # Every cell the splay lowered is a cell it claims; nothing is lowered
    # outside the band, and nothing in the band is lowered by nothing.
    assert not (cut[~band] > 1e-9).any()
    assert (cut[band] > 0).all()

    # And the default really is contiguous.
    from guildmodel.core.project.schema import PadSplayParams
    assert PadSplayParams().non_contiguous is False


def test_the_raster_splay_is_deterministic(aviator):
    a = _relief(aviator, _castle())
    b = _relief(aviator, _castle())
    assert np.array_equal(a.field.z, b.field.z)


# ------------------------------------------------- the run-out (2026-08-12)

def test_the_feather_runs_the_cut_out_instead_of_flattening_it(aviator):
    """The follow-up report: "a very abrupt end leaving sharp material no matter
    what I do", with the inner ends of a non-contiguous splay in the picture.

    The feather scaled the *drop*, which took the chamfer's angle to zero while
    its width stayed at the full crest — the last millimetres of the run came out
    as a flat shelf planed at the crest's anchor height and then stopped dead.
    Now it lifts the chamfer plane out of the surface instead, so the cut narrows
    away and the *depth profile along the run has no step at the span end*.

    Measured on the built surface rather than on the parameters: how much the
    splay took off, sampled 0.3 mm inside the outline at stations walking out
    from the keyhole. It has to start at nothing and climb, with no step.

    Stations come from the ring's own parametrisation, which is the one the
    cutter is built on — projecting grid cells back onto the ring instead reads
    the wrong side of a thin bridge strip, the same trap `_carve_pad_splay`
    documents for its own windowed polyline.
    """
    from guildmodel.core.geometry.rings import inward_normals
    from guildmodel.core.model.build import build_castle_model
    from guildmodel.core.model.kernel import surface_z_at, to_trimesh
    from guildmodel.core.relief.features import _bottom_center_station

    body = aviator.partition.body
    bare = to_trimesh(build_castle_model(aviator.partition,
                                         _castle(enabled=False),
                                         aviator.hinge_polys))
    cut = to_trimesh(build_castle_model(
        aviator.partition,
        _castle(non_contiguous=True, gap_mm=12.0, feather_mm=4.0),
        aviator.hinge_polys))

    ring, total, s0 = _bottom_center_station(body)
    us = np.arange(6.0, 13.01, 0.5)                 # the OD span's inner end is +6
    pts, tans = [], []
    for u in us:
        s = (s0 + float(u)) % total
        q = ring.interpolate(s)
        a = ring.interpolate((s - 0.75) % total)
        b = ring.interpolate((s + 0.75) % total)
        t = np.array([b.x - a.x, b.y - a.y])
        pts.append([q.x, q.y]); tans.append(t / max(np.linalg.norm(t), 1e-12))
    pts, tans = np.array(pts), np.array(tans)
    probe = pts + inward_normals(body, pts, tans) * 0.3

    depth = surface_z_at(bare, probe) - surface_z_at(cut, probe)
    assert np.isfinite(depth).all(), "the probe missed the part"

    assert depth[-1] > 0.2, "no cut 7 mm in — the span is in the wrong place"
    assert depth[0] < 0.05, (
        f"the cut still starts {depth[0]:.3f} mm deep at the keyhole edge — "
        "a wall, not a run-out")
    # Monotonic outward through the feather, to a millimetre of grid slack.
    assert np.all(np.diff(depth[:9]) > -0.05), (
        f"the run-out is not monotonic: {np.round(depth[:9], 3).tolist()}")


def test_the_lift_is_the_stations_own_depth_not_the_floored_one(aviator):
    """A station whose crest has already gone to zero has no depth to lift.

    `crest_deviation_end_mm = 0` takes the crest to zero at the outer run end all
    by itself, and `drops` is floored at `MIN_TAPER_DROP_MM` before it is used.
    Lifting by the floored value moved a section that was sitting flush on the
    surface by 0.02 mm and handed the sweep a degenerate end cap — measured as a
    zero-length edge at `u = run` exactly, on the outline, at the eyewire terrace
    height, on the gabriel with a 5.5 mm feather.

    So: with the crest tapering to nothing on its own, the feather must change
    nothing at that end. Checked as bit-equality against the same build with the
    feather off, over the last millimetre of the run.
    """
    from guildmodel.core.model.features import splay_cutter
    from guildmodel.core.model.build import build_castle_model
    from guildmodel.core.model.kernel import to_trimesh

    bare = to_trimesh(build_castle_model(aviator.partition,
                                         _castle(enabled=False),
                                         aviator.hinge_polys))
    body = aviator.partition.body
    kw = dict(crest_deviation_end_mm=0.0, run_mm=18.0)
    tip = splay_cutter(bare, body, _castle(feather_mm=4.0, **kw).pad_splay)
    flat = splay_cutter(bare, body, _castle(feather_mm=0.0, **kw).pad_splay)

    tip_m, flat_m = to_trimesh(tip), to_trimesh(flat)
    # The far ends are the same geometry; only the middle differs.
    assert tip_m.bounds[1][0] == pytest.approx(flat_m.bounds[1][0], abs=1e-9)
    assert tip_m.bounds[0][0] == pytest.approx(flat_m.bounds[0][0], abs=1e-9)
    # And the feathered cutter is the smaller one — it lifted out of the run.
    assert tip_m.volume < flat_m.volume


# ------------------------------------------------------------------ the kernels

def test_mesh_kernel_builds_two_cutters_and_a_closed_solid(aviator):
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model.build import build_castle_model
    from guildmodel.core.model.features import splay_cutters
    from guildmodel.core.model.kernel import to_trimesh

    castle = _castle(non_contiguous=True, gap_mm=12.0)
    bare = to_trimesh(build_castle_model(aviator.partition,
                                         _castle(enabled=False),
                                         aviator.hinge_polys))
    # Two bodies, not one strip with a flat middle — nothing stands over the gap.
    assert len(splay_cutters(bare, aviator.partition.body, castle.pad_splay)) == 2
    assert len(splay_cutters(bare, aviator.partition.body,
                             _castle().pad_splay)) == 1

    built = to_trimesh(build_castle_model(aviator.partition, castle,
                                          aviator.hinge_polys))
    verdict = verify_mesh(built)
    assert verdict.ok, verdict.summary
    assert built.volume < bare.volume            # it did cut something
    whole = to_trimesh(build_castle_model(aviator.partition, _castle(),
                                          aviator.hinge_polys))
    assert whole.volume < built.volume           # and less than the whole run


def test_brep_kernel_agrees_on_the_span_count(aviator):
    pytest.importorskip("OCP")
    from guildmodel.core.solid import castle_base, clear_base_cache
    from guildmodel.core.solid.features import splay_cutters

    castle = _castle(non_contiguous=True, gap_mm=12.0)
    clear_base_cache()
    # castle_base returns (partition, heights, top, solid)
    _part, _h, _top, base = castle_base(aviator.partition, _castle(enabled=False))
    assert len(splay_cutters(base, aviator.partition.body,
                             castle.pad_splay)) == 2
    assert len(splay_cutters(base, aviator.partition.body,
                             _castle().pad_splay)) == 1
