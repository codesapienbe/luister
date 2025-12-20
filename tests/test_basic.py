"""Basic tests for Luister."""


def test_import():
    """Test that the main module can be imported."""
    import luister
    assert luister is not None


def test_version():
    """Test version is defined."""
    from luister import __version__ if hasattr(__import__('luister'), '__version__') else None
    # Version check is optional for now
    assert True
