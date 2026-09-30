"""Apex CLI.

Deliberately does not import :mod:`apex.cli.main`. Doing so makes
``python -m apex.cli.main`` warn that the module is already in
``sys.modules`` when the package finishes importing, and it drags the whole
command tree (and therefore click, rich and the content library) into any
``import apex.cli`` -- including the test suite.
"""

__all__: list[str] = []
"""Intentionally empty: import :mod:`apex.cli.main` for the command group."""
