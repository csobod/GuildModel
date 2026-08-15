"""The post-time Z-profile guard (M-Z1).

Corner Optical caught the Fine Relief sawtooth by reading a toolpath display and
writing their own analyzer, because nothing here measured its own output. These
gates pin the measurement definition, the calibration against every program we
have, and the two properties that make the guard worth having: it measures every
operation, and a program carries its numbers in its own header.
"""
from __future__ import annotations

import math

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
