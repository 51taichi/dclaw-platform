# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from fastapi import HTTPException

from qwenpaw.app.auth import verify_password
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
            }
            for row in self.users.values()
        ]

    def get_user_by_username(self, username):
        return next(
            (row for row in self.users.values() if row["username"] == username),
            None,
        )

    def get_user_by_id(self, user_id):
        return self.users.get(user_id)

    def count_admins(self):
        return sum(1 for row in self.users.values() if row["role"] == "admin")

    def create_user(self, *, username, password_hash, password_salt, role):
        user_id = self.next_id
        self.next_id += 1
        row = {
            "id": user_id,
            "username": username,
            "role": role,
            "created_at": f"2026-06-08T10:00:0{user_id}",
            "password_hash": password_hash,
            "password_salt": password_salt,
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

    def delete_user_cascade(self, user_id):
        if user_id not in self.users:
            return False
        self.deleted.append(user_id)
        del self.users[user_id]
        return True


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeUserRepository()
    monkeypatch.setattr(admin_users, "get_user_repository", lambda: repo)
    return repo


@pytest.mark.asyncio
async def test_admin_user_routes_use_user_repository(fake_repo):
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
    stored = fake_repo.get_user_by_username("alice")
    assert verify_password(
        "new-password",
        stored["password_hash"],
        stored["password_salt"],
    )

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
async def test_admin_user_routes_prevent_duplicate_and_last_admin_delete(fake_repo):
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
