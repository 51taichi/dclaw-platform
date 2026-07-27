# -*- coding: utf-8 -*-
"""Mindspace knowledge base domain services."""

from .models import MindspaceDoc, MindspaceScope, MindspaceSearchHit
from .service import MindspaceService

__all__ = [
    "MindspaceDoc",
    "MindspaceScope",
    "MindspaceSearchHit",
    "MindspaceService",
]
