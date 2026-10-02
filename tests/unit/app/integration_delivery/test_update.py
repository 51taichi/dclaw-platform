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
