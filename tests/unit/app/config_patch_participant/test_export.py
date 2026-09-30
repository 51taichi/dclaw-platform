from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.config_patch_participant import router as router_module
from qwenpaw.app.config_patch_participant.export import (
    DclawSnapshotExporter,
    SnapshotExportError,
)
from qwenpaw.app.config_patch_participant.models import (
    DclawConfigurationContext,
    Readiness,
)
from qwenpaw.app.sealed_agents.models import SealedAgentRecord, SealedReleaseRecord
from qwenpaw.config.config import AgentProfileRef, Config
from qwenpaw.mindspace.models import MindspaceDoc, MindspaceScope


class _ContextService:
    def __init__(self, context, publication=None):
        self.context = context
        self.publication = publication or {
            "id": "publication-1",
            "target_type": "agent",
            "target_id": context.agent_id,
            "knowledge_base_id": "kb-1",
        }

    def describe(self, agent_id: str):
        assert agent_id == self.context.agent_id
        return self.context

    def resolve_publication(self, agent_id: str):
        assert agent_id == self.context.agent_id
        return self.publication


class _Registry:
    def __init__(self, record=None):
        self.record = record

    def get_agent(self, agent_id: str):
        if self.record and self.record.agent_id == agent_id:
            return self.record
        return None


class _KnowledgeService:
    def __init__(self, documents):
        self.documents = documents

    def list_documents(self, scope):
        assert scope == MindspaceScope.PERSONAL
        return [item[0] for item in self.documents]

    def read_document_source(self, doc_id: str) -> bytes:
        return next(content for doc, content in self.documents if doc.id == doc_id)


def _ready_context(*, agent_type="standard", profile="standard-2026.09", version="workspace"):
    return DclawConfigurationContext(
        agent_id="a_service",
        agent_type=agent_type,
        agent_profile_id=profile,
        enabled=True,
        source_version=version,
        publication_id="publication-1",
        openapi_public_id="pub-1",
        knowledge_base_id="kb-1",
        billing_account_configured=True,
        readiness=Readiness(ready=True),
    )


def _config(workspace: Path | None = None):
    config = Config()
    if workspace is not None:
        config.agents.profiles = {
            "a_service": AgentProfileRef(
                id="a_service",
                workspace_dir=str(workspace),
                enabled=True,
            ),
        }
    return config


def _knowledge_docs():
    return [
        (
            MindspaceDoc(
                id="doc-1",
                scope=MindspaceScope.PERSONAL,
                name="产品说明.pdf",
                source_type="pdf",
                category="product",
                tags=["售后", "保修"],
                status="ready",
                byte_size=7,
            ),
            b"PDFDATA",
        ),
    ]


def _exporter(
    *,
    tmp_path: Path,
    context=None,
    config=None,
    record=None,
    knowledge_docs=None,
):
    return DclawSnapshotExporter(
        context_service=_ContextService(context or _ready_context()),
        config_loader=lambda: config or Config(),
        sealed_registry=_Registry(record),
        sealed_root=tmp_path / "sealed_agents",
        knowledge_service_factory=lambda _publication: _KnowledgeService(
            _knowledge_docs() if knowledge_docs is None else knowledge_docs,
        ),
    )


def _archive_files(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_standard_snapshot_exports_agent_and_publication_knowledge(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        '{"id":"a_service","name":"售后客服"}',
        encoding="utf-8",
    )
    (workspace / "AGENTS.md").write_text("# Rules", encoding="utf-8")

    exported = _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
        "a_service",
    )
    files = _archive_files(exported.archive)

    assert sorted(files) == [
        "agent/AGENTS.md",
        "agent/agent.json",
        "dclaw-component.json",
        "knowledge/documents/doc-1/产品说明.pdf",
        "knowledge/knowledge-manifest.json",
    ]
    component = json.loads(files["dclaw-component.json"])
    assert component == {
        "agentDigest": exported.agent_digest,
        "agentId": "a_service",
        "agentProfileId": "standard-2026.09",
        "knowledgeBaseId": "kb-1",
        "knowledgeDigest": exported.knowledge_digest,
        "sourceVersion": "workspace",
    }
    manifest = json.loads(files["knowledge/knowledge-manifest.json"])
    assert manifest["documents"] == [
        {
            "category": "product",
            "id": "doc-1",
            "name": "产品说明.pdf",
            "path": "documents/doc-1/产品说明.pdf",
            "sourceType": "pdf",
            "tags": ["售后", "保修"],
        },
    ]
    serialized = exported.archive.decode("latin1")
    assert str(workspace) not in serialized
    assert "bound_user_id" not in serialized


def test_super_expert_exports_signed_release_source_not_runtime_workspace(tmp_path):
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="3.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="official",
        package_type="super_expert",
        state="active",
    )
    record = SealedAgentRecord(
        agent_id="a_service",
        name="超级售后",
        active_release_id="rel-1",
        releases=[release],
    )
    source = tmp_path / "sealed_agents" / "releases" / "a_service" / "rel-1" / "agent"
    source.mkdir(parents=True)
    (source / "source.md").write_text("editable source", encoding="utf-8")
    runtime = tmp_path / "sealed_agents" / "runtime_workspaces" / "a_service" / "rel-1" / "agent"
    runtime.mkdir(parents=True)
    (runtime / "runtime-only.txt").write_text("must not export", encoding="utf-8")

    exported = _exporter(
        tmp_path=tmp_path,
        context=_ready_context(
            agent_type="sealed",
            profile="super-expert-2026.09",
            version="3.0.0",
        ),
        record=record,
    ).export("a_service")
    files = _archive_files(exported.archive)

    assert files["agent/source.md"] == b"editable source"
    assert "agent/runtime-only.txt" not in files
    assert exported.profile_id == "super-expert-2026.09"


def test_super_expert_without_protected_release_source_requires_admin_bootstrap(tmp_path):
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="3.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="official",
        package_type="super_expert",
        state="active",
    )
    record = SealedAgentRecord(
        agent_id="a_service",
        name="超级售后",
        active_release_id="rel-1",
        releases=[release],
    )

    with pytest.raises(SnapshotExportError) as exc_info:
        _exporter(
            tmp_path=tmp_path,
            context=_ready_context(
                agent_type="sealed",
                profile="super-expert-2026.09",
                version="3.0.0",
            ),
            record=record,
        ).export("a_service")

    assert exc_info.value.code == "ADMIN_BOOTSTRAP_REQUIRED"
    assert exc_info.value.missing_items == ["agent_source_snapshot"]


@pytest.mark.parametrize("secret_name", [".env", "server.pem", "credentials.json"])
def test_snapshot_rejects_secret_named_source_files(tmp_path, secret_name):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text('{"id":"a_service"}', encoding="utf-8")
    (workspace / secret_name).write_text("secret-value", encoding="utf-8")

    with pytest.raises(SnapshotExportError) as exc_info:
        _exporter(tmp_path=tmp_path, config=_config(workspace)).export("a_service")

    assert exc_info.value.code == "ADMIN_BOOTSTRAP_REQUIRED"
    assert exc_info.value.missing_items == ["agent_source_security"]


def test_snapshot_rejects_symlink_in_agent_source(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text('{"id":"a_service"}', encoding="utf-8")
    (workspace / "link.txt").symlink_to(workspace / "agent.json")

    with pytest.raises(SnapshotExportError) as exc_info:
        _exporter(tmp_path=tmp_path, config=_config(workspace)).export("a_service")

    assert exc_info.value.missing_items == ["agent_source_security"]


def test_snapshot_route_returns_archive_identity_headers(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text('{"id":"a_service"}', encoding="utf-8")
    exporter = _exporter(tmp_path=tmp_path, config=_config(workspace))
    app = FastAPI()
    app.dependency_overrides[router_module.require_config_patch_service] = lambda: None
    app.dependency_overrides[router_module.get_dclaw_snapshot_exporter] = lambda: exporter
    app.include_router(router_module.router, prefix="/api")

    response = TestClient(app).get(
        "/api/internal/config-patch/v1/agents/a_service/snapshot",
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-dclaw-agent-id"] == "a_service"
    assert response.headers["x-dclaw-agent-digest"].startswith("sha256:")
    assert response.headers["x-dclaw-knowledge-digest"].startswith("sha256:")
