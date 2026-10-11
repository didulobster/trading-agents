"""CONTEXT-MAP.md, enforced: Trading reaches EDGAR Research through one
published module, EDGAR Research never imports Trading, and the shared
kernel imports neither (see docs/adr/0001-two-contexts-one-package.md).

`app/main.py` is the composition root that mounts both, so it is exempt.
Each context's tests follow its code's rule: a Trading test reaching an
EDGAR Research private would pin what the seam is meant to hide.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
TRADING = APP / "trading"
EDGAR_RESEARCH = APP / "edgar_research"
SHARED = APP / "shared"
TRADING_TESTS = REPO / "tests" / "trading"
EDGAR_RESEARCH_TESTS = REPO / "tests" / "edgar_research"
PUBLISHED = "app.edgar_research.fundamentals_memo"


def _imported_names(root: Path) -> list[tuple[str, str]]:
    """(file, dotted name) for every absolute import under `root`; a
    `from a import b` counts as `a.b`, so importing the module by its parent
    package is caught too.

    A missing `root` fails rather than scanning nothing: after a move, a
    stale path would otherwise pass every rule vacuously."""
    assert root.is_dir(), root
    found = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found += [(str(path.relative_to(REPO)), a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found += [(str(path.relative_to(REPO)), f"{node.module}.{a.name}") for a in node.names]
    return found


def _under(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


@pytest.mark.parametrize("root", [TRADING, TRADING_TESTS], ids=["code", "tests"])
def test_trading_reaches_edgar_research_only_through_the_published_module(root):
    offenders = [
        (path, name) for path, name in _imported_names(root)
        if _under(name, "app.edgar_research") and not _under(name, PUBLISHED)
    ]
    assert offenders == []


@pytest.mark.parametrize("root", [EDGAR_RESEARCH, EDGAR_RESEARCH_TESTS], ids=["code", "tests"])
def test_edgar_research_never_imports_trading(root):
    offenders = [
        (path, name) for path, name in _imported_names(root)
        if _under(name, "app.trading")
    ]
    assert offenders == []


def test_the_shared_kernel_imports_neither_context():
    offenders = [
        (path, name) for path, name in _imported_names(SHARED)
        if _under(name, "app.trading") or _under(name, "app.edgar_research")
    ]
    assert offenders == []
