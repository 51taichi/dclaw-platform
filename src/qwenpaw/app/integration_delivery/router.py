# -*- coding: utf-8 -*-
"""Internal read-only routes consumed by the integration client."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from importlib.resources import files

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
)

from .auth import AuthenticatedIntegrationClient, require_integration_client
from .models import (
    DclawConfigurationContext,
    DeliveryOperationView,
    DeliveryValidation,
)
from .service import (
    DclawConfigurationContextService,
    get_dclaw_configuration_context_service,
)
from .export import (
    DclawSnapshotExporter,
    SnapshotExportError,
    get_dclaw_snapshot_exporter,
)
from .update import (
    DeliveryBundleError,
    DeliveryIdempotencyKeyReused,
    DeliverySourceChanged,
    IntegrationDeliveryUpdater,
)


router = APIRouter(
    prefix="/internal/integrations/v1",
    tags=["dclaw-integrations"],
    dependencies=[Depends(require_integration_client)],
)


@lru_cache(maxsize=1)
def _capability_catalog() -> dict[str, object]:
    resource = files("qwenpaw.app.integration_delivery.resources").joinpath(
        "dclaw-capability-catalog.v1.json",
    )
    return json.loads(resource.read_text(encoding="utf-8"))


@router.get("/capabilities")
def get_integration_capabilities() -> dict[str, object]:
    return _capability_catalog()


@router.get(
    "/agents/{agent_id}/delivery-context",
    response_model=DclawConfigurationContext,
)
def get_agent_configuration_context(
    agent_id: str,
    service: DclawConfigurationContextService = Depends(
        get_dclaw_configuration_context_service,
    ),
) -> DclawConfigurationContext:
    return service.describe(agent_id)


@router.get("/agents/{agent_id}/source-bundle")
def get_agent_configuration_snapshot(
    agent_id: str,
    exporter: DclawSnapshotExporter = Depends(get_dclaw_snapshot_exporter),
) -> Response:
    try:
        snapshot = exporter.export(agent_id)
    except SnapshotExportError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "missingItems": exc.missing_items,
            },
        ) from exc
    return Response(
        content=snapshot.archive,
        media_type="application/zip",
        headers={
            "X-DClaw-Agent-Id": snapshot.agent_id,
            "X-DClaw-Agent-Profile-Id": snapshot.profile_id,
            "X-DClaw-Source-Version": snapshot.source_version,
            "X-DClaw-Agent-Digest": snapshot.agent_digest,
            "X-DClaw-Knowledge-Digest": snapshot.knowledge_digest,
        },
    )


def get_integration_delivery_updater() -> IntegrationDeliveryUpdater:
    return IntegrationDeliveryUpdater()


def _required_write_headers(
    expected_agent_digest: str | None,
    expected_knowledge_digest: str | None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    if (
        not expected_agent_digest
        or not expected_knowledge_digest
        or idempotency_key is not None
        and not idempotency_key.strip()
    ):
        raise HTTPException(
            status_code=400,
            detail={"code": "DCLAW_REQUEST_INVALID"},
        )
    return expected_agent_digest, expected_knowledge_digest


def _write_error(
    exc: Exception,
    *,
    operation_lookup: bool = False,
) -> HTTPException:
    if isinstance(exc, DeliverySourceChanged):
        return HTTPException(409, detail={"code": "DCLAW_SOURCE_CHANGED"})
    if isinstance(exc, DeliveryIdempotencyKeyReused):
        return HTTPException(409, detail={"code": "IDEMPOTENCY_KEY_REUSED"})
    if isinstance(exc, DeliveryBundleError):
        return HTTPException(
            404 if operation_lookup else 400,
            detail={
                "code": (
                    "DCLAW_OPERATION_NOT_FOUND"
                    if operation_lookup
                    else "DCLAW_DELIVERY_BUNDLE_INVALID"
                ),
            },
        )
    return HTTPException(500, detail={"code": "DCLAW_DELIVERY_APPLY_FAILED"})


async def _reload_agent(request: Request, agent_id: str) -> None:
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return
    loaded = (
        await manager.reload_agent(agent_id)
        if manager.is_agent_loaded(agent_id)
        else await manager.preload_agent(agent_id)
    )
    if not loaded:
        raise RuntimeError("Agent reload failed")


@router.post(
    "/agents/{agent_id}/delivery-bundle/validate",
    response_model=DeliveryValidation,
)
async def validate_agent_delivery_bundle(
    agent_id: str,
    request: Request,
    expected_agent_digest: str
    | None = Header(
        default=None,
        alias="X-DClaw-Expected-Agent-Digest",
    ),
    expected_knowledge_digest: str
    | None = Header(
        default=None,
        alias="X-DClaw-Expected-Knowledge-Digest",
    ),
    updater: IntegrationDeliveryUpdater = Depends(
        get_integration_delivery_updater,
    ),
) -> DeliveryValidation:
    expected_agent_digest, expected_knowledge_digest = _required_write_headers(
        expected_agent_digest,
        expected_knowledge_digest,
    )
    try:
        return updater.validate(
            agent_id,
            await request.body(),
            expected_agent_digest=expected_agent_digest,
            expected_knowledge_digest=expected_knowledge_digest,
        )
    except Exception as exc:
        raise _write_error(exc) from exc


@router.put(
    "/agents/{agent_id}/delivery-bundle",
    response_model=DeliveryOperationView,
)
async def apply_agent_delivery_bundle(
    agent_id: str,
    request: Request,
    client: AuthenticatedIntegrationClient = Depends(
        require_integration_client,
    ),
    idempotency_key: str
    | None = Header(default=None, alias="Idempotency-Key"),
    expected_agent_digest: str
    | None = Header(
        default=None,
        alias="X-DClaw-Expected-Agent-Digest",
    ),
    expected_knowledge_digest: str
    | None = Header(
        default=None,
        alias="X-DClaw-Expected-Knowledge-Digest",
    ),
    updater: IntegrationDeliveryUpdater = Depends(
        get_integration_delivery_updater,
    ),
) -> DeliveryOperationView:
    expected_agent_digest, expected_knowledge_digest = _required_write_headers(
        expected_agent_digest,
        expected_knowledge_digest,
        idempotency_key,
    )
    if idempotency_key is None:
        raise HTTPException(400, detail={"code": "DCLAW_REQUEST_INVALID"})
    operation_id = hashlib.sha256(
        f"{client.client_id}\0{idempotency_key}".encode("utf-8"),
    ).hexdigest()
    try:
        result = updater.apply(
            agent_id,
            await request.body(),
            operation_id,
            expected_agent_digest=expected_agent_digest,
            expected_knowledge_digest=expected_knowledge_digest,
        )
        if result.previous_agent_digest != result.agent_digest:
            await _reload_agent(request, agent_id)
        return result
    except Exception as exc:
        if not isinstance(
            exc,
            (
                DeliveryBundleError,
                DeliverySourceChanged,
                DeliveryIdempotencyKeyReused,
            ),
        ):
            try:
                updater.restore(agent_id, operation_id)
                await _reload_agent(request, agent_id)
            except Exception:
                pass
        raise _write_error(exc) from exc


@router.get(
    "/agents/{agent_id}/delivery-operations/{operation_id}",
    response_model=DeliveryOperationView,
)
def get_agent_delivery_operation(
    agent_id: str,
    operation_id: str,
    updater: IntegrationDeliveryUpdater = Depends(
        get_integration_delivery_updater,
    ),
) -> DeliveryOperationView:
    try:
        return updater.get_operation(agent_id, operation_id)
    except Exception as exc:
        raise _write_error(exc, operation_lookup=True) from exc


@router.post(
    "/agents/{agent_id}/delivery-operations/{operation_id}/restore",
    response_model=DeliveryOperationView,
)
async def restore_agent_delivery_operation(
    agent_id: str,
    operation_id: str,
    request: Request,
    idempotency_key: str
    | None = Header(default=None, alias="Idempotency-Key"),
    updater: IntegrationDeliveryUpdater = Depends(
        get_integration_delivery_updater,
    ),
) -> DeliveryOperationView:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(400, detail={"code": "DCLAW_REQUEST_INVALID"})
    try:
        before = updater.get_operation(agent_id, operation_id)
        result = updater.restore(agent_id, operation_id)
        if before.agent_digest != result.agent_digest:
            await _reload_agent(request, agent_id)
        return result
    except Exception as exc:
        raise _write_error(exc, operation_lookup=True) from exc
