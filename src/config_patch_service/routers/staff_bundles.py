"""Employee export of trusted baseline workspaces."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..dependencies import require_staff_token
from ..models import AuthenticatedStaffToken
from ..releases import BaselineExportError, BaselineExportService
from ..upstreams import UpstreamNotFoundError


router = APIRouter(prefix="/staff/v1", tags=["config-patch-staff"])


def _export_service(request: Request) -> BaselineExportService:
    return request.app.state.baseline_export_service


@router.post("/bots/{bot_id}/workspace-bundles/export")
def export_workspace_bundle(
    bot_id: str,
    request: Request,
    identity: AuthenticatedStaffToken = Depends(require_staff_token),
    service: BaselineExportService = Depends(_export_service),
) -> Response:
    correlation_id = uuid.uuid4().hex
    try:
        built = service.export(
            bot_id,
            actor_token_id=identity.token_id,
            correlation_id=correlation_id,
        )
    except UpstreamNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONFIG_PATCH_BOT_NOT_FOUND"},
        ) from exc
    except BaselineExportError as exc:
        detail: dict[str, object] = {"code": exc.code}
        if exc.missing_items:
            detail["missingItems"] = exc.missing_items
        raise HTTPException(status_code=409, detail=detail) from exc

    request.app.state.config_patch_audit.record(
        "staff.workspace_bundle.export",
        token_id=identity.token_id,
        employee_name=identity.employee_name,
        result="success",
        metadata={
            "botId": bot_id,
            "releaseId": built.release_id,
            "bundleDigest": built.bundle_digest,
            "correlationId": correlation_id,
        },
    )
    return Response(
        content=built.archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="workspace-{built.release_id}.zip"'
            ),
            "X-DClaw-Release-Id": built.release_id,
            "X-DClaw-Bundle-Digest": built.bundle_digest,
        },
    )
