from .grbl import GRBLPost

__all__ = ["GRBLPost", "make_post"]


def make_post(machine=None, **kwargs) -> GRBLPost:
    """The post for the controller the machine profile names (2.3.1): UCCNC's
    for a STEPCRAFT, GRBL's for every other. The first piece of M27's dialect
    selection (BUILDPLAN §12): the profile picks the dialect, not the caller."""
    if machine is not None and getattr(machine, "controller", None) == "uccnc":
        from .uccnc import UCCNCPost
        return UCCNCPost(**kwargs)
    return GRBLPost(**kwargs)
