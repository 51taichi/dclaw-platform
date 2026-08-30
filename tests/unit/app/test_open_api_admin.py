# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from qwenpaw.app.routers import open_api_admin


class FakeOpenApiRepository:
    def __init__(self) -> None:
        self.publications: dict[str, dict[str, object]] = {}
        self.apps: dict[str, dict[str, object]] = {}
        self.keys: dict[str, dict[str, object]] = {}
        self.invocations = [{"id": "inv-1", "publication_id": "pub-1"}]
        self.list_invocations_calls: list[dict[str, object]] = []
        self.revoked: list[tuple[str, str]] = []
        self.list_publications_enabled_only: list[bool] = []
        self.list_external_apps_owner_user_ids: list[str | None] = []

    def list_publications(self, enabled_only: bool = False):
        self.list_publications_enabled_only.append(enabled_only)
        return list(self.publications.values())

    def get_publication(self, publication_id: str):
        return self.publications.get(publication_id)

    def update_publication_bound_user(
        self,
        publication_id: str,
        owner_user_id: str,
        bound_user_id: str,
    ):
        publication = self.publications.get(publication_id)
        if (
            publication is None
            or str(publication.get("owner_user_id")) != owner_user_id
        ):
            return None
        publication["bound_user_id"] = bound_user_id
        return publication

    def upsert_publication(self, row: dict[str, object]):
        self.publications[str(row["id"])] = dict(row)
        return self.publications[str(row["id"])]

    def list_external_apps(self, owner_user_id: str | None = None):
        self.list_external_apps_owner_user_ids.append(owner_user_id)
        rows = list(self.apps.values())
        if owner_user_id is not None:
            rows = [
                row
                for row in rows
                if row.get("owner_user_id") == owner_user_id
            ]
        return rows

    def get_external_app(self, app_id: str):
        return self.apps.get(app_id)

    def create_external_app(self, row: dict[str, object]):
        self.apps[str(row["id"])] = dict(row)
        return self.apps[str(row["id"])]

    def list_api_keys(
        self, app_id: str | None = None, publication_id: str | None = None
    ):
        rows = list(self.keys.values())
        if app_id is not None:
            rows = [row for row in rows if row.get("app_id") == app_id]
        if publication_id is not None:
            rows = [
                row
                for row in rows
                if row.get("publication_id") == publication_id
            ]
        return rows

    def create_api_key(self, row: dict[str, object]):
        self.keys[str(row["id"])] = dict(row)
        return self.keys[str(row["id"])]

    def update_api_key_status(self, key_id: str, status: str):
        self.revoked.append((key_id, status))
        row = self.keys.get(key_id)
        if row is None:
            return None
        row["status"] = status
        return row

    def list_invocations(
        self,
        publication_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        self.list_invocations_calls.append(
            {
                "publication_id": publication_id,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = self.invocations
        if publication_id is not None:
            rows = [
                row
                for row in rows
                if row.get("publication_id") == publication_id
            ]
        return rows[offset : offset + limit]


def _request(*, role: str = "admin", user_id: str = "admin-1") -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/admin/open-api/publications",
            "raw_path": b"/api/admin/open-api/publications",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8088),
            "scheme": "http",
        },
    )
    request.state.role = role
    request.state.user_id = user_id
    return request


def _patch_repo(
    monkeypatch, repo: FakeOpenApiRepository
) -> FakeOpenApiRepository:
    monkeypatch.setattr(
        open_api_admin, "get_open_api_repository", lambda: repo
    )
    return repo


def _patch_agent(monkeypatch, agent_id: str = "agent-1") -> None:
    monkeypatch.setattr(
        open_api_admin,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={agent_id: SimpleNamespace(enabled=True)}
            ),
        ),
    )


def _patch_users(monkeypatch, *user_ids: int) -> None:
    users = {user_id: {"id": user_id} for user_id in user_ids}
    monkeypatch.setattr(
        open_api_admin,
        "get_user_repository",
        lambda: SimpleNamespace(
            get_user_by_id=lambda user_id: users.get(user_id),
        ),
    )


def _patch_expert_team(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(
        open_api_admin,
        "get_expert_team_template",
        lambda team_id: SimpleNamespace(id=team_id, enabled=enabled),
    )


def test_list_publications_rejects_non_admin_request(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository())

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.list_publications(_request(role="user"))

    assert exc_info.value.status_code == 403


def test_list_publications_only_returns_current_owner(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-1"}
    repo.publications["pub-2"] = {"id": "pub-2", "owner_user_id": "admin-2"}

    rows = open_api_admin.list_publications(_request(user_id="admin-1"))

    assert rows == [{"id": "pub-1", "owner_user_id": "admin-1"}]


def test_create_publication_uses_admin_owner_and_validates_agent(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "agent-1")

    created = open_api_admin.create_publication(
        open_api_admin.PublicationCreateRequest(
            public_id="support_agent",
            target_type="agent",
            target_id="agent-1",
            name="Support Agent",
            description="External support endpoint",
            allowed_scopes=["messages:create", "messages:read"],
        ),
        _request(user_id="admin-42"),
    )

    assert created["owner_user_id"] == "admin-42"
    assert created["target_type"] == "agent"
    assert created["target_id"] == "agent-1"
    assert created["status"] == "enabled"
    assert repo.publications[created["id"]]["owner_user_id"] == "admin-42"


def test_create_publication_honors_disabled_initial_status(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "agent-1")

    created = open_api_admin.create_publication(
        open_api_admin.PublicationCreateRequest(
            public_id="support_agent",
            target_type="agent",
            target_id="agent-1",
            name="Support Agent",
            allowed_scopes=["messages:create"],
            status="disabled",
        ),
        _request(user_id="admin-42"),
    )

    assert created["status"] == "disabled"
    assert repo.publications[created["id"]]["status"] == "disabled"


def test_create_publication_rejects_public_id_owned_by_another_admin(
    monkeypatch,
):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "agent-1")
    repo.publications["pub-existing"] = {
        "id": "pub-existing",
        "public_id": "support_agent",
        "owner_user_id": "admin-other",
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="support_agent",
                target_type="agent",
                target_id="agent-1",
                name="Support Agent",
                allowed_scopes=["messages:create"],
            ),
            _request(user_id="admin-42"),
        )

    assert exc_info.value.status_code == 409
    assert repo.publications["pub-existing"]["owner_user_id"] == "admin-other"


@pytest.mark.parametrize(
    "repo_error",
    [
        "Open API publication owner cannot be changed",
        "Open API publication public_id is already used",
    ],
)
def test_create_publication_maps_repo_public_id_conflict_to_409(
    monkeypatch,
    repo_error,
):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "agent-1")

    def raise_owner_conflict(row: dict[str, object]):
        _ = row
        raise ValueError(repo_error)

    repo.upsert_publication = raise_owner_conflict

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="support_agent",
                target_type="agent",
                target_id="agent-1",
                name="Support Agent",
                allowed_scopes=["messages:create"],
            ),
            _request(user_id="admin-42"),
        )

    assert exc_info.value.status_code == 409


def test_create_publication_rejects_empty_allowed_scopes(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "agent-1")

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="support_agent",
                target_type="agent",
                target_id="agent-1",
                name="Support Agent",
                allowed_scopes=[],
            ),
            _request(user_id="admin-42"),
        )

    assert exc_info.value.status_code == 400


def test_create_publication_rejects_missing_agent(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_agent(monkeypatch, "other-agent")

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="support_agent",
                target_type="agent",
                target_id="agent-1",
                name="Support Agent",
                allowed_scopes=["messages:create"],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 404


def test_create_publication_validates_expert_team(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_expert_team(monkeypatch)

    created = open_api_admin.create_publication(
        open_api_admin.PublicationCreateRequest(
            public_id="team_public",
            target_type="expert_team",
            target_id="team-1",
            name="Team",
            allowed_scopes=["messages:create"],
        ),
        _request(user_id="admin-42"),
    )

    assert created["owner_user_id"] == "admin-42"
    assert created["target_type"] == "expert_team"
    assert created["target_id"] == "team-1"


@pytest.mark.parametrize("enabled", [False])
def test_create_publication_rejects_disabled_expert_team(monkeypatch, enabled):
    _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_expert_team(monkeypatch, enabled=enabled)

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="team_public",
                target_type="expert_team",
                target_id="team-1",
                name="Team",
                allowed_scopes=["messages:create"],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400


def test_create_publication_rejects_missing_expert_team(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository())
    monkeypatch.setattr(
        open_api_admin, "get_expert_team_template", lambda _team_id: None
    )

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_publication(
            open_api_admin.PublicationCreateRequest(
                public_id="team_public",
                target_type="expert_team",
                target_id="team-1",
                name="Team",
                allowed_scopes=["messages:create"],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 404


def test_update_publication_status_uses_existing_publication(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "public_id": "support_agent",
        "target_type": "agent",
        "target_id": "agent-1",
        "owner_user_id": "admin-42",
        "name": "Support Agent",
        "description": "",
        "status": "disabled",
        "allowed_scopes": ["messages:create"],
    }

    updated = open_api_admin.update_publication_status(
        "pub-1",
        open_api_admin.PublicationStatusUpdateRequest(status="disabled"),
        _request(user_id="admin-42"),
    )

    assert updated["id"] == "pub-1"
    assert updated["status"] == "disabled"
    assert repo.publications["pub-1"]["status"] == "disabled"


def test_update_publication_bound_user_changes_only_future_owner(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_users(monkeypatch, 9)
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "public_id": "support_agent",
        "target_type": "agent",
        "target_id": "agent-1",
        "owner_user_id": "admin-42",
        "bound_user_id": "7",
        "knowledge_base_id": "openapi-pub-1",
        "name": "Support Agent",
        "description": "",
        "status": "disabled",
        "allowed_scopes": ["messages:create"],
    }

    updated = open_api_admin.update_publication_bound_user(
        "pub-1",
        open_api_admin.PublicationBoundUserUpdateRequest(bound_user_id=9),
        _request(user_id="admin-42"),
    )

    assert updated["bound_user_id"] == "9"
    assert updated["owner_user_id"] == "admin-42"
    assert updated["knowledge_base_id"] == "openapi-pub-1"
    assert updated["status"] == "disabled"


def test_update_publication_bound_user_rejects_missing_user(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_users(monkeypatch)
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-42",
        "bound_user_id": "7",
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.update_publication_bound_user(
            "pub-1",
            open_api_admin.PublicationBoundUserUpdateRequest(bound_user_id=9),
            _request(user_id="admin-42"),
        )

    assert exc_info.value.status_code == 404
    assert repo.publications["pub-1"]["bound_user_id"] == "7"


def test_update_publication_bound_user_rejects_cross_owner(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    _patch_users(monkeypatch, 9)
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-other",
        "bound_user_id": "7",
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.update_publication_bound_user(
            "pub-1",
            open_api_admin.PublicationBoundUserUpdateRequest(bound_user_id=9),
            _request(user_id="admin-42"),
        )

    assert exc_info.value.status_code == 404
    assert repo.publications["pub-1"]["bound_user_id"] == "7"


def test_create_external_app_uses_admin_owner(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())

    created = open_api_admin.create_external_app(
        open_api_admin.ExternalAppCreateRequest(
            name="CRM",
            ip_allowlist=["203.0.113.7"],
            quota_policy={"daily": 100},
        ),
        _request(user_id="admin-42"),
    )

    assert created["owner_user_id"] == "admin-42"
    assert created["status"] == "enabled"
    assert created["ip_allowlist"] == ["203.0.113.7"]
    assert repo.apps[created["id"]]["quota_policy"] == {"daily": 100}


def test_create_api_key_returns_plaintext_once_and_stores_safe_active_hash(
    monkeypatch,
):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.apps["app-1"] = {"id": "app-1", "status": "enabled"}
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-1",
        "status": "enabled",
        "allowed_scopes": ["messages:create", "messages:read"],
    }
    repo.apps["app-1"]["owner_user_id"] = "admin-1"

    response = open_api_admin.create_api_key(
        open_api_admin.ApiKeyCreateRequest(
            app_id="app-1",
            publication_id="pub-1",
            scopes=["messages:create"],
        ),
        _request(),
    )

    plaintext = response["plaintext_key"]
    key = response["key"]
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert plaintext.startswith("qp_live_")
    assert key["key_hash"] == f"sha256:{digest}"
    assert plaintext not in key["key_hash"]
    assert key["status"] == "active"
    assert key["scopes"] == ["messages:create"]
    assert "plaintext_key" not in key
    assert repo.keys[key["id"]]["key_hash"] == key["key_hash"]


def test_create_api_key_rejects_scope_outside_publication(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.apps["app-1"] = {"id": "app-1", "status": "enabled"}
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-1",
        "status": "enabled",
        "allowed_scopes": ["messages:create"],
    }
    repo.apps["app-1"]["owner_user_id"] = "admin-1"

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_api_key(
            open_api_admin.ApiKeyCreateRequest(
                app_id="app-1",
                publication_id="pub-1",
                scopes=["messages:read"],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("app_status", "publication_status"),
    [
        ("disabled", "enabled"),
        ("enabled", "disabled"),
    ],
)
def test_create_api_key_requires_enabled_app_and_publication(
    monkeypatch,
    app_status,
    publication_status,
):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.apps["app-1"] = {"id": "app-1", "status": app_status}
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-1",
        "status": publication_status,
        "allowed_scopes": ["messages:create"],
    }
    repo.apps["app-1"]["owner_user_id"] = "admin-1"

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_api_key(
            open_api_admin.ApiKeyCreateRequest(
                app_id="app-1",
                publication_id="pub-1",
                scopes=["messages:create"],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400


def test_revoke_api_key_updates_status_to_revoked(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-1"}
    repo.keys["key-1"] = {
        "id": "key-1",
        "status": "active",
        "publication_id": "pub-1",
    }

    revoked = open_api_admin.revoke_api_key("key-1", _request())

    assert repo.revoked == [("key-1", "revoked")]
    assert revoked["status"] == "revoked"


def test_create_api_key_rejects_cross_owner_publication(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.apps["app-1"] = {
        "id": "app-1",
        "owner_user_id": "admin-1",
        "status": "enabled",
    }
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-2",
        "status": "enabled",
        "allowed_scopes": ["messages:create"],
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_api_key(
            open_api_admin.ApiKeyCreateRequest(
                app_id="app-1",
                publication_id="pub-1",
                scopes=["messages:create"],
            ),
            _request(user_id="admin-1"),
        )

    assert exc_info.value.status_code == 404


def test_create_api_key_rejects_empty_scopes(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.apps["app-1"] = {
        "id": "app-1",
        "owner_user_id": "admin-1",
        "status": "enabled",
    }
    repo.publications["pub-1"] = {
        "id": "pub-1",
        "owner_user_id": "admin-1",
        "status": "enabled",
        "allowed_scopes": ["messages:create"],
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.create_api_key(
            open_api_admin.ApiKeyCreateRequest(
                app_id="app-1",
                publication_id="pub-1",
                scopes=[],
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400


def test_revoke_api_key_rejects_cross_owner_key(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-2"}
    repo.keys["key-1"] = {
        "id": "key-1",
        "status": "active",
        "publication_id": "pub-1",
    }

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.revoke_api_key("key-1", _request(user_id="admin-1"))

    assert exc_info.value.status_code == 404


def test_list_invocations_passes_filters_to_repo(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-1"}

    rows = open_api_admin.list_invocations(
        _request(),
        publication_id="pub-1",
        limit=25,
        offset=50,
    )

    assert rows == []
    assert repo.list_invocations_calls == [
        {"publication_id": "pub-1", "limit": 25, "offset": 50},
    ]


def test_list_invocations_rejects_cross_owner_publication(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-2"}

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin.list_invocations(
            _request(user_id="admin-1"),
            publication_id="pub-1",
        )

    assert exc_info.value.status_code == 404


def test_list_invocations_filters_owner_before_paginating(monkeypatch):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-1"}
    repo.publications["pub-2"] = {"id": "pub-2", "owner_user_id": "admin-2"}
    repo.invocations = [
        {
            "id": "other-new",
            "publication_id": "pub-2",
            "created_at": "2026-07-02T10:00:00",
        },
        {
            "id": "own-new",
            "publication_id": "pub-1",
            "created_at": "2026-07-02T09:00:00",
        },
        {
            "id": "own-old",
            "publication_id": "pub-1",
            "created_at": "2026-07-02T08:00:00",
        },
    ]

    rows = open_api_admin.list_invocations(
        _request(user_id="admin-1"),
        limit=1,
        offset=0,
    )

    assert rows == [
        {
            "id": "own-new",
            "publication_id": "pub-1",
            "created_at": "2026-07-02T09:00:00",
        },
    ]
    assert {
        "publication_id": None,
        "limit": 1,
        "offset": 0,
    } not in repo.list_invocations_calls


def test_list_api_keys_only_returns_current_owner_publication_keys(
    monkeypatch,
):
    repo = _patch_repo(monkeypatch, FakeOpenApiRepository())
    repo.publications["pub-1"] = {"id": "pub-1", "owner_user_id": "admin-1"}
    repo.publications["pub-2"] = {"id": "pub-2", "owner_user_id": "admin-2"}
    repo.keys["key-1"] = {"id": "key-1", "publication_id": "pub-1"}
    repo.keys["key-2"] = {"id": "key-2", "publication_id": "pub-2"}

    rows = open_api_admin.list_api_keys(_request(user_id="admin-1"))

    assert rows == [{"id": "key-1", "publication_id": "pub-1"}]


def test_open_api_admin_router_is_mounted_under_admin_prefix():
    from fastapi import FastAPI

    from qwenpaw.app.routers import router

    effective_app = FastAPI()
    effective_app.include_router(router, prefix="/api")
    api_paths = {
        path for path in effective_app.openapi()["paths"] if "open-api" in path
    }

    assert "/api/admin/open-api/publications" in api_paths
    assert not any(path.startswith("/api/user/open-api") for path in api_paths)
