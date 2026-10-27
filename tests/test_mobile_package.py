"""The mobile/luister package stub exposes the app version."""

import importlib.util
from pathlib import Path

MOBILE_PKG = Path(__file__).resolve().parent.parent / "mobile" / "luister" / "__init__.py"


def test_mobile_package_version_matches_buildozer_spec():
    spec = importlib.util.spec_from_file_location("luister_mobile_pkg", MOBILE_PKG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    spec_text = (MOBILE_PKG.parent.parent / "buildozer.spec").read_text()
    assert f"version = {module.__version__}" in spec_text
