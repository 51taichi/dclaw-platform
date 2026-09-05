"""The core storage contract must work without HTTP or expert modules."""

import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def test_core_modules_do_not_import_upper_layer_contracts():
    source_root = Path(__file__).resolve().parents[4] / "src"
    forbidden = ("fastapi", "qwenpaw.app.routers", "qwenpaw.app.super_experts", "qwenpaw.app.workspace")
    violations = []
    for path in (source_root / "qwenpaw/app/aigc").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                resolved = importlib.util.resolve_name(module, "qwenpaw.app.aigc")
                names = [resolved, *(resolved + "." + alias.name for alias in node.names)]
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, "\n".join(violations)


def test_shared_resources_work_when_upper_layers_are_unavailable(tmp_path):
    source_root = Path(__file__).resolve().parents[4] / "src"
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
from pathlib import Path
import sys

class BlockUpperLayers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ('fastapi', 'qwenpaw.app.routers', 'qwenpaw.app.super_experts'):
            if fullname == prefix or fullname.startswith(prefix + '.'):
                raise ImportError('core tried to load upper layer: ' + fullname)

sys.meta_path.insert(0, BlockUpperLayers())
from qwenpaw.app.aigc.models import Canvas
from qwenpaw.app.aigc.resource_store import AigcResourceStore
store = AigcResourceStore(Path(sys.argv[1]))
canvas = Canvas(id='c', created_at='start', updated_at='start')
store.write('canvases', 'c', canvas.model_dump())
assert store.read('canvases', 'c')['id'] == 'c'
""", str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(source_root)},
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
