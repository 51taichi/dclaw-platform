# -*- coding: utf-8 -*-
"""Per-claim fencing identity for OpenAPI execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .open_api import OpenApiBillingSession


@dataclass(frozen=True)
class OpenApiExecutionFence:
    """A lease owner's monotonic identity for one invocation claim."""

    owner_token: str
    generation: int


@dataclass(frozen=True)
class OpenApiBillingExecutionContext:
    """A committed session combined with the current execution claim."""

    session: "OpenApiBillingSession"
    fence: OpenApiExecutionFence
