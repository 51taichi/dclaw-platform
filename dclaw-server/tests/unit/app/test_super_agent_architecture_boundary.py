from __future__ import annotations

import ast
from pathlib import Path

PLATFORM_ROOT = Path(__file__).parents[3] / "src" / "qwenpaw"
BUSINESS_MODULE_PREFIXES = (
    "dazibao_relay",
    "tikhub",
    "luyu_dazibao",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_dclaw_platform_does_not_import_super_agent_business_modules():
    violations = {
        str(path.relative_to(PLATFORM_ROOT)): sorted(
            name
            for name in _imports(path)
            if name.startswith(BUSINESS_MODULE_PREFIXES)
        )
        for path in PLATFORM_ROOT.rglob("*.py")
    }
    violations = {path: names for path, names in violations.items() if names}

    assert violations == {}
