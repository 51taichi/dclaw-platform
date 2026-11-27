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


def test_system_route_does_not_import_expert_platform():
    source_root = Path(__file__).resolve().parents[4] / "src"
    source = (source_root / "qwenpaw/app/routers/aigc_studio.py").read_text()
    assert "get_super_expert_platform_service" not in source
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            name = importlib.util.resolve_name(module, "qwenpaw.app.routers")
            names = [name, *(name + "." + alias.name for alias in node.names)]
        assert not any(name.startswith("qwenpaw.app.super_experts")
                       or name.startswith("qwenpaw.app.routers.super_expert_platform") for name in names)


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
from qwenpaw.app.aigc.models import Canvas, CanvasUpsert, CapabilityList
from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.capability_service import project_workflow_capability_catalog
store = AigcResourceStore(Path(sys.argv[1]))
canvas = Canvas(id='c', created_at='start', updated_at='start')
store.write('canvases', 'c', canvas.model_dump())
assert store.read('canvases', 'c')['id'] == 'c'
service = AigcCanvasService(store)
owned = service.create('user', CanvasUpsert(name='Without experts'))
assert service.get('user', owned.id).name == 'Without experts'
assert AigcAssetService(store).store is store
assert project_workflow_capability_catalog(CapabilityList(capabilities=[])).nodes
from sqlalchemy import create_engine
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.repos.aigc_execution_repo import AigcExecutionRepository
from qwenpaw.app.aigc.workflow_execution import WorkflowExecutionBinding, validate_execution
engine = create_engine('sqlite:///' + str(Path(sys.argv[1]) / 'core.sqlite'))
create_all(engine)
repository = AigcExecutionRepository(engine)
binding = WorkflowExecutionBinding(owner_user_id='u', canvas_id='c', workflow_id='w',
    workflow_revision=1, node_id='n', logical_node_id='clip', provider_id='p',
    model_id='m', capability='text_to_video')
repository.register_bindings([binding], 'migration')
saved = repository.get_binding('u', 'c', 'n')
try:
    validate_execution(saved, provider_id='p', model_id='other', capability='text_to_video')
except ValueError as exc:
    assert str(exc) == 'EXECUTION_BINDING_MISMATCH'
else:
    raise AssertionError('mismatched model accepted without experts')
engine.dispose()
""", str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(source_root)},
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
