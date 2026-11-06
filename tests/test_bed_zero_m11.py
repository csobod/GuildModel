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


# ------------------------------------------------------------------ 2.3.1: said, and read back

def test_the_zero_label_says_the_point_on_the_bed():
    """The bed's zero in words names the work area, not a blank, and the point
    the operator touches off, a shift included (a .bed's shift has no combo
    item); it ends "bottom face", which GuildSend reads."""
    wt = _bed()
    assert wt.zero_label() == ("Work area lower-left: touch off at bed X0.00 Y0.00, "
                               "bottom face")
    wt.program_zero = ProgramZero(x_ref="center", y_ref="center")
    assert wt.zero_label() == ("Work area center: touch off at bed X150.00 Y100.00, "
                               "bottom face")
    wt.program_zero = ProgramZero(x_ref="left", y_ref="bottom",
                                  shift_x_mm=85.0, shift_y_mm=35.0)
    assert wt.zero_label() == ("Work area lower-left, shifted (+85.00, +35.00) mm: "
                               "touch off at bed X85.00 Y35.00, bottom face")
    wt.program_zero = ProgramZero(mode="fixture")
    assert wt.zero_label().endswith("bottom face")
    assert "top face" not in wt.zero_label()


def test_a_program_is_read_back_less_the_zero_it_was_posted_with():
    """`parse_program` takes the post's work offset back out, so a reader gets
    the frame the ops were built in (the bed sim did not, 2.3.1)."""
    from guildmodel.core.stock import parse_program
    text = "G21\nG90\nG0 X-90.0 Y-60.0 Z5.0\nG1 Z-1.0 F200\nG1 X-70.0 Y-60.0\n"
    plain = parse_program(text)
    back = parse_program(text, work_offset=(-100.0, -100.0, 0.0))
    assert [p[:3] for r in back for p in r.points] == [
        (x + 100.0, y + 100.0, z) for r in plain for (x, y, z, *_a) in r.points]
    assert back[-1].points[-1][:3] == (30.0, 40.0, -1.0)


def test_the_grouped_program_reader_takes_the_zero_out_too():
    """`bed_report_from_program` reads through the grouped paths; they take the
    offset as `parse_program` does."""
    from guildmodel.core.sim.paths import cutting_paths_from_program_grouped
    text = "G90\nG0 X-90 Y-60 Z5\nG1 Z-1 F200\nG1 X-70 Y-60 F200\n"
    (path, _tool), = cutting_paths_from_program_grouped(text, work_offset=(-100.0, -100.0, 0.0))
    assert path[-1] == (30.0, 40.0, -1.0)
