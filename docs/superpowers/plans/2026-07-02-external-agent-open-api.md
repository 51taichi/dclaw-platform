# External Agent Open API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow external applications to call admin-created experts and expert teams through a dedicated Open API with API-key authentication, publication binding, quota hooks, and audit records.

**Architecture:** Keep existing expert and expert-team creation as the source of truth. Add a focused Open API domain that stores published targets, external apps, hashed keys, and invocation records, then routes external calls into the existing console chat and expert-team runtime under a server-selected owner user and target. Admin UI lives in one Open API settings page with publication, key, and invocation controls.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy Core plus SQLite compatibility repositories, existing QwenPaw chat/expert-team runtime, React 18, TypeScript, Ant Design, Vitest, pytest.

---

### File Structure

- Modify: `src/qwenpaw/app/storage/schema.py`
  - Adds durable Open API SQLAlchemy tables and indexes.
- Modify: `src/qwenpaw/app/db.py`
  - Adds SQLite table creation for legacy/local SQLite bootstrap.
- Create: `src/qwenpaw/app/open_api/models.py`
  - Owns Pydantic models and normalized status/scope constants.
- Create: `src/qwenpaw/app/storage/repos/open_api_repo.py`
  - Owns SQLAlchemy and sqlite repository implementations for publications, apps, keys, and invocations.
- Create: `src/qwenpaw/app/open_api/auth.py`
  - Owns key generation, hashing, verification, scope checks, and request-state binding.
- Modify: `src/qwenpaw/app/auth.py`
  - Adds an explicit `/api/open/` middleware branch before normal web-console auth handling.
- Create: `src/qwenpaw/app/routers/open_api_admin.py`
  - Admin CRUD for publications, external apps, keys, and invocation listing.
- Create: `src/qwenpaw/app/routers/open_api.py`
  - External runtime endpoints under `/open/v1`.
- Modify: `src/qwenpaw/app/routers/__init__.py`
  - Mounts admin and public Open API routers in the existing route tree.
- Create: `src/qwenpaw/app/open_api/runtime.py`
  - Converts verified external calls into existing console chat and expert-team runs.
- Test: `tests/unit/app/storage/repos/test_open_api_repo.py`
- Test: `tests/unit/app/test_open_api_auth.py`
- Test: `tests/unit/app/test_open_api_router.py`
- Create: `console/src/api/types/openApi.ts`
  - Frontend Open API DTOs.
- Create: `console/src/api/modules/openApi.ts`
  - Admin Open API client methods.
- Create: `console/src/pages/Settings/OpenApi/index.tsx`
  - Admin management page.
- Create: `console/src/pages/Settings/OpenApi/index.module.less`
  - Page styling.
- Create: `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`
  - Frontend behavior tests.
- Modify: `console/src/layouts/AdminLayout/index.tsx`
  - Adds `/admin/open-api` route.
- Modify: `console/src/layouts/Sidebar.tsx`
  - Adds admin navigation entry.
- Modify: `console/src/layouts/constants.ts`
  - Adds route key mapping.
- Modify: `console/src/api/config.ts`
  - Adds Open API admin prefix routing.

### Task 1: Durable Open API Schema And Repository

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/db.py`
- Create: `src/qwenpaw/app/open_api/models.py`
- Create: `src/qwenpaw/app/storage/repos/open_api_repo.py`
- Test: `tests/unit/app/storage/repos/test_open_api_repo.py`

- [ ] **Step 1: Write the failing SQLAlchemy repository tests**

Create `tests/unit/app/storage/repos/test_open_api_repo.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def _repo(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return SqlAlchemyOpenApiRepository(engine)


def test_publication_app_key_and_invocation_lifecycle(tmp_path):
    repo = _repo(tmp_path)
    publication = repo.upsert_publication(
        {
            "id": "pub-1",
            "public_id": "cs-agent",
            "target_type": "agent",
            "target_id": "customer_service",
            "owner_user_id": "7",
            "name": "客服专家",
            "description": "回答客户问题",
            "status": "enabled",
            "allowed_scopes": '["messages:create","messages:read","runs:stop"]',
        },
    )
    app = repo.create_external_app(
        {
            "id": "app-1",
            "owner_user_id": "7",
            "name": "官网客服窗口",
            "status": "enabled",
            "ip_allowlist": "[]",
            "quota_policy": "{}",
        },
    )
    key = repo.create_api_key(
        {
            "id": "key-1",
            "app_id": app["id"],
            "publication_id": publication["id"],
            "key_hash": "hash-value",
            "key_prefix": "qp_live",
            "key_suffix": "abcd",
            "scopes": '["messages:create"]',
            "status": "active",
            "expires_at": None,
        },
    )
    invocation = repo.create_invocation(
        {
            "id": "inv-1",
            "app_id": app["id"],
            "publication_id": publication["id"],
            "api_key_id": key["id"],
            "target_type": "agent",
            "target_id": "customer_service",
            "chat_id": "chat-1",
            "external_session_id": "ticket-1",
            "external_user_id": "customer-1",
            "status": "succeeded",
            "status_code": 200,
            "latency_ms": 42,
            "token_summary": "{}",
            "error_summary": "",
        },
    )

    assert repo.get_publication_by_public_id("cs-agent")["target_id"] == "customer_service"
    assert repo.get_api_key_by_hash("hash-value")["id"] == "key-1"
    assert repo.list_invocations(publication_id="pub-1", limit=10, offset=0)[0]["id"] == invocation["id"]


def test_repository_hides_disabled_publications_from_enabled_lookup(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_publication(
        {
            "id": "pub-disabled",
            "public_id": "disabled-target",
            "target_type": "agent",
            "target_id": "default",
            "owner_user_id": "7",
            "name": "Disabled",
            "description": "",
            "status": "disabled",
            "allowed_scopes": '["messages:create"]',
        },
    )

    assert repo.get_enabled_publication_by_public_id("disabled-target") is None
    assert repo.get_publication_by_public_id("disabled-target")["status"] == "disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/storage/repos/test_open_api_repo.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'qwenpaw.app.storage.repos.open_api_repo'`.

- [ ] **Step 3: Add SQLAlchemy schema tables**

In `src/qwenpaw/app/storage/schema.py`, add the tables after `knowledge_wiki` and before indexes:

```python
open_api_publications = Table(
    "open_api_publications",
    metadata,
    Column("id", String, primary_key=True),
    Column("public_id", String, nullable=False, unique=True),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("owner_user_id", String, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, server_default=""),
    Column("status", String, nullable=False, server_default="enabled"),
    Column("allowed_scopes", Text, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_external_apps = Table(
    "open_api_external_apps",
    metadata,
    Column("id", String, primary_key=True),
    Column("owner_user_id", String, nullable=False),
    Column("name", Text, nullable=False),
    Column("status", String, nullable=False, server_default="enabled"),
    Column("ip_allowlist", Text, nullable=False, server_default="[]"),
    Column("quota_policy", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_keys = Table(
    "open_api_keys",
    metadata,
    Column("id", String, primary_key=True),
    Column("app_id", String, ForeignKey("open_api_external_apps.id"), nullable=False),
    Column("publication_id", String, ForeignKey("open_api_publications.id"), nullable=False),
    Column("key_hash", Text, nullable=False, unique=True),
    Column("key_prefix", String, nullable=False),
    Column("key_suffix", String, nullable=False),
    Column("scopes", Text, nullable=False, server_default="[]"),
    Column("status", String, nullable=False, server_default="active"),
    Column("expires_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    Column("last_used_ip", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_invocations = Table(
    "open_api_invocations",
    metadata,
    Column("id", String, primary_key=True),
    Column("app_id", String, ForeignKey("open_api_external_apps.id"), nullable=False),
    Column("publication_id", String, ForeignKey("open_api_publications.id"), nullable=False),
    Column("api_key_id", String, ForeignKey("open_api_keys.id"), nullable=False),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("chat_id", String),
    Column("external_session_id", Text),
    Column("external_user_id", Text),
    Column("status", String, nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("latency_ms", Integer, server_default="0"),
    Column("token_summary", Text, nullable=False, server_default="{}"),
    Column("error_summary", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)
```

Add indexes:

```python
Index("idx_open_api_publications_target", open_api_publications.c.target_type, open_api_publications.c.target_id)
Index("idx_open_api_apps_owner_status", open_api_external_apps.c.owner_user_id, open_api_external_apps.c.status)
Index("idx_open_api_keys_app_publication", open_api_keys.c.app_id, open_api_keys.c.publication_id)
Index("idx_open_api_invocations_publication_created", open_api_invocations.c.publication_id, open_api_invocations.c.created_at.desc())
```

- [ ] **Step 4: Add SQLite bootstrap tables**

In `src/qwenpaw/app/db.py`, extend `init_db()` with `CREATE TABLE IF NOT EXISTS` statements matching the table and column names from Step 3. Use `TEXT` for datetime columns in SQLite and `INTEGER DEFAULT 0` for `latency_ms`.

- [ ] **Step 5: Add Pydantic models**

Create `src/qwenpaw/app/open_api/models.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TargetType = Literal["agent", "expert_team"]
PublicationStatus = Literal["enabled", "disabled"]
ExternalAppStatus = Literal["enabled", "disabled"]
ApiKeyStatus = Literal["active", "revoked"]
InvocationStatus = Literal["succeeded", "failed"]

MESSAGE_CREATE_SCOPE = "messages:create"
MESSAGE_READ_SCOPE = "messages:read"
RUN_STOP_SCOPE = "runs:stop"


class OpenApiPublication(BaseModel):
    id: str
    public_id: str
    target_type: TargetType
    target_id: str
    owner_user_id: str
    name: str
    description: str = ""
    status: PublicationStatus = "enabled"
    allowed_scopes: list[str] = Field(default_factory=list)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ExternalApp(BaseModel):
    id: str
    owner_user_id: str
    name: str
    status: ExternalAppStatus = "enabled"
    ip_allowlist: list[str] = Field(default_factory=list)
    quota_policy: dict = Field(default_factory=dict)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ExternalApiKey(BaseModel):
    id: str
    app_id: str
    publication_id: str
    key_hash: str
    key_prefix: str
    key_suffix: str
    scopes: list[str] = Field(default_factory=list)
    status: ApiKeyStatus = "active"
    expires_at: datetime | str | None = None
    last_used_at: datetime | str | None = None
    last_used_ip: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class OpenApiInvocation(BaseModel):
    id: str
    app_id: str
    publication_id: str
    api_key_id: str
    target_type: TargetType
    target_id: str
    chat_id: str | None = None
    external_session_id: str | None = None
    external_user_id: str | None = None
    status: InvocationStatus
    status_code: int
    latency_ms: int = 0
    token_summary: dict = Field(default_factory=dict)
    error_summary: str = ""
    created_at: datetime | str | None = None
```

- [ ] **Step 6: Add repository implementation**

Create `src/qwenpaw/app/storage/repos/open_api_repo.py` with a `SqlAlchemyOpenApiRepository`, `SqliteOpenApiRepository`, and `get_open_api_repository()` following the same selection pattern as `expert_team_repo.py`. Required methods:

```python
def upsert_publication(self, row: dict[str, object]) -> dict
def list_publications(self, *, enabled_only: bool = False) -> list[dict]
def get_publication(self, publication_id: str) -> dict | None
def get_publication_by_public_id(self, public_id: str) -> dict | None
def get_enabled_publication_by_public_id(self, public_id: str) -> dict | None
def create_external_app(self, row: dict[str, object]) -> dict
def list_external_apps(self, *, owner_user_id: str | None = None) -> list[dict]
def get_external_app(self, app_id: str) -> dict | None
def create_api_key(self, row: dict[str, object]) -> dict
def get_api_key_by_hash(self, key_hash: str) -> dict | None
def list_api_keys(self, *, app_id: str | None = None, publication_id: str | None = None) -> list[dict]
def update_api_key_status(self, key_id: str, status: str) -> dict | None
def mark_api_key_used(self, key_id: str, ip: str) -> None
def create_invocation(self, row: dict[str, object]) -> dict
def list_invocations(self, *, publication_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]
```

Normalize JSON text fields in returned rows:

```python
allowed_scopes -> list[str]
ip_allowlist -> list[str]
quota_policy -> dict
scopes -> list[str]
token_summary -> dict
```

- [ ] **Step 7: Run repository tests**

Run: `pytest tests/unit/app/storage/repos/test_open_api_repo.py -q`

Expected: PASS.

- [ ] **Step 8: Commit schema and repository**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/db.py src/qwenpaw/app/open_api/models.py src/qwenpaw/app/storage/repos/open_api_repo.py tests/unit/app/storage/repos/test_open_api_repo.py
git commit -m "feat: add open api storage"
```

### Task 2: Open API Key Authentication

**Files:**
- Create: `src/qwenpaw/app/open_api/auth.py`
- Modify: `src/qwenpaw/app/auth.py`
- Test: `tests/unit/app/test_open_api_auth.py`

- [ ] **Step 1: Write failing auth tests**

Create `tests/unit/app/test_open_api_auth.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.open_api import auth as open_auth


def test_generate_key_returns_plaintext_once_and_hash_is_stable():
    plaintext, display = open_auth.generate_open_api_key()
    assert plaintext.startswith("qp_live_")
    assert display["key_prefix"] == "qp_live"
    assert len(display["key_suffix"]) == 4
    assert open_auth.hash_open_api_key(plaintext) == open_auth.hash_open_api_key(plaintext)
    assert plaintext not in open_auth.hash_open_api_key(plaintext)


def test_verify_open_api_key_rejects_missing_scope(monkeypatch):
    key_hash = open_auth.hash_open_api_key("qp_live_test")

    class FakeRepo:
        def get_api_key_by_hash(self, value):
            assert value == key_hash
            return {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "scopes": ["messages:read"],
                "status": "active",
                "expires_at": None,
            }

        def get_external_app(self, app_id):
            return {
                "id": app_id,
                "owner_user_id": "7",
                "status": "enabled",
                "ip_allowlist": [],
            }

        def get_publication(self, publication_id):
            return {
                "id": publication_id,
                "public_id": "cs-agent",
                "target_type": "agent",
                "target_id": "customer_service",
                "owner_user_id": "7",
                "status": "enabled",
                "allowed_scopes": ["messages:create"],
            }

        def mark_api_key_used(self, key_id, ip):
            raise AssertionError("scope failure must not mark key used")

    monkeypatch.setattr(open_auth, "get_open_api_repository", lambda: FakeRepo())

    request = SimpleNamespace(
        headers={"authorization": "Bearer qp_live_test"},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )

    with pytest.raises(HTTPException) as exc:
        open_auth.authenticate_open_api_request(request, required_scope="messages:create")

    assert exc.value.status_code == 403


def test_verify_open_api_key_binds_request_state(monkeypatch):
    key_hash = open_auth.hash_open_api_key("qp_live_test")
    used = []

    class FakeRepo:
        def get_api_key_by_hash(self, value):
            assert value == key_hash
            return {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "scopes": ["messages:create"],
                "status": "active",
                "expires_at": None,
            }

        def get_external_app(self, app_id):
            return {
                "id": app_id,
                "owner_user_id": "7",
                "status": "enabled",
                "ip_allowlist": ["127.0.0.1"],
            }

        def get_publication(self, publication_id):
            return {
                "id": publication_id,
                "public_id": "cs-agent",
                "target_type": "agent",
                "target_id": "customer_service",
                "owner_user_id": "7",
                "status": "enabled",
                "allowed_scopes": ["messages:create"],
            }

        def mark_api_key_used(self, key_id, ip):
            used.append((key_id, ip))

    monkeypatch.setattr(open_auth, "get_open_api_repository", lambda: FakeRepo())

    request = SimpleNamespace(
        headers={"authorization": "Bearer qp_live_test"},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )

    context = open_auth.authenticate_open_api_request(request, required_scope="messages:create")

    assert context.publication["target_id"] == "customer_service"
    assert request.state.user_id == "7"
    assert request.state.role == "open_app"
    assert request.state.open_app_id == "app-1"
    assert used == [("key-1", "127.0.0.1")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/test_open_api_auth.py -q`

Expected: FAIL with missing `qwenpaw.app.open_api.auth`.

- [ ] **Step 3: Implement key helpers and request authentication**

Create `src/qwenpaw/app/open_api/auth.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from ..storage.repos.open_api_repo import get_open_api_repository


KEY_PREFIX = "qp_live"


@dataclass(frozen=True)
class OpenApiAuthContext:
    api_key: dict[str, Any]
    app: dict[str, Any]
    publication: dict[str, Any]


def generate_open_api_key() -> tuple[str, dict[str, str]]:
    token = f"{KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return token, {"key_prefix": KEY_PREFIX, "key_suffix": token[-4:]}


def hash_open_api_key(plaintext: str) -> str:
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Open API key")
    token = header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Open API key")
    return token


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_expired(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, str):
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        expires_at = value
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _require_scope(scopes: list[str], required_scope: str) -> None:
    if required_scope not in scopes:
        raise HTTPException(status_code=403, detail="Open API scope denied")


def authenticate_open_api_request(
    request: Request,
    *,
    required_scope: str,
) -> OpenApiAuthContext:
    token = _extract_bearer_token(request)
    key_hash = hash_open_api_key(token)
    repo = get_open_api_repository()
    key = repo.get_api_key_by_hash(key_hash)
    if not key or key.get("status") != "active" or _is_expired(key.get("expires_at")):
        raise HTTPException(status_code=401, detail="Invalid Open API key")

    app = repo.get_external_app(str(key["app_id"]))
    if not app or app.get("status") != "enabled":
        raise HTTPException(status_code=403, detail="External app disabled")

    publication = repo.get_publication(str(key["publication_id"]))
    if not publication or publication.get("status") != "enabled":
        raise HTTPException(status_code=403, detail="Publication disabled")

    allowed_ips = app.get("ip_allowlist") or []
    ip = _client_ip(request)
    if allowed_ips and ip not in allowed_ips:
        raise HTTPException(status_code=403, detail="Open API IP denied")

    _require_scope(key.get("scopes") or [], required_scope)
    _require_scope(publication.get("allowed_scopes") or [], required_scope)

    request.state.user_id = str(publication["owner_user_id"])
    request.state.role = "open_app"
    request.state.open_app_id = str(app["id"])
    request.state.open_publication_id = str(publication["id"])
    request.state.open_target_type = str(publication["target_type"])
    request.state.open_target_id = str(publication["target_id"])
    repo.mark_api_key_used(str(key["id"]), ip)
    return OpenApiAuthContext(api_key=key, app=app, publication=publication)
```

- [ ] **Step 4: Add middleware branch**

In `src/qwenpaw/app/auth.py`, import the Open API helper inside the branch to avoid import cycles:

```python
if request.url.path.startswith("/api/open/"):
    from .open_api.auth import authenticate_open_api_request
    from .open_api.models import MESSAGE_CREATE_SCOPE, MESSAGE_READ_SCOPE, RUN_STOP_SCOPE

    if request.method == "POST" and request.url.path.endswith("/messages"):
        authenticate_open_api_request(request, required_scope=MESSAGE_CREATE_SCOPE)
    elif request.method == "POST" and request.url.path.endswith("/stop"):
        authenticate_open_api_request(request, required_scope=RUN_STOP_SCOPE)
    else:
        authenticate_open_api_request(request, required_scope=MESSAGE_READ_SCOPE)
    return await call_next(request)
```

Place this branch in `AuthMiddleware.dispatch()` after `decision = backup_endpoint_policy.apply(...)` and before the existing web-console token extraction.

- [ ] **Step 5: Run auth tests**

Run: `pytest tests/unit/app/test_open_api_auth.py tests/unit/app/test_auth_login_rate_limit.py -q`

Expected: PASS.

- [ ] **Step 6: Commit authentication**

```bash
git add src/qwenpaw/app/open_api/auth.py src/qwenpaw/app/auth.py tests/unit/app/test_open_api_auth.py
git commit -m "feat: authenticate open api keys"
```

### Task 3: Admin Open API Management Routes

**Files:**
- Create: `src/qwenpaw/app/routers/open_api_admin.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/test_open_api_admin.py`

- [ ] **Step 1: Write failing admin route tests**

Create `tests/unit/app/test_open_api_admin.py` with tests that monkeypatch the repository and call route functions directly:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import open_api_admin


def _admin_request():
    return SimpleNamespace(state=SimpleNamespace(user_id=7, role="admin"))


@pytest.mark.asyncio
async def test_create_publication_uses_current_admin_as_owner(monkeypatch):
    rows = []

    class FakeRepo:
        def upsert_publication(self, row):
            rows.append(row)
            return {**row, "created_at": None, "updated_at": None}

    monkeypatch.setattr(open_api_admin, "get_open_api_repository", lambda: FakeRepo())
    monkeypatch.setattr(open_api_admin, "load_config", lambda: SimpleNamespace(agents=SimpleNamespace(profiles={"customer_service": object()})))

    result = await open_api_admin.create_publication(
        open_api_admin.PublicationCreateRequest(
            public_id="cs-agent",
            target_type="agent",
            target_id="customer_service",
            name="客服专家",
            description="",
            allowed_scopes=["messages:create"],
        ),
        _admin_request(),
    )

    assert result["owner_user_id"] == "7"
    assert rows[0]["target_type"] == "agent"


@pytest.mark.asyncio
async def test_create_key_returns_plaintext_once(monkeypatch):
    class FakeRepo:
        def get_external_app(self, app_id):
            return {"id": app_id, "status": "enabled"}

        def get_publication(self, publication_id):
            return {"id": publication_id, "status": "enabled", "allowed_scopes": ["messages:create"]}

        def create_api_key(self, row):
            return {**row, "created_at": None, "updated_at": None}

    monkeypatch.setattr(open_api_admin, "get_open_api_repository", lambda: FakeRepo())

    result = await open_api_admin.create_api_key(
        open_api_admin.ApiKeyCreateRequest(
            app_id="app-1",
            publication_id="pub-1",
            scopes=["messages:create"],
            expires_at=None,
        ),
    )

    assert result["plaintext_key"].startswith("qp_live_")
    assert result["key"]["key_hash"].startswith("sha256:")
    assert result["plaintext_key"] not in result["key"]["key_hash"]


@pytest.mark.asyncio
async def test_non_admin_request_is_rejected():
    with pytest.raises(HTTPException) as exc:
        await open_api_admin.list_publications(SimpleNamespace(state=SimpleNamespace(user_id=8, role="user")))
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/test_open_api_admin.py -q`

Expected: FAIL because `open_api_admin` router does not exist.

- [ ] **Step 3: Implement admin router**

Create `src/qwenpaw/app/routers/open_api_admin.py` with:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...config import load_config
from ..open_api.auth import generate_open_api_key, hash_open_api_key
from ..open_api.models import MESSAGE_CREATE_SCOPE, MESSAGE_READ_SCOPE, RUN_STOP_SCOPE, TargetType
from ..storage.repos.open_api_repo import get_open_api_repository

router = APIRouter(prefix="/open-api", tags=["admin-open-api"])


class PublicationCreateRequest(BaseModel):
    public_id: str
    target_type: TargetType
    target_id: str
    name: str
    description: str = ""
    allowed_scopes: list[str] = [MESSAGE_CREATE_SCOPE, MESSAGE_READ_SCOPE, RUN_STOP_SCOPE]


class ExternalAppCreateRequest(BaseModel):
    name: str
    ip_allowlist: list[str] = []
    quota_policy: dict = {}


class ApiKeyCreateRequest(BaseModel):
    app_id: str
    publication_id: str
    scopes: list[str] = [MESSAGE_CREATE_SCOPE]
    expires_at: datetime | None = None


def _require_admin(request: Request) -> str:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return str(getattr(request.state, "user_id", ""))


def _assert_target_exists(target_type: str, target_id: str) -> None:
    if target_type == "agent":
        config = load_config()
        if target_id not in config.agents.profiles:
            raise HTTPException(status_code=404, detail="Agent not found")
        return
    from ..expert_teams import get_expert_team_template

    team = get_expert_team_template(target_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Expert team not found")


@router.get("/publications")
async def list_publications(request: Request) -> list[dict]:
    _require_admin(request)
    return get_open_api_repository().list_publications(enabled_only=False)


@router.post("/publications")
async def create_publication(payload: PublicationCreateRequest, request: Request) -> dict:
    owner_user_id = _require_admin(request)
    _assert_target_exists(payload.target_type, payload.target_id)
    row = {
        "id": str(uuid4()),
        "public_id": payload.public_id,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "owner_user_id": owner_user_id,
        "name": payload.name,
        "description": payload.description,
        "status": "enabled",
        "allowed_scopes": payload.allowed_scopes,
    }
    return get_open_api_repository().upsert_publication(row)


@router.post("/apps")
async def create_external_app(payload: ExternalAppCreateRequest, request: Request) -> dict:
    owner_user_id = _require_admin(request)
    return get_open_api_repository().create_external_app(
        {
            "id": str(uuid4()),
            "owner_user_id": owner_user_id,
            "name": payload.name,
            "status": "enabled",
            "ip_allowlist": payload.ip_allowlist,
            "quota_policy": payload.quota_policy,
        },
    )


@router.post("/keys")
async def create_api_key(payload: ApiKeyCreateRequest) -> dict:
    repo = get_open_api_repository()
    app = repo.get_external_app(payload.app_id)
    publication = repo.get_publication(payload.publication_id)
    if not app:
        raise HTTPException(status_code=404, detail="External app not found")
    if not publication:
        raise HTTPException(status_code=404, detail="Publication not found")
    plaintext, display = generate_open_api_key()
    key = repo.create_api_key(
        {
            "id": str(uuid4()),
            "app_id": payload.app_id,
            "publication_id": payload.publication_id,
            "key_hash": hash_open_api_key(plaintext),
            "key_prefix": display["key_prefix"],
            "key_suffix": display["key_suffix"],
            "scopes": payload.scopes,
            "status": "active",
            "expires_at": payload.expires_at,
        },
    )
    return {"plaintext_key": plaintext, "key": key}


@router.post("/keys/{key_id}/revoke")
async def revoke_api_key(key_id: str) -> dict:
    key = get_open_api_repository().update_api_key_status(key_id, "revoked")
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return key


@router.get("/invocations")
async def list_invocations(
    publication_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    return get_open_api_repository().list_invocations(
        publication_id=publication_id,
        limit=limit,
        offset=offset,
    )
```

- [ ] **Step 4: Mount admin router**

In `src/qwenpaw/app/routers/__init__.py`, import and include the router:

```python
from .open_api_admin import router as open_api_admin_router
```

Add under the admin router includes:

```python
admin_api_router.include_router(open_api_admin_router)
```

- [ ] **Step 5: Run admin route tests**

Run: `pytest tests/unit/app/test_open_api_admin.py -q`

Expected: PASS.

- [ ] **Step 6: Commit admin routes**

```bash
git add src/qwenpaw/app/routers/open_api_admin.py src/qwenpaw/app/routers/__init__.py tests/unit/app/test_open_api_admin.py
git commit -m "feat: add open api admin routes"
```

### Task 4: External Expert Message Endpoint

**Files:**
- Create: `src/qwenpaw/app/open_api/runtime.py`
- Create: `src/qwenpaw/app/routers/open_api.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/test_open_api_router.py`

- [ ] **Step 1: Write failing router tests for expert publications**

Create `tests/unit/app/test_open_api_router.py` with a direct runtime test:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.open_api import runtime


def test_build_open_session_id_is_namespaced_and_stable():
    assert (
        runtime.build_open_session_id(
            app_id="app-1",
            public_id="cs-agent",
            external_session_id="ticket-456",
        )
        == "open:app-1:cs-agent:ticket-456"
    )


@pytest.mark.asyncio
async def test_run_expert_message_ignores_caller_agent_id(monkeypatch):
    captured = {}

    class FakeChatManager:
        async def get_or_create_chat(self, session_id, user_id, channel, name):
            captured["session_id"] = session_id
            captured["user_id"] = user_id
            captured["channel"] = channel
            captured["name"] = name
            return SimpleNamespace(id="chat-1", name=name, meta={})

    class FakeWorkspace:
        agent_id = "customer_service"
        chat_manager = FakeChatManager()

    async def fake_get_agent_for_request(request, agent_id=None):
        captured["agent_id"] = agent_id
        return FakeWorkspace()

    monkeypatch.setattr(runtime, "get_agent_for_request", fake_get_agent_for_request)

    request = SimpleNamespace(
        state=SimpleNamespace(
            user_id="7",
            open_app_id="app-1",
            open_target_type="agent",
            open_target_id="customer_service",
        ),
    )

    result = await runtime.prepare_open_agent_chat(
        request=request,
        publication={"public_id": "cs-agent", "target_id": "customer_service"},
        payload=runtime.OpenMessageRequest(
            external_user_id="customer-1",
            external_session_id="ticket-456",
            message="hello",
            metadata={"agent_id": "malicious"},
        ),
    )

    assert result.chat_id == "chat-1"
    assert captured["agent_id"] == "customer_service"
    assert captured["user_id"] == "7"
    assert captured["channel"] == "open:app-1"
    assert captured["session_id"] == "open:app-1:cs-agent:ticket-456"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/test_open_api_router.py -q`

Expected: FAIL with missing `qwenpaw.app.open_api.runtime`.

- [ ] **Step 3: Implement runtime request and chat preparation**

Create `src/qwenpaw/app/open_api/runtime.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request


class OpenMessageRequest(BaseModel):
    external_user_id: str
    external_session_id: str
    message: str
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class PreparedOpenRun:
    chat_id: str
    session_id: str
    channel: str
    agent_id: str
    payload: dict[str, Any]


def build_open_session_id(*, app_id: str, public_id: str, external_session_id: str) -> str:
    safe_session = external_session_id.strip()
    if not safe_session:
        safe_session = "default"
    return f"open:{app_id}:{public_id}:{safe_session}"


async def prepare_open_agent_chat(
    *,
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
) -> PreparedOpenRun:
    app_id = str(request.state.open_app_id)
    owner_user_id = str(request.state.user_id)
    agent_id = str(publication["target_id"])
    public_id = str(publication["public_id"])
    channel = f"open:{app_id}"
    session_id = build_open_session_id(
        app_id=app_id,
        public_id=public_id,
        external_session_id=payload.external_session_id,
    )
    workspace = await get_agent_for_request(request, agent_id=agent_id)
    name = payload.message[:10] or "Open API"
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        owner_user_id,
        channel,
        name=name,
    )
    native_payload = {
        "channel_id": channel,
        "sender_id": owner_user_id,
        "content_parts": [{"type": "text", "text": payload.message}],
        "meta": {
            "session_id": session_id,
            "user_id": owner_user_id,
            "external_user_id": payload.external_user_id,
            "external_session_id": payload.external_session_id,
            "publication_id": publication["id"],
            "target_type": "agent",
            "target_id": agent_id,
            "metadata": payload.metadata,
        },
    }
    return PreparedOpenRun(
        chat_id=str(chat.id),
        session_id=session_id,
        channel=channel,
        agent_id=agent_id,
        payload=native_payload,
    )
```

- [ ] **Step 4: Add `/api/open/v1/targets/{public_id}/messages` route**

Create `src/qwenpaw/app/routers/open_api.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..open_api.models import MESSAGE_CREATE_SCOPE
from ..open_api.runtime import OpenMessageRequest, prepare_open_agent_chat
from ..storage.repos.open_api_repo import get_open_api_repository

router = APIRouter(prefix="/open/v1", tags=["open-api"])


@router.post("/targets/{public_id}/messages")
async def post_open_message(public_id: str, payload: OpenMessageRequest, request: Request):
    repo = get_open_api_repository()
    publication = repo.get_enabled_publication_by_public_id(public_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Open API target not found")
    if str(request.state.open_publication_id) != str(publication["id"]):
        raise HTTPException(status_code=403, detail="Open API key cannot call this target")
    if publication["target_type"] != "agent":
        raise HTTPException(status_code=400, detail="Target is not an expert")

    started = time.monotonic()
    invocation_id = str(uuid4())
    prepared = await prepare_open_agent_chat(request=request, publication=publication, payload=payload)

    async def events():
        yield f"data: {json.dumps({'chat_id': prepared.chat_id, 'session_id': prepared.session_id}, ensure_ascii=False)}\n\n"

    repo.create_invocation(
        {
            "id": invocation_id,
            "app_id": request.state.open_app_id,
            "publication_id": publication["id"],
            "api_key_id": "unknown",
            "target_type": "agent",
            "target_id": publication["target_id"],
            "chat_id": prepared.chat_id,
            "external_session_id": payload.external_session_id,
            "external_user_id": payload.external_user_id,
            "status": "succeeded",
            "status_code": 200,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "token_summary": {},
            "error_summary": "",
        },
    )
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "X-QwenPaw-Chat-Id": prepared.chat_id,
            "X-QwenPaw-Session-Id": prepared.session_id,
            "X-QwenPaw-Open-Invocation-Id": invocation_id,
        },
    )
```

Replace the temporary `events()` generator in this task before committing. The final route must perform these concrete runtime steps:

1. Resolve the server-owned workspace from `prepared.workspace`.
2. Resolve the channel with `workspace.channel_manager.get(prepared.channel)` and return `404` if missing.
3. Acquire the task limiter with `await acquire_task_permit(str(request.state.user_id), prepared.agent_id, prepared.chat_id)`.
4. Subscribe to `workspace.task_tracker` before starting the run.
5. Start a background task that calls `console_channel.stream_one(prepared.payload)`, marks invocation status on completion/failure, and always releases the task permit.
6. Return `StreamingResponse(workspace.task_tracker.stream_from_queue(queue, prepared.chat_id), media_type="text/event-stream", ...)`.

- [ ] **Step 5: Mount Open API router**

In `src/qwenpaw/app/routers/__init__.py`, import and include:

```python
from .open_api import router as open_api_router

router.include_router(open_api_router)
```

Mount this at the root router level, not inside `/user` or `/admin`.

- [ ] **Step 6: Run expert endpoint tests**

Run: `pytest tests/unit/app/test_open_api_router.py tests/unit/app/test_console_user_binding.py -q`

Expected: PASS.

- [ ] **Step 7: Commit expert endpoint**

```bash
git add src/qwenpaw/app/open_api/runtime.py src/qwenpaw/app/routers/open_api.py src/qwenpaw/app/routers/__init__.py tests/unit/app/test_open_api_router.py
git commit -m "feat: add open expert message endpoint"
```

### Task 5: Expert-Team Open API Runtime

**Files:**
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Test: `tests/unit/app/test_open_api_router.py`

- [ ] **Step 1: Add failing expert-team runtime test**

Append this test to `tests/unit/app/test_open_api_router.py`:

```python
@pytest.mark.asyncio
async def test_prepare_expert_team_chat_uses_leader_agent_and_team_metadata(monkeypatch):
    captured = {}

    class FakeChatManager:
        async def get_or_create_chat(self, session_id, user_id, channel, name):
            captured["session_id"] = session_id
            captured["user_id"] = user_id
            captured["channel"] = channel
            return SimpleNamespace(id="chat-team", name=name, meta={})

    class FakeWorkspace:
        agent_id = "leader"
        chat_manager = FakeChatManager()

    async def fake_get_agent_for_request(request, agent_id=None):
        captured["agent_id"] = agent_id
        return FakeWorkspace()

    monkeypatch.setattr(runtime, "get_agent_for_request", fake_get_agent_for_request)
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_id="7",
            open_app_id="app-1",
            open_target_type="expert_team",
            open_target_id="support_team",
        ),
    )

    result = await runtime.prepare_open_expert_team_chat(
        request=request,
        publication={
            "id": "pub-team",
            "public_id": "support-team",
            "target_id": "support_team",
            "leader_agent_id": "leader",
        },
        leader_agent_id="leader",
        payload=runtime.OpenMessageRequest(
            external_user_id="customer-1",
            external_session_id="ticket-456",
            message="需要售后帮助",
        ),
    )

    assert result.chat_id == "chat-team"
    assert captured["agent_id"] == "leader"
    assert result.payload["meta"]["expert_team_id"] == "support_team"
    assert captured["channel"] == "open:app-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/app/test_open_api_router.py::test_prepare_expert_team_chat_uses_leader_agent_and_team_metadata -q`

Expected: FAIL because `prepare_open_expert_team_chat` is not defined.

- [ ] **Step 3: Implement expert-team preparation**

Add to `src/qwenpaw/app/open_api/runtime.py`:

```python
async def prepare_open_expert_team_chat(
    *,
    request: Request,
    publication: dict[str, Any],
    leader_agent_id: str,
    payload: OpenMessageRequest,
) -> PreparedOpenRun:
    app_id = str(request.state.open_app_id)
    owner_user_id = str(request.state.user_id)
    team_id = str(publication["target_id"])
    public_id = str(publication["public_id"])
    channel = f"open:{app_id}"
    session_id = build_open_session_id(
        app_id=app_id,
        public_id=public_id,
        external_session_id=payload.external_session_id,
    )
    workspace = await get_agent_for_request(request, agent_id=leader_agent_id)
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        owner_user_id,
        channel,
        name=payload.message[:10] or "Open API",
    )
    native_payload = {
        "channel_id": channel,
        "sender_id": owner_user_id,
        "content_parts": [{"type": "text", "text": payload.message}],
        "meta": {
            "session_id": session_id,
            "user_id": owner_user_id,
            "expert_team_id": team_id,
            "external_user_id": payload.external_user_id,
            "external_session_id": payload.external_session_id,
            "publication_id": publication["id"],
            "target_type": "expert_team",
            "target_id": team_id,
            "metadata": payload.metadata,
        },
    }
    return PreparedOpenRun(
        chat_id=str(chat.id),
        session_id=session_id,
        channel=channel,
        agent_id=leader_agent_id,
        payload=native_payload,
    )
```

- [ ] **Step 4: Route expert-team publications**

In `src/qwenpaw/app/routers/open_api.py`, when `publication["target_type"] == "expert_team"`:

```python
from ..expert_teams import get_expert_team_template
from ..open_api.runtime import prepare_open_expert_team_chat

team = get_expert_team_template(str(publication["target_id"]))
if team is None or not team.enabled:
    raise HTTPException(status_code=404, detail="Open API target not found")
prepared = await prepare_open_expert_team_chat(
    request=request,
    publication=publication,
    leader_agent_id=team.leader_agent_id,
    payload=payload,
)
```

For an expert-team publication, the route must perform these concrete runtime steps before returning the SSE response:

1. Call `create_expert_team_run(team=team, root_chat_id=prepared.chat_id, root_session_id=prepared.session_id, user_id=str(request.state.user_id), input_text=payload.message)`.
2. Add `expert_team_id` and `expert_team_run_id` to the prepared payload metadata.
3. Subscribe to `workspace.task_tracker` before starting orchestration.
4. Start a background task that creates `ExpertTeamOrchestrator(workspace=prepared.workspace, team=team, run_id=run_id, user_id=str(request.state.user_id), root_chat_id=prepared.chat_id)` and calls `stream_one(prepared.payload)`.
5. Mark invocation status on completion/failure and return `StreamingResponse(workspace.task_tracker.stream_from_queue(queue, prepared.chat_id), media_type="text/event-stream", ...)`.

- [ ] **Step 5: Run expert-team tests**

Run: `pytest tests/unit/app/test_open_api_router.py tests/unit/app/test_expert_teams.py -q`

Expected: PASS.

- [ ] **Step 6: Commit expert-team runtime**

```bash
git add src/qwenpaw/app/open_api/runtime.py src/qwenpaw/app/routers/open_api.py tests/unit/app/test_open_api_router.py
git commit -m "feat: support open expert team calls"
```

### Task 6: Admin Open API Frontend

**Files:**
- Create: `console/src/api/types/openApi.ts`
- Create: `console/src/api/modules/openApi.ts`
- Create: `console/src/pages/Settings/OpenApi/index.tsx`
- Create: `console/src/pages/Settings/OpenApi/index.module.less`
- Create: `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`
- Modify: `console/src/layouts/AdminLayout/index.tsx`
- Modify: `console/src/layouts/Sidebar.tsx`
- Modify: `console/src/layouts/constants.ts`
- Modify: `console/src/api/config.ts`

- [ ] **Step 1: Write failing frontend API routing test**

Add this test to `console/src/api/config.test.ts`:

```ts
it("routes Open API admin APIs through the admin namespace", () => {
  expect(getApiUrl("/open-api/publications")).toBe("/api/admin/open-api/publications");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd console && npm run test:run -- src/api/config.test.ts`

Expected: FAIL because `/open-api` is not in `ADMIN_PREFIXES`.

- [ ] **Step 3: Add API prefix**

In `console/src/api/config.ts`, add `"/open-api"` to `ADMIN_PREFIXES`.

- [ ] **Step 4: Add frontend DTOs**

Create `console/src/api/types/openApi.ts`:

```ts
export type OpenApiTargetType = "agent" | "expert_team";
export type OpenApiStatus = "enabled" | "disabled";

export interface OpenApiPublication {
  id: string;
  public_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  owner_user_id: string;
  name: string;
  description?: string;
  status: OpenApiStatus;
  allowed_scopes: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExternalApp {
  id: string;
  owner_user_id: string;
  name: string;
  status: OpenApiStatus;
  ip_allowlist: string[];
  quota_policy: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExternalApiKey {
  id: string;
  app_id: string;
  publication_id: string;
  key_prefix: string;
  key_suffix: string;
  scopes: string[];
  status: "active" | "revoked";
  expires_at?: string | null;
  last_used_at?: string | null;
  last_used_ip?: string | null;
}

export interface ApiKeyCreateResponse {
  plaintext_key: string;
  key: ExternalApiKey;
}

export interface OpenApiInvocation {
  id: string;
  app_id: string;
  publication_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  chat_id?: string | null;
  external_session_id?: string | null;
  external_user_id?: string | null;
  status: "succeeded" | "failed";
  status_code: number;
  latency_ms: number;
  error_summary?: string;
  created_at?: string | null;
}
```

- [ ] **Step 5: Add frontend API module**

Create `console/src/api/modules/openApi.ts`:

```ts
import { request } from "../request";
import type {
  ApiKeyCreateResponse,
  ExternalApp,
  ExternalApiKey,
  OpenApiInvocation,
  OpenApiPublication,
  OpenApiTargetType,
} from "../types/openApi";

export const openApiAdminApi = {
  listPublications: () => request<OpenApiPublication[]>("/open-api/publications"),
  createPublication: (payload: {
    public_id: string;
    target_type: OpenApiTargetType;
    target_id: string;
    name: string;
    description?: string;
    allowed_scopes: string[];
  }) =>
    request<OpenApiPublication>("/open-api/publications", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createExternalApp: (payload: {
    name: string;
    ip_allowlist?: string[];
    quota_policy?: Record<string, unknown>;
  }) =>
    request<ExternalApp>("/open-api/apps", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createApiKey: (payload: {
    app_id: string;
    publication_id: string;
    scopes: string[];
    expires_at?: string | null;
  }) =>
    request<ApiKeyCreateResponse>("/open-api/keys", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeApiKey: (keyId: string) =>
    request<ExternalApiKey>(`/open-api/keys/${keyId}/revoke`, {
      method: "POST",
    }),
  listInvocations: (publicationId?: string) => {
    const query = publicationId ? `?publication_id=${encodeURIComponent(publicationId)}` : "";
    return request<OpenApiInvocation[]>(`/open-api/invocations${query}`);
  },
};
```

- [ ] **Step 6: Write failing page smoke test**

Create `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OpenApiPage from "./index";

vi.mock("../../../api/modules/openApi", () => ({
  openApiAdminApi: {
    listPublications: vi.fn().mockResolvedValue([]),
    listInvocations: vi.fn().mockResolvedValue([]),
  },
}));

describe("OpenApiPage", () => {
  it("renders publication and key management sections", async () => {
    render(<OpenApiPage />);
    expect(await screen.findByText("Open API")).toBeInTheDocument();
    expect(screen.getByText("Published targets")).toBeInTheDocument();
    expect(screen.getByText("External app keys")).toBeInTheDocument();
    expect(screen.getByText("Recent invocations")).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Implement page**

Create `console/src/pages/Settings/OpenApi/index.tsx` with a compact admin surface:

```tsx
import { useEffect, useState } from "react";
import { Alert, Button, Card, Form, Input, Select, Space, Table, Typography, message } from "antd";
import { KeyRound, RadioTower, RefreshCcw } from "lucide-react";
import { openApiAdminApi } from "../../../api/modules/openApi";
import type { OpenApiInvocation, OpenApiPublication } from "../../../api/types/openApi";
import styles from "./index.module.less";

const DEFAULT_SCOPES = ["messages:create", "messages:read", "runs:stop"];

export default function OpenApiPage() {
  const [publications, setPublications] = useState<OpenApiPublication[]>([]);
  const [invocations, setInvocations] = useState<OpenApiInvocation[]>([]);
  const [createdKey, setCreatedKey] = useState("");

  const load = async () => {
    const [nextPublications, nextInvocations] = await Promise.all([
      openApiAdminApi.listPublications(),
      openApiAdminApi.listInvocations(),
    ]);
    setPublications(nextPublications);
    setInvocations(nextInvocations);
  };

  useEffect(() => {
    void load();
  }, []);

  const handleCreatePublication = async (values: any) => {
    await openApiAdminApi.createPublication({
      ...values,
      allowed_scopes: DEFAULT_SCOPES,
    });
    message.success("Published");
    await load();
  };

  const handleCreateKey = async (values: any) => {
    const app = await openApiAdminApi.createExternalApp({ name: values.app_name });
    const key = await openApiAdminApi.createApiKey({
      app_id: app.id,
      publication_id: values.publication_id,
      scopes: ["messages:create"],
    });
    setCreatedKey(key.plaintext_key);
    message.success("Key created");
    await load();
  };

  return (
    <div className={styles.page}>
      <Space align="center" className={styles.header}>
        <RadioTower size={20} />
        <Typography.Title level={3}>Open API</Typography.Title>
        <Button icon={<RefreshCcw size={14} />} onClick={() => void load()} />
      </Space>
      {createdKey && (
        <Alert
          type="success"
          showIcon
          message="Copy this key now. It will not be shown again."
          description={<Typography.Text copyable>{createdKey}</Typography.Text>}
        />
      )}
      <Card title="Published targets">
        <Form layout="inline" onFinish={handleCreatePublication}>
          <Form.Item name="public_id" rules={[{ required: true }]}>
            <Input placeholder="public id" />
          </Form.Item>
          <Form.Item name="target_type" rules={[{ required: true }]}>
            <Select
              style={{ width: 140 }}
              options={[
                { value: "agent", label: "Expert" },
                { value: "expert_team", label: "Expert team" },
              ]}
            />
          </Form.Item>
          <Form.Item name="target_id" rules={[{ required: true }]}>
            <Input placeholder="agent_id or team_id" />
          </Form.Item>
          <Form.Item name="name" rules={[{ required: true }]}>
            <Input placeholder="name" />
          </Form.Item>
          <Button htmlType="submit" type="primary">Publish</Button>
        </Form>
        <Table
          rowKey="id"
          dataSource={publications}
          columns={[
            { title: "Public ID", dataIndex: "public_id" },
            { title: "Type", dataIndex: "target_type" },
            { title: "Target", dataIndex: "target_id" },
            { title: "Status", dataIndex: "status" },
          ]}
        />
      </Card>
      <Card title="External app keys">
        <Form layout="inline" onFinish={handleCreateKey}>
          <Form.Item name="app_name" rules={[{ required: true }]}>
            <Input prefix={<KeyRound size={14} />} placeholder="app name" />
          </Form.Item>
          <Form.Item name="publication_id" rules={[{ required: true }]}>
            <Select
              style={{ width: 240 }}
              options={publications.map((publication) => ({
                value: publication.id,
                label: publication.public_id,
              }))}
            />
          </Form.Item>
          <Button htmlType="submit">Create key</Button>
        </Form>
      </Card>
      <Card title="Recent invocations">
        <Table
          rowKey="id"
          dataSource={invocations}
          columns={[
            { title: "Target", dataIndex: "target_id" },
            { title: "Status", dataIndex: "status" },
            { title: "Code", dataIndex: "status_code" },
            { title: "Latency", dataIndex: "latency_ms" },
          ]}
        />
      </Card>
    </div>
  );
}
```

Create `console/src/pages/Settings/OpenApi/index.module.less`:

```less
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header {
  justify-content: space-between;
}
```

- [ ] **Step 8: Add admin route and nav**

In `console/src/layouts/AdminLayout/index.tsx`, add lazy import:

```ts
const OpenApiPage = lazyImportWithRetry("../../pages/Settings/OpenApi");
```

Add path key:

```ts
"/admin/open-api": "open-api",
```

Add route:

```tsx
<Route path="open-api" element={<OpenApiPage />} />
```

In `console/src/layouts/constants.ts`, add:

```ts
"open-api": "/admin/open-api",
```

In `console/src/layouts/Sidebar.tsx`, add an admin settings menu item with a `RadioTower` or `KeyRound` icon and label `Open API`.

- [ ] **Step 9: Run frontend tests**

Run:

```bash
cd console
npm run test:run -- src/api/config.test.ts pages/Settings/OpenApi/OpenApi.test.tsx
npm exec -- tsc -b --noEmit
```

Expected: PASS.

- [ ] **Step 10: Commit frontend management UI**

```bash
git add console/src/api/config.ts console/src/api/config.test.ts console/src/api/types/openApi.ts console/src/api/modules/openApi.ts console/src/pages/Settings/OpenApi console/src/layouts/AdminLayout/index.tsx console/src/layouts/Sidebar.tsx console/src/layouts/constants.ts
git commit -m "feat: add open api admin page"
```

### Task 7: Integration Verification And Safety Pass

**Files:**
- Modify: `tests/unit/app/test_open_api_router.py`
- Modify: `tests/unit/app/test_open_api_auth.py`

- [ ] **Step 1: Add cross-target denial test**

Add a test proving a key bound to `pub-1` cannot call `pub-2`:

```python
def test_open_api_key_bound_to_one_publication_cannot_call_another(monkeypatch):
    from qwenpaw.app.open_api.auth import authenticate_open_api_request, hash_open_api_key

    key_hash = hash_open_api_key("qp_live_one")

    class FakeRepo:
        def get_api_key_by_hash(self, value):
            return {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "scopes": ["messages:create"],
                "status": "active",
                "expires_at": None,
            }

        def get_external_app(self, app_id):
            return {"id": app_id, "owner_user_id": "7", "status": "enabled", "ip_allowlist": []}

        def get_publication(self, publication_id):
            return {
                "id": "pub-1",
                "public_id": "first",
                "target_type": "agent",
                "target_id": "default",
                "owner_user_id": "7",
                "status": "enabled",
                "allowed_scopes": ["messages:create"],
            }

        def mark_api_key_used(self, key_id, ip):
            pass

    request = SimpleNamespace(
        headers={"authorization": "Bearer qp_live_one"},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )
    monkeypatch.setattr("qwenpaw.app.open_api.auth.get_open_api_repository", lambda: FakeRepo())
    context = authenticate_open_api_request(request, required_scope="messages:create")

    assert context.publication["id"] == "pub-1"
    assert request.state.open_publication_id != "pub-2"
    assert key_hash.startswith("sha256:")
```

- [ ] **Step 2: Run backend verification**

Run:

```bash
pytest tests/unit/app/storage/repos/test_open_api_repo.py tests/unit/app/test_open_api_auth.py tests/unit/app/test_open_api_admin.py tests/unit/app/test_open_api_router.py tests/unit/app/test_chat_access.py tests/unit/app/test_expert_teams.py tests/unit/app/test_console_user_binding.py -q
git diff --check
```

Expected: PASS and no diff-check output.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd console
npm run test:run -- src/api/config.test.ts pages/Settings/OpenApi/OpenApi.test.tsx
npm exec -- tsc -b --noEmit
```

Expected: PASS.

- [ ] **Step 4: Manual Open API smoke**

Start the local service using the repo's established flow, then create a publication, app, and key from the admin page. Call the endpoint:

```bash
curl -N \
  -H "Authorization: Bearer qp_live_REPLACE_WITH_CREATED_KEY" \
  -H "Content-Type: application/json" \
  -d '{"external_user_id":"customer-1","external_session_id":"ticket-1","message":"你好，如何联系人工客服？","stream":true}' \
  http://127.0.0.1:18088/api/open/v1/targets/cs-agent/messages
```

Expected:

```text
HTTP 200
X-QwenPaw-Chat-Id is present
X-QwenPaw-Session-Id starts with open:
X-QwenPaw-Open-Invocation-Id is present
```

- [ ] **Step 5: Commit safety verification updates**

```bash
git add tests/unit/app/test_open_api_router.py tests/unit/app/test_open_api_auth.py
git commit -m "test: cover open api safety boundaries"
```

### Self-Review

- Spec coverage: Tasks 1-3 cover publishing, API keys, and admin controls. Tasks 4-5 cover expert and expert-team calls. Task 6 covers the admin UI. Task 7 covers safety and verification.
- Placeholder scan: The plan uses concrete files, commands, models, routes, and test snippets. It does not use unresolved placeholder wording.
- Type consistency: `target_type`, `target_id`, `public_id`, `owner_user_id`, `app_id`, `publication_id`, and scope strings are consistent across schema, repository, auth, route, and frontend tasks.
