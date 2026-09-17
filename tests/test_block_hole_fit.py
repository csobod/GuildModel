"""Does the mounting pattern fit the lens it is drilled into?

`BaseCurveBlockParams.hole_centers()` is a fixed pattern — three M4 holes on a
10 mm pitch by default — and until 2026-09-16 nothing checked it against the lens
actually being cut. It does not fit every lens, and the failure is silent at
every gate the app had:

  * the mesh stays **watertight**, because a hole that breaks the rim merges into
    the outline and leaves a clean notch, so `verify_mesh` reports "Model
    verified";
  * the viewer draws it;
  * `generate_block_program` drills it anyway.

Swept over a maker's own corpus it is not hypothetical: 10 of 96 templates
fail, and the smallest eye in it — 43 mm — comes out with **one** usable
mounting point instead of three. Genus is the tell: a good template is Euler
−4, and that one's two are 0.
"""
import pytest
from shapely.geometry import Point, Polygon

from guildmodel.core.cam.block_ops import (HoleFit, hole_fit_warnings,
                                           hole_fits)
from guildmodel.core.project.schema import BaseCurveBlockParams


def _round_lens(radius: float) -> Polygon:
    """A lens big enough to swallow the default pattern, or not, by radius."""
    return Point(0.0, 0.0).buffer(radius, quad_segs=128)


def test_a_roomy_lens_fits_the_default_pattern():
    """The 86 library templates that are fine must stay silent — a check that
    cries wolf on the healthy majority is worse than no check."""
    block = BaseCurveBlockParams()
    fits = hole_fits(_round_lens(25.0), block)
    assert len(fits) == block.hole_count
    assert all(f.inside and not f.breaches for f in fits)
    assert hole_fit_warnings(_round_lens(25.0), block) == []


def test_a_hole_breaking_the_rim_is_caught_and_measured():
    """The small-eye failure. The outer holes sit 10 mm off center with a 2.25 mm
    radius, so a 12 mm lens leaves them 0.25 mm proud of the rim."""
    block = BaseCurveBlockParams()
    fits = {f.center[0]: f for f in hole_fits(_round_lens(12.0), block)}
    assert fits[0.0].inside and not fits[0.0].breaches      # the center hole is fine
    assert fits[10.0].breaches and fits[10.0].inside
    assert fits[10.0].wall_mm == pytest.approx(-0.25, abs=0.02)

    warnings = hole_fit_warnings(_round_lens(12.0), block)
    assert len(warnings) == 2                               # both outer holes
    assert all("breaks through the block rim" in w for w in warnings)
    assert all("cannot be bolted" in w for w in warnings)


def test_a_hole_that_misses_the_block_entirely_is_named_differently():
    """Worse than a breach, and worth its own words: the drill plunges into blank
    scrap and the part gets no hole there at all. One library drawing has four
    templates like this, because ~220 mm2 decorative LENS curves each become
    their own block."""
    block = BaseCurveBlockParams()
    fits = {f.center[0]: f for f in hole_fits(_round_lens(5.0), block)}
    assert not fits[10.0].inside
    assert fits[10.0].wall_mm < 0

    warnings = hole_fit_warnings(_round_lens(5.0), block)
    assert any("off the block entirely" in w for w in warnings)
    assert not any("breaks through the block rim" in w for w in warnings[:1])


def test_a_wall_thinner_than_the_blank_is_flagged_before_it_breaks():
    """The thin-wall bound is the blank's own thickness, and it was measured, not
    chosen: across the library's 96 templates the walls fall into two populations
    with **nothing** between them — 86 at 6.84 mm or more (median 11.04), and 10
    at 1.14 mm or less. Any bound inside that empty band separates them;
    `blank_thickness_mm` sits in the middle of it and means something physical.

    A 15 mm lens leaves the outer holes 2.75 mm — comfortably inside the band.
    """
    block = BaseCurveBlockParams()
    fits = {f.center[0]: f for f in hole_fits(_round_lens(15.0), block)}
    assert fits[10.0].inside and not fits[10.0].breaches
    assert fits[10.0].wall_mm == pytest.approx(2.75, abs=0.02)
    assert fits[10.0].wall_mm < block.blank_thickness_mm

    warnings = hole_fit_warnings(_round_lens(15.0), block)
    assert len(warnings) == 2
    assert all("thinner than" in w for w in warnings)
    assert all("likely to break" in w for w in warnings)


def test_the_bound_moves_with_the_blank_rather_than_being_a_magic_number():
    """Thin the blank and the same wall stops being a complaint — the rule is
    "thinner than the plate is thick", not a constant someone typed."""
    lens = _round_lens(15.0)                       # 2.75 mm of wall
    assert hole_fit_warnings(lens, BaseCurveBlockParams()) != []
    thin_blank = BaseCurveBlockParams(blank_thickness_mm=2.0)
    assert hole_fit_warnings(lens, thin_blank) == []


def test_a_tighter_pitch_rescues_a_small_lens():
    """The warning has to be actionable, and the action it names is "reduce the
    hole pitch or diameter" — so that has to actually work.

    4 mm of pitch, not 5: at 5 the outer holes leave 4.75 mm against a 4.7625 mm
    blank and are still — correctly — a hair inside the complaint.

    On this lens the pitch is the binding constraint and the diameter cannot
    rescue it at any value: the outer holes sit 10 mm out on a 12 mm radius, so
    even a zero-width hole leaves 2 mm. The message offers both levers because
    on a wider lens either one works; here only the first does.
    """
    lens = _round_lens(12.0)
    assert hole_fit_warnings(lens, BaseCurveBlockParams()) != []
    assert hole_fit_warnings(lens, BaseCurveBlockParams(hole_spacing_mm=4.0)) == []
    assert hole_fit_warnings(lens, BaseCurveBlockParams(hole_diameter_mm=0.5)) != []
    # ...and on a roomier lens the diameter alone is enough.
    tight = _round_lens(16.0)
    assert hole_fit_warnings(tight, BaseCurveBlockParams()) != []
    assert hole_fit_warnings(tight, BaseCurveBlockParams(hole_diameter_mm=2.0)) == []


def test_the_fit_is_measured_against_the_centered_lens():
    """`hole_centers()` is in the block frame, which is the lens centerd on the
    origin (`center_on_origin`). A lens drawn far from the origin — every real
    one, they sit left and right of the bridge — must measure the same."""
    from shapely.affinity import translate

    block = BaseCurveBlockParams()
    here = hole_fits(_round_lens(25.0), block)
    there = hole_fits(translate(_round_lens(25.0), 60.0, -18.0), block)
    assert [round(f.wall_mm, 9) for f in here] == [round(f.wall_mm, 9) for f in there]


def test_holefit_reports_the_hole_it_is_talking_about():
    """The message names coordinates, so the maker can tell which of three."""
    warnings = hole_fit_warnings(_round_lens(12.0), BaseCurveBlockParams())
    assert any("(-10.0, +0.0)" in w for w in warnings)
    assert any("(+10.0, +0.0)" in w for w in warnings)
    assert isinstance(hole_fits(_round_lens(12.0), BaseCurveBlockParams())[0], HoleFit)
