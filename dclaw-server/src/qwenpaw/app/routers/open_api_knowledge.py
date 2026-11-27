# -*- coding: utf-8 -*-
"""Role-aware routes for Open API agent experience libraries."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from ...mindspace import MindspaceScope
from ...mindspace.models import (
    normalize_knowledge_category,
    normalize_knowledge_tags,
)
from ..open_api import knowledge


router = APIRouter(
    prefix="/open-api-knowledge",
    tags=["open-api-knowledge"],
)


@router.get("/publications")
def list_experience_publications(request: Request) -> list[dict[str, Any]]:
    return knowledge.list_accessible_publications(request)


@router.get("/publications/{publication_id}/docs")
def list_documents(
    publication_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    publication = knowledge.require_accessible_publication(publication_id, request)
    service = knowledge.publication_knowledge_service(publication)
    return [
        doc.to_api_dict()
        for doc in service.list_documents(MindspaceScope.PERSONAL)
    ]


@router.post("/publications/{publication_id}/docs")
async def upload_document(
    publication_id: str,
    request: Request,
    file: UploadFile = File(...),
    category: str = Query("uncategorized", max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict[str, Any]:
    publication = knowledge.require_accessible_publication(publication_id, request)
    service = knowledge.publication_knowledge_service(publication)
    filename = file.filename or "knowledge.txt"
    suffix = os.path.splitext(filename)[1].lower().lstrip(".") or "txt"
    content = await file.read()
    doc = await asyncio.to_thread(
        service.stage_local_bytes,
        name=filename,
        content=content,
        scope=MindspaceScope.PERSONAL,
        source_type=suffix,
        mime_type=file.content_type,
        category=normalize_knowledge_category(category),
        tags=normalize_knowledge_tags(tags),
    )
    indexed = await asyncio.to_thread(
        service.process_staged_document,
        doc.id,
        MindspaceScope.PERSONAL,
    )
    return (indexed or doc).to_api_dict()


@router.post("/publications/{publication_id}/docs/{doc_id}/sync")
async def sync_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    publication = knowledge.require_accessible_publication(publication_id, request)
    service = knowledge.publication_knowledge_service(publication)
    doc = service.get_document(doc_id, MindspaceScope.PERSONAL)
    if doc is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    indexed = await service.resync_document(doc.id, MindspaceScope.PERSONAL)
    return (indexed or doc).to_api_dict()


@router.delete("/publications/{publication_id}/docs/{doc_id}")
def delete_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    publication = knowledge.require_accessible_publication(publication_id, request)
    service = knowledge.publication_knowledge_service(publication)
    if not service.delete_document(doc_id, MindspaceScope.PERSONAL):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"deleted": True, "id": doc_id}
