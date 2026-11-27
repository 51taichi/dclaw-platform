"""The capability service works without importing a system HTTP router."""

import importlib
import os
from pathlib import Path
import subprocess
import sys


def test_service_is_available_outside_http_router():
    from qwenpaw.app.routers import super_expert_platform

    service = importlib.import_module("qwenpaw.app.super_experts.service")
    assert super_expert_platform.SuperExpertPlatformService is service.SuperExpertPlatformService


def test_expert_adapter_creates_owned_canvas_with_http_imports_blocked(tmp_path):
    # Moving creation back into an HTTP route must break this real invocation.
    script = '''
import importlib.abc
from pathlib import Path
import sys
class NoHttp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "fastapi" or fullname.startswith("qwenpaw.app.routers"):
            raise AssertionError("HTTP dependency: " + fullname)
sys.meta_path.insert(0, NoHttp())
from qwenpaw.app.super_experts.service import SuperExpertPlatformService
from qwenpaw.app.super_experts.aigc_adapter import AigcServiceAdapter
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.resource_store import AigcResourceStore, AigcResourceError
store = AigcResourceStore(Path(sys.argv[1]))
adapter = AigcServiceAdapter(AigcCanvasService(store), AigcAssetService(store))
binding = adapter.provision_workspace(
    owner_user_id="owner", material_task_id="material-one",
    operation_id="aigc.text_to_video.create",
    arguments={"prompt": "A classroom", "aspect_ratio": "9:16",
               "duration_seconds": 5, "model_id": "video-model",
               "project_name": "Lesson"},
)
canvas = AigcCanvasService(store).get("owner", binding["canvas_id"])
assert canvas.name == "Lesson"
assert canvas.nodes[0].id == binding["node_id"]
assert canvas.nodes[0].data["text"] == "A classroom"
assert canvas.meta["super_expert_material_task_id"] == "material-one"
assert list(store.directory("jobs").glob("*.json")) == []
try:
    AigcCanvasService(store).get("other", canvas.id)
except AigcResourceError:
    pass
else:
    raise AssertionError("cross-owner canvas access")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
