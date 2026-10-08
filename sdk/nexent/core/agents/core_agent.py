"""Compatibility alias for the relocated implementation.

Keep the legacy import and patch target attached to the same module instance.
"""

import sys
from importlib import import_module

_implementation = import_module(".execution.code.legacy_agent", __package__)
sys.modules[__name__] = _implementation
