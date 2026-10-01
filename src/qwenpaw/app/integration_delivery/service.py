"""Read-only DClaw configuration context aggregation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...config.config import AgentProfileConfig, load_agent_config
from ...config.utils import load_config
from ..sealed_agents.registry import (
    SealedAgentRegistry,
    get_sealed_agent_registry,
)
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.open_api_repo import (
    OpenApiRepository,
    get_open_api_repository,
)
from .models import DclawConfigurationContext, Readiness


class DclawConfigurationContextService:
    """Resolve authoritative platform delivery metadata for one Agent."""

    def __init__(
        self,
        *,
        config_loader: Callable[[], Any] = load_config,
        agent_loader: Callable[[str], AgentProfileConfig] = load_agent_config,
        sealed_registry: SealedAgentRegistry | Any | None = None,
        publication_repository: OpenApiRepository | Any | None = None,
        wallet_repository: BillingRepository | Any | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._agent_loader = agent_loader
        self._sealed_registry = sealed_registry or get_sealed_agent_registry()
        self._publication_repository = (
            publication_repository or get_open_api_repository()
        )
        self._wallet_repository = wallet_repository or BillingRepository(
            get_app_engine(),
        )

    def describe(self, agent_id: str) -> DclawConfigurationContext:
        missing: list[str] = []
        agent_type: str = "unknown"
        profile_id: str | None = None
        enabled = False
        source_version: str | None = None

        sealed = self._sealed_registry.get_agent(agent_id)
        if sealed is not None:
            agent_type = "sealed"
            enabled = bool(sealed.enabled)
            active = sealed.active_release
            if active is None:
                missing.append("agent_active_release")
            else:
                source_version = active.version
                profile_id = (
                    "super-expert-2026.09"
                    if active.package_type == "super_expert"
                    else "sealed-2026.09"
                )
        else:
            config = self._config_loader()
            ref = getattr(getattr(config, "agents", None), "profiles", {}).get(
                agent_id,
            )
            if ref is None:
                missing.append("agent")
            else:
                agent_type = "standard"
                profile_id = "standard-2026.09"
                enabled = bool(ref.enabled)
                source_version = "workspace"
                try:
                    self._agent_loader(agent_id)
                except Exception:
                    missing.append("agent_source")

        if agent_type != "unknown" and not enabled:
            missing.append("agent_enabled")

        publication = self.resolve_publication(agent_id)
        publication_id: str | None = None
        public_id: str | None = None
        knowledge_base_id: str | None = None
        billing_ready = False

        if publication is None:
            missing.append("openapi_publication")
        else:
            publication_id = str(publication.get("id") or "") or None
            public_id = str(publication.get("public_id") or "") or None
            knowledge_base_id = (
                str(publication.get("knowledge_base_id") or "") or None
            )
            if str(publication.get("status") or "") != "enabled":
                missing.append("openapi_publication_enabled")
            if not public_id:
                missing.append("openapi_public_id")
            if not knowledge_base_id:
                missing.append("knowledge_base")

            bound_user_id = str(publication.get("bound_user_id") or "")
            if bound_user_id:
                billing_ready = (
                    self._wallet_repository.get_wallet("user", bound_user_id)
                    is not None
                )
            if not billing_ready:
                missing.append("billing_account")

        return DclawConfigurationContext(
            agent_id=agent_id,
            agent_type=agent_type,
            agent_profile_id=profile_id,
            enabled=enabled,
            source_version=source_version,
            publication_id=publication_id,
            openapi_public_id=public_id,
            knowledge_base_id=knowledge_base_id,
            billing_account_configured=billing_ready,
            readiness=Readiness(ready=not missing, missing_items=missing),
        )

    def resolve_publication(self, agent_id: str) -> dict[str, Any] | None:
        """Return the unique authoritative Publication for an Agent."""
        matches = [
            row
            for row in self._publication_repository.list_publications(
                enabled_only=False,
            )
            if str(row.get("target_type") or "") == "agent"
            and str(row.get("target_id") or "") == agent_id
        ]
        return matches[0] if len(matches) == 1 else None


def get_dclaw_configuration_context_service() -> DclawConfigurationContextService:
    return DclawConfigurationContextService()
