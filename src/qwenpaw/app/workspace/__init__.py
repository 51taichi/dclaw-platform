# -*- coding: utf-8 -*-
"""Workspace module for agent lifecycle management.

This module provides unified workspace management including:
- Workspace: Single agent instance manager
- ServiceManager: Component lifecycle orchestration
- ServiceDescriptor: Declarative service configuration
"""

__all__ = ["Workspace", "ServiceManager", "ServiceDescriptor"]


def __getattr__(name):
    """Keep lifecycle exports without eagerly importing Runner dependencies."""
    if name == "Workspace":
        from .workspace import Workspace

        return Workspace
    if name in {"ServiceManager", "ServiceDescriptor"}:
        from .service_manager import ServiceDescriptor, ServiceManager

        return {
            "ServiceManager": ServiceManager,
            "ServiceDescriptor": ServiceDescriptor,
        }[name]
    raise AttributeError(name)
