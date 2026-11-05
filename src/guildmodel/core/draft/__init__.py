"""The draft view and the blueprint (2.3; research section 6).

Qt-free and kernel-free, like `core.forming`: the assembly is built from
the drawing's curves and the forming map, and nothing here reaches the CAM;
the built front's mesh, when the window hands it over, is formed by the
same map and gives the views their edges. A local frame per hinge pocket
gives the hinge axis; each temple is bent by its tip bend and opened to
the panto and splay targets; the butt cut follows; the checks of bench
alignment are reported; the sheets are composed with hidden lines removed
and painted by `gui.draft_render` (QPainter) or written by `dxf_out`.
"""
from .assembly import (Check, DraftAssembly, FrontInput, SideResult,
                       TempleInput, TemplePlacement, build_assembly)
from .hinges import HingeFill, PocketFit, fill_hinge, fit_pocket, hinge_detail
from .measure import Dimension, DraftMeasures, measure
from .sheet import Sheet, compose_sheets
from .tipbend import DEFAULT_DROP_MM, TipBend, resolve_tip_bend

__all__ = [
    "Check", "DEFAULT_DROP_MM", "Dimension", "DraftAssembly", "DraftMeasures",
    "FrontInput", "HingeFill", "PocketFit", "Sheet", "SideResult",
    "TempleInput", "TemplePlacement", "TipBend", "build_assembly",
    "compose_sheets", "fill_hinge", "fit_pocket", "hinge_detail", "measure",
    "resolve_tip_bend",
]
