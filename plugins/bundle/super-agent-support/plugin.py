"""Registration entry point for the isolated Super Agent Support package."""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from .credentials import CredentialBroker
from .mcp_server import LocalExecutionMcp
from .packages import CapabilityPackageRegistry
from .routes import create_app
from .service import LocalExecutionService
from .session import CAPABILITY_ID, PREFLIGHT_CAPABILITY_ID, SessionSigner
from .store import StateStore
from .super_agent.capabilities import PLATFORM_CAPABILITY_CATALOG_V1
from .super_agent.composition import (
    accepted_workflow_allows_unbound_node,
    create_aigc_event_consumer,
)
from .super_agent.package_handler import SuperAgentPackageHandler
from .super_agent.orchestration import handle_workspace_turn
from .super_agent.router import frontend_read_routes, user_routes
from qwenpaw.app.guards import require_user
from qwenpaw.app.sealed_agents.signing import load_trusted_signers
from qwenpaw.constant import WORKING_DIR


def _state_root(config: dict[str, Any]) -> Path:
    configured = config.get("state_dir") or os.environ.get(
        "DCLAW_SUPER_AGENT_SUPPORT_STATE_DIR",
    )
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".qwenpaw" / "super-agent-support"
    )


def _load_or_create_key(root: Path, configured: str | None) -> bytes:
    configured = configured or os.environ.get(
        "DCLAW_SUPER_AGENT_SUPPORT_MASTER_KEY_BASE64",
    )
    if configured:
        try:
            value = base64.urlsafe_b64decode(
                configured + "=" * (-len(configured) % 4),
            )
        except ValueError as exc:
            raise ValueError("invalid master_key_base64") from exc
        if len(value) < 32:
            raise ValueError(
                "master_key_base64 must decode to at least 32 bytes",
            )
        return value
    path = root / "master.key"
    if path.exists():
        value = path.read_bytes()
        if len(value) < 32:
            raise ValueError(
                "stored Super Agent Support master key is invalid",
            )
        return value
    root.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    path.write_bytes(value)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


class SuperAgentSupportPlugin:
    def __init__(self) -> None:
        self.mcp: LocalExecutionMcp | None = None

    def register(self, api) -> None:
        root = _state_root(api.config)
        key = _load_or_create_key(root, api.config.get("master_key_base64"))
        store = StateStore(root / "state.sqlite3")
        signer = SessionSigner(key)
        credentials = CredentialBroker(store, key)
        packages = CapabilityPackageRegistry(
            store,
            Path(__file__).parent
            / "schemas"
            / "capability-descriptor.schema.json",
            dict(api.config.get("trusted_package_signers") or {}),
        )
        service = LocalExecutionService(store, signer, credentials)
        sealed_root = Path(WORKING_DIR) / "sealed_agents"
        official_signers = load_trusted_signers(
            sealed_root / "official_super_expert_signers.json",
        )
        package_handler = SuperAgentPackageHandler(
            sealed_root,
            official_signer_ids=frozenset(official_signers),
            trusted_signers=official_signers,
        )
        self.mcp = LocalExecutionMcp(service)
        app = create_app(
            store=store,
            service=service,
            mcp=self.mcp,
            packages=packages,
            credentials=credentials,
        )
        api.register_asgi_app(
            app,
            prefix="/super-agent-support",
            name="dclaw-super-agent-support",
        )
        frontend_api = APIRouter(dependencies=[Depends(require_user)])
        frontend_api.include_router(frontend_read_routes)
        api.register_http_router(
            frontend_api,
            prefix="/super-expert-platform",
            tags=["super-expert-platform"],
        )
        user_api = APIRouter(dependencies=[Depends(require_user)])
        user_api.include_router(user_routes)
        api.register_http_router(
            user_api,
            prefix="/user/super-expert-platform",
            tags=["super-expert-platform"],
        )
        for definition in PLATFORM_CAPABILITY_CATALOG_V1.values():
            api.register_platform_capability(
                definition.capability_id,
                definition.contract_version,
                definition.group,
                dependencies=definition.dependencies,
            )
        for capability_id in (CAPABILITY_ID, PREFLIGHT_CAPABILITY_ID):
            api.register_platform_capability(
                capability_id,
                "1",
                "local_execution",
            )
        api.register_aigc_event_consumer_factory(
            "super-agent-aigc-projection",
            create_aigc_event_consumer,
        )
        api.register_aigc_canvas_policy(
            "super-agent-accepted-workflow",
            accepted_workflow_allows_unbound_node,
        )
        api.register_sealed_package_type("super_expert", package_handler)
        api.register_workspace_turn_handler(
            "workspace.turn.orchestrate/1",
            handle_workspace_turn,
        )
        api.register_workspace_context_enricher(
            "local-execution-session",
            signer.enrich,
            priority=100,
        )
        api.register_startup_hook(
            "mcp-session-manager",
            self.mcp.start,
            priority=20,
        )
        api.register_shutdown_hook(
            "mcp-session-manager",
            self.mcp.stop,
            priority=20,
        )


plugin = SuperAgentSupportPlugin()
