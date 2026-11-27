# -*- coding: utf-8 -*-
"""Tests for the Mindspace knowledge-base domain service."""

from __future__ import annotations

import json

import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all, knowledge_embeddings
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.mindspace.connectors import MindspaceConnectorError
from qwenpaw.mindspace.models import MindspaceScope
from qwenpaw.mindspace.parsers import DocumentParseError
from qwenpaw.mindspace.service import MindspaceService


def _engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


def _service(tmp_path, *, user_id="user-a", agent_id="agent-a", connectors=None):
    return MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / agent_id,
        agent_id=agent_id,
        user_id=user_id,
        engine=_engine(tmp_path),
        connectors=connectors,
    )


class FakeEmbedder:
    model_name = "fake-embedding-v1"
    storage_key = "fake/fake-embedding-v1"

    def __init__(self):
        self.documents = []
        self.queries = []

    def is_configured(self):
        return True

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return [_fake_vector(text) for text in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return _fake_vector(text)


def _fake_vector(text):
    lowered = text.lower()
    if "expense" in lowered or "reimbursement" in lowered:
        return [1.0, 0.0, 0.0]
    if "atlas" in lowered:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


class FailingEmbedder(FakeEmbedder):
    def embed_documents(self, texts):
        raise RuntimeError("embedding upstream is down")


def test_stages_uploaded_file_before_parsing_and_indexing(tmp_path):
    service = _service(tmp_path)

    staged = service.stage_local_bytes(
        name="handbook.md",
        content=b"# Handbook\n\nExpense claims require manager approval.",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
        mime_type="text/markdown",
    )

    assert staged.status == "pending"
    assert staged.progress == 5
    assert staged.chunk_count == 0
    assert service.search("Expense claims", scope=MindspaceScope.PERSONAL) == []

    indexed = service.process_staged_document(
        staged.id,
        scope=MindspaceScope.PERSONAL,
    )

    assert indexed is not None
    assert indexed.status == "ready"
    assert indexed.progress == 100
    assert indexed.chunk_count == 1
    assert service.search("Expense claims", scope=MindspaceScope.PERSONAL)


def test_pdf_parser_timeout_marks_document_failed_and_releases_processing(
    tmp_path,
    monkeypatch,
):
    service = _service(tmp_path)
    staged = service.stage_local_bytes(
        name="stalled.pdf",
        content=b"%PDF-stalled",
        scope=MindspaceScope.PERSONAL,
        source_type="pdf",
        mime_type="application/pdf",
    )

    def timeout_parser(**_kwargs):
        raise DocumentParseError(
            "PDF page parsing made no progress for 45 seconds."
        )

    monkeypatch.setattr(
        "qwenpaw.mindspace.service.parse_document_path_isolated",
        timeout_parser,
    )

    result = service.process_staged_document(
        staged.id,
        scope=MindspaceScope.PERSONAL,
    )

    assert result is not None
    assert result.status == "failed"
    assert result.failed_stage == "parsing"
    assert result.progress == 0
    assert "made no progress" in (result.last_error or "")


def test_migrates_legacy_cloud_docs_into_enterprise_and_personal_scopes(tmp_path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "docs.json").write_text(
        json.dumps(
            [
                {
                    "id": "legacy-global-1",
                    "name": "Legacy Enterprise",
                    "type": "md",
                    "size": "共享知识库",
                    "slices": 2,
                    "status": "ready",
                    "updatedAt": "2026-06-01 09:30",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    workspace_dir = tmp_path / "agent"
    workspace_dir.mkdir()
    (workspace_dir / "cloud_docs.json").write_text(
        json.dumps(
            [
                {
                    "id": "legacy-1",
                    "name": "Legacy Plan",
                    "type": "md",
                    "size": "共享知识库",
                    "slices": 2,
                    "status": "ready",
                    "updatedAt": "2026-06-01 09:30",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace_dir,
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
    )

    enterprise_docs = service.list_documents(scope=MindspaceScope.ENTERPRISE)
    personal_docs = service.list_documents(scope=MindspaceScope.PERSONAL)

    assert [doc.id for doc in enterprise_docs] == ["legacy-global-1"]
    assert enterprise_docs[0].scope == MindspaceScope.ENTERPRISE
    assert [doc.id for doc in personal_docs] == ["legacy-1"]
    assert personal_docs[0].scope == MindspaceScope.PERSONAL
    assert personal_docs[0].owner_user_id == "user-a"
    assert personal_docs[0].legacy_agent_id == "agent-a"


@pytest.mark.asyncio
async def test_ingests_enterprise_and_personal_docs_and_searches_by_scope(tmp_path):
    service = _service(tmp_path, user_id="user-a")

    enterprise_doc = await service.ingest_local_content(
        name="Enterprise Handbook.md",
        source_type="md",
        content="Pricing policy says enterprise renewals need legal review.",
        scope=MindspaceScope.ENTERPRISE,
    )
    personal_doc = await service.ingest_local_content(
        name="Private Notes.md",
        source_type="md",
        content="The launch codename is Polaris and should stay private.",
        scope=MindspaceScope.PERSONAL,
    )

    assert enterprise_doc.status == "ready"
    assert personal_doc.status == "ready"
    assert personal_doc.owner_user_id == "user-a"

    enterprise_hits = service.search("legal review", scope=MindspaceScope.ENTERPRISE)
    personal_hits = service.search("Polaris", scope=MindspaceScope.PERSONAL)
    all_hits = service.search("Polaris", scope=None)

    assert enterprise_hits[0].doc_id == enterprise_doc.id
    assert personal_hits[0].doc_id == personal_doc.id
    assert all_hits[0].scope == MindspaceScope.PERSONAL


@pytest.mark.asyncio
async def test_ingest_stores_embeddings_when_semantic_search_is_configured(tmp_path):
    engine = _engine(tmp_path)
    embedder = FakeEmbedder()
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=engine,
        embedder=embedder,
    )

    doc = await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims above 5000 need manager approval.",
        scope=MindspaceScope.ENTERPRISE,
    )

    with engine.connect() as conn:
        rows = conn.execute(knowledge_embeddings.select()).mappings().all()

    assert doc.status == "ready"
    assert service.semantic_search_enabled() is True
    assert len(rows) == doc.chunk_count
    assert rows[0]["model"] == "fake/fake-embedding-v1"
    assert embedder.documents

    capabilities = service.search_capabilities()
    assert capabilities["keyword_search_enabled"] is True
    assert capabilities["semantic_search_enabled"] is True
    assert capabilities["embedding_model"] == "fake-embedding-v1"
    assert capabilities["retrieval_mode"] == "hybrid"
    assert capabilities["reranking_enabled"] is True
    assert capabilities["citation_metadata_enabled"] is True


@pytest.mark.asyncio
async def test_semantic_search_can_find_chunks_without_keyword_overlap(tmp_path):
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        embedder=FakeEmbedder(),
    )
    doc = await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims above 5000 need manager approval.",
        scope=MindspaceScope.ENTERPRISE,
    )

    hits = service.search("reimbursement", scope=MindspaceScope.ENTERPRISE)

    assert hits
    assert hits[0].doc_id == doc.id
    assert hits[0].match_reason == "semantic"
    assert hits[0].score > 0.9


@pytest.mark.asyncio
async def test_embedding_provider_switch_does_not_reuse_old_vectors(tmp_path):
    embedder = FakeEmbedder()
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        embedder=embedder,
    )
    await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims above 5000 need manager approval.",
        scope=MindspaceScope.ENTERPRISE,
    )

    embedder.storage_key = "another-provider/fake-embedding-v1"

    assert service.search(
        "reimbursement",
        scope=MindspaceScope.ENTERPRISE,
    ) == []


@pytest.mark.asyncio
async def test_embedding_failure_marks_doc_failed_without_searchable_chunks(tmp_path):
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        embedder=FailingEmbedder(),
    )

    doc = await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims above 5000 need manager approval.",
        scope=MindspaceScope.ENTERPRISE,
    )

    assert doc.status == "failed"
    assert doc.failed_stage == "embedding"
    assert "embedding upstream is down" in (doc.last_error or "")
    assert service.search("expense", scope=MindspaceScope.ENTERPRISE) == []


@pytest.mark.asyncio
async def test_personal_docs_are_isolated_by_user_while_enterprise_is_shared(tmp_path):
    engine = _engine(tmp_path)
    service_a = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=engine,
    )
    service_b = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-b",
        agent_id="agent-b",
        user_id="user-b",
        engine=engine,
    )

    await service_a.ingest_local_content(
        name="Enterprise Handbook.md",
        source_type="md",
        content="All employees can see the Mercury approval policy.",
        scope=MindspaceScope.ENTERPRISE,
    )
    await service_a.ingest_local_content(
        name="User A Notes.md",
        source_type="md",
        content="User A private codename is Polaris.",
        scope=MindspaceScope.PERSONAL,
    )

    assert service_b.search("Mercury", scope=None)
    assert service_b.search("Polaris", scope=None) == []
    assert service_b.read_document("missing", scope=MindspaceScope.PERSONAL) is None


@pytest.mark.asyncio
async def test_cloud_doc_requires_current_user_authorized_account(tmp_path):
    service = _service(tmp_path, user_id="user-a")

    doc = await service.link_cloud_document(
        title="Tencent Roadmap",
        url="https://docs.qq.com/doc/example",
        source_type="tencent",
        scope=MindspaceScope.ENTERPRISE,
        user_id="user-a",
    )

    stored = service.get_document(doc.id, scope=MindspaceScope.ENTERPRISE)
    hits = service.search("mock context", scope=MindspaceScope.ENTERPRISE)

    assert stored.status == "failed"
    assert stored.failed_stage == "fetching"
    assert "authorization" in (stored.last_error or "").lower()
    assert hits == []


@pytest.mark.asyncio
async def test_cloud_doc_uses_bound_cloud_account_for_fetch(tmp_path):
    class FakeConnector:
        def __init__(self):
            self.calls = []

        async def fetch_text(
            self,
            source_type,
            url,
            title,
            *,
            cloud_account_id=None,
            user_id=None,
        ):
            self.calls.append(
                {
                    "source_type": source_type,
                    "url": url,
                    "title": title,
                    "cloud_account_id": cloud_account_id,
                    "user_id": user_id,
                }
            )
            return "The Tencent document says Nova launch approval is complete."

    connector = FakeConnector()
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        connectors=connector,
    )

    doc = await service.link_cloud_document(
        title="Tencent Approval",
        url="https://docs.qq.com/doc/example",
        source_type="tencent",
        scope=MindspaceScope.ENTERPRISE,
        cloud_account_id="acct-user-a",
        user_id="user-a",
    )

    hits = service.search("Nova launch", scope=MindspaceScope.ENTERPRISE)

    assert doc.status == "ready"
    assert doc.cloud_account_id == "acct-user-a"
    assert connector.calls[0]["cloud_account_id"] == "acct-user-a"
    assert connector.calls[0]["user_id"] == "user-a"
    assert hits[0].doc_id == doc.id


@pytest.mark.asyncio
async def test_cloud_doc_resync_uses_current_user_for_bound_account(tmp_path):
    class FakeConnector:
        def __init__(self):
            self.calls = []

        async def fetch_text(
            self,
            source_type,
            url,
            title,
            *,
            cloud_account_id=None,
            user_id=None,
        ):
            self.calls.append(
                {
                    "cloud_account_id": cloud_account_id,
                    "user_id": user_id,
                }
            )
            return "The Lark document says Atlas review is ready."

    connector = FakeConnector()
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        connectors=connector,
    )
    doc = await service.link_cloud_document(
        title="Lark Review",
        url="https://feishu.cn/docx/example",
        source_type="lark",
        scope=MindspaceScope.PERSONAL,
        cloud_account_id="acct-user-a",
        user_id="user-a",
    )
    connector.calls.clear()

    resynced = await service.resync_document(
        doc.id,
        scope=MindspaceScope.PERSONAL,
        user_id="user-a",
    )

    assert resynced is not None
    assert connector.calls[0]["cloud_account_id"] == "acct-user-a"
    assert connector.calls[0]["user_id"] == "user-a"


@pytest.mark.asyncio
async def test_delete_document_removes_chunks_and_generated_wiki(tmp_path):
    service = _service(tmp_path, user_id="user-a")

    doc = await service.ingest_local_content(
        name="Architecture.md",
        source_type="md",
        content="Architecture Decision Record\nThe gateway handles auth.",
        scope=MindspaceScope.PERSONAL,
    )

    assert service.search("gateway", scope=MindspaceScope.PERSONAL)

    service.delete_document(doc.id, scope=MindspaceScope.PERSONAL)

    assert service.search("gateway", scope=MindspaceScope.PERSONAL) == []
    assert not service.list_wiki(scope=MindspaceScope.PERSONAL)


@pytest.mark.asyncio
async def test_search_returns_citation_rank_and_neighbor_context(tmp_path):
    service = _service(tmp_path, user_id="user-a")
    intro = "Background guidance. " + ("A" * 840)
    target = "Refund approval requires the finance lead. " + ("B" * 830)
    follow_up = "Escalation owner is customer success. " + ("C" * 830)
    doc = await service.ingest_local_content(
        name="Expense Process.md",
        source_type="md",
        content="\n\n".join([intro, target, follow_up]),
        scope=MindspaceScope.PERSONAL,
    )

    hits = service.search(
        "refund approval",
        scope=MindspaceScope.PERSONAL,
        top_k=1,
    )

    assert len(hits) == 1
    assert hits[0].doc_id == doc.id
    assert hits[0].rank == 1
    assert hits[0].citation == "[KB: Expense Process.md · chunk:2]"
    assert "Background guidance" in (hits[0].context or "")
    assert "Refund approval" in (hits[0].context or "")
    assert "Escalation owner" in (hits[0].context or "")


@pytest.mark.asyncio
async def test_search_expands_chinese_query_terms(tmp_path):
    service = _service(tmp_path, user_id="user-a")
    doc = await service.ingest_local_content(
        name="费用制度.md",
        source_type="md",
        content="员工提交费用报销后，由直属负责人和财务部门依次审批。",
        scope=MindspaceScope.ENTERPRISE,
    )

    hits = service.search("请问公司的报销流程是什么", scope=MindspaceScope.ENTERPRISE)

    assert hits
    assert hits[0].doc_id == doc.id
    assert "报销" in (hits[0].match_reason or "")


@pytest.mark.asyncio
async def test_cloud_resync_failure_keeps_previous_index_searchable(tmp_path):
    class ToggleConnector:
        def __init__(self):
            self.fail = False

        async def fetch_text(self, *_args, **_kwargs):
            if self.fail:
                raise MindspaceConnectorError("cloud provider is temporarily unavailable")
            return "The Atlas renewal policy requires legal approval."

    connector = ToggleConnector()
    service = _service(
        tmp_path,
        user_id="user-a",
        connectors=connector,
    )
    doc = await service.link_cloud_document(
        title="Atlas Policy",
        url="https://example.com/atlas",
        source_type="lark",
        scope=MindspaceScope.PERSONAL,
        cloud_account_id="account-a",
        user_id="user-a",
    )
    previous_chunk_count = doc.chunk_count
    connector.fail = True

    resynced = await service.resync_document(
        doc.id,
        scope=MindspaceScope.PERSONAL,
        user_id="user-a",
    )

    assert resynced is not None
    assert resynced.status == "failed"
    assert resynced.chunk_count == previous_chunk_count
    assert "previous index remains searchable" in (resynced.last_error or "").lower()
    assert service.search("Atlas renewal", scope=MindspaceScope.PERSONAL)


@pytest.mark.asyncio
async def test_embedding_resync_failure_restores_previous_index(tmp_path):
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=_engine(tmp_path),
        embedder=FakeEmbedder(),
    )
    doc = await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims above 5000 need manager approval.",
        scope=MindspaceScope.PERSONAL,
    )
    previous_chunk_count = doc.chunk_count
    service.embedder = FailingEmbedder()

    resynced = await service.resync_document(
        doc.id,
        scope=MindspaceScope.PERSONAL,
        user_id="user-a",
    )

    assert resynced is not None
    assert resynced.status == "failed"
    assert resynced.chunk_count == previous_chunk_count
    assert "previous index remains searchable" in (resynced.last_error or "").lower()
    assert service.search("Expense claims", scope=MindspaceScope.PERSONAL)


@pytest.mark.asyncio
async def test_classification_filters_and_metadata_updates_do_not_reindex(tmp_path):
    service = _service(tmp_path, user_id="user-a")
    policy = await service.ingest_local_content(
        name="Expense Policy.md",
        source_type="md",
        content="Expense claims require manager approval.",
        scope=MindspaceScope.PERSONAL,
        category="policy",
        tags=["财务", "2026", "财务"],
    )
    await service.ingest_local_content(
        name="Gateway Design.md",
        source_type="md",
        content="The gateway uses a circuit breaker.",
        scope=MindspaceScope.PERSONAL,
        category="technology",
        tags=["架构"],
    )

    assert [doc.id for doc in service.list_documents(category="policy")] == [policy.id]
    assert [doc.id for doc in service.list_documents(tags=["财务", "2026"])] == [
        policy.id
    ]
    assert service.search("manager approval", category="technology") == []
    assert service.search("manager approval", category="policy")

    updated = service.update_document_metadata(
        policy.id,
        scope=MindspaceScope.PERSONAL,
        category="operations",
        tags=["报销"],
    )

    assert updated is not None
    assert updated.category == "operations"
    assert updated.tags == ["报销"]
    assert updated.chunk_count == policy.chunk_count
    assert service.search("manager approval", category="operations", tags=["报销"])
