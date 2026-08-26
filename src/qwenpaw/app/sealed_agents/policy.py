"""Asset-first authorization for sealed agents."""

from __future__ import annotations

from fastapi import HTTPException

from .models import SealedCapability

_PUBLIC_CAPABILITIES = {
    SealedCapability.INVOKE,
    SealedCapability.PUBLIC_METADATA,
}


def assert_sealed_capability(
    agent_id: str,
    capability: SealedCapability,
    *,
    is_sealed: bool,
) -> None:
    del agent_id
    if not is_sealed or capability in _PUBLIC_CAPABILITIES:
        return
    raise HTTPException(
        status_code=403,
        detail="Sealed agent asset access denied",
    )
