# -*- coding: utf-8 -*-
"""Role-aware routes for Open API agent experience libraries."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..open_api.knowledge import list_accessible_publications


router = APIRouter(
    prefix="/open-api-knowledge",
    tags=["open-api-knowledge"],
)


@router.get("/publications")
def list_experience_publications(request: Request) -> list[dict[str, Any]]:
    return list_accessible_publications(request)
