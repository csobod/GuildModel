"""Worktable bed zero (BUILDPLAN M11): the whole-bed worktable.nc touches off its
own datum over the work-area box, separate from each component's program zero."""
from guildmodel.core.project.schema import ProgramZero, Worktable


def _bed():
    return Worktable(work_area_width_mm=300.0, work_area_height_mm=200.0)


def test_default_bed_zero_is_lower_left_origin():
    assert _bed().bed_work_offset() == (0.0, 0.0, 0.0)        # historical bed origin


def test_center_zero_shifts_to_work_area_center():
    wt = _bed()
    wt.program_zero = ProgramZero(x_ref="center", y_ref="center")
    assert wt.bed_work_offset() == (-150.0, -100.0, 0.0)


def test_upper_right_maps_to_work_area_extent():
    wt = _bed()
    wt.program_zero = ProgramZero(x_ref="right", y_ref="top")
    assert wt.bed_work_offset() == (-300.0, -200.0, 0.0)


def test_fixture_mode_keeps_raw_bed_coords():
    wt = _bed()
    wt.program_zero = ProgramZero(mode="fixture")
    assert wt.bed_work_offset() == (0.0, 0.0, 0.0)
