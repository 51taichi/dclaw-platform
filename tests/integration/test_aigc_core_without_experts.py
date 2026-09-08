"""Core workflow constraints and results survive a restart without experts.

Media output is an isolated metadata fixture, not a provider or review test.
"""

import os
from pathlib import Path
import subprocess
import sys


def test_core_workflow_and_results_restart_without_expert_components(tmp_path):
    repository_root = Path(__file__).resolve().parents[2]
    script = r'''
import importlib.abc
import itertools
import json
from pathlib import Path
import sys

class NoExpertsOrHttp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ("fastapi", "qwenpaw.app.routers", "qwenpaw.app.super_experts"):
            if fullname == prefix or fullname.startswith(prefix + "."):
                raise AssertionError("core dependency on " + fullname)

sys.meta_path.insert(0, NoExpertsOrHttp())
from sqlalchemy import create_engine
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.repos.aigc_execution_repo import AigcExecutionRepository
from qwenpaw.app.aigc.resource_store import AigcResourceStore, AigcResourceError
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.models import CanvasUpsert, AigcJob, AigcAsset
from qwenpaw.app.aigc.workflow_execution import AigcWorkflowExecutionService, validate_execution
from qwenpaw.app.aigc.job_lifecycle import AigcJobLifecycle

root, mode, fixture = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
engine = create_engine("sqlite:///" + str(root / "core.sqlite"))
create_all(engine)
store = AigcResourceStore(root / "studio")
repository = AigcExecutionRepository(engine)
canvases = AigcCanvasService(store)
workflows = AigcWorkflowExecutionService(store, repository)
if mode == "create":
    from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
    from qwenpaw.aigc.workflow_compiler import AvailableWorkflowModel, compile_workflow
    ordinary = canvases.create("owner", CanvasUpsert(name="Ordinary canvas"))
    blueprint = WorkflowBlueprint.model_validate(json.loads(fixture.read_text())["workflow"])
    sequence = itertools.count()
    compiled = compile_workflow(blueprint, available_models=tuple(
        AvailableWorkflowModel(provider_id="provider-1", model_id=model, capabilities=frozenset(caps))
        for model, caps in (("text-1", ["storyboard"]), ("image-1", ["text_to_image"]),
                            ("video-1", ["image_to_video", "text_to_video"]))
    ), id_factory=lambda kind: f"independent-{kind}-{next(sequence)}", asset_resolver=lambda _: None)
    canvas, compiled = workflows.create("owner", "create", command=blueprint.model_dump(mode="json"), compiled=compiled)
    asset = AigcAsset(id="fixture-asset", name="metadata fixture", kind="video", path="not-real-media.mp4",
                      created_at="2026-09-06T00:00:00Z", meta={"owner_user_id": "owner",
                      "canvas_id": canvas.id, "node_id": compiled.output_node_id})
    store.write("assets", asset.id, asset.model_dump())
    job = AigcJob(id="fixture-job", canvas_id=canvas.id, node_id=compiled.output_node_id,
                  provider_id="provider-1", model_id="video-1", capability="image_to_video",
                  status="running", created_at="2026-09-06T00:00:00Z", updated_at="2026-09-06T00:00:00Z")
    AigcJobLifecycle(store, repository).record_success(job, [asset], owner_user_id="owner")
else:
    stored = [canvases.load(path.stem) for path in store.directory("canvases").glob("*.json")]
    assert len(stored) == 2
    assert sum(canvas.name == "Ordinary canvas" for canvas in stored) == 1
    result = repository.get_job_result("fixture-job")
    job = AigcJob.model_validate_json(result["snapshot"])
    assert job.status == "succeeded" and job.outputs[0].id == "fixture-asset"
    canvas = canvases.get("owner", job.canvas_id)
    binding = repository.get_binding("owner", job.canvas_id, job.node_id)
    assert binding is not None
    try:
        validate_execution(binding, provider_id="provider-1", model_id="changed", capability="image_to_video")
    except ValueError as error:
        assert str(error) == "EXECUTION_BINDING_MISMATCH"
    else:
        raise AssertionError("incorrect model accepted")
    try:
        canvases.get("other", job.canvas_id)
    except AigcResourceError:
        pass
    else:
        raise AssertionError("cross-owner access")
    output = next(node for node in canvas.nodes if node.id == job.node_id)
    assert output.data["outputs"][0]["id"] == "fixture-asset"
    assert repository.claim_domain_events("independent", now=0, limit=10)
    assert not any(name.startswith("qwenpaw.app.super_experts") for name in sys.modules)
engine.dispose()
'''
    for mode in ("create", "restart"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), mode,
             str(repository_root / "tests/fixtures/super_expert/aigc-workflow-v2/three-node.json")],
            env={**os.environ, "PYTHONPATH": str(repository_root / "src")},
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
