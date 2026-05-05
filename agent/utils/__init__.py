import sys

sys.modules.setdefault("utils", sys.modules[__name__])

from .logger import *
from .params import *
from .pienv import *

try:
    from .time import *
    from .version_checker import check_resource_version
except ImportError:
    logger.warning("utils module import failed")
