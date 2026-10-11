"""CONTEXT-MAP.md, enforced: Trading reaches EDGAR Research through one
published module, EDGAR Research never imports Trading, and the shared
kernel imports neither (see docs/adr/0001-two-contexts-one-package.md).

`app/main.py` is the composition root that mounts both, so it is exempt.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
TRADING = APP / "trading"
EDGAR_RESEARCH = APP / "edgar_research"
SHARED = APP / "shared"
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
                found += [(str(path.relative_to(APP)), a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found += [(str(path.relative_to(APP)), f"{node.module}.{a.name}") for a in node.names]
    return found


def _under(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def test_trading_reaches_edgar_research_only_through_the_published_module():
    offenders = [
        (path, name) for path, name in _imported_names(TRADING)
        if _under(name, "app.edgar_research") and not _under(name, PUBLISHED)
    ]
    assert offenders == []


def test_edgar_research_never_imports_trading():
    offenders = [
        (path, name) for path, name in _imported_names(EDGAR_RESEARCH)
        if _under(name, "app.trading")
    ]
    assert offenders == []


def test_the_shared_kernel_imports_neither_context():
    offenders = [
        (path, name) for path, name in _imported_names(SHARED)
        if _under(name, "app.trading") or _under(name, "app.edgar_research")
    ]
    assert offenders == []
