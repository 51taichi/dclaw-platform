# -*- coding: utf-8 -*-
"""Admin enterprise knowledge-base APIs."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope, MindspaceService
from ...mindspace.cloud_auth import CloudAuthStore
from ...mindspace.connectors import CloudConnectorRegistry
from ...mindspace.jobs import KnowledgeJobOperation, enqueue_knowledge_job
from ...mindspace.models import (
    MindspaceDoc,
    normalize_knowledge_category,
    normalize_knowledge_tags,
)
from ..chat_access import current_user_id


admin_router = APIRouter(prefix="/knowledge", tags=["admin-knowledge"])


class LinkKnowledgeRequest(BaseModel):
    title: str
    url: str
    docType: str
    cloud_account_id: str | None = None
    cloudAccountId: str | None = None
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)


class SyncKnowledgeRequest(BaseModel):
    id: str


class KnowledgeMetadataRequest(BaseModel):
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)


def _service(request: Request) -> MindspaceService:
    root = Path(WORKING_DIR) / "mindspace"
    auth_store = CloudAuthStore(root)
    return MindspaceService(
        global_root=root,
        agent_workspace=root / "_admin",
        agent_id="enterprise",
        user_id=current_user_id(request),
        connectors=CloudConnectorRegistry(auth_store=auth_store),
    )


async def _enqueue(
    service: MindspaceService,
    doc: MindspaceDoc,
    *,
    operation: KnowledgeJobOperation,
) -> dict:
    try:
        job_id = await enqueue_knowledge_job(
            service,
            doc,
            operation=operation,
        )
    except Exception as exc:
        await asyncio.to_thread(
            service.mark_document_failed,
            doc.id,
            scope=doc.scope,
            failed_stage="queue",
            error=f"Knowledge background queue is unavailable: {exc}",
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Knowledge background queue is unavailable. "
                "Please retry later."
            ),
        ) from exc
    payload = doc.to_api_dict()
    payload.update({"accepted": True, "job_id": job_id})
    return payload


@admin_router.get("/docs", response_model=list[dict])
async def list_enterprise_knowledge_docs(
    request: Request,
    category: str | None = Query(None, max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> list[dict]:
    service = _service(request)
    return [
        doc.to_api_dict()
        for doc in service.list_documents(
            scope=MindspaceScope.ENTERPRISE,
            category=category,
            tags=normalize_knowledge_tags(tags),
        )
    ]


@admin_router.get("/capabilities", response_model=dict)
async def enterprise_knowledge_capabilities(request: Request) -> dict:
    service = _service(request)
    return service.search_capabilities()


@admin_router.post("/docs/upload", response_model=dict)
async def upload_enterprise_knowledge_doc(
    request: Request,
    file: UploadFile = File(...),
    category: str = Query("uncategorized", max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict:
    service = _service(request)
    filename = file.filename or "unknown_file.txt"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    content = await file.read()
    doc = await asyncio.to_thread(
        service.stage_local_bytes,
        name=filename,
        source_type=suffix,
        content=content,
        scope=MindspaceScope.ENTERPRISE,
        mime_type=file.content_type,
        category=normalize_knowledge_category(category),
        tags=normalize_knowledge_tags(tags),
    )
    return await _enqueue(service, doc, operation="ingest")


@admin_router.post("/docs/link", response_model=dict)
async def link_enterprise_knowledge_doc(
    request: Request,
    payload: LinkKnowledgeRequest = Body(...),
) -> dict:
    service = _service(request)
    doc = service.stage_cloud_document(
        title=payload.title,
        url=payload.url,
        source_type=payload.docType,
        scope=MindspaceScope.ENTERPRISE,
        cloud_account_id=payload.cloud_account_id or payload.cloudAccountId,
        category=payload.category,
        tags=payload.tags,
    )
    return await _enqueue(service, doc, operation="link")


@admin_router.post("/docs/{doc_id}/sync", response_model=dict)
async def sync_enterprise_knowledge_doc(
    doc_id: str,
    request: Request,
) -> dict:
    service = _service(request)
    doc = await asyncio.to_thread(
        service.mark_document_queued,
        doc_id,
        scope=MindspaceScope.ENTERPRISE,
        operation="resync",
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _enqueue(service, doc, operation="resync")


@admin_router.post("/docs/sync", response_model=dict)
async def sync_enterprise_knowledge_doc_compat(
    request: Request,
    payload: SyncKnowledgeRequest = Body(...),
) -> dict:
    return await sync_enterprise_knowledge_doc(payload.id, request)


@admin_router.get("/docs/{doc_id}", response_model=dict)
async def read_enterprise_knowledge_doc(
    doc_id: str,
    request: Request,
) -> dict:
    service = _service(request)
    payload = service.read_document(doc_id, scope=MindspaceScope.ENTERPRISE)
    if payload is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return payload


@admin_router.patch("/docs/{doc_id}/metadata", response_model=dict)
async def update_enterprise_knowledge_metadata(
    doc_id: str,
    request: Request,
    payload: KnowledgeMetadataRequest = Body(...),
) -> dict:
    service = _service(request)
    doc = service.update_document_metadata(
        doc_id,
        scope=MindspaceScope.ENTERPRISE,
        category=payload.category,
        tags=payload.tags,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.to_api_dict()


@admin_router.delete("/docs/{doc_id}", response_model=dict)
async def delete_enterprise_knowledge_doc(
    doc_id: str,
    request: Request,
    scope: str = Query("enterprise"),
) -> dict:
    _ = scope
    service = _service(request)
    if not service.delete_document(doc_id, scope=MindspaceScope.ENTERPRISE):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True, "id": doc_id}


@admin_router.get("/search", response_model=dict)
async def search_enterprise_knowledge(
    request: Request,
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    min_score: float = Query(0.15, ge=0, le=1),
    category: str | None = Query(None, max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict:
    service = _service(request)
    hits = service.search(
        q,
        scope=MindspaceScope.ENTERPRISE,
        top_k=top_k,
        min_score=min_score,
        category=category,
        tags=normalize_knowledge_tags(tags),
    )
    return {
        "hits": [hit.to_dict() for hit in hits],
        **service.search_capabilities(),
    }
