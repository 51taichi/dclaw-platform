from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

from qwenpaw.app.integration_delivery.archive import (
    build_deterministic_archive,
    deterministic_digest,
)
from qwenpaw.app.integration_delivery.update import (
    DeliveryBundleError,
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
