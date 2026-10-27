"""Loader for the mobile/main.py script (not an installed package)."""

import importlib.util
import os
import sys

_MOD = None
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mobile", "main.py")


def load_mobile_main(name="luister_mobile_main_shared", fresh=False):
    """Import mobile/main.py under a unique module name (cached unless fresh)."""
    global _MOD
    if _MOD is not None and not fresh and name == "luister_mobile_main_shared":
        return _MOD
    spec = importlib.util.spec_from_file_location(name, _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    if name == "luister_mobile_main_shared":
        _MOD = mod
    return mod
