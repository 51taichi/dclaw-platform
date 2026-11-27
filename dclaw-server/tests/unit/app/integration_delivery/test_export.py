from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.integration_delivery import router as router_module
from qwenpaw.app.integration_delivery.archive import ArchiveLimits
from qwenpaw.app.integration_delivery.export import (
    DclawSnapshotExporter,
    SnapshotExportError,
)
from qwenpaw.app.integration_delivery.models import (
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
    archive_limits=ArchiveLimits(),
):
    return DclawSnapshotExporter(
        context_service=_ContextService(context or _ready_context()),
        config_loader=lambda: config or Config(),
        sealed_registry=_Registry(record),
        sealed_root=tmp_path / "sealed_agents",
        knowledge_service_factory=lambda _publication: _KnowledgeService(
            _knowledge_docs() if knowledge_docs is None else knowledge_docs,
        ),
        archive_limits=archive_limits,
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


def test_standard_snapshot_excludes_runtime_state_and_keeps_agent_source(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_files = {
        "agent.json": '{"id":"a_service","name":"售后客服"}',
        "AGENTS.md": "# Rules",
        "skills/refund/SKILL.md": "# Refund skill",
    }
    runtime_files = {
        "sessions_data/session:2026-10-02/MEMORY.md": "runtime session",
        "tool_results/result.json": "{}",
        "file_store/chroma.sqlite3": "runtime database",
        "backup/old-agent.json": "{}",
        "memory/cache.json": "{}",
        ".reme_store_v1": "1",
        ".skill.json.lock": "locked",
        "memory_file_metadata.json": "{}",
        "qwenpaw_app.log": "runtime log",
        "nested/__pycache__/module.pyc": "compiled",
        "._AGENTS.md": "AppleDouble metadata",
        "skills/refund/._SKILL.md": "AppleDouble metadata",
        "__MACOSX/agent.json": "AppleDouble metadata",
        "nested/.DS_Store": "Finder metadata",
    }
    for relative, content in {**source_files, **runtime_files}.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    exported = _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
        "a_service",
    )
    files = _archive_files(exported.archive)

    assert {path for path in files if path.startswith("agent/")} == {
        "agent/AGENTS.md",
        "agent/agent.json",
        "agent/skills/refund/SKILL.md",
    }


def test_standard_snapshot_excludes_runtime_skill_manifest_fields(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        '{"id":"a_service","name":"Service"}',
        encoding="utf-8",
    )
    (workspace / "skill.json").write_text(
        '{"skills":{"refund":{"builtin_language":null,"enabled":true,'
        '"updated_at":"2026-10-01T07:09:52Z",'
        '"metadata":{"updated_at":"2026-10-01T07:09:52Z"}}},'
        '"version":1791016236618}',
        encoding="utf-8",
    )

    first = _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
        "a_service",
    )
    (workspace / "skill.json").write_text(
        '{"skills":{"refund":{"builtin_language":"zh","enabled":true,'
        '"updated_at":"2026-10-06T09:58:36Z",'
        '"metadata":{"updated_at":"2026-10-06T09:58:36Z"}}},'
        '"version":1791017000000}',
        encoding="utf-8",
    )
    second = _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
        "a_service",
    )

    assert json.loads(_archive_files(first.archive)["agent/skill.json"]) == {
        "skills": {"refund": {"enabled": True, "metadata": {}}}
    }
    assert second.agent_digest == first.agent_digest
    assert second.archive == first.archive


def test_snapshot_sanitizes_runtime_credentials_from_agent_json(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = {
        "id": "a_service",
        "name": "售后客服",
        "workspace_dir": "/srv/private/a_service",
        "running": {"token_count_estimate_divisor": 4.0},
        "channels": {"telegram": {"bot_token": "channel-secret"}},
        "mcp": {
            "clients": {
                "crm": {
                    "name": "crm",
                    "transport": "streamable_http",
                    "url": "https://mcp.example.test/api?api_key=url-secret",
                    "headers": {"Authorization": "Bearer header-secret"},
                    "env": {"CRM_API_KEY": "env-secret"},
                    "cwd": "/srv/private/mcp-runtime",
                    "oauth": {
                        "access_token": "oauth-access-secret",
                        "refresh_token": "oauth-refresh-secret",
                    },
                }
            }
        },
        "acp": {
            "agents": {
                "codex": {
                    "enabled": True,
                    "command": "/usr/local/private/codex",
                    "args": [
                        "--token",
                        "argument-secret",
                        "-H",
                        "Authorization: Bearer header-argument-secret",
                        "-u",
                        "alice:basic-auth-secret",
                        "--user",
                        "bob:other-basic-secret",
                        "--header=X-Api-Key: inline-header-secret",
                        "-HCookie: session=cookie-secret",
                    ],
                    "env": {"OPENAI_API_KEY": "acp-env-secret"},
                }
            }
        },
        "tools": {
            "builtin_tools": {
                "custom": {
                    "name": "custom",
                    "enabled": True,
                    "config": {"apiKey": "tool-secret", "region": "cn"},
                }
            }
        },
    }
    (workspace / "agent.json").write_text(
        json.dumps(source, ensure_ascii=False),
        encoding="utf-8",
    )

    exported = _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
        "a_service",
    )
    files = _archive_files(exported.archive)
    sanitized = json.loads(files["agent/agent.json"])
    serialized = json.dumps(sanitized, ensure_ascii=False)

    for secret in (
        "channel-secret",
        "url-secret",
        "header-secret",
        "env-secret",
        "oauth-access-secret",
        "oauth-refresh-secret",
        "argument-secret",
        "header-argument-secret",
        "basic-auth-secret",
        "other-basic-secret",
        "inline-header-secret",
        "cookie-secret",
        "acp-env-secret",
        "tool-secret",
        "/srv/private/a_service",
        "/srv/private/mcp-runtime",
        "/usr/local/private/codex",
    ):
        assert secret not in serialized
    assert "channels" not in sanitized
    assert sanitized["mcp"]["clients"]["crm"]["headers"] == {
        "Authorization": ""
    }
    assert sanitized["mcp"]["clients"]["crm"]["env"] == {
        "CRM_API_KEY": ""
    }
    assert sanitized["tools"]["builtin_tools"]["custom"]["config"][
        "region"
    ] == "cn"
    assert sanitized["running"]["token_count_estimate_divisor"] == 4.0
    assert sanitized["acp"]["agents"]["codex"]["args"] == []
    assert json.loads((workspace / "agent.json").read_text(encoding="utf-8")) == source


@pytest.mark.parametrize(
    "content",
    [
        "api_key: literal-secret-1234",
        "Authorization: Bearer literal-bearer-secret",
        "-----BEGIN PRIVATE KEY-----\nliteral-key-material",
        "endpoint: https://example.test/api?token=literal-url-secret",
    ],
)
def test_snapshot_rejects_embedded_credentials_in_non_json_source(
    tmp_path, content
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        json.dumps({"id": "a_service", "name": "售后客服"}),
        encoding="utf-8",
    )
    (workspace / "settings.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(SnapshotExportError) as captured:
        _exporter(tmp_path=tmp_path, config=_config(workspace)).export(
            "a_service"
        )

    assert captured.value.code == "ADMIN_BOOTSTRAP_REQUIRED"
    assert captured.value.missing_items == ["agent_source_security"]


def test_snapshot_rejects_declared_oversized_knowledge_before_reading(
    tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        json.dumps({"id": "a_service", "name": "售后客服"}),
        encoding="utf-8",
    )
    document, content = _knowledge_docs()[0]
    document.byte_size = 101

    with pytest.raises(SnapshotExportError) as captured:
        _exporter(
            tmp_path=tmp_path,
            config=_config(workspace),
            knowledge_docs=[(document, content)],
            archive_limits=ArchiveLimits(max_file_bytes=100),
        ).export("a_service")

    assert captured.value.missing_items == ["knowledge_source_snapshot"]


def test_snapshot_allows_code_that_reads_credentials_from_environment(
    tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        json.dumps({"id": "a_service", "name": "售后客服"}),
        encoding="utf-8",
    )
    (workspace / "client.py").write_text(
        'API_KEY = os.getenv("CRM_API_KEY")\n',
        encoding="utf-8",
    )

    exported = _exporter(
        tmp_path=tmp_path,
        config=_config(workspace),
    ).export("a_service")

    assert _archive_files(exported.archive)["agent/client.py"].startswith(
        b"API_KEY = os.getenv"
    )


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
    app.dependency_overrides[router_module.require_integration_client] = lambda: None
    app.dependency_overrides[router_module.get_dclaw_snapshot_exporter] = lambda: exporter
    app.include_router(router_module.router, prefix="/api")

    response = TestClient(app).get(
        "/api/internal/integrations/v1/agents/a_service/source-bundle",
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-dclaw-agent-id"] == "a_service"
    assert response.headers["x-dclaw-agent-digest"].startswith("sha256:")
    assert response.headers["x-dclaw-knowledge-digest"].startswith("sha256:")
