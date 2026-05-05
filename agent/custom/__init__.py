import sys

from . import action, reco, sink

sys.modules.setdefault("custom", sys.modules[__name__])
sys.modules.setdefault("custom.action", action)
sys.modules.setdefault("custom.reco", reco)
sys.modules.setdefault("custom.sink", sink)


def register_all() -> None:
    action.register_all()
    reco.register_all()
    sink.register_all()


__all__ = ["register_all"]
