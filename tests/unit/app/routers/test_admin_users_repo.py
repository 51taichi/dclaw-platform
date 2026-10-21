# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from fastapi import HTTPException

from qwenpaw.app.auth import verify_password
from qwenpaw.app.billing.models import WalletBalance
from qwenpaw.app.routers import admin_users


class FakeUserRepository:
    def __init__(self):
        self.users = {
            1: {
                "id": 1,
                "username": "admin",
                "role": "admin",
                "created_at": "2026-06-08T10:00:00",
                "password_hash": "old-hash",
                "password_salt": "old-salt",
                "display_name": None,
                "phone_number_e164": None,
                "ai_customer_service_url": None,
                "scene_tabs_json": None,
            }
        }
        self.next_id = 2
        self.deleted = []

    def list_users(self):
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "created_at": row["created_at"],
                "display_name": row.get("display_name"),
                "phone_number_e164": row.get("phone_number_e164"),
                "ai_customer_service_url": row.get("ai_customer_service_url"),
                "scene_tabs_json": row.get("scene_tabs_json"),
            }
            for row in self.users.values()
        ]

    def get_user_by_username(self, username):
        return next(
            (
                row
                for row in self.users.values()
                if row["username"] == username
            ),
            None,
        )

    def get_user_by_id(self, user_id):
        return self.users.get(user_id)

    def count_admins(self):
        return sum(1 for row in self.users.values() if row["role"] == "admin")

    def create_user(
        self, *, username, password_hash, password_salt, role,
        display_name=None, phone_number_e164=None,
        ai_customer_service_url=None,
        scene_tabs_json=None,
    ):
        user_id = self.next_id
        self.next_id += 1
        row = {
            "id": user_id,
            "username": username,
            "role": role,
            "created_at": f"2026-06-08T10:00:0{user_id}",
            "password_hash": password_hash,
            "password_salt": password_salt,
            "display_name": display_name,
            "phone_number_e164": phone_number_e164,
            "ai_customer_service_url": ai_customer_service_url,
            "scene_tabs_json": scene_tabs_json,
        }
        self.users[user_id] = row
        return row

    def update_user_password(self, user_id, password_hash, password_salt):
        row = self.users.get(user_id)
        if row is None:
            return False
        row["password_hash"] = password_hash
        row["password_salt"] = password_salt
        return True

    def update_user_ai_customer_service_url(self, user_id, url):
        row = self.users.get(user_id)
        if row is None:
            return None
        row["ai_customer_service_url"] = url
        row["scene_tabs_json"] = None
        return row

    def update_user_scene_tabs(self, user_id, scene_tabs_json):
        row = self.users.get(user_id)
        if row is None:
            return None
        row["scene_tabs_json"] = scene_tabs_json
        row["ai_customer_service_url"] = None
        return row

    def delete_user_cascade(self, user_id):
        if user_id not in self.users:
            return False
        self.deleted.append(user_id)
        del self.users[user_id]
        return True


class FakeWalletService:
    def __init__(self):
        self.wallet_users = []

    def get_or_create_personal_wallet(self, user_id):
        self.wallet_users.append(user_id)
        return WalletBalance(0, 0, 0, 0, 0)


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeUserRepository()
    monkeypatch.setattr(admin_users, "get_user_repository", lambda: repo)
    return repo


@pytest.fixture
def fake_wallet_service(monkeypatch):
    service = FakeWalletService()
    monkeypatch.setattr(admin_users, "get_wallet_service", lambda: service)
    return service


@pytest.mark.asyncio
async def test_admin_user_routes_use_user_repository(
    fake_repo,
    fake_wallet_service,
):
    listed = await admin_users.list_users()

    assert [user.username for user in listed] == ["admin"]

    created = await admin_users.create_user(
        admin_users.CreateUserRequest(
            username="alice",
            password="new-password",
            role="user",
        )
    )
    assert created.username == "alice"
    assert created.display_name is None
    assert created.phone_number is None
    assert created.ai_customer_service_url is None
    assert created.scene_tabs == []
    stored = fake_repo.get_user_by_username("alice")
    assert verify_password(
        "new-password",
        stored["password_hash"],
        stored["password_salt"],
    )
    assert fake_wallet_service.wallet_users == [created.id]

    result = await admin_users.reset_password(
        created.id,
        admin_users.ResetPasswordRequest(new_password="rotated-password"),
    )
    assert result == {"success": True}
    stored = fake_repo.get_user_by_id(created.id)
    assert verify_password(
        "rotated-password",
        stored["password_hash"],
        stored["password_salt"],
    )

    assert await admin_users.delete_user(created.id) == {"success": True}
    assert fake_repo.deleted == [created.id]


@pytest.mark.asyncio
async def test_admin_create_user_normalizes_identity(fake_repo, fake_wallet_service):
    created = await admin_users.create_user(admin_users.CreateUserRequest(
        username="alice", password="password", role="user",
        display_name="  Alice Chen  ", phone_number="13800138000",
    ))

    assert created.display_name == "Alice Chen"
    assert created.phone_number == "+8613800138000"
    stored = fake_repo.get_user_by_username("alice")
    assert stored["display_name"] == "Alice Chen"
    assert stored["phone_number_e164"] == "+8613800138000"


@pytest.mark.asyncio
async def test_admin_user_routes_manage_ai_customer_service_url(
    fake_repo,
    fake_wallet_service,
):
    created = await admin_users.create_user(admin_users.CreateUserRequest(
        username="alice",
        password="password",
        ai_customer_service_url=(
            "  https://service.example.com/console/?workspace=alice  "
        ),
    ))

    assert created.ai_customer_service_url == (
        "https://service.example.com/console/?workspace=alice"
    )

    updated = await admin_users.update_ai_customer_service(
        created.id,
        admin_users.AiCustomerServiceRequest(
            url="https://service.example.com/console/?workspace=updated",
        ),
    )
    assert updated.ai_customer_service_url == (
        "https://service.example.com/console/?workspace=updated"
    )

    removed = await admin_users.update_ai_customer_service(
        created.id,
        admin_users.AiCustomerServiceRequest(url=None),
    )
    assert removed.ai_customer_service_url is None


@pytest.mark.asyncio
async def test_admin_user_routes_manage_multiple_scene_tabs(
    fake_repo,
    fake_wallet_service,
):
    created = await admin_users.create_user(admin_users.CreateUserRequest(
        username="alice",
        password="password",
        scene_tabs=[
            admin_users.SceneTabInput(
                title=" AI客服 ",
                url=" https://service.example.com/alice ",
            ),
            admin_users.SceneTabInput(
                title="Agent官网",
                url="https://site.example.com/alice",
            ),
        ],
    ))

    assert [scene.model_dump() for scene in created.scene_tabs] == [
        {"title": "AI客服", "url": "https://service.example.com/alice"},
        {"title": "Agent官网", "url": "https://site.example.com/alice"},
    ]
    assert created.ai_customer_service_url is None

    updated = await admin_users.update_scene_tabs(
        created.id,
        admin_users.SceneTabsRequest(scene_tabs=[]),
    )
    assert updated.scene_tabs == []


@pytest.mark.asyncio
async def test_admin_user_routes_reject_unsafe_ai_customer_service_url(
    fake_repo,
    fake_wallet_service,
):
    with pytest.raises(HTTPException) as error:
        await admin_users.create_user(admin_users.CreateUserRequest(
            username="alice",
            password="password",
            ai_customer_service_url="http://service.example.com/console/",
        ))

    assert error.value.status_code == 422
    assert fake_repo.get_user_by_username("alice") is None
    assert fake_wallet_service.wallet_users == []


@pytest.mark.asyncio
async def test_admin_create_user_rejects_invalid_phone_before_side_effects(
    fake_repo, fake_wallet_service,
):
    with pytest.raises(HTTPException) as error:
        await admin_users.create_user(admin_users.CreateUserRequest(
            username="alice", password="password", phone_number="12345",
        ))

    assert error.value.status_code == 422
    assert fake_repo.get_user_by_username("alice") is None
    assert fake_wallet_service.wallet_users == []


def test_admin_user_router_does_not_expose_a_signup_trial_path():
    paths = {route.path for route in admin_users.router.routes}

    assert "/users/{user_id}/signup-trial" not in paths


@pytest.mark.asyncio
async def test_admin_user_routes_prevent_duplicate_and_last_admin_delete(
    fake_repo,
):
    with pytest.raises(HTTPException) as duplicate:
        await admin_users.create_user(
            admin_users.CreateUserRequest(
                username="admin",
                password="password",
                role="admin",
            )
        )
    assert duplicate.value.status_code == 409

    with pytest.raises(HTTPException) as last_admin:
        await admin_users.delete_user(1)
    assert last_admin.value.status_code == 400
