# -*- coding: utf-8 -*-
"""Mindspace service: storage, ingestion, search, and wiki persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import Engine

from ..app.storage.engine import get_app_engine
from ..app.storage.schema import (
    create_all,
    knowledge_assets,
    knowledge_chunks,
    knowledge_docs,
    knowledge_embeddings,
    knowledge_wiki,
)
from .connectors import CloudConnectorRegistry, MindspaceConnectorError
from .embeddings import (
    EmbeddingBackend,
    EmbeddingError,
    MindspaceEmbedder,
    cosine_similarity,
)
from .models import (
    MindspaceChunk,
    MindspaceDoc,
    MindspaceScope,
    MindspaceSearchHit,
    normalize_knowledge_category,
    normalize_knowledge_tags,
    normalize_mindspace_scope,
    utc_now_iso,
)
from .parser_process import parse_document_path_isolated
from .parsers import DocumentParseError, parse_document_bytes, source_type_from_name


class MindspaceService:
    def __init__(
        self,
        global_root: Path,
        agent_workspace: Path,
        agent_id: str,
        connectors: CloudConnectorRegistry | None = None,
        embedder: EmbeddingBackend | None = None,
        user_id: str | int | None = None,
        engine: Engine | None = None,
        exclusive_personal: bool = False,
    ) -> None:
        self.global_root = Path(global_root)
        self.agent_workspace = Path(agent_workspace)
        self.agent_id = agent_id
        self.user_id = str(user_id if user_id is not None else "0")
        self.exclusive_personal = bool(exclusive_personal)
        self.agent_root = self.agent_workspace / "mindspace"
        self.engine = engine or get_app_engine()
        self.connectors = connectors or CloudConnectorRegistry()
        self.embedder = embedder or MindspaceEmbedder.from_agent_config(agent_id)
        self._ensure_roots()
        create_all(self.engine)
        if not self.exclusive_personal:
            self._migrate_legacy_cloud_docs()

    def list_documents(
        self,
        scope: MindspaceScope | str | None = None,
        *,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> list[MindspaceDoc]:
        resolved_scope = normalize_mindspace_scope(scope)
        stmt = select(knowledge_docs)
        if self.exclusive_personal:
            stmt = stmt.where(
                knowledge_docs.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_docs.c.owner_user_id == self.user_id,
            )
            if resolved_scope == MindspaceScope.ENTERPRISE:
                stmt = stmt.where(
                    knowledge_docs.c.scope == MindspaceScope.ENTERPRISE.value,
                )
        elif resolved_scope == MindspaceScope.ENTERPRISE:
            stmt = stmt.where(knowledge_docs.c.scope == MindspaceScope.ENTERPRISE.value)
        elif resolved_scope == MindspaceScope.PERSONAL:
            stmt = stmt.where(
                knowledge_docs.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_docs.c.owner_user_id == self.user_id,
            )
        else:
            stmt = stmt.where(self._readable_docs_clause())
        stmt = stmt.order_by(knowledge_docs.c.updated_at.desc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        docs = [self._doc_from_row(dict(row)) for row in rows]
        normalized_category = (
            normalize_knowledge_category(category)
            if category and category != "all"
            else None
        )
        normalized_tags = normalize_knowledge_tags(tags)
        if normalized_category:
            docs = [doc for doc in docs if doc.category == normalized_category]
        if normalized_tags:
            required = {tag.casefold() for tag in normalized_tags}
            docs = [
                doc
                for doc in docs
                if required.issubset({tag.casefold() for tag in doc.tags})
            ]
        return docs

    def get_document(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
    ) -> MindspaceDoc | None:
        stmt = select(knowledge_docs).where(knowledge_docs.c.id == doc_id)
        resolved_scope = normalize_mindspace_scope(scope)
        if resolved_scope:
            stmt = stmt.where(knowledge_docs.c.scope == resolved_scope.value)
        stmt = stmt.where(self._readable_docs_clause())
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._doc_from_row(dict(row)) if row else None

    def update_document_metadata(
        self,
        doc_id: str,
        *,
        scope: MindspaceScope | str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc | None:
        """Update classification metadata without rebuilding document vectors."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        if category is not None:
            doc.category = normalize_knowledge_category(category)
        if tags is not None:
            doc.tags = normalize_knowledge_tags(tags)
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        return doc

    async def ingest_local_content(
        self,
        name: str,
        source_type: str,
        content: str,
        scope: MindspaceScope | str,
        source_url: str | None = None,
        agent_ids: list[str] | None = None,
        cloud_account_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        resolved_scope = self._require_scope(scope)
        encoded = content.encode("utf-8")
        doc = self._new_doc(
            name=name,
            source_type=source_type,
            scope=resolved_scope,
            source_url=source_url,
            byte_size=len(encoded),
            status="parsing",
            progress=35,
            agent_ids=agent_ids,
            cloud_account_id=cloud_account_id,
            category=category,
            tags=tags,
        )
        self._upsert_doc(doc)
        self._store_asset(doc, encoded, mime_type="text/plain")
        return self._index_text(doc, content)

    async def ingest_local_bytes(
        self,
        *,
        name: str,
        content: bytes,
        scope: MindspaceScope | str,
        source_type: str | None = None,
        mime_type: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        doc = self.stage_local_bytes(
            name=name,
            content=content,
            scope=scope,
            source_type=source_type,
            mime_type=mime_type,
            category=category,
            tags=tags,
        )
        result = self.process_staged_document(doc.id, scope=doc.scope)
        return result or doc

    def stage_local_bytes(
        self,
        *,
        name: str,
        content: bytes,
        scope: MindspaceScope | str,
        source_type: str | None = None,
        mime_type: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        """Persist an uploaded file and return before parsing or indexing it."""
        resolved_scope = self._require_scope(scope)
        normalized_type = (source_type or source_type_from_name(name)).lower()
        doc = self._new_doc(
            name=name,
            source_type=normalized_type,
            scope=resolved_scope,
            byte_size=len(content),
            status="pending",
            progress=5,
            category=category,
            tags=tags,
        )
        self._upsert_doc(doc)
        self._store_asset(doc, content, mime_type=mime_type)
        return doc

    def process_staged_document(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
    ) -> MindspaceDoc | None:
        """Parse and index a previously persisted local upload."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        asset = self._first_asset(doc.id, kind="raw")
        if not asset:
            return self.mark_document_failed(
                doc.id,
                scope=doc.scope,
                failed_stage="parsing",
                error="Original document asset is missing; cannot build the index.",
            )
        path = Path(str(asset["storage_path"]))
        if not path.exists():
            return self.mark_document_failed(
                doc.id,
                scope=doc.scope,
                failed_stage="parsing",
                error="Original document file is missing; cannot build the index.",
            )
        doc.status = "parsing"
        doc.progress = 30
        doc.failed_stage = None
        doc.last_error = None
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        try:
            parsed = self._parse_local_asset(doc, asset, path)
        except DocumentParseError as exc:
            return self.mark_document_failed(
                doc.id,
                scope=doc.scope,
                failed_stage="parsing",
                error=str(exc),
            )
        doc.source_type = parsed.source_type
        return self._index_text(doc, parsed.text)

    def _parse_local_asset(
        self,
        doc: MindspaceDoc,
        asset: dict[str, Any],
        path: Path,
    ):
        """Parse local content, isolating CPU-heavy PDF work in a process."""
        if doc.source_type.lower() != "pdf":
            return parse_document_bytes(
                name=doc.name,
                source_type=doc.source_type,
                content=path.read_bytes(),
                mime_type=asset.get("mime_type"),
            )

        def update_page_progress(completed: int, total: int) -> None:
            ratio = min(1.0, max(0.0, completed / max(1, total)))
            next_progress = min(70, 30 + int(ratio * 40))
            if next_progress <= int(doc.progress or 0):
                return
            doc.progress = next_progress
            doc.updated_at = utc_now_iso()
            self._upsert_doc(doc)

        return parse_document_path_isolated(
            path=path,
            name=doc.name,
            source_type=doc.source_type,
            mime_type=asset.get("mime_type"),
            progress_callback=update_page_progress,
        )

    async def link_cloud_document(
        self,
        title: str,
        url: str,
        source_type: str,
        scope: MindspaceScope | str,
        agent_ids: list[str] | None = None,
        cloud_account_id: str | None = None,
        user_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        doc = self.stage_cloud_document(
            title=title,
            url=url,
            source_type=source_type,
            scope=scope,
            agent_ids=agent_ids,
            cloud_account_id=cloud_account_id,
            category=category,
            tags=tags,
        )
        result = await self.process_staged_cloud_document(
            doc.id,
            scope=doc.scope,
            user_id=user_id,
        )
        return result or doc

    def stage_cloud_document(
        self,
        *,
        title: str,
        url: str,
        source_type: str,
        scope: MindspaceScope | str,
        agent_ids: list[str] | None = None,
        cloud_account_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        """Persist cloud-document metadata for asynchronous fetching."""
        resolved_scope = self._require_scope(scope)
        doc = self._new_doc(
            name=title,
            source_type=source_type,
            scope=resolved_scope,
            source_url=url,
            status="pending",
            progress=5,
            agent_ids=agent_ids,
            cloud_account_id=cloud_account_id,
            category=category,
            tags=tags,
        )
        self._upsert_doc(doc)
        return doc

    async def process_staged_cloud_document(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
        user_id: str | None = None,
    ) -> MindspaceDoc | None:
        """Fetch and index a previously staged cloud document."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        doc.status = "fetching"
        doc.progress = 15
        doc.failed_stage = None
        doc.last_error = None
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        try:
            text = await self.connectors.fetch_text(
                doc.source_type,
                doc.source_url or "",
                doc.name,
                cloud_account_id=doc.cloud_account_id,
                user_id=user_id or self.user_id,
            )
        except MindspaceConnectorError as exc:
            return self.mark_document_failed(
                doc.id,
                scope=doc.scope,
                failed_stage="fetching",
                error=str(exc),
            )
        await asyncio.to_thread(
            self._store_asset,
            doc,
            text.encode("utf-8"),
            mime_type="text/plain",
            kind="export",
        )
        return await asyncio.to_thread(self._index_text, doc, text)

    def mark_document_queued(
        self,
        doc_id: str,
        *,
        scope: MindspaceScope | str | None = None,
        operation: str = "ingest",
    ) -> MindspaceDoc | None:
        """Expose a truthful queued state while a worker is waiting to run."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        doc.status = "syncing" if operation == "resync" else "pending"
        doc.progress = 5
        doc.failed_stage = None
        doc.last_error = None
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        return doc

    def mark_document_failed(
        self,
        doc_id: str,
        *,
        scope: MindspaceScope | str | None = None,
        failed_stage: str,
        error: str,
    ) -> MindspaceDoc | None:
        """Persist a terminal background-job failure on the document."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        doc.status = "failed"
        doc.progress = 0
        doc.failed_stage = failed_stage
        doc.last_error = error
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        return doc

    async def resync_document(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
        user_id: str | None = None,
    ) -> MindspaceDoc | None:
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        previous_index = self._snapshot_index(doc.id)
        previous_chunk_count = doc.chunk_count
        previous_generated_wiki = list(doc.generated_wiki)
        doc.failed_stage = None
        doc.last_error = None
        if doc.source_url and doc.source_type in {"lark", "feishu", "tencent"}:
            doc.status = "fetching"
            doc.progress = 15
            self._upsert_doc(doc)
            try:
                text = await self.connectors.fetch_text(
                    doc.source_type,
                    doc.source_url,
                    doc.name,
                    cloud_account_id=doc.cloud_account_id,
                    user_id=user_id or self.user_id,
                )
            except MindspaceConnectorError as exc:
                return self._mark_resync_failed(
                    doc,
                    failed_stage="fetching",
                    error=str(exc),
                    previous_index_available=bool(previous_index["chunks"]),
                )
            await asyncio.to_thread(
                self._store_asset,
                doc,
                text.encode("utf-8"),
                mime_type="text/plain",
                kind="export",
            )
            return await asyncio.to_thread(
                self._reindex_with_recovery,
                doc,
                text,
                previous_index=previous_index,
                previous_chunk_count=previous_chunk_count,
                previous_generated_wiki=previous_generated_wiki,
            )

        asset = self._first_asset(doc.id)
        if not asset:
            return self._mark_resync_failed(
                doc,
                failed_stage="parsing",
                error="Original document asset is missing; cannot resync.",
                previous_index_available=bool(previous_index["chunks"]),
            )
        path = Path(str(asset["storage_path"]))
        if not path.exists():
            return self._mark_resync_failed(
                doc,
                failed_stage="parsing",
                error="Original document file is missing; cannot resync.",
                previous_index_available=bool(previous_index["chunks"]),
            )
        return await asyncio.to_thread(
            self._resync_local_document,
            doc,
            asset,
            path,
            previous_index=previous_index,
            previous_chunk_count=previous_chunk_count,
            previous_generated_wiki=previous_generated_wiki,
        )

    def _resync_local_document(
        self,
        doc: MindspaceDoc,
        asset: dict[str, Any],
        path: Path,
        *,
        previous_index: dict[str, list[dict[str, Any]]],
        previous_chunk_count: int,
        previous_generated_wiki: list[str],
    ) -> MindspaceDoc:
        doc.status = "parsing"
        doc.progress = 30
        self._upsert_doc(doc)
        try:
            parsed = self._parse_local_asset(doc, asset, path)
        except DocumentParseError as exc:
            return self._mark_resync_failed(
                doc,
                failed_stage="parsing",
                error=str(exc),
                previous_index_available=bool(previous_index["chunks"]),
            )
        doc.source_type = parsed.source_type
        return self._reindex_with_recovery(
            doc,
            parsed.text,
            previous_index=previous_index,
            previous_chunk_count=previous_chunk_count,
            previous_generated_wiki=previous_generated_wiki,
        )

    def _reindex_with_recovery(
        self,
        doc: MindspaceDoc,
        text: str,
        *,
        previous_index: dict[str, list[dict[str, Any]]],
        previous_chunk_count: int,
        previous_generated_wiki: list[str],
    ) -> MindspaceDoc:
        """Reindex a document and restore its last good index on failure."""
        try:
            result = self._index_text(doc, text)
        except Exception as exc:
            if previous_index["chunks"]:
                self._restore_index_snapshot(doc.id, previous_index)
            doc.chunk_count = previous_chunk_count
            doc.generated_wiki = previous_generated_wiki
            self._mark_resync_failed(
                doc,
                failed_stage="indexing",
                error=str(exc),
                previous_index_available=bool(previous_index["chunks"]),
            )
            raise

        if result.status == "failed" and previous_index["chunks"]:
            self._restore_index_snapshot(doc.id, previous_index)
            result.chunk_count = previous_chunk_count
            result.generated_wiki = previous_generated_wiki
            return self._mark_resync_failed(
                result,
                failed_stage=result.failed_stage or "indexing",
                error=result.last_error or "Knowledge reindex failed.",
                previous_index_available=True,
            )
        return result

    def _mark_resync_failed(
        self,
        doc: MindspaceDoc,
        *,
        failed_stage: str,
        error: str,
        previous_index_available: bool,
    ) -> MindspaceDoc:
        doc.status = "failed"
        doc.progress = 0
        doc.failed_stage = failed_stage
        suffix = (
            " Previous index remains searchable."
            if previous_index_available
            else ""
        )
        doc.last_error = error.rstrip() + suffix
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        return doc

    def _snapshot_index(self, doc_id: str) -> dict[str, list[dict[str, Any]]]:
        with self.engine.connect() as conn:
            chunks = [
                dict(row)
                for row in conn.execute(
                    select(knowledge_chunks).where(knowledge_chunks.c.doc_id == doc_id),
                ).mappings().all()
            ]
            chunk_ids = [str(row["id"]) for row in chunks]
            embeddings = (
                [
                    dict(row)
                    for row in conn.execute(
                        select(knowledge_embeddings).where(
                            knowledge_embeddings.c.chunk_id.in_(chunk_ids),
                        ),
                    ).mappings().all()
                ]
                if chunk_ids
                else []
            )
            wiki = [
                dict(row)
                for row in conn.execute(
                    select(knowledge_wiki).where(knowledge_wiki.c.doc_id == doc_id),
                ).mappings().all()
            ]
        return {
            "chunks": chunks,
            "embeddings": embeddings,
            "wiki": wiki,
        }

    def _restore_index_snapshot(
        self,
        doc_id: str,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> None:
        with self.engine.begin() as conn:
            current_chunk_ids = [
                str(row[0])
                for row in conn.execute(
                    select(knowledge_chunks.c.id).where(
                        knowledge_chunks.c.doc_id == doc_id,
                    ),
                ).all()
            ]
            if current_chunk_ids:
                conn.execute(
                    delete(knowledge_embeddings).where(
                        knowledge_embeddings.c.chunk_id.in_(current_chunk_ids),
                    ),
                )
            conn.execute(delete(knowledge_chunks).where(knowledge_chunks.c.doc_id == doc_id))
            conn.execute(delete(knowledge_wiki).where(knowledge_wiki.c.doc_id == doc_id))
            if snapshot["chunks"]:
                conn.execute(insert(knowledge_chunks), snapshot["chunks"])
            if snapshot["embeddings"]:
                conn.execute(insert(knowledge_embeddings), snapshot["embeddings"])
            if snapshot["wiki"]:
                conn.execute(insert(knowledge_wiki), snapshot["wiki"])

    def delete_document(self, doc_id: str, scope: MindspaceScope | str | None = None) -> bool:
        doc = self.get_document(doc_id, scope)
        if not doc:
            return False
        with self.engine.begin() as conn:
            asset_rows = conn.execute(
                select(knowledge_assets).where(knowledge_assets.c.doc_id == doc_id),
            ).mappings().all()
            conn.execute(
                delete(knowledge_embeddings).where(
                    knowledge_embeddings.c.chunk_id.in_(
                        select(knowledge_chunks.c.id).where(knowledge_chunks.c.doc_id == doc_id)
                    )
                )
            )
            conn.execute(delete(knowledge_chunks).where(knowledge_chunks.c.doc_id == doc_id))
            conn.execute(delete(knowledge_wiki).where(knowledge_wiki.c.doc_id == doc_id))
            conn.execute(delete(knowledge_assets).where(knowledge_assets.c.doc_id == doc_id))
            result = conn.execute(delete(knowledge_docs).where(knowledge_docs.c.id == doc_id))
        for row in asset_rows:
            self._unlink_asset(Path(str(row["storage_path"])))
        return bool(result.rowcount and result.rowcount > 0)

    def search(
        self,
        query: str,
        scope: MindspaceScope | str | None = None,
        top_k: int = 5,
        min_score: float = 0.15,
        include_neighbor_context: bool = True,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> list[MindspaceSearchHit]:
        normalized_query = self._normalize_search_text(query)
        if not normalized_query:
            return []
        chunks = self._load_chunks(scope, category=category, tags=tags)
        if not chunks:
            return []

        terms = self._query_terms(query)
        keyword_scores: dict[str, float] = {}
        keyword_reasons: dict[str, str] = {}
        if terms:
            for chunk in chunks:
                text_terms = set(self._terms(f"{chunk.doc_name}\n{chunk.text}"))
                if not text_terms:
                    continue
                matched = [
                    term
                    for term in terms
                    if term in text_terms
                    or term in self._normalize_search_text(chunk.text)
                ]
                if not matched:
                    continue
                unique_matched = sorted(set(matched))
                keyword_scores[chunk.id] = len(unique_matched) / max(len(set(terms)), 1)
                keyword_reasons[chunk.id] = "keyword:" + ",".join(unique_matched)

        semantic_scores: dict[str, float] = {}
        if self.semantic_search_enabled():
            try:
                query_vector = self.embedder.embed_query(query)
                chunk_vectors = self._load_embeddings([chunk.id for chunk in chunks])
                for chunk in chunks:
                    vector = chunk_vectors.get(chunk.id)
                    if not vector:
                        continue
                    score = cosine_similarity(query_vector, vector)
                    if score >= 0.2:
                        semantic_scores[chunk.id] = max(0.0, score)
            except Exception:
                semantic_scores = {}

        hits: list[MindspaceSearchHit] = []
        for chunk in chunks:
            keyword_score = keyword_scores.get(chunk.id, 0.0)
            semantic_score = semantic_scores.get(chunk.id, 0.0)
            if keyword_score <= 0 and semantic_score <= 0:
                continue
            if keyword_score > 0 and semantic_score > 0:
                score = (keyword_score * 0.35) + (semantic_score * 0.65)
                match_reason = f"hybrid:{keyword_reasons[chunk.id]},semantic"
            elif semantic_score > 0:
                score = semantic_score
                match_reason = "semantic"
            else:
                score = keyword_score
                match_reason = keyword_reasons[chunk.id]
            score, rerank_reason = self._rerank_score(
                query=normalized_query,
                query_terms=terms,
                chunk=chunk,
                score=score,
            )
            if score < max(0.0, min(1.0, min_score)):
                continue
            if rerank_reason:
                match_reason = f"{match_reason},{rerank_reason}"
            hits.append(
                MindspaceSearchHit(
                    doc_id=chunk.doc_id,
                    doc_name=chunk.doc_name,
                    chunk_id=chunk.id,
                    text=chunk.text,
                    score=round(score, 4),
                    scope=chunk.scope,
                    source_url=chunk.source_url,
                    match_reason=match_reason,
                    locator=chunk.locator,
                )
            )

        ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)
        selected: list[MindspaceSearchHit] = []
        seen: set[tuple[str, str]] = set()
        for hit in ranked:
            fingerprint = (
                hit.doc_id,
                self._normalize_search_text(hit.text),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            selected.append(hit)
            if len(selected) >= min(max(1, int(top_k)), 20):
                break

        for rank, hit in enumerate(selected, start=1):
            hit.rank = rank
            locator = hit.locator or hit.chunk_id
            hit.citation = f"[KB: {hit.doc_name} · {locator}]"
            if include_neighbor_context:
                context, context_chunk_ids = self._neighbor_context(hit, chunks)
                hit.context = context
                hit.context_chunk_ids = context_chunk_ids
            else:
                hit.context = hit.text
                hit.context_chunk_ids = [hit.chunk_id]
        return selected

    def read_document(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
    ) -> dict[str, object] | None:
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        chunks = [chunk.to_dict() for chunk in self._load_chunks(doc.scope, doc_id=doc.id)]
        return {"doc": doc.to_api_dict(), "chunks": chunks}

    def read_raw_document_asset(
        self,
        doc_id: str,
        scope: MindspaceScope | str | None = None,
    ) -> dict[str, object] | None:
        """Return metadata and bytes for a readable document's latest raw asset."""
        doc = self.get_document(doc_id, scope)
        if not doc:
            return None
        asset = self._first_asset(doc.id, kind="raw")
        if not asset:
            return None
        path = Path(str(asset["storage_path"]))
        if not path.is_file():
            return None
        return {
            "doc": doc.to_api_dict(),
            "content": path.read_bytes(),
            "sha256": str(asset.get("sha256") or ""),
            "mime_type": asset.get("mime_type"),
        }

    def list_wiki(self, scope: MindspaceScope | str | None = None) -> list[dict[str, str]]:
        resolved_scope = normalize_mindspace_scope(scope)
        stmt = select(knowledge_wiki)
        if self.exclusive_personal:
            stmt = stmt.where(
                knowledge_wiki.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_wiki.c.owner_user_id == self.user_id,
            )
            if resolved_scope == MindspaceScope.ENTERPRISE:
                stmt = stmt.where(
                    knowledge_wiki.c.scope == MindspaceScope.ENTERPRISE.value,
                )
        elif resolved_scope == MindspaceScope.ENTERPRISE:
            stmt = stmt.where(knowledge_wiki.c.scope == MindspaceScope.ENTERPRISE.value)
        elif resolved_scope == MindspaceScope.PERSONAL:
            stmt = stmt.where(
                knowledge_wiki.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_wiki.c.owner_user_id == self.user_id,
            )
        else:
            stmt = stmt.where(self._readable_wiki_clause())
        stmt = stmt.order_by(knowledge_wiki.c.updated_at.desc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            {
                "concept": str(row["concept"]),
                "name": str(row["concept"]),
                "scope": str(row["scope"]),
                "updated_at": _iso(row.get("updated_at")),
            }
            for row in rows
        ]

    def read_wiki(self, concept: str, scope: MindspaceScope | str) -> str | None:
        resolved_scope = self._require_scope(scope)
        stmt = select(knowledge_wiki.c.content).where(
            knowledge_wiki.c.concept == concept,
            knowledge_wiki.c.scope == resolved_scope.value,
        )
        if self.exclusive_personal:
            stmt = stmt.where(
                knowledge_wiki.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_wiki.c.owner_user_id == self.user_id,
            )
        elif resolved_scope == MindspaceScope.PERSONAL:
            stmt = stmt.where(knowledge_wiki.c.owner_user_id == self.user_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        return str(row[0]) if row else None

    def connector_status(self) -> list[dict[str, str | bool]]:
        return [status.to_dict() for status in self.connectors.status()]

    def semantic_search_enabled(self) -> bool:
        return self.embedder.is_configured()

    def search_capabilities(self) -> dict[str, object]:
        return {
            "keyword_search_enabled": True,
            "semantic_search_enabled": self.semantic_search_enabled(),
            "embedding_model": self.embedder.model_name if self.semantic_search_enabled() else "",
            "retrieval_mode": "hybrid" if self.semantic_search_enabled() else "keyword",
            "reranking_enabled": True,
            "neighbor_context_enabled": True,
            "citation_metadata_enabled": True,
            "default_top_k": 5,
            "default_min_score": 0.15,
        }

    def _index_text(self, doc: MindspaceDoc, text: str) -> MindspaceDoc:
        self._remove_chunks(doc.id)
        self._remove_generated_wiki(doc)
        doc.status = "indexing"
        doc.progress = 80
        doc.failed_stage = None
        self._upsert_doc(doc)

        chunks = self._chunk_text(text)
        now = _now()
        with self.engine.begin() as conn:
            if chunks:
                conn.execute(
                    insert(knowledge_chunks),
                    [
                        {
                            "id": f"{doc.id}-chunk-{idx + 1}",
                            "doc_id": doc.id,
                            "doc_name": doc.name,
                            "scope": doc.scope.value,
                            "owner_user_id": doc.owner_user_id,
                            "chunk_index": idx,
                            "text": chunk,
                            "source_url": doc.source_url,
                            "locator": f"chunk:{idx + 1}",
                            "created_at": now,
                        }
                        for idx, chunk in enumerate(chunks)
                    ],
                )

        try:
            self._index_embeddings(doc, chunks)
        except EmbeddingError as exc:
            self._remove_chunks(doc.id)
            doc.chunk_count = 0
            doc.status = "failed"
            doc.progress = 0
            doc.failed_stage = "embedding"
            doc.last_error = str(exc)
            doc.updated_at = utc_now_iso()
            self._upsert_doc(doc)
            return doc

        doc.generated_wiki = self._write_wiki(
            doc,
            text,
            [f"{doc.id}-chunk-{idx + 1}" for idx in range(len(chunks))],
        )
        doc.chunk_count = len(chunks)
        doc.status = "ready"
        doc.progress = 100
        doc.last_error = None
        doc.failed_stage = None
        doc.updated_at = utc_now_iso()
        self._upsert_doc(doc)
        return doc

    def _index_embeddings(self, doc: MindspaceDoc, chunks: list[str]) -> None:
        if not chunks or not self.semantic_search_enabled():
            return

        doc.status = "embedding"
        doc.progress = 85
        doc.failed_stage = None
        self._upsert_doc(doc)

        def update_embedding_progress(completed: int, total: int) -> None:
            ratio = min(1.0, max(0.0, completed / max(1, total)))
            next_progress = min(99, 85 + int(ratio * 14))
            if next_progress <= int(doc.progress or 0):
                return
            doc.progress = next_progress
            doc.updated_at = utc_now_iso()
            self._upsert_doc(doc)

        try:
            embed_with_progress = getattr(
                self.embedder,
                "embed_documents_with_progress",
                None,
            )
            if callable(embed_with_progress):
                vectors = embed_with_progress(
                    chunks,
                    progress_callback=update_embedding_progress,
                )
            else:
                vectors = self.embedder.embed_documents(chunks)
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc
        if len(vectors) != len(chunks):
            raise EmbeddingError("Embedding backend returned an unexpected vector count.")

        now = _now()
        model = (
            getattr(self.embedder, "storage_key", None)
            or self.embedder.model_name
            or "default"
        )
        rows = []
        for idx, vector in enumerate(vectors):
            chunk_id = f"{doc.id}-chunk-{idx + 1}"
            rows.append(
                {
                    "id": f"{chunk_id}-embedding-{uuid.uuid4().hex[:8]}",
                    "chunk_id": chunk_id,
                    "model": model,
                    "vector": json.dumps(vector, ensure_ascii=False),
                    "created_at": now,
                }
            )
        with self.engine.begin() as conn:
            conn.execute(
                delete(knowledge_embeddings).where(
                    knowledge_embeddings.c.chunk_id.in_(
                        [f"{doc.id}-chunk-{idx + 1}" for idx in range(len(chunks))]
                    )
                )
            )
            if rows:
                conn.execute(insert(knowledge_embeddings), rows)

    def _write_wiki(self, doc: MindspaceDoc, text: str, chunk_ids: list[str]) -> list[str]:
        concept = self._safe_concept(Path(doc.name).stem or doc.name)
        wiki_id = f"{doc.id}-{concept}"
        excerpt = text.strip()[:1200]
        content = (
            f"# {doc.name}\n\n"
            f"- Source document: {doc.id}\n"
            f"- Scope: {doc.scope.value}\n"
            f"- Source type: {doc.source_type}\n\n"
            f"## Extracted Notes\n\n{excerpt}\n"
        )
        now = _now()
        values = {
            "id": wiki_id,
            "doc_id": doc.id,
            "scope": doc.scope.value,
            "owner_user_id": doc.owner_user_id,
            "concept": wiki_id,
            "content": content,
            "chunk_ids": json.dumps(chunk_ids, ensure_ascii=False),
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(knowledge_wiki.c.id).where(knowledge_wiki.c.id == wiki_id),
            ).first()
            if existing:
                conn.execute(
                    update(knowledge_wiki)
                    .where(knowledge_wiki.c.id == wiki_id)
                    .values(**values),
                )
            else:
                values["created_at"] = now
                conn.execute(insert(knowledge_wiki).values(**values))
        return [wiki_id]

    def _remove_generated_wiki(self, doc: MindspaceDoc) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(knowledge_wiki).where(knowledge_wiki.c.doc_id == doc.id))

    def _remove_chunks(self, doc_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(knowledge_embeddings).where(
                    knowledge_embeddings.c.chunk_id.in_(
                        select(knowledge_chunks.c.id).where(knowledge_chunks.c.doc_id == doc_id)
                    )
                )
            )
            conn.execute(delete(knowledge_chunks).where(knowledge_chunks.c.doc_id == doc_id))

    def _load_chunks(
        self,
        scope: MindspaceScope | str | None = None,
        *,
        doc_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> list[MindspaceChunk]:
        resolved_scope = normalize_mindspace_scope(scope)
        stmt = select(knowledge_chunks)
        if category or normalize_knowledge_tags(tags):
            allowed_doc_ids = {
                doc.id
                for doc in self.list_documents(
                    scope,
                    category=category,
                    tags=tags,
                )
            }
            if not allowed_doc_ids:
                return []
            stmt = stmt.where(knowledge_chunks.c.doc_id.in_(allowed_doc_ids))
        if doc_id:
            stmt = stmt.where(knowledge_chunks.c.doc_id == doc_id)
        if self.exclusive_personal:
            stmt = stmt.where(
                knowledge_chunks.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_chunks.c.owner_user_id == self.user_id,
            )
            if resolved_scope == MindspaceScope.ENTERPRISE:
                stmt = stmt.where(
                    knowledge_chunks.c.scope == MindspaceScope.ENTERPRISE.value,
                )
        elif resolved_scope == MindspaceScope.ENTERPRISE:
            stmt = stmt.where(knowledge_chunks.c.scope == MindspaceScope.ENTERPRISE.value)
        elif resolved_scope == MindspaceScope.PERSONAL:
            stmt = stmt.where(
                knowledge_chunks.c.scope == MindspaceScope.PERSONAL.value,
                knowledge_chunks.c.owner_user_id == self.user_id,
            )
        else:
            stmt = stmt.where(self._readable_chunks_clause())
        stmt = stmt.order_by(knowledge_chunks.c.chunk_index.asc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        chunks = []
        for row in rows:
            scope_value = normalize_mindspace_scope(row["scope"], MindspaceScope.PERSONAL)
            assert scope_value is not None
            chunks.append(
                MindspaceChunk(
                    id=str(row["id"]),
                    doc_id=str(row["doc_id"]),
                    doc_name=str(row["doc_name"]),
                    scope=scope_value,
                    owner_user_id=(
                        str(row["owner_user_id"])
                        if row["owner_user_id"] is not None
                        else None
                    ),
                    chunk_index=int(row["chunk_index"] or 0),
                    text=str(row["text"] or ""),
                    source_url=row["source_url"],
                    locator=row["locator"],
                )
            )
        return chunks

    def _load_embeddings(self, chunk_ids: Iterable[str]) -> dict[str, list[float]]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        stmt = select(
            knowledge_embeddings.c.chunk_id,
            knowledge_embeddings.c.vector,
        ).where(knowledge_embeddings.c.chunk_id.in_(ids))
        model = (
            getattr(self.embedder, "storage_key", None)
            or self.embedder.model_name
        )
        if model:
            stmt = stmt.where(knowledge_embeddings.c.model == model)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()

        vectors: dict[str, list[float]] = {}
        for row in rows:
            try:
                raw = json.loads(str(row["vector"]))
                if isinstance(raw, list):
                    vectors[str(row["chunk_id"])] = [float(value) for value in raw]
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return vectors

    def _new_doc(
        self,
        *,
        name: str,
        source_type: str,
        scope: MindspaceScope,
        source_url: str | None = None,
        byte_size: int = 0,
        status: str = "pending",
        progress: int = 0,
        agent_ids: list[str] | None = None,
        cloud_account_id: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | str | None = None,
    ) -> MindspaceDoc:
        owner_user_id = self.user_id if scope == MindspaceScope.PERSONAL else None
        return MindspaceDoc(
            id=self._new_doc_id(),
            scope=scope,
            owner_user_id=owner_user_id,
            legacy_agent_id=self.agent_id if scope == MindspaceScope.PERSONAL else None,
            name=name,
            source_type=source_type,
            category=normalize_knowledge_category(category),
            tags=normalize_knowledge_tags(tags),
            source_url=source_url,
            cloud_account_id=cloud_account_id,
            size=self._human_size(byte_size),
            byte_size=byte_size,
            status=status,
            progress=progress,
            agent_ids=agent_ids or [],
        )

    def _upsert_doc(self, doc: MindspaceDoc) -> None:
        values = self._doc_to_row(doc)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(knowledge_docs.c.id).where(knowledge_docs.c.id == doc.id),
            ).first()
            if existing:
                conn.execute(
                    update(knowledge_docs)
                    .where(knowledge_docs.c.id == doc.id)
                    .values(**values),
                )
            else:
                values["created_at"] = _now()
                conn.execute(insert(knowledge_docs).values(**values))

    def _doc_to_row(self, doc: MindspaceDoc) -> dict[str, Any]:
        resolved_scope = self._require_scope(doc.scope)
        doc.scope = resolved_scope
        doc.owner_user_id = self.user_id if resolved_scope == MindspaceScope.PERSONAL else None
        doc.category = normalize_knowledge_category(doc.category)
        doc.tags = normalize_knowledge_tags(doc.tags)
        now = _now()
        return {
            "id": doc.id,
            "scope": doc.scope.value,
            "owner_user_id": doc.owner_user_id,
            "name": doc.name,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "category": doc.category,
            "tags": json.dumps(doc.tags, ensure_ascii=False),
            "size": doc.size,
            "byte_size": int(doc.byte_size or 0),
            "chunk_count": int(doc.chunk_count or 0),
            "status": doc.status,
            "progress": int(doc.progress or 0),
            "failed_stage": doc.failed_stage,
            "last_error": doc.last_error,
            "cloud_account_id": doc.cloud_account_id,
            "agent_ids": json.dumps(doc.agent_ids, ensure_ascii=False),
            "legacy_agent_id": doc.legacy_agent_id,
            "generated_wiki": json.dumps(doc.generated_wiki, ensure_ascii=False),
            "updated_at": _parse_iso(doc.updated_at) or now,
        }

    def _doc_from_row(self, row: dict[str, Any]) -> MindspaceDoc:
        scope = self._require_scope(str(row["scope"]))
        return MindspaceDoc(
            id=str(row["id"]),
            scope=scope,
            owner_user_id=(
                str(row["owner_user_id"]) if row.get("owner_user_id") is not None else None
            ),
            name=str(row["name"]),
            source_type=str(row["source_type"]),
            category=normalize_knowledge_category(row.get("category")),
            tags=normalize_knowledge_tags(row.get("tags")),
            source_url=row.get("source_url"),
            size=str(row.get("size") or "0 KB"),
            byte_size=int(row.get("byte_size") or 0),
            chunk_count=int(row.get("chunk_count") or 0),
            status=str(row.get("status") or "pending"),
            progress=int(row.get("progress") or 0),
            failed_stage=row.get("failed_stage"),
            last_error=row.get("last_error"),
            cloud_account_id=row.get("cloud_account_id"),
            agent_ids=_json_list(row.get("agent_ids")),
            legacy_agent_id=row.get("legacy_agent_id"),
            generated_wiki=_json_list(row.get("generated_wiki")),
            updated_at=_iso(row.get("updated_at")),
        )

    def _store_asset(
        self,
        doc: MindspaceDoc,
        content: bytes,
        *,
        mime_type: str | None = None,
        kind: str = "raw",
    ) -> None:
        asset_id = f"{doc.id}-{kind}-{uuid.uuid4().hex[:8]}"
        root = self._asset_root(doc.scope)
        root.mkdir(parents=True, exist_ok=True)
        suffix = Path(doc.name).suffix or f".{doc.source_type}"
        path = root / f"{asset_id}{suffix}"
        path.write_bytes(content)
        now = _now()
        with self.engine.begin() as conn:
            conn.execute(
                insert(knowledge_assets).values(
                    id=asset_id,
                    doc_id=doc.id,
                    kind=kind,
                    storage_path=str(path),
                    mime_type=mime_type or mimetypes.guess_type(doc.name)[0],
                    sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content),
                    created_at=now,
                )
            )

    def _first_asset(
        self,
        doc_id: str,
        *,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        stmt = select(knowledge_assets).where(knowledge_assets.c.doc_id == doc_id)
        if kind:
            stmt = stmt.where(knowledge_assets.c.kind == kind)
        with self.engine.connect() as conn:
            row = conn.execute(
                stmt.order_by(knowledge_assets.c.created_at.desc()),
            ).mappings().first()
        return dict(row) if row else None

    def _asset_root(self, scope: MindspaceScope) -> Path:
        if scope == MindspaceScope.ENTERPRISE:
            return self.global_root / "assets" / "enterprise"
        return self.global_root / "assets" / "users" / self.user_id

    def _migrate_legacy_cloud_docs(self) -> None:
        self._migrate_legacy_docs_file(
            self.global_root / "docs.json",
            default_scope=MindspaceScope.ENTERPRISE,
            owner_user_id=None,
            legacy_agent_id=None,
        )
        self._migrate_legacy_chunks_file(
            self.global_root / "chunks.json",
            default_scope=MindspaceScope.ENTERPRISE,
        )
        self._migrate_legacy_docs_file(
            self.agent_root / "docs.json",
            default_scope=MindspaceScope.PERSONAL,
            owner_user_id=self.user_id,
            legacy_agent_id=self.agent_id,
        )
        self._migrate_legacy_chunks_file(
            self.agent_root / "chunks.json",
            default_scope=MindspaceScope.PERSONAL,
        )
        self._migrate_legacy_docs_file(
            self.agent_workspace / "cloud_docs.json",
            default_scope=MindspaceScope.PERSONAL,
            owner_user_id=self.user_id,
            legacy_agent_id=self.agent_id,
        )

    def _migrate_legacy_docs_file(
        self,
        path: Path,
        *,
        default_scope: MindspaceScope,
        owner_user_id: str | None,
        legacy_agent_id: str | None,
    ) -> None:
        if not path.exists():
            return
        try:
            raw_docs = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw_docs, list):
            return
        for raw in raw_docs:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            if self._doc_exists(str(raw["id"])):
                continue
            doc = MindspaceDoc.from_dict(raw, default_scope=default_scope)
            doc.scope = default_scope
            doc.owner_user_id = owner_user_id
            doc.legacy_agent_id = legacy_agent_id
            doc.progress = 100 if doc.status == "ready" else doc.progress
            self._upsert_doc(doc)

    def _migrate_legacy_chunks_file(
        self,
        path: Path,
        *,
        default_scope: MindspaceScope,
    ) -> None:
        if not path.exists():
            return
        try:
            raw_chunks = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw_chunks, list):
            return
        rows = []
        existing_ids = set()
        with self.engine.connect() as conn:
            existing_ids = {
                str(row[0])
                for row in conn.execute(select(knowledge_chunks.c.id)).all()
            }
        for index, raw in enumerate(raw_chunks):
            if not isinstance(raw, dict) or not raw.get("id") or raw["id"] in existing_ids:
                continue
            scope = normalize_mindspace_scope(raw.get("scope"), default_scope) or default_scope
            owner_user_id = self.user_id if scope == MindspaceScope.PERSONAL else None
            rows.append(
                {
                    "id": str(raw["id"]),
                    "doc_id": str(raw.get("doc_id") or ""),
                    "doc_name": str(raw.get("doc_name") or ""),
                    "scope": scope.value,
                    "owner_user_id": owner_user_id,
                    "chunk_index": int(raw.get("chunk_index") or index),
                    "text": str(raw.get("text") or ""),
                    "source_url": raw.get("source_url"),
                    "locator": raw.get("locator") or f"legacy:{index + 1}",
                    "created_at": _now(),
                }
            )
        if rows:
            with self.engine.begin() as conn:
                conn.execute(insert(knowledge_chunks), rows)

    def _doc_exists(self, doc_id: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(knowledge_docs.c.id).where(knowledge_docs.c.id == doc_id),
            ).first()
        return row is not None

    def _readable_docs_clause(self):
        if self.exclusive_personal:
            return (
                (knowledge_docs.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_docs.c.owner_user_id == self.user_id)
            )
        return or_(
            knowledge_docs.c.scope == MindspaceScope.ENTERPRISE.value,
            (
                (knowledge_docs.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_docs.c.owner_user_id == self.user_id)
            ),
        )

    def _readable_chunks_clause(self):
        if self.exclusive_personal:
            return (
                (knowledge_chunks.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_chunks.c.owner_user_id == self.user_id)
            )
        return or_(
            knowledge_chunks.c.scope == MindspaceScope.ENTERPRISE.value,
            (
                (knowledge_chunks.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_chunks.c.owner_user_id == self.user_id)
            ),
        )

    def _readable_wiki_clause(self):
        if self.exclusive_personal:
            return (
                (knowledge_wiki.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_wiki.c.owner_user_id == self.user_id)
            )
        return or_(
            knowledge_wiki.c.scope == MindspaceScope.ENTERPRISE.value,
            (
                (knowledge_wiki.c.scope == MindspaceScope.PERSONAL.value)
                & (knowledge_wiki.c.owner_user_id == self.user_id)
            ),
        )

    def _require_scope(self, scope: MindspaceScope | str | None) -> MindspaceScope:
        resolved = normalize_mindspace_scope(scope)
        if resolved not in {MindspaceScope.ENTERPRISE, MindspaceScope.PERSONAL}:
            raise ValueError("scope must be enterprise, personal, global, or agent")
        return resolved

    def _ensure_roots(self) -> None:
        for root in [self.global_root, self.agent_root]:
            root.mkdir(parents=True, exist_ok=True)
        (self.global_root / "assets").mkdir(parents=True, exist_ok=True)

    def _unlink_asset(self, path: Path) -> None:
        try:
            if path.exists() and self.global_root.resolve() in path.resolve().parents:
                path.unlink()
        except OSError:
            pass

    def _new_doc_id(self) -> str:
        return f"mindspace-{uuid.uuid4().hex[:12]}"

    def _chunk_text(self, text: str, max_chars: int = 900) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
        if not normalized:
            return []
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 2 <= max_chars:
                current = f"{current}\n\n{paragraph}".strip()
                continue
            if current:
                chunks.append(current)
            while len(paragraph) > max_chars:
                chunks.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            current = paragraph
        if current:
            chunks.append(current)
        return chunks or [normalized[:max_chars]]

    def _normalize_search_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _terms(self, text: str) -> list[str]:
        """Tokenize Latin words and expand Chinese phrases into bigrams.

        The previous regex treated an entire Chinese sentence as one token,
        which meant a query such as ``报销流程`` could not match a sentence
        containing ``费用报销``.  Keeping the full phrase plus bigrams gives
        deterministic partial recall without requiring an external tokenizer.
        """
        raw_terms = re.findall(
            r"[a-z0-9_]+|[\u4e00-\u9fff]+",
            self._normalize_search_text(text),
        )
        terms: list[str] = []
        for term in raw_terms:
            terms.append(term)
            if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
                terms.extend(term[index : index + 2] for index in range(len(term) - 1))
        return list(dict.fromkeys(terms))

    def _query_terms(self, text: str) -> list[str]:
        normalized = self._normalize_search_text(text)
        for phrase in (
            "请问",
            "麻烦",
            "帮我",
            "我们",
            "公司",
            "当前",
            "这个",
            "那个",
            "是什么",
            "有哪些",
            "怎么",
            "如何",
            "是否",
            "可以",
            "需要",
            "一下",
            "的",
        ):
            normalized = normalized.replace(phrase, " ")
        english_stopwords = {
            "a",
            "an",
            "and",
            "are",
            "do",
            "does",
            "for",
            "how",
            "is",
            "of",
            "our",
            "please",
            "the",
            "to",
            "what",
        }
        terms = [
            term
            for term in self._terms(normalized)
            if term not in english_stopwords
        ]
        return terms or self._terms(text)

    def _rerank_score(
        self,
        *,
        query: str,
        query_terms: list[str],
        chunk: MindspaceChunk,
        score: float,
    ) -> tuple[float, str | None]:
        """Apply a small deterministic rerank after hybrid recall."""
        text = self._normalize_search_text(chunk.text)
        title = self._normalize_search_text(chunk.doc_name)
        bonus = 0.0
        reasons: list[str] = []

        if query and query in text:
            bonus += 0.08
            reasons.append("exact-phrase")

        title_matches = [term for term in query_terms if term and term in title]
        if title_matches:
            bonus += min(0.08, 0.02 * len(set(title_matches)))
            reasons.append("title")

        positions = sorted(
            position
            for term in set(query_terms)
            if term and (position := text.find(term)) >= 0
        )
        if len(positions) >= 2 and positions[-1] - positions[0] <= 160:
            bonus += 0.04
            reasons.append("proximity")

        return min(1.0, max(0.0, score + bonus)), (
            "rerank:" + "+".join(reasons) if reasons else None
        )

    def _neighbor_context(
        self,
        hit: MindspaceSearchHit,
        chunks: list[MindspaceChunk],
        *,
        radius: int = 1,
        max_chars: int = 3200,
    ) -> tuple[str, list[str]]:
        doc_chunks = sorted(
            (chunk for chunk in chunks if chunk.doc_id == hit.doc_id),
            key=lambda chunk: chunk.chunk_index,
        )
        target_index = next(
            (
                index
                for index, chunk in enumerate(doc_chunks)
                if chunk.id == hit.chunk_id
            ),
            None,
        )
        if target_index is None:
            return hit.text, [hit.chunk_id]

        start = max(0, target_index - max(0, radius))
        end = min(len(doc_chunks), target_index + max(0, radius) + 1)
        selected = doc_chunks[start:end]
        parts = [
            f"[{chunk.locator or chunk.id}] {chunk.text}"
            for chunk in selected
        ]
        context = "\n\n".join(parts)
        if len(context) > max_chars:
            context = context[: max_chars - 1].rstrip() + "…"
        return context, [chunk.id for chunk in selected]

    def _safe_concept(self, value: str) -> str:
        concept = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip()).strip("-")
        return concept or "document"

    def _human_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value:
        return str(value)
    return utc_now_iso()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []
