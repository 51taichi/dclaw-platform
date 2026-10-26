from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from qwenpaw.app.routers import sealed_agents as router_module
from qwenpaw.app.sealed_agents.models import (
    RuntimeValidationRecord,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.config.config import Config, OrchestrationConfig
from qwenpaw.app.super_experts.grants import (
    SuperExpertGrant,
    SuperExpertGrantPreview,
)
from qwenpaw.plugins.registry import PluginRegistry


def _request(role="admin"):
    return SimpleNamespace(state=SimpleNamespace(role=role, user_id="1"))


def _record():
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
        runtime_adapter="standard",
        runtime_contract_version="1",
        runtime_validation=RuntimeValidationRecord(
            status="valid",
            adapter="standard",
            contract_version="1",
        ),
    )
    return SealedAgentRecord(
        agent_id="luyu",
        name="陆羽",
        description="茶文化专家",
        active_release_id="rel-1",
        releases=[release],
    )


def _super_expert_record():
    record = _record()
    release = record.active_release.model_copy(
        update={"package_type": "super_expert"},
    )
    return record.model_copy(update={"releases": [release]})


def _write_active_agent_config(tmp_path, payload):
    config_path = (
        tmp_path
        / "sealed_agents"
        / "runtime_workspaces"
        / "luyu"
        / "rel-1"
        / "agent"
        / "agent.json"
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def test_admin_list_returns_operational_metadata_without_asset_paths(
    monkeypatch,
):
    class Service:
        def list_agents(self):
            return [_record()]

    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )

    response = router_module.list_sealed_agents(_request())

    assert response[0]["agent_id"] == "luyu"
    assert response[0]["version"] == "1.0.0"
    assert response[0]["runtime"] == {
        "adapter": "standard",
        "contract_version": "1",
    }
    serialized = str(response)
    assert "workspace" not in serialized
    assert "AGENTS.md" not in serialized
    assert "path" not in serialized


def test_agent_loop_harness_declaration_is_nullable_and_explicit():
    assert OrchestrationConfig().agent_loop_enabled is None
    assert (
        OrchestrationConfig(agent_loop_enabled=True).agent_loop_enabled is True
    )


def test_admin_list_projects_active_super_expert_harness_config(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(router_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        PluginRegistry,
        "sealed_package_type_supports",
        lambda _self, package_type, feature: (
            package_type == "super_expert" and feature == "harness_status"
        ),
    )
    _write_active_agent_config(
        tmp_path,
        {
            "id": "luyu",
            "name": "陆羽",
            "tools": {
                "builtin_tools": {
                    "read_agent_skill": {
                        "name": "read_agent_skill",
                        "enabled": False,
                    },
                },
            },
            "orchestration": {
                "agent_loop_enabled": True,
            },
        },
    )

    response = router_module._operational_dto(_super_expert_record())

    assert response["harness_status"] == {
        "skill_reader_enabled": False,
        "agent_loop_enabled": True,
    }
    serialized = str(response)
    assert "agent.json" not in serialized
    assert "runtime_workspaces" not in serialized


def test_admin_list_marks_missing_super_expert_harness_config_undeclared(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(router_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        PluginRegistry,
        "sealed_package_type_supports",
        lambda _self, package_type, feature: (
            package_type == "super_expert" and feature == "harness_status"
        ),
    )
    _write_active_agent_config(tmp_path, {"id": "luyu", "name": "陆羽"})

    response = router_module._operational_dto(_super_expert_record())

    assert response["harness_status"] == {
        "skill_reader_enabled": None,
        "agent_loop_enabled": None,
    }


def test_admin_list_omits_harness_status_for_ordinary_sealed_agent(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(router_module, "WORKING_DIR", tmp_path)
    _write_active_agent_config(
        tmp_path,
        {
            "id": "luyu",
            "name": "陆羽",
            "orchestration": {"agent_loop_enabled": True},
        },
    )

    response = router_module._operational_dto(_record())

    assert "harness_status" not in response


def test_invalid_active_release_is_reported_unavailable_without_internal_path():
    record = _record()
    invalid = record.active_release.model_copy(
        update={
            "runtime_validation": RuntimeValidationRecord(
                status="invalid",
                adapter="standard",
                contract_version="1",
                error_code="invalid_agent_profile",
            ),
        },
    )
    record = record.model_copy(update={"releases": [invalid]})

    response = router_module._operational_dto(record)

    assert response["availability"] == "unavailable"
    assert response["runtime_validation"]["error_code"] == (
        "invalid_agent_profile"
    )
    serialized = str(response)
    assert "/private" not in serialized
    assert "agent.json" not in serialized


def test_non_admin_cannot_use_release_routes():
    with pytest.raises(HTTPException) as exc_info:
        router_module.list_sealed_agents(_request(role="user"))

    assert exc_info.value.status_code == 403


def test_official_super_expert_root_is_separate_from_other_trusted_signers(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(router_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(router_module, "_service", None)

    def load(_path):
        return {"ordinary": object()}

    monkeypatch.setattr(router_module, "load_trusted_signers", load)
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: object(),
    )
    handler = SimpleNamespace(
        trusted_signers={"official": object()},
        trust_store=SimpleNamespace(
            official_signer_ids={"official"},
        ),
    )
    monkeypatch.setattr(
        PluginRegistry,
        "get_sealed_package_types",
        lambda _self: {
            "super_expert": SimpleNamespace(handler=handler),
        },
    )

    service = router_module.get_sealed_agent_service()

    assert set(service._current_trusted_signers()) == {"ordinary", "official"}
    assert handler.trust_store.official_signer_ids == {"official"}
    router_module._service = None


def test_router_has_no_package_or_content_download_route():
    routes = [
        (route.path, frozenset(route.methods or set()))
        for route in router_module.router.routes
    ]

    assert any(
        path == "/sealed-agents/releases" and "POST" in methods
        for path, methods in routes
    )
    assert all(
        not (
            "GET" in methods
            and any(
                word in path
                for word in ("download", "content", "files", "package")
            )
        )
        for path, methods in routes
    )


@pytest.mark.asyncio
async def test_upload_returns_identity_and_complete_package_declaration(
    monkeypatch,
):
    release = _record().active_release.model_copy(
        update={
            "package_type": "super_expert",
            "capability_digest": "sha256:" + "b" * 64,
            "declared_capabilities": (("workspace.turn.orchestrate/1", "1"),),
        },
    )

    class Service:
        def install(self, data):
            assert data == b"signed-package"
            return release

        def list_agents(self):
            return [
                _record().model_copy(
                    update={
                        "agent_id": "generic-super-expert",
                        "releases": [release],
                    },
                ),
            ]

    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    response = await router_module.upload_sealed_agent_release(
        _request(),
        UploadFile(filename="expert.zip", file=BytesIO(b"signed-package")),
    )

    assert response["agent_id"] == "generic-super-expert"
    assert response["package_type"] == "super_expert"
    assert response["capability_digest"] == "sha256:" + "b" * 64
    assert response["declared_capabilities"] == [
        ["workspace.turn.orchestrate/1", "1"],
    ]


def test_grant_routes_expose_complete_preview_and_accept_all_only(monkeypatch):
    capabilities = (
        ("workspace.turn.orchestrate/1", "1"),
        ("agent.execute", "1"),
    )
    preview = SuperExpertGrantPreview(
        preview_id="preview-1",
        tenant_id="local",
        agent_id="luyu",
        release_id="rel-1",
        package_digest="sha256:" + "a" * 64,
        package_version="1.0.0",
        capability_digest="sha256:" + "b" * 64,
        capabilities=capabilities,
    )

    class Service:
        def preview_grant(self, agent_id, release_id, *, tenant_id):
            assert (agent_id, release_id, tenant_id) == (
                "luyu",
                "rel-1",
                "local",
            )
            return preview

        def grant_installation(
            self,
            agent_id,
            release_id,
            *,
            tenant_id,
            administrator_id,
        ):
            return SuperExpertGrant(
                installation_id="installation-1",
                tenant_id=tenant_id,
                agent_id=agent_id,
                release_id=release_id,
                package_digest=preview.package_digest,
                package_version=preview.package_version,
                capability_digest=preview.capability_digest,
                capabilities=preview.capabilities,
                administrator_id=administrator_id,
            )

    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )

    preview_response = router_module.preview_super_expert_grant(
        "luyu",
        "rel-1",
        _request(),
    )
    grant_response = router_module.accept_super_expert_grant(
        "luyu",
        "rel-1",
        _request(),
    )

    assert preview_response["capabilities"] == [
        list(item) for item in capabilities
    ]
    assert grant_response["capabilities"] == [
        list(item) for item in capabilities
    ]
    route_paths = {route.path for route in router_module.router.routes}
    assert (
        "/sealed-agents/{agent_id}/releases/{release_id}/grant" in route_paths
    )
    assert all("capability" not in path for path in route_paths)


@pytest.mark.asyncio
async def test_activation_registers_private_runtime_only_after_preload_succeeds(
    monkeypatch,
    tmp_path,
):
    record = _record()
    release_root = tmp_path / "releases/luyu/rel-1"
    (release_root / "agent").mkdir(parents=True)
    (release_root / "agent/agent.json").write_text(
        '{"id":"luyu","name":"陆羽"}',
    )

    class Service:
        async def validate_release_runtime(self, agent_id, release_id):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )

        def release_root(self, agent_id, release_id):
            return release_root

        def prepare_runtime_workspace(self, agent_id, release_id):
            return release_root / "agent"

        def get_agent(self, agent_id):
            return record

        def activate(self, agent_id, release_id, *, tenant_id="local"):
            assert tenant_id == "local"
            return record

    class Manager:
        async def preload_agent(self, agent_id):
            assert agent_id == "luyu"
            return True

        def is_agent_loaded(self, agent_id):
            return False

    config = Config()
    saved = []
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(
        router_module,
        "save_config",
        lambda value: saved.append(value),
    )
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=Manager()),
    )

    response = await router_module.activate_sealed_agent_release(
        "luyu",
        "rel-1",
        request,
    )

    assert response["agent_id"] == "luyu"
    assert config.agents.profiles["luyu"].workspace_dir == str(
        release_root / "agent",
    )
    assert saved


@pytest.mark.asyncio
async def test_activation_failure_restores_previous_profile_and_runtime(
    monkeypatch,
    tmp_path,
):
    release_root = tmp_path / "releases/luyu/rel-1"
    (release_root / "agent").mkdir(parents=True)
    (release_root / "agent/agent.json").write_text(
        '{"id":"luyu","name":"陆羽"}',
    )
    activated = []
    restored = []
    previous_record = _record()

    class Service:
        async def validate_release_runtime(self, agent_id, release_id):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )

        def release_root(self, agent_id, release_id):
            return release_root

        def prepare_runtime_workspace(self, agent_id, release_id):
            return release_root / "agent"

        def get_agent(self, agent_id):
            return previous_record

        def activate(self, agent_id, release_id, *, tenant_id="local"):
            assert tenant_id == "local"
            activated.append((agent_id, release_id))
            return _record()

        def restore_agent_record(self, record):
            restored.append(record)
            return record

    class Manager:
        def __init__(self):
            self.reload_calls = []

        def is_agent_loaded(self, agent_id):
            return True

        async def reload_agent(self, agent_id):
            self.reload_calls.append(agent_id)
            return len(self.reload_calls) > 1

    from qwenpaw.config.config import AgentProfileRef

    previous = AgentProfileRef(
        id="luyu",
        workspace_dir="/existing/luyu",
        enabled=True,
    )
    config = Config()
    config.agents.profiles["luyu"] = previous
    manager = Manager()
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda _value: None)
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=manager),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.activate_sealed_agent_release(
            "luyu",
            "rel-1",
            request,
        )

    assert exc_info.value.status_code == 400
    assert config.agents.profiles["luyu"] == previous
    assert manager.reload_calls == ["luyu", "luyu"]
    assert activated == [("luyu", "rel-1")]
    assert restored == [previous_record]


@pytest.mark.asyncio
async def test_first_activation_failure_stops_partially_loaded_runtime(
    monkeypatch,
    tmp_path,
):
    release_root = tmp_path / "releases/luyu/rel-1"
    (release_root / "agent").mkdir(parents=True)
    (release_root / "agent/agent.json").write_text(
        '{"id":"luyu","name":"陆羽"}',
    )

    previous_record = _record()
    restored = []

    class Service:
        async def validate_release_runtime(self, agent_id, release_id):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )

        def release_root(self, agent_id, release_id):
            return release_root

        def prepare_runtime_workspace(self, agent_id, release_id):
            return release_root / "agent"

        def get_agent(self, agent_id):
            return previous_record

        def activate(self, agent_id, release_id, *, tenant_id="local"):
            return _record()

        def restore_agent_record(self, record):
            restored.append(record)
            return record

    class Manager:
        def __init__(self):
            self.loaded_checks = 0
            self.stopped = []

        def is_agent_loaded(self, agent_id):
            self.loaded_checks += 1
            return self.loaded_checks > 1

        async def preload_agent(self, agent_id):
            return False

        async def stop_agent(self, agent_id):
            self.stopped.append(agent_id)

    config = Config()
    manager = Manager()
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda _value: None)
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=manager),
    )

    with pytest.raises(HTTPException):
        await router_module.activate_sealed_agent_release(
            "luyu",
            "rel-1",
            request,
        )

    assert "luyu" not in config.agents.profiles
    assert manager.stopped == ["luyu"]
    assert restored == [previous_record]


@pytest.mark.asyncio
async def test_activation_requests_for_same_agent_are_serialized(monkeypatch):
    active = 0
    max_active = 0

    async def activate_locked(agent_id, release_id, request):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await __import__("asyncio").sleep(0)
        active -= 1
        return {"release_id": release_id}

    monkeypatch.setattr(
        router_module,
        "_activate_sealed_agent_release_locked",
        activate_locked,
    )
    router_module._activation_locks.clear()
    request = _request()

    results = await __import__("asyncio").gather(
        router_module.activate_sealed_agent_release("luyu", "one", request),
        router_module.activate_sealed_agent_release("luyu", "two", request),
    )

    assert max_active == 1
    assert results == [{"release_id": "one"}, {"release_id": "two"}]


@pytest.mark.asyncio
async def test_disable_stops_loaded_runtime_and_config(monkeypatch):
    record = _record().model_copy(update={"enabled": False})

    class Service:
        def disable(self, agent_id):
            return record

    stopped = []

    class Manager:
        def is_agent_loaded(self, agent_id):
            return True

        async def stop_agent(self, agent_id):
            stopped.append(agent_id)

    config = Config()
    from qwenpaw.config.config import AgentProfileRef

    config.agents.profiles["luyu"] = AgentProfileRef(
        id="luyu",
        workspace_dir="/private/release",
        enabled=True,
    )
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda _value: None)
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=Manager()),
    )

    response = await router_module.disable_sealed_agent("luyu", request)

    assert response["enabled"] is False
    assert config.agents.profiles["luyu"].enabled is False
    assert stopped == ["luyu"]


@pytest.mark.asyncio
async def test_avatar_upload_persists_normalized_image(monkeypatch, tmp_path):
    from PIL import Image
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_record())
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    data = BytesIO()
    Image.new("RGB", (16, 16), "gold").save(data, format="PNG")
    data.seek(0)
    result = await router_module.upload_sealed_agent_avatar(
        "luyu",
        _request(),
        UploadFile(data, filename="avatar.png"),
    )
    assert result["avatar"].startswith("data:image/png;base64,")
    assert registry.get_agent("luyu").avatar == result["avatar"]


@pytest.mark.asyncio
async def test_avatar_upload_rejects_non_admin_and_invalid_image(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_record())
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    for role, status in [("user", 403), ("admin", 400)]:
        with pytest.raises(HTTPException) as error:
            await router_module.upload_sealed_agent_avatar(
                "luyu",
                _request(role),
                UploadFile(BytesIO(b"not an image")),
            )
        assert error.value.status_code == status


@pytest.mark.asyncio
async def test_avatar_upload_rejects_missing_expert_and_oversized_upload(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    with pytest.raises(HTTPException) as missing:
        await router_module.upload_sealed_agent_avatar(
            "unknown",
            _request(),
            UploadFile(BytesIO(b"image")),
        )
    assert missing.value.status_code == 404
    registry.upsert_agent(_record())
    with pytest.raises(HTTPException) as oversized:
        await router_module.upload_sealed_agent_avatar(
            "luyu",
            _request(),
            UploadFile(BytesIO(b"x" * (2 * 1024 * 1024 + 1))),
        )
    assert oversized.value.status_code == 400
    assert registry.get_agent("luyu").avatar is None


@pytest.mark.asyncio
async def test_banner_upload_is_independent_and_keeps_image_proportions(
    monkeypatch,
    tmp_path,
):
    import base64
    from PIL import Image
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(
        _record().model_copy(update={"avatar": "existing-avatar"}),
    )
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    data = BytesIO()
    Image.new("RGB", (1800, 150), "blue").save(data, format="PNG")
    data.seek(0)
    result = await router_module.upload_sealed_agent_banner(
        "luyu",
        _request(),
        UploadFile(data),
    )
    assert result["avatar"] == "existing-avatar"
    with Image.open(
        BytesIO(base64.b64decode(result["banner_image"].split(",", 1)[1])),
    ) as image:
        assert image.size == (1800, 150)
    assert registry.get_agent("luyu").banner_image == result["banner_image"]


@pytest.mark.asyncio
async def test_banner_upload_rejects_invalid_image_and_non_admin(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_record())
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    for role, code in [("user", 403), ("admin", 400)]:
        with pytest.raises(HTTPException) as error:
            await router_module.upload_sealed_agent_banner(
                "luyu",
                _request(role),
                UploadFile(BytesIO(b"bad")),
            )
        assert error.value.status_code == code


@pytest.mark.asyncio
async def test_banner_size_limit_preserves_existing_media(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry

    registry = SealedAgentRegistry(tmp_path)
    original = _record().model_copy(
        update={"avatar": "avatar", "banner_image": "banner"},
    )
    registry.upsert_agent(original)
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    with pytest.raises(HTTPException) as error:
        await router_module.upload_sealed_agent_banner(
            "luyu",
            _request(),
            UploadFile(BytesIO(b"x" * (5 * 1024 * 1024 + 1))),
        )
    assert error.value.status_code == 400
    assert registry.get_agent("luyu") == original


@pytest.mark.asyncio
async def test_delete_requires_admin():
    with pytest.raises(HTTPException) as error:
        await router_module.delete_sealed_agent("luyu", _request("user"))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_removes_profile_and_stops_runtime(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from qwenpaw.config.config import AgentProfileRef

    config = Config()
    config.agents.profiles["luyu"] = AgentProfileRef(
        id="luyu",
        workspace_dir="/tmp/luyu",
        enabled=False,
    )
    service = Mock()
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: service,
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    save = Mock()
    monkeypatch.setattr(router_module, "save_config", save)
    manager = SimpleNamespace(
        is_agent_loaded=lambda _: True,
        stop_agent=AsyncMock(),
    )
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=manager),
    )
    result = await router_module.delete_sealed_agent("luyu", request)
    assert result["deleted"]
    assert "luyu" not in config.agents.profiles
    service.delete.assert_called_once_with("luyu", actor="1")
    manager.stop_agent.assert_awaited_once_with("luyu")
    save.assert_called_once_with(config)
