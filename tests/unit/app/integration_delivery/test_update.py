from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from qwenpaw.app.integration_delivery.archive import (
    build_deterministic_archive,
    deterministic_digest,
)
from qwenpaw.app.integration_delivery.update import (
    DeliveryBundleError,
    DeliveryIdempotencyKeyReused,
    IntegrationDeliveryUpdater,
    apply_standard_agent_source,
    parse_delivery_bundle,
    restore_standard_agent_source,
    validate_delivery_bundle,
)


def _delivery_archive(*, agent_id: str = "a_service") -> tuple[bytes, str, str]:
    agent_files = {
        "agent/AGENTS.md": b"# Rules\n",
        "agent/agent.json": json.dumps(
            {"id": agent_id, "name": "Service"},
            separators=(",", ":"),
        ).encode(),
    }
    knowledge_files = {
        "knowledge/documents/doc-1/faq.md": b"# FAQ\n",
        "knowledge/knowledge-manifest.json": json.dumps(
            {
                "documents": [
                    {
                        "category": "faq",
                        "id": "doc-1",
                        "name": "faq.md",
                        "path": "documents/doc-1/faq.md",
                        "sourceType": "md",
                        "tags": [],
                    },
                ],
            },
            separators=(",", ":"),
        ).encode(),
    }
    agent_digest = deterministic_digest(agent_files)
    knowledge_digest = deterministic_digest(knowledge_files)
    component = {
        "agentDigest": agent_digest,
        "agentId": agent_id,
        "agentProfileId": "standard-2026.09",
        "knowledgeBaseId": "kb-1",
        "knowledgeDigest": knowledge_digest,
        "sourceVersion": "workspace",
    }
    return (
        build_deterministic_archive(
            {
                **agent_files,
                **knowledge_files,
                "dclaw-component.json": json.dumps(
                    component,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode(),
            },
        ),
        agent_digest,
        knowledge_digest,
    )


def _custom_delivery_archive(
    *,
    agent_files: dict[str, bytes],
    documents: list[dict[str, object]],
) -> tuple[bytes, str, str]:
    knowledge_files: dict[str, bytes] = {}
    manifest: list[dict[str, object]] = []
    for document in documents:
        doc_id = str(document["id"])
        name = str(document["name"])
        relative = f"documents/{doc_id}/{name}"
        knowledge_files[f"knowledge/{relative}"] = bytes(document["content"])
        manifest.append(
            {
                "category": document.get("category", "faq"),
                "id": doc_id,
                "name": name,
                "path": relative,
                "sourceType": document.get("sourceType", "md"),
                "tags": document.get("tags", []),
            }
        )
    knowledge_files["knowledge/knowledge-manifest.json"] = json.dumps(
        {"documents": manifest}, separators=(",", ":"), sort_keys=True
    ).encode()
    agent_digest = deterministic_digest(agent_files)
    knowledge_digest = deterministic_digest(knowledge_files)
    component = {
        "agentDigest": agent_digest,
        "agentId": "a_service",
        "agentProfileId": "standard-2026.09",
        "knowledgeBaseId": "kb-1",
        "knowledgeDigest": knowledge_digest,
        "sourceVersion": "workspace",
    }
    return (
        build_deterministic_archive(
            {
                **agent_files,
                **knowledge_files,
                "dclaw-component.json": json.dumps(
                    component, separators=(",", ":"), sort_keys=True
                ).encode(),
            }
        ),
        agent_digest,
        knowledge_digest,
    )


def test_validate_delivery_bundle_is_read_only_and_returns_four_identifiers(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "agent-workspace" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("unchanged", encoding="utf-8")
    archive, agent_digest, knowledge_digest = _delivery_archive()

    result = validate_delivery_bundle(
        "a_service",
        archive,
        expected_agent_digest=agent_digest,
        expected_knowledge_digest=knowledge_digest,
    )

    assert result.model_dump(by_alias=True) == {
        "valid": True,
        "agentId": "a_service",
        "agentProfileId": "standard-2026.09",
        "sourceVersion": "workspace",
        "agentDigest": agent_digest,
        "knowledgeDigest": knowledge_digest,
    }
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == [
        "agent-workspace",
        "agent-workspace/marker.txt",
    ]


def test_validate_rejects_agent_id_mismatch() -> None:
    archive, agent_digest, knowledge_digest = _delivery_archive(agent_id="other")

    with pytest.raises(DeliveryBundleError, match="agent identity mismatch"):
        validate_delivery_bundle(
            "a_service",
            archive,
            expected_agent_digest=agent_digest,
            expected_knowledge_digest=knowledge_digest,
        )


@pytest.mark.parametrize("unsafe_name", ["../agent.json", "/agent/agent.json"])
def test_validate_rejects_unsafe_members(unsafe_name: str) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(unsafe_name, b"{}")

    with pytest.raises(DeliveryBundleError, match="invalid"):
        validate_delivery_bundle(
            "a_service",
            output.getvalue(),
            expected_agent_digest="sha256:" + "0" * 64,
            expected_knowledge_digest="sha256:" + "0" * 64,
        )


def test_validate_rejects_compression_bomb_member() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("agent/agent.json", b"0" * (2 * 1024 * 1024))

    with pytest.raises(DeliveryBundleError, match="invalid"):
        validate_delivery_bundle(
            "a_service",
            output.getvalue(),
            expected_agent_digest="sha256:" + "0" * 64,
            expected_knowledge_digest="sha256:" + "0" * 64,
        )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    files = {
        "agent.json": '{"id":"a_service","name":"Old"}',
        "AGENTS.md": "# Old rules\n",
        "obsolete.md": "remove me",
        "sessions_data/session-1/MEMORY.md": "runtime session",
        "qwenpaw_app.log": "runtime log",
    }
    for relative, content in files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return workspace


def test_standard_update_replaces_only_exported_source_files(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive, _, _ = _delivery_archive()
    bundle = parse_delivery_bundle("a_service", archive)

    receipt = apply_standard_agent_source(
        bundle,
        "operation-1",
        workspace_dir=workspace,
        reload_agent=lambda _agent_id: None,
    )

    assert json.loads((workspace / "agent.json").read_text()) == {
        "id": "a_service",
        "name": "Service",
    }
    assert (workspace / "AGENTS.md").read_text() == "# Rules\n"
    assert not (workspace / "obsolete.md").exists()
    assert receipt.agent_id == "a_service"
    assert receipt.operation_id == "operation-1"
    assert receipt.backup_dir.is_dir()


def test_standard_update_preserves_runtime_directories(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive, _, _ = _delivery_archive()

    apply_standard_agent_source(
        parse_delivery_bundle("a_service", archive),
        "operation-2",
        workspace_dir=workspace,
        reload_agent=lambda _agent_id: None,
    )

    assert (workspace / "sessions_data/session-1/MEMORY.md").read_text() == (
        "runtime session"
    )
    assert (workspace / "qwenpaw_app.log").read_text() == "runtime log"


def test_standard_update_preserves_server_owned_json_values(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "agent.json").write_text(
        json.dumps(
            {
                "id": "a_service",
                "name": "Old",
                "cwd": "/srv/private/a_service",
                "env": {"API_TOKEN": "server-secret"},
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    archive, _, _ = _custom_delivery_archive(
        agent_files={
            "agent/AGENTS.md": b"# Rules\n",
            "agent/agent.json": (
                b'{"env":{"API_TOKEN":""},"id":"a_service","name":"Service"}'
            ),
        },
        documents=[{"id": "doc-1", "name": "faq.md", "content": b"FAQ"}],
    )

    apply_standard_agent_source(
        parse_delivery_bundle("a_service", archive),
        "operation-secret",
        workspace_dir=workspace,
        reload_agent=lambda _agent_id: None,
    )

    installed = json.loads((workspace / "agent.json").read_text())
    assert installed["name"] == "Service"
    assert installed["cwd"] == "/srv/private/a_service"
    assert installed["env"]["API_TOKEN"] == "server-secret"


def test_standard_update_can_restore_previous_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive, _, _ = _delivery_archive()
    reloaded: list[str] = []
    receipt = apply_standard_agent_source(
        parse_delivery_bundle("a_service", archive),
        "operation-3",
        workspace_dir=workspace,
        reload_agent=reloaded.append,
    )

    restore_standard_agent_source(receipt, reload_agent=reloaded.append)

    assert json.loads((workspace / "agent.json").read_text()) == {
        "id": "a_service",
        "name": "Old",
    }
    assert (workspace / "obsolete.md").read_text() == "remove me"
    assert reloaded == ["a_service", "a_service"]


def test_standard_update_restores_old_source_after_reload_failure(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    archive, _, _ = _delivery_archive()
    attempts = 0

    def reload_agent(_agent_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("reload failed")

    with pytest.raises(RuntimeError, match="reload failed"):
        apply_standard_agent_source(
            parse_delivery_bundle("a_service", archive),
            "operation-4",
            workspace_dir=workspace,
            reload_agent=reload_agent,
        )

    assert json.loads((workspace / "agent.json").read_text()) == {
        "id": "a_service",
        "name": "Old",
    }
    assert (workspace / "obsolete.md").read_text() == "remove me"
    assert (workspace / "sessions_data/session-1/MEMORY.md").read_text() == (
        "runtime session"
    )
    assert attempts == 2


class _KnowledgeStore:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self.documents = [dict(document) for document in documents]
        self.fail_next = False

    def replace_delivery_documents(self, documents: list[dict[str, object]]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("knowledge failed")
        self.documents = [dict(document) for document in documents]


def _transaction_fixture(tmp_path: Path):
    workspace = _workspace(tmp_path)
    old_documents = [
        {"id": "old-doc", "name": "old.md", "content": b"old knowledge"}
    ]
    new_documents = [
        {"id": "doc-1", "name": "faq.md", "content": b"# FAQ\n"}
    ]
    old_archive, old_agent_digest, old_knowledge_digest = _custom_delivery_archive(
        agent_files={
            "agent/AGENTS.md": b"# Old rules\n",
            "agent/agent.json": b'{"id":"a_service","name":"Old"}',
            "agent/obsolete.md": b"remove me",
        },
        documents=old_documents,
    )
    new_archive, new_agent_digest, new_knowledge_digest = _custom_delivery_archive(
        agent_files={
            "agent/AGENTS.md": b"# Rules\n",
            "agent/agent.json": b'{"id":"a_service","name":"Service"}',
        },
        documents=new_documents,
    )
    exported = SimpleNamespace(
        archive=old_archive,
        agent_digest=old_agent_digest,
        knowledge_digest=old_knowledge_digest,
    )
    exporter = SimpleNamespace(export=lambda agent_id: exported)
    context = SimpleNamespace(resolve_publication=lambda agent_id: {"id": "pub-1"})
    knowledge = _KnowledgeStore(old_documents)

    def apply_agent(bundle, operation_id):
        return apply_standard_agent_source(
            bundle,
            operation_id,
            workspace_dir=workspace,
            reload_agent=lambda _agent_id: None,
        )

    return SimpleNamespace(
        workspace=workspace,
        old_documents=old_documents,
        new_documents=new_documents,
        old_archive=old_archive,
        new_archive=new_archive,
        old_agent_digest=old_agent_digest,
        old_knowledge_digest=old_knowledge_digest,
        new_agent_digest=new_agent_digest,
        new_knowledge_digest=new_knowledge_digest,
        exporter=exporter,
        context=context,
        knowledge=knowledge,
        apply_agent=apply_agent,
    )


def _updater(tmp_path: Path, fixture) -> IntegrationDeliveryUpdater:
    return IntegrationDeliveryUpdater(
        operations_root=tmp_path / "operations",
        snapshot_exporter=fixture.exporter,
        context_service=fixture.context,
        knowledge_service_factory=lambda publication: fixture.knowledge,
        apply_agent=fixture.apply_agent,
        restore_agent=restore_standard_agent_source,
    )


def _knowledge_identity(documents: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [
        (item["id"], item["name"], item["content"])
        for item in documents
    ]


def test_apply_replaces_agent_and_knowledge_as_one_operation(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)

    result = _updater(tmp_path, fixture).apply(
        "a_service",
        fixture.new_archive,
        "operation-5",
        expected_agent_digest=fixture.old_agent_digest,
        expected_knowledge_digest=fixture.old_knowledge_digest,
    )

    assert result.status == "applied"
    assert result.agent_digest == fixture.new_agent_digest
    assert result.knowledge_digest == fixture.new_knowledge_digest
    assert _knowledge_identity(fixture.knowledge.documents) == _knowledge_identity(
        fixture.new_documents
    )
    assert json.loads((fixture.workspace / "agent.json").read_text())["name"] == (
        "Service"
    )


def test_knowledge_failure_restores_agent_and_documents(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    fixture.knowledge.fail_next = True

    with pytest.raises(RuntimeError, match="knowledge failed"):
        _updater(tmp_path, fixture).apply(
            "a_service",
            fixture.new_archive,
            "operation-6",
            expected_agent_digest=fixture.old_agent_digest,
            expected_knowledge_digest=fixture.old_knowledge_digest,
        )

    assert json.loads((fixture.workspace / "agent.json").read_text())["name"] == "Old"
    assert _knowledge_identity(fixture.knowledge.documents) == _knowledge_identity(
        fixture.old_documents
    )


def test_restore_is_idempotent(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    updater = _updater(tmp_path, fixture)
    updater.apply(
        "a_service",
        fixture.new_archive,
        "operation-7",
        expected_agent_digest=fixture.old_agent_digest,
        expected_knowledge_digest=fixture.old_knowledge_digest,
    )

    first = updater.restore("a_service", "operation-7")
    second = updater.restore("a_service", "operation-7")

    assert first == second
    assert first.status == "restored"
    assert _knowledge_identity(fixture.knowledge.documents) == _knowledge_identity(
        fixture.old_documents
    )
    assert json.loads((fixture.workspace / "agent.json").read_text())["name"] == "Old"


def test_operation_receipt_survives_service_restart(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    _updater(tmp_path, fixture).apply(
        "a_service",
        fixture.new_archive,
        "operation-8",
        expected_agent_digest=fixture.old_agent_digest,
        expected_knowledge_digest=fixture.old_knowledge_digest,
    )

    restarted = _updater(tmp_path, fixture)
    result = restarted.get_operation("a_service", "operation-8")
    restored = restarted.restore("a_service", "operation-8")

    assert result.status == "applied"
    assert restored.status == "restored"


def test_operation_idempotency_reuses_only_the_same_request(tmp_path: Path) -> None:
    fixture = _transaction_fixture(tmp_path)
    updater = _updater(tmp_path, fixture)
    first = updater.apply(
        "a_service",
        fixture.new_archive,
        "operation-9",
        expected_agent_digest=fixture.old_agent_digest,
        expected_knowledge_digest=fixture.old_knowledge_digest,
    )

    repeated = updater.apply(
        "a_service",
        fixture.new_archive,
        "operation-9",
        expected_agent_digest=fixture.old_agent_digest,
        expected_knowledge_digest=fixture.old_knowledge_digest,
    )

    assert repeated == first
    with pytest.raises(DeliveryIdempotencyKeyReused):
        updater.apply(
            "a_service",
            fixture.new_archive,
            "operation-9",
            expected_agent_digest=fixture.old_agent_digest,
            expected_knowledge_digest="sha256:" + "0" * 64,
        )
