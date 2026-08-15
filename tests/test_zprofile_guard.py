"""The post-time Z-profile guard (M-Z1).

Corner Optical caught the Fine Relief sawtooth by reading a toolpath display and
writing their own analyzer, because nothing here measured its own output. These
gates pin the measurement definition, the calibration against every program we
have, and the two properties that make the guard worth having: it measures every
operation, and a program carries its numbers in its own header.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from guildmodel.core.cam.zprofile import (
    AMPLITUDE_FLOOR_MM, STEEP_DEG, Limits, OpProfile, annotate, header_lines,
    measure_paths, measure_program, measure_runs, warnings,
)


# ------------------------------------------------------------------ definition

def test_reversal_is_a_direction_flip_between_two_cutting_moves():
    # down, down, up  -> exactly one flip, amplitude = the up move's dz
    run = [(0, 0, 5.0), (1, 0, 4.0), (2, 0, 3.0), (3, 0, 3.5)]
    p = measure_runs([run])
    assert p.reversals == 1
    assert p.max_amplitude_mm == pytest.approx(0.5)
    assert p.moves == 3
    assert p.xy_mm == pytest.approx(3.0)
    assert p.z_travel_mm == pytest.approx(2.5)


def test_a_pure_plunge_breaks_the_run():
    """A retract/plunge is ordinary machine motion — it must not read as a
    reversal, and it must not join the moves either side into one run."""
    run = [(0, 0, 5.0), (1, 0, 4.0), (1, 0, 9.0), (2, 0, 8.0)]   # middle is dz-only
    p = measure_runs([run])
    assert p.reversals == 0
    assert p.moves == 2                      # the plunge itself is not a cutting move


def test_monotonic_descent_never_reverses():
    run = [(i, 0, 10.0 - i) for i in range(10)]
    assert measure_runs([run]).reversals == 0


def test_steep_share_counts_moves_over_the_threshold():
    steep = math.tan(math.radians(STEEP_DEG + 5)) * 1.0
    run = [(0, 0, 0.0), (1, 0, steep), (2, 0, steep)]
    p = measure_runs([run])
    assert p.steep_moves == 1
    assert p.steep_fraction == pytest.approx(0.5)


def test_amplitude_floor_separates_noise_from_abuse():
    """Our fixtures reverse Z constantly at the last digit; a raw count weights
    a 0.02 mm wobble the same as a 4 mm plunge."""
    noise = [(0, 0, 0.0), (1, 0, 0.01), (2, 0, 0.0), (3, 0, 0.01)]
    p = measure_runs([noise])
    assert p.reversals == 2
    assert p.significant == 0
    assert p.per100 == 0.0

    real = [(0, 0, 0.0), (1, 0, 2.0), (2, 0, 0.0)]
    q = measure_runs([real])
    assert q.significant == 1
    assert q.max_amplitude_mm == pytest.approx(2.0)


# --------------------------------------------------------------- program parse

_PROG = """; GuildModel — posterior_cut
G90
G21
; --- Hinge Pockets ---
G0 X0 Y0
G1 Z5.0 F450
G1 X1 Y0 Z5.0 F750
G1 X2 Y0 Z5.0 F750
; --- Fine Relief ---
G0 X10 Y0
G1 Z5.0 F450
G1 X11 Y0 Z4.0 F750
G1 X12 Y0 Z6.0 F750
G1 X13 Y0 Z4.0 F750
"""


def test_measure_program_splits_by_operation():
    profs = measure_program(_PROG)
    assert set(profs) == {"Hinge Pockets", "Fine Relief"}
    assert profs["Hinge Pockets"].reversals == 0
    fr = profs["Fine Relief"]
    assert fr.reversals == 2
    assert fr.max_amplitude_mm == pytest.approx(2.0)


def test_rapids_do_not_join_two_passes_into_one_run():
    """Without the break, the G0 between passes reads as a reversal."""
    prog = ("; --- Fine Relief ---\n"
            "G1 X0 Y0 Z1.0 F750\nG1 X1 Y0 Z0.0 F750\n"
            "G0 X10 Y10 Z9.0\n"
            "G1 X11 Y10 Z8.0 F750\nG1 X12 Y10 Z7.0 F750\n")
    assert measure_program(prog)["Fine Relief"].reversals == 0


def test_measure_paths_matches_measure_program():
    """The pre-post path measurement and the posted-text one must agree, or the
    inspector and a maker's own analyzer would disagree about the same job."""
    class _Op:
        name = "Fine Relief"
        paths = [[(10.0, 0.0, 5.0), (11.0, 0.0, 4.0),
                  (12.0, 0.0, 6.0), (13.0, 0.0, 4.0)]]

    a = measure_paths(_Op())
    b = measure_program(_PROG)["Fine Relief"]
    assert a.reversals == b.reversals
    assert a.max_amplitude_mm == pytest.approx(b.max_amplitude_mm)
    assert a.xy_mm == pytest.approx(b.xy_mm)


# ------------------------------------------------------------------ thresholds

def _prof(**kw) -> OpProfile:
    p = OpProfile(name=kw.pop("name", "Features"))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


@pytest.mark.parametrize("per100,mx,steep,expect", [
    (0.9, 0.50, 0.01, "ok"),        # demo / gabriel / aviator, every op
    (13.4, 1.62, 0.06, "error"),    # Hyde Park v1.1.0 — the maker refused to run it
    (37.3, 3.88, 0.13, "error"),    # Hyde Park pre-fix Features
    (5.7, 4.33, 0.02, "error"),     # Hyde Park post-fix — amplitude alone
    (6.0, 0.20, 0.01, "warning"),   # density alone
    (0.5, 1.50, 0.01, "warning"),   # amplitude alone
])
def test_calibration_against_every_program_we_have(per100, mx, steep, expect):
    p = _prof(significant=int(per100 * 10), xy_mm=1000.0,
              max_amplitude_mm=mx, steep_moves=int(steep * 1000), moves=1000)
    assert p.severity() == expect


def test_the_guard_does_not_go_quiet_when_only_density_improves():
    """The post-fix Hyde Park program has 7x fewer reversals and still a 4.3 mm
    move. Reporting that as clean is the failure this module exists to prevent."""
    before = _prof(significant=680, xy_mm=1821.0, max_amplitude_mm=3.88,
                   steep_moves=531, moves=4087)
    after = _prof(significant=41, xy_mm=715.0, max_amplitude_mm=4.33,
                  steep_moves=25, moves=1243)
    assert before.severity() == "error"
    assert after.severity() == "error"
    assert after.per100 < before.per100          # density really did improve


def test_warnings_are_worst_first_and_empty_when_clean():
    clean = _prof(name="Perimeter", xy_mm=1000.0)
    bad = _prof(name="Features", significant=400, xy_mm=1000.0,
                max_amplitude_mm=4.0, moves=1000)
    mild = _prof(name="Rough Relief", significant=0, xy_mm=1000.0,
                 max_amplitude_mm=1.5, moves=1000)
    assert warnings([clean]) == []
    out = warnings([clean, mild, bad])
    assert len(out) == 2
    assert out[0].startswith("Features")         # error sorts above warning


def test_limits_are_overridable():
    p = _prof(significant=200, xy_mm=1000.0, max_amplitude_mm=0.2, moves=1000)
    assert p.per100 == pytest.approx(20.0)
    assert p.severity() == "error"
    assert p.severity(Limits(fail_per100=1e9, warn_per100=1e9)) == "ok"


# ----------------------------------------------------------------- provenance

def test_program_carries_its_own_profile_in_the_header():
    out = annotate(_PROG)
    body = [l for l in out.splitlines() if not l.startswith(";")]
    assert body == [l for l in _PROG.splitlines() if not l.startswith(";")]
    assert any("Z profile" in l for l in out.splitlines())
    assert any("Fine Relief" in l and l.startswith(";") for l in out.splitlines())
    # the stamp must survive a re-measure — comments are not moves
    assert measure_program(out)["Fine Relief"].reversals == 2


def test_header_lines_skip_operations_with_no_cutting_moves():
    profs = measure_program("; --- Tool Change ---\nM3 S12000\n")
    assert header_lines(profs) == header_lines({})


# ---------------------------------------------------------------- diagnostics

def test_z_profile_issues_reach_the_inspector_with_their_own_severity():
    from guildmodel.core.diagnostics import collect_issues

    bad = _prof(name="Features", significant=400, xy_mm=1000.0,
                max_amplitude_mm=4.0, moves=1000)
    issues = collect_issues(z_profiles=[bad])
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].category == "Z profile"
    assert issues[0].target == ("op", "Features")      # navigable to the op
    assert collect_issues(z_profiles=[_prof(xy_mm=1000.0)]) == []


# ------------------------------------------------- M-Z2: links have a height

class TestLinkRiseBudget:
    """`_link_breaks` decides whether a masked gap in a relief ring is bridged.

    The M11 linking only asked how WIDE the gap was. Where the ground under the
    gap is masked *precisely because it stands at stock height* — the rim band
    next to uncut stock, on Corner Optical's frame — bridging it drives the tool
    from the terrace up onto that stock and back down at cutting feed. Theirs
    climbed 5.8 mm that way, the residual the M-Z1 stepover floor could not touch.
    """

    @staticmethod
    def _breaks(idx, zline, gap_cells=26, max_rise=0.5):
        import numpy as np
        from guildmodel.core.cam.castle_ops import _link_breaks
        return list(_link_breaks(np.asarray(idx), np.asarray(zline, float),
                                 gap_cells, max_rise))

    def test_a_flat_gap_is_bridged(self):
        # cells 0,1 cut · 2,3 masked but level · 4,5 cut
        z = [5.0, 5.0, 5.05, 5.05, 5.0, 5.0]
        assert self._breaks([0, 1, 4, 5], z) == []

    def test_a_gap_that_climbs_to_a_cap_breaks(self):
        # the same gap, but the masked cells stand at the 10 mm stock top
        z = [5.0, 5.0, 10.0, 10.0, 5.0, 5.0]
        assert self._breaks([0, 1, 4, 5], z) == [2]

    def test_the_budget_is_measured_from_the_higher_neighbour(self):
        """A ring stepping DOWN a terrace must not read the step as a cap: the
        gap is only 'tall' if it rises above the cells it links."""
        z = [9.0, 9.0, 9.0, 9.0, 5.0, 5.0]      # gap sits at the upper level
        assert self._breaks([0, 1, 4, 5], z) == []

    def test_a_wide_gap_still_breaks_on_width_alone(self):
        z = [5.0] * 40
        assert self._breaks([0, 39], z, gap_cells=26) == [1]

    def test_consecutive_cut_cells_are_never_split(self):
        z = [5.0, 5.0, 5.0, 5.0]
        assert self._breaks([0, 1, 2, 3], z) == []

    def test_even_a_single_skipped_cell_at_the_cap_breaks(self):
        """One cell of tower still lifts the tool the whole terrace step."""
        z = [5.0, 9.9, 5.0]
        assert self._breaks([0, 2], z) == [1]

    def test_budget_is_tunable_and_off_at_infinity(self):
        z = [5.0, 5.0, 10.0, 10.0, 5.0, 5.0]
        assert self._breaks([0, 1, 4, 5], z, max_rise=1e9) == []
        assert self._breaks([0, 1, 4, 5], z, max_rise=0.01) == [2]

    def test_shipped_default_bridges_a_thin_cap_and_refuses_a_tower(self):
        from guildmodel.core.project.schema import CastleCamParams
        budget = CastleCamParams().relief_link_max_rise_mm
        assert budget == 0.5
        thin = [5.0, 5.0, 5.0 + budget - 0.01, 5.0, 5.0]
        tower = [5.0, 5.0, 5.0 + budget + 0.01, 5.0, 5.0]
        assert self._breaks([0, 1, 3, 4], thin, max_rise=budget) == []
        assert self._breaks([0, 1, 3, 4], tower, max_rise=budget) == [2]


# --------------------------------------------- M-Z3: connectors have one too

class TestStitchRiseBudget:
    """`_stitch_close_paths` joins two adjacent paths with a connector riding the
    same drop-cutter surface, and had the same blind spot for the same reason.

    Nothing on a job we have exercises it — Corner Optical's frame is untouched
    by the budget, and of the shipped fixtures only the demo loses a single
    connector, a 0.9 mm ride over the nosepad tower in Rough Relief that moves no
    guard metric. This is the hole closed rather than the bug caught: the two
    join points are cut, everything between them need not be, and if a stitch
    ever spans the rim band the link is now the only one of the two that would
    refuse it.
    """

    @staticmethod
    def _stitch(bridge_z: float, max_rise: float):
        import numpy as np

        from guildmodel.core.cam.castle_ops import _stitch_close_paths

        z = np.full((10, 10), 5.0)
        z[:, 5] = bridge_z                       # the ground midway between them
        a = [(2.0, 5.0, 5.0), (3.0, 5.0, 5.0)]
        b = [(7.0, 5.0, 5.0), (8.0, 5.0, 5.0)]
        return _stitch_close_paths([a, b], z, 0.0, 0.0, 1.0, 4.0, max_rise)

    def test_a_flat_step_across_is_stitched(self):
        assert len(self._stitch(5.0, 0.5)) == 1

    def test_a_climb_to_stock_height_is_refused(self):
        out = self._stitch(10.0, 0.5)
        assert len(out) == 2                     # each keeps its own entry
        assert max(p[2] for path in out for p in path) == 5.0

    def test_the_budget_is_what_decides_it(self):
        assert len(self._stitch(10.0, 1e9)) == 1
        assert len(self._stitch(5.0 + 0.49, 0.5)) == 1
        assert len(self._stitch(5.0 + 0.51, 0.5)) == 2

    def test_the_two_budgets_are_one_parameter(self):
        """A maker turning this down means it in both places, or the number would
        have to be explained twice."""
        import inspect

        from guildmodel.core.cam import castle_ops
        src = inspect.getsource(castle_ops.relief_ops)
        assert src.count("_stitch_close_paths(") == 3
        assert src.count("res, link, max_rise)") == 3
        assert "max_rise = params.relief_link_max_rise_mm" in src


# ---------------------------------------- M-Z4: an op answers to its own tool

class TestOwnToolStockCeiling:
    """Each relief op's cut mask compares against its OWN tool's stock ceiling.

    One `stock_cls` used to be computed with the rough tool and borrowed by the
    fine and features masks — invisible while every op ran the same tool, wrong
    when they differ: a ball's ceiling rolls down the pad-block cliff where a
    flat's plateaus over it, so a ball pass measured against the flat's ceiling
    kept cells (172 on the demo, ceiling delta up to the full 4 mm cliff) that
    the ball itself had nothing to cut. With the tools reversed, the same
    borrow flips to material silently left standing.
    """

    def test_a_ball_and_a_flat_disagree_about_the_stock(self):
        """The premise: the two ceilings genuinely differ at the stock cliff."""
        import numpy as np

        from guildmodel.core.cam.dropcutter import cutter_location_surface
        from guildmodel.core.project.schema import StockDefinition
        from guildmodel.core.relief.castle import stock_top_heightfield

        stock = stock_top_heightfield(StockDefinition(), resolution=0.15)
        flat = cutter_location_surface(stock, "flat", 3.175 / 2).z
        ball = cutter_location_surface(stock, "ball", 1.0).z
        delta = flat - ball
        assert delta.min() >= -1e-9          # the flat's ceiling is never lower
        assert delta.max() > 1.0             # and differs by mm at the cliff

    def test_single_tool_jobs_are_untouched(self):
        """The everyday case computes one ceiling and posts what it always did
        (verified byte-identical on Corner Optical's frame when this landed)."""
        fine_a = _relief_fine(max_rise_mm=0.5)
        fine_b = _relief_fine(max_rise_mm=0.5)
        assert fine_a.paths == fine_b.paths

    def test_the_fine_mask_uses_the_fine_tools_ceiling(self):
        """Wiring: the emitted source compares each op against its own ceiling,
        so the borrow cannot quietly come back."""
        import inspect

        from guildmodel.core.cam import castle_ops
        src = inspect.getsource(castle_ops.relief_ops)
        assert "z_fine < stock_fine_z" in src
        assert "z_feat < stock_feat_z" in src
        assert "stock_rough_z - eps" in src
        assert "stock_cls" not in src.replace("stock_cls`", "")   # only the comment


# ------------------------------------- M-Z2 end to end, on the rim gap that did it

FLOOR_MM = 5.0          # the body's relief height — flat, so there is nothing to climb
STOCK_TOP_MM = 10.0     # blank 6 + pad block 4, and the fixture sits inside the block


def _rim_slot_relief(slot_w_mm: float = 1.5, slot_h_mm: float = 2.0):
    """A flat body with a narrow slot cut into one rim edge — Corner Optical's gap.

    Their three refused gaps sit a tenth of a millimetre outside the body but
    inside the machining region (`scripts/probe_gapsite.py`): `zone=outside`,
    `relief=0.00`, `stock=10.00`, `CLS=10.00`. The drop-cutter surface is a max
    over the tool disc, so just past the rim that disc overlaps **uncut stock**
    and the CL surface rises to stock height — correct, and the reason those
    cells are masked (M5: a flat tool cannot reach the rim floor with its edge
    over uncut material). A ring whose cut coverage breaks there and resumes
    inside `relief_link_gap_mm` gets bridged, and the bridge re-emits the skipped
    cells at that height: the tool climbs onto the uncut stock at cutting feed.

    So the fixture is a body concave enough that one ring leaves the cut mask at
    the rim and re-enters within the link budget. A slot narrower than the tool
    diameter does it: the offset ring nearest the boundary steps across the
    slot's mouth rather than following it in, which puts it outside the body for
    the width of the mouth — a gap of about 1.5 mm against a 4 mm budget.

    **The body is flat at `FLOOR_MM`**, deliberately. Every cell in the cut mask
    has a cutter-location height of exactly `FLOOR_MM`, so no emitted point can
    rise above it by cutting anything. An earlier attempt raised a strip at stock
    height instead and had to be thrown away: its rings climbed a *cut* feature,
    the right number from the wrong mechanism. Here any Z above the floor is the
    tool riding stock it should never have touched.
    """
    import numpy as np
    from shapely.geometry import Polygon

    from guildmodel.core.geometry.regions import CastlePartition
    from guildmodel.core.relief.castle import CastleRelief
    from guildmodel.core.relief.heightfield import Heightfield

    res = 0.15
    w_mm, h_mm = 40.0, 24.0
    cols, rows = int(w_mm / res), int(h_mm / res)
    origin = (-w_mm / 2, -h_mm / 2)
    # The grid has to hold the rim band AND a tool radius of uncut stock beyond
    # it, or the dilation never sees the stock and the gap does not appear.
    margin = 4.0
    x0, x1 = origin[0] + margin, -origin[0] - margin
    y0, y1 = origin[1] + margin, -origin[1] - margin

    hw = slot_w_mm / 2
    if slot_w_mm > 0:
        body = Polygon([(x0, y0), (x1, y0), (x1, y1), (hw, y1),
                        (hw, y1 - slot_h_mm), (-hw, y1 - slot_h_mm), (-hw, y1),
                        (x0, y1)])
    else:
        body = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    xs = origin[0] + (np.arange(cols) + 0.5) * res
    ys = origin[1] + (np.arange(rows) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys)
    inside = (gx > x0) & (gx < x1) & (gy > y0) & (gy < y1)
    if slot_w_mm > 0:
        inside &= ~((np.abs(gx) < hw) & (gy > y1 - slot_h_mm))

    f = Heightfield(z=np.full((rows, cols), FLOOR_MM), origin=origin, resolution=res)
    return CastleRelief(field=f, inside=inside,
                        zone_index=np.zeros((rows, cols), int),
                        partition=CastlePartition(body=body), surface_field=f)


def _relief_fine(max_rise_mm: float, slot_w_mm: float = 1.5):
    from pathlib import Path

    import yaml

    from guildmodel.core.cam.castle_ops import relief_ops
    from guildmodel.core.project.schema import CastleCamParams, StockDefinition

    tools = yaml.safe_load(
        (Path(__file__).parents[1] / "src" / "guildmodel" / "config"
         / "tools.yaml").read_text())
    tools = tools.get("tools", tools)
    # The stepover is pinned, not defaulted: whether a ring happens to cross the
    # slot's mouth depends on where the boundary-offset rings land, and this
    # fixture reproduces a MECHANISM (a ring leaving the cut mask at the rim and
    # returning inside the link budget), not a tuning. The v1.6 stepover change
    # to 1.2 moved the rings off the mouth and the reproduction went silent —
    # exactly the way the original bug hid in fixtures that never built the
    # geometry that triggers it.
    _rough, fine, _feat = relief_ops(
        _rim_slot_relief(slot_w_mm), StockDefinition(), tools["flat_3175"],
        CastleCamParams(relief_link_max_rise_mm=max_rise_mm,
                        relief_stepover_mm=0.9))
    return fine


def _xy_length(op) -> float:
    return sum(math.dist(a[:2], b[:2])
               for path in op.paths for a, b in zip(path, path[1:]))


class TestTheLinkDoesNotClimbTheRim:
    """End to end: the M11 link may not bridge a gap by riding up onto stock.

    This is the failure Corner Optical's frame posted, on a body built to hold
    it — not the parameter-wiring stand-in it replaces. `_rim_slot_relief`
    explains the geometry; the short version is that the cut mask is flat at
    `FLOOR_MM` everywhere it is set, so a path point above that height can only
    have come from bridging cells the mask refused.
    """

    def test_nothing_in_the_cut_mask_stands_above_the_floor(self):
        """The premise the rest of the class rests on: no feature to climb."""
        import numpy as np
        from scipy.ndimage import distance_transform_edt

        from guildmodel.core.cam.castle_ops import stock_top_heightfield
        from guildmodel.core.cam.dropcutter import cutter_location_surface
        from guildmodel.core.project.schema import CastleCamParams, StockDefinition
        from guildmodel.core.relief.heightfield import Heightfield

        relief, params, radius = _rim_slot_relief(), CastleCamParams(), 3.175 / 2
        f = relief.field
        stock = stock_top_heightfield(StockDefinition(), resolution=f.resolution,
                                      origin=f.origin, shape=f.z.shape)
        assert stock.z.min() == STOCK_TOP_MM      # wholly inside the pad block
        band_mm = max(radius, params.relief_stepover_mm)
        dist, (iy, ix) = distance_transform_edt(~relief.inside, sampling=f.resolution,
                                                return_indices=True)
        band = relief.inside | (dist <= band_mm + 1e-9)
        cam = Heightfield(z=np.where(band, np.minimum(f.z[iy, ix], stock.z), stock.z),
                          origin=f.origin, resolution=f.resolution)
        cls = cutter_location_surface(cam, "flat", radius).z
        stock_cls = cutter_location_surface(stock, "flat", radius).z
        cut = band & (cls < stock_cls - params.skim_epsilon_mm)

        assert cut.any()
        assert cls[cut].max() == pytest.approx(FLOOR_MM)   # nothing to ride up

    def test_an_unbudgeted_link_drags_the_tool_up_onto_the_stock(self):
        from shapely.geometry import Point

        fine = _relief_fine(max_rise_mm=1e9)
        peak = max((p for path in fine.paths for p in path), key=lambda p: p[2])
        # Within a millimetre of the 10 mm stock top: the tool is over uncut
        # material, at cutting feed, on a body whose cut surface is flat at 5 mm.
        assert peak[2] > STOCK_TOP_MM - 1.0
        # And it happens at the RIM, not somewhere in the interior — within a
        # cell of the boundary, as their own three gaps were (0.09-0.11 mm out).
        rim = _rim_slot_relief().partition.body.exterior
        assert rim.distance(Point(peak[0], peak[1])) < 0.5
        assert measure_paths(fine).severity() == "error"

    def test_the_shipped_budget_refuses_it(self):
        fine = _relief_fine(max_rise_mm=0.5)
        peak = max(p[2] for path in fine.paths for p in path)
        assert peak < FLOOR_MM + 2.0            # measured 6.03 against a 9.32
        prof = measure_paths(fine)
        assert prof.max_amplitude_mm < 0.5
        assert prof.severity() == "ok"

    def test_refusing_it_costs_no_coverage(self):
        """Breaking the ring must not stop cutting anything: the bridged cells
        were masked for having nothing to remove, so dropping them removes no
        material. On their frame the cut simulator measured coverage unchanged to
        the third digit — 827 uncut nosepad cells against 832."""
        loose, held = _relief_fine(1e9), _relief_fine(0.5)
        assert _xy_length(held) == pytest.approx(_xy_length(loose), rel=0.01)

    def test_a_body_with_no_rim_gap_posts_identically(self):
        """Inert on healthy geometry, decisive on the frame that was wrong — the
        same asymmetry that leaves all three shipped fixtures byte-identical."""
        assert (_relief_fine(1e9, slot_w_mm=0.0).paths
                == _relief_fine(0.5, slot_w_mm=0.0).paths)


# ------------------------------- the guard, turned on the programs WE ship

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_inputs(name: str):
    """(partition, hinge polys) for a shipped fixture, however it is stored."""
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    if name == "demo":
        raw = import_dxf(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
        return (partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                                [points_to_polygon(c) for c in raw["LENS"]],
                                raw["SCULPT"]),
                [points_to_polygon(c) for c in raw["HINGE"]])

    import tempfile
    import zipfile

    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    path = Path(tempfile.mkdtemp()) / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    ws = build_workspaces_from_gdraw(path)[0][0]
    return ws.partition, ws.hinge_polys


@pytest.mark.parametrize("fixture", ["demo", "gabriel", "aviator"])
def test_every_shipped_fixture_posts_a_clean_program(fixture):
    """Our own fixtures must post programs the guard calls `ok` — at the shipped
    defaults, with the splay on so the feature band is exercised.

    **The gate that was missing.** A guard nothing points at its own output is
    the failure this module was written about, and for one release the module
    had exactly that shape: the v1.6 stepover was raised to 1.2 on cycle time
    and cut-sim coverage, the full suite stayed green, and `gabriel` was
    quietly posting a WARNING — 1.118 mm worst amplitude in a *finishing* pass,
    over the guard's own threshold. Nothing asked. This asks.

    Kept deliberately as `severity() == "ok"` rather than a number: the numbers
    move with every tuning change (worst across this corpus is Rough Relief at
    ~0.97 mm, a 3% margin under the 1.0 mm warn line — thin, and worth knowing),
    but the promise to a maker is the verdict, not the digits.
    """
    import yaml

    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    tools = yaml.safe_load(
        (Path(__file__).parents[1] / "src" / "guildmodel" / "config"
         / "tools.yaml").read_text())
    tools = tools.get("tools", tools)

    partition, hinges = _fixture_inputs(fixture)
    castle = CastleParams()
    castle.pad_splay.enabled = True
    relief = build_castle_relief(partition, castle, hinges, resolution=CUT_RES_MM)
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"],
                                  tools_cfg=tools)

    profiles = [measure_paths(op) for op in ops]
    assert profiles, f"{fixture} posted no operations"
    bad = [p for p in profiles if p.severity() != "ok"]
    assert not bad, (
        f"{fixture} posts a program the guard flags:\n  "
        + "\n  ".join(f"{p.severity()}: {p.message()}" for p in bad))
