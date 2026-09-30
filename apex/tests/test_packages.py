"""Package-level contract tests.

These guard the shape of the public API rather than the behaviour of any
one function, which is why they live in their own file.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

PACKAGES = ["apex", "apex.cli", "apex.core", "apex.engine", "apex.teachers"]


#: Packages that must publish a real public surface. apex.cli is
#: deliberately absent: it exports nothing so that `import apex.cli` does
#: not drag in click, rich and the content library.
MUST_DECLARE_ALL = ["apex", "apex.core", "apex.engine", "apex.teachers"]


def _iter_submodules(package_name: str) -> list[str]:
    """Every importable module under *package_name*, excluding tests."""
    package = importlib.import_module(package_name)
    names = [package_name]
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
        if ".tests" in info.name or info.name.endswith(".tests"):
            continue
        names.append(info.name)
    return names


@pytest.mark.parametrize("package_name", PACKAGES)
def test_all_entries_are_importable(package_name: str) -> None:
    """Every name in __all__ must actually exist in the module.

    Regression: apex.core listed "Exercise" in __all__ while never importing
    it, so `from apex.core import *` raised AttributeError and
    `from apex.core import Exercise` failed. Nothing caught it because no
    test star-imported the package.
    """
    module = importlib.import_module(package_name)
    declared = getattr(module, "__all__", None)
    assert isinstance(declared, list), f"{package_name} must define __all__ as a list"
    missing = [name for name in declared if not hasattr(module, name)]
    assert not missing, f"{package_name}.__all__ names undefined symbols: {missing}"


@pytest.mark.parametrize("package_name", MUST_DECLARE_ALL)
def test_public_packages_declare_a_surface(package_name: str) -> None:
    """The packages consumers import from must not export nothing."""
    module = importlib.import_module(package_name)
    assert module.__all__, f"{package_name} should publish a non-empty __all__"


@pytest.mark.parametrize("package_name", PACKAGES)
def test_star_import_succeeds(package_name: str) -> None:
    """A star-import must not raise."""
    namespace: dict[str, object] = {}
    exec(f"from {package_name} import *", namespace)  # noqa: S102 - the point of the test
    assert namespace


@pytest.mark.parametrize("module_name", [n for p in PACKAGES for n in _iter_submodules(p)])
def test_every_module_imports(module_name: str) -> None:
    """Importing any module must not raise at import time."""
    importlib.import_module(module_name)


def test_core_reexports_resolve() -> None:
    """The convenience re-exports in apex.core all point at real objects."""
    from apex import core

    for name in core.__all__:
        assert getattr(core, name) is not None
