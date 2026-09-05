# -*- coding: utf-8 -*-
"""API routers."""

from fastapi import APIRouter, Depends
from ..guards import require_admin, require_user
from ..sealed_agents.policy import (
    deny_sealed_asset_access,
    deny_sealed_skill_asset_access,
)

from .agents import router as agents_router
from .config import router as config_router
from .local_models import router as local_models_router
from .providers import router as providers_router
from .skills import router as skills_router
from .skills_stream import router as skills_stream_router
from .workspace import router as workspace_router
from .envs import router as envs_router
from .mcp import router as mcp_router
from .mcp_oauth import router as mcp_oauth_router
from .tools import router as tools_router
from ..crons.api import router as cron_router
from ..runner.api import router as runner_router
from .console import router as console_router
from .token_usage import router as token_usage_router
from .agent_stats import router as agent_stats_router
from .auth import router as auth_router
from .messages import router as messages_router
from .audit import router as audit_router
from .files import router as files_router
from .settings import router as settings_router
from .plugins import router as plugins_router
from .backup import router as backup_router
from .performance import router as performance_router
from .plan import router as plan_router
from .runtime_events import router as runtime_events_router
from .user_config import router as user_config_router
from .admin_users import router as admin_users_router
from .object_storage import router as object_storage_router
from .web_search import router as web_search_router
from .open_api_admin import router as open_api_admin_router
from .open_api import router as open_api_router
from .open_api_knowledge import router as open_api_knowledge_router
from .sealed_agents import router as sealed_agents_router
from .super_expert_platform import router as super_expert_platform_router
from .aigc_studio import public_router as public_aigc_studio_router
from .aigc_studio import router as aigc_studio_router
from .aigc_model_policy import router as aigc_model_policy_router
from .desktop import router as desktop_router
from .mobile import router as mobile_router
from .billing import admin_router as admin_billing_router
from .billing import user_router as user_billing_router
from .expert_teams import (
    admin_router as admin_expert_teams_router,
    user_router as user_expert_teams_router,
)
from .knowledge import admin_router as admin_knowledge_router
from .mindspace_cloud import (
    admin_router as admin_mindspace_cloud_router,
    public_router as public_mindspace_cloud_router,
    user_router as user_mindspace_cloud_router,
)


router = APIRouter()

# Auth and providers routers stay at root
router.include_router(auth_router)
router.include_router(providers_router)
router.include_router(public_mindspace_cloud_router)
router.include_router(desktop_router)
router.include_router(public_aigc_studio_router)
router.include_router(settings_router)
router.include_router(open_api_router)
router.include_router(
    open_api_knowledge_router,
    dependencies=[Depends(require_user)],
)

# ── User-facing APIs ──────────────────────────────────────────
user_deps = [Depends(require_user)]
user_api_router = APIRouter(prefix="/user", dependencies=user_deps)

user_api_router.include_router(agents_router)
user_api_router.include_router(console_router)
user_api_router.include_router(runner_router)
user_api_router.include_router(messages_router)
asset_deps = [Depends(deny_sealed_asset_access)]

user_api_router.include_router(workspace_router, dependencies=asset_deps)
user_api_router.include_router(files_router, dependencies=asset_deps)
user_api_router.include_router(settings_router)
user_api_router.include_router(
    skills_router,
    dependencies=[Depends(deny_sealed_skill_asset_access)],
)
user_api_router.include_router(skills_stream_router, dependencies=asset_deps)
user_api_router.include_router(tools_router, dependencies=asset_deps)
user_api_router.include_router(plan_router, dependencies=asset_deps)
user_api_router.include_router(runtime_events_router)
user_api_router.include_router(user_config_router)
user_api_router.include_router(cron_router, dependencies=asset_deps)
user_api_router.include_router(mcp_oauth_router)
user_api_router.include_router(aigc_studio_router)
user_api_router.include_router(user_expert_teams_router)
user_api_router.include_router(user_mindspace_cloud_router)
user_api_router.include_router(mobile_router)
user_api_router.include_router(user_billing_router)
user_api_router.include_router(super_expert_platform_router)


router.include_router(user_api_router)

# ── Admin-only APIs ───────────────────────────────────────────
admin_deps = [Depends(require_admin)]
admin_api_router = APIRouter(prefix="/admin", dependencies=admin_deps)

admin_api_router.include_router(config_router, dependencies=asset_deps)
admin_api_router.include_router(cron_router, dependencies=asset_deps)
admin_api_router.include_router(local_models_router)
admin_api_router.include_router(mcp_router, dependencies=asset_deps)

admin_api_router.include_router(envs_router)
admin_api_router.include_router(audit_router)
admin_api_router.include_router(token_usage_router)
admin_api_router.include_router(agent_stats_router)
admin_api_router.include_router(plugins_router, dependencies=asset_deps)
admin_api_router.include_router(backup_router)
admin_api_router.include_router(performance_router)
admin_api_router.include_router(admin_users_router)
admin_api_router.include_router(object_storage_router)
admin_api_router.include_router(web_search_router)
admin_api_router.include_router(admin_expert_teams_router)
admin_api_router.include_router(admin_mindspace_cloud_router)
admin_api_router.include_router(admin_knowledge_router)
admin_api_router.include_router(open_api_admin_router)
admin_api_router.include_router(sealed_agents_router)
admin_api_router.include_router(admin_billing_router)
admin_api_router.include_router(aigc_model_policy_router)


router.include_router(admin_api_router)
router.include_router(envs_router, dependencies=admin_deps)


def create_agent_scoped_router() -> APIRouter:
    """Create agent-scoped router that wraps existing routers.

    Returns:
        APIRouter with all routers mounted under /agents/{agentId}/
    """
    from .agent_scoped import create_agent_scoped_router as _create

    return _create()


__all__ = ["router", "create_agent_scoped_router"]
