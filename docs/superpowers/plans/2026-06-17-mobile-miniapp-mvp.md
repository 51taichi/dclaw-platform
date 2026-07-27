# Mobile Mini Program MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first employee-facing DClaw mini-program MVP for task creation, task tracking, Tool Guard confirmation, knowledge search, and artifact viewing.

**Architecture:** Keep the existing web and desktop console unchanged. Add a user-scoped mobile facade under `/api/user/mobile/*` so the mini-program reads compact, mobile-shaped payloads instead of stitching together desktop web calls. Build the client as a Taro React/TypeScript mini-program under `miniapp/`, targeting WeChat mini-program first and intentionally excluding mobile Web from V1.

**Tech Stack:** FastAPI, Pydantic, pytest, existing qwenpaw chat/approval/workspace services, Taro React, TypeScript, Sass, WeChat mini-program APIs.

---

## Confirmed Product Scope

The source of truth for screens and business mapping is `docs/mobile-miniapp-v1-mapping.md`.

V1 serves ordinary employees only. It does not include administrator features, user management, model configuration, MCP/plugin management, enterprise knowledge connector setup, AIGC Studio editing, or mobile Web.

The confirmation feature is Tool Guard execution confirmation. Use `待确认操作`, `AI确认`, and `确认执行` in the UI. Do not use OA approval language such as leave, reimbursement, travel, or admin approval.

Style direction is "风格4 / 伙伴陪伴风". Static assets in the prototype may stay as placeholders during implementation, but all asset slots must be named so the original DClaw logo and mascot files can replace them before production release.

## External Framework Decision

Use Taro React for V1 because the existing console is React/TypeScript and Taro officially supports React/Vue development for WeChat mini-programs, H5, React Native, and other mini-program platforms: https://docs.taro.zone/docs/

For V1 builds, only ship the WeChat mini-program target. Do not create or promote an H5/mobile Web target.

Before implementing streaming and file-download behavior, verify these official WeChat API pages in the implementation environment:

- `https://developers.weixin.qq.com/miniprogram/dev/api/network/request/wx.request.html`
- `https://developers.weixin.qq.com/miniprogram/dev/api/network/download/wx.downloadFile.html`
- `https://developers.weixin.qq.com/miniprogram/dev/api/share/wx.shareFileMessage.html`

## File Structure

Backend files:

- Create `src/qwenpaw/app/mobile/__init__.py`: exports mobile DTOs and service helpers.
- Create `src/qwenpaw/app/mobile/models.py`: Pydantic request/response models for mobile facade APIs.
- Create `src/qwenpaw/app/mobile/service.py`: pure helpers for display status derivation, approval serialization, task summary shaping, and artifact summary shaping.
- Create `src/qwenpaw/app/routers/mobile.py`: user-scoped mobile facade router mounted under `/api/user/mobile`.
- Modify `src/qwenpaw/app/routers/__init__.py`: include `mobile_router` in `user_api_router`.
- Create `tests/unit/app/test_mobile_models.py`: pure unit tests for status derivation and serialization.
- Create `tests/unit/app/test_mobile_router.py`: router-level tests with mocked services and access checks.

Mini-program files:

- Create `miniapp/package.json`: Taro React project scripts for WeChat mini-program builds.
- Create `miniapp/project.config.json`: WeChat developer tool project config.
- Create `miniapp/config/index.ts`, `miniapp/config/dev.ts`, `miniapp/config/prod.ts`: Taro build config.
- Create `miniapp/src/app.ts`, `miniapp/src/app.config.ts`, `miniapp/src/app.scss`: app entry, tab routes, global styles.
- Create `miniapp/src/theme/tokens.scss`: style direction 4 tokens.
- Create `miniapp/src/assets/README.md`: named asset slots and replacement rules.
- Create `miniapp/src/services/api.ts`: Taro request wrapper with auth headers, API base, and error parsing.
- Create `miniapp/src/services/auth.ts`: token persistence and login/verify helpers.
- Create `miniapp/src/services/mobile.ts`: typed calls to `/api/user/mobile/*`.
- Create `miniapp/src/services/consoleChat.ts`: task message send/stop helpers around existing `/api/user/console/chat` and `/api/user/console/chat/stop`.
- Create `miniapp/src/stores/mobileStore.ts`: lightweight shared state for token, current task, and badge counts.
- Create `miniapp/src/components/AppShell/index.tsx` and `index.scss`: phone-safe page frame, status spacing, bottom safe area.
- Create `miniapp/src/components/TaskCard/index.tsx` and `index.scss`: repeated task row.
- Create `miniapp/src/components/ConfirmationCard/index.tsx` and `index.scss`: Tool Guard confirmation card.
- Create `miniapp/src/components/AssetImage/index.tsx` and `index.scss`: slot-based mascot/logo image component.
- Create page folders under `miniapp/src/pages/`: `workbench`, `create-task`, `tasks`, `task-detail`, `confirmations`, `knowledge`, `result`, `me`, and `login`.

Documentation files:

- Modify `docs/mobile-miniapp-v1-mapping.md` only when an implementation discovery changes an interface or field name.
- Modify this plan after each completed task by checking off the exact steps that were executed.

## Backend Contract

All mobile facade endpoints are user-facing APIs and must be mounted through `user_api_router`, producing paths under `/api/user/mobile/*`.

Required endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/mobile/workbench` | Employee summary: greeting data, task summaries, pending count, recent result summaries |
| `GET` | `/mobile/tasks` | Current user's task summaries |
| `GET` | `/mobile/tasks/{chat_id}` | Task detail bundle: chat history, status, confirmations, artifacts |
| `GET` | `/mobile/confirmations` | Current user's visible Tool Guard confirmations |
| `POST` | `/mobile/confirmations/{request_id}/approve` | Approve a Tool Guard request |
| `POST` | `/mobile/confirmations/{request_id}/deny` | Reject a Tool Guard request |
| `GET` | `/mobile/results/{chat_id}` | Artifact summaries for a task |

Use existing ownership enforcement:

- Task reads must call or reuse `ensure_chat_access(request, chat_id)`.
- Confirmation actions must preserve the current approval router rule: `pending.root_session_id` must match the submitted root session, then `ensure_chat_access` must verify ownership.
- Knowledge search remains on existing `/api/user/workspace/knowledge/search`; the mobile facade does not invent knowledge results.

## Task 1: Backend Mobile Models And Pure Helpers

**Files:**

- Create: `src/qwenpaw/app/mobile/__init__.py`
- Create: `src/qwenpaw/app/mobile/models.py`
- Create: `src/qwenpaw/app/mobile/service.py`
- Create: `tests/unit/app/test_mobile_models.py`

- [x] **Step 1: Write failing model/helper tests**

Create `tests/unit/app/test_mobile_models.py` with tests for display status and approval serialization:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.mobile.service import (
    derive_mobile_display_status,
    serialize_pending_confirmation,
)


def test_running_status_wins_over_artifacts() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="running",
            task_status="completed",
            pending_confirmation_count=0,
            artifact_count=2,
        )
        == "running"
    )


def test_pending_confirmation_wins_over_idle() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status=None,
            pending_confirmation_count=1,
            artifact_count=0,
        )
        == "pending_confirmation"
    )


def test_completed_can_be_derived_from_artifacts() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status=None,
            pending_confirmation_count=0,
            artifact_count=1,
        )
        == "completed"
    )


def test_failed_task_status_is_preserved() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status="failed",
            pending_confirmation_count=0,
            artifact_count=0,
        )
        == "failed"
    )


def test_approval_serialization_preserves_tool_guard_fields() -> None:
    approval = SimpleNamespace(
        request_id="req-1",
        session_id="child-session",
        root_session_id="root-session",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="MEDIUM",
        findings_count=2,
        result_summary="包含业务数据，需本人确认",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={
            "tool_call": {
                "input": {
                    "file": "sales_analysis.xlsx",
                    "scope": "全部数据",
                },
            },
        },
    )

    payload = serialize_pending_confirmation(approval)

    assert payload.request_id == "req-1"
    assert payload.root_session_id == "root-session"
    assert payload.tool_name == "workspace.export"
    assert payload.severity == "MEDIUM"
    assert payload.findings_summary == "包含业务数据，需本人确认"
    assert payload.tool_params == {
        "file": "sales_analysis.xlsx",
        "scope": "全部数据",
    }
```

- [x] **Step 2: Run the tests and confirm failure**

Run:

```bash
pytest tests/unit/app/test_mobile_models.py -q
```

Expected result: import failure for `qwenpaw.app.mobile`.

- [x] **Step 3: Implement mobile DTOs**

Create `src/qwenpaw/app/mobile/models.py` with these response models:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MobileDisplayStatus = Literal[
    "running",
    "pending_confirmation",
    "completed",
    "failed",
    "idle",
]


class MobileTaskSummary(BaseModel):
    id: str
    session_id: str
    name: str
    runtime_status: str | None = None
    task_status: str | None = None
    display_status: MobileDisplayStatus
    pending_confirmation_count: int = 0
    artifact_count: int = 0
    updated_at: float | None = None


class MobilePendingConfirmation(BaseModel):
    request_id: str
    session_id: str
    root_session_id: str
    owner_agent_id: str | None = None
    agent_id: str
    tool_name: str
    severity: str
    findings_count: int = 0
    findings_summary: str = ""
    tool_params: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    timeout_seconds: int


class MobileArtifactSummary(BaseModel):
    name: str
    path: str
    size: int | None = None
    modified_time: str | None = None
    kind: str = "file"


class MobileWorkbenchResponse(BaseModel):
    user_id: str
    pending_confirmation_count: int
    running_task_count: int
    recent_tasks: list[MobileTaskSummary]
    recent_results: list[MobileArtifactSummary]


class MobileTaskDetailResponse(BaseModel):
    task: MobileTaskSummary
    messages: list[dict[str, Any]]
    confirmations: list[MobilePendingConfirmation]
    artifacts: list[MobileArtifactSummary]


class MobileConfirmationActionResponse(BaseModel):
    success: bool
    message: str
    request_id: str
    tool_name: str | None = None
```

- [x] **Step 4: Implement pure helper functions**

Create `src/qwenpaw/app/mobile/service.py`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .models import (
    MobileArtifactSummary,
    MobileDisplayStatus,
    MobilePendingConfirmation,
)


def derive_mobile_display_status(
    *,
    runtime_status: str | None,
    task_status: str | None,
    pending_confirmation_count: int,
    artifact_count: int,
) -> MobileDisplayStatus:
    if runtime_status == "running":
        return "running"
    if pending_confirmation_count > 0:
        return "pending_confirmation"
    if task_status == "failed":
        return "failed"
    if task_status == "completed" or artifact_count > 0:
        return "completed"
    return "idle"


def _extract_tool_params(approval: Any) -> dict[str, Any]:
    extra = getattr(approval, "extra", None)
    if not isinstance(extra, dict):
        return {}
    tool_call = extra.get("tool_call")
    if isinstance(tool_call, dict) and isinstance(tool_call.get("input"), dict):
        return tool_call["input"]
    return {}


def serialize_pending_confirmation(approval: Any) -> MobilePendingConfirmation:
    return MobilePendingConfirmation(
        request_id=str(getattr(approval, "request_id", "")),
        session_id=str(getattr(approval, "session_id", "")),
        root_session_id=str(getattr(approval, "root_session_id", "")),
        owner_agent_id=getattr(approval, "owner_agent_id", None),
        agent_id=str(getattr(approval, "agent_id", "")),
        tool_name=str(getattr(approval, "tool_name", "")),
        severity=str(getattr(approval, "severity", "")),
        findings_count=int(getattr(approval, "findings_count", 0) or 0),
        findings_summary=str(
            getattr(approval, "findings_summary", None)
            or getattr(approval, "result_summary", "")
            or ""
        ),
        tool_params=_extract_tool_params(approval),
        created_at=float(getattr(approval, "created_at", 0) or 0),
        timeout_seconds=int(getattr(approval, "timeout_seconds", 0) or 0),
    )


def serialize_artifact_summary(file_info: Any) -> MobileArtifactSummary:
    name = str(getattr(file_info, "name", "") or getattr(file_info, "filename", ""))
    path = str(getattr(file_info, "path", "") or name)
    return MobileArtifactSummary(
        name=name,
        path=path,
        size=getattr(file_info, "size", None),
        modified_time=getattr(file_info, "modified_time", None),
        kind="file",
    )
```

- [x] **Step 5: Export DTOs and helpers**

Create `src/qwenpaw/app/mobile/__init__.py`:

```python
# -*- coding: utf-8 -*-
"""Mobile mini-program facade helpers."""

from .models import (
    MobileArtifactSummary,
    MobileConfirmationActionResponse,
    MobilePendingConfirmation,
    MobileTaskDetailResponse,
    MobileTaskSummary,
    MobileWorkbenchResponse,
)
from .service import (
    derive_mobile_display_status,
    serialize_artifact_summary,
    serialize_pending_confirmation,
)

__all__ = [
    "MobileArtifactSummary",
    "MobileConfirmationActionResponse",
    "MobilePendingConfirmation",
    "MobileTaskDetailResponse",
    "MobileTaskSummary",
    "MobileWorkbenchResponse",
    "derive_mobile_display_status",
    "serialize_artifact_summary",
    "serialize_pending_confirmation",
]
```

- [x] **Step 6: Run helper tests**

Run:

```bash
pytest tests/unit/app/test_mobile_models.py -q
```

Expected result: all tests pass.

## Task 2: Backend Mobile Router

**Files:**

- Create: `src/qwenpaw/app/routers/mobile.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Create: `tests/unit/app/test_mobile_router.py`

- [x] **Step 1: Write failing router tests**

Create `tests/unit/app/test_mobile_router.py` with focused tests for registration and user filtering. The tests should mock service dependencies rather than run a real agent.

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.mobile.models import MobilePendingConfirmation
from qwenpaw.app.routers import mobile as mobile_router


def test_mobile_router_prefix_is_user_scoped() -> None:
    assert mobile_router.router.prefix == "/mobile"


@pytest.mark.asyncio
async def test_mobile_confirmations_filters_inaccessible_approvals(monkeypatch) -> None:
    accessible = SimpleNamespace(
        request_id="req-visible",
        session_id="root-visible",
        root_session_id="root-visible",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="LOW",
        findings_count=0,
        result_summary="visible",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={},
    )
    hidden = SimpleNamespace(
        request_id="req-hidden",
        session_id="root-hidden",
        root_session_id="root-hidden",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="LOW",
        findings_count=0,
        result_summary="hidden",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={},
    )

    class FakeApprovalService:
        async def list_all_pending(self):
            return [accessible, hidden]

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        if chat_id == "root-hidden":
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        return {"id": chat_id, "session_id": chat_id}

    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_confirmations(request)

    assert [item.request_id for item in response] == ["req-visible"]
    assert isinstance(response[0], MobilePendingConfirmation)
```

- [x] **Step 2: Run router tests and confirm failure**

Run:

```bash
pytest tests/unit/app/test_mobile_router.py -q
```

Expected result: import failure for `qwenpaw.app.routers.mobile`.

- [x] **Step 3: Implement `mobile.py` router skeleton**

Create `src/qwenpaw/app/routers/mobile.py` with all endpoint signatures, then replace the initial task/result skeletons in Step 6 of this task:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..approvals import get_approval_service
from ..chat_access import current_user_id, ensure_chat_access
from ..mobile.models import (
    MobileArtifactSummary,
    MobileConfirmationActionResponse,
    MobilePendingConfirmation,
    MobileTaskDetailResponse,
    MobileTaskSummary,
    MobileWorkbenchResponse,
)
from ..mobile.service import serialize_pending_confirmation
from ...security.tool_guard.approval import ApprovalDecision


router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/confirmations", response_model=list[MobilePendingConfirmation])
async def get_mobile_confirmations(request: Request) -> list[MobilePendingConfirmation]:
    approval_svc = get_approval_service()
    pending = await approval_svc.list_all_pending()
    visible: list[MobilePendingConfirmation] = []
    for item in pending:
        try:
            ensure_chat_access(request, item.root_session_id, allow_admin=False)
        except HTTPException:
            continue
        visible.append(serialize_pending_confirmation(item))
    return visible


@router.post(
    "/confirmations/{request_id}/approve",
    response_model=MobileConfirmationActionResponse,
)
async def approve_mobile_confirmation(
    request_id: str,
    request: Request,
) -> MobileConfirmationActionResponse:
    approval_svc = get_approval_service()
    pending = await approval_svc.get_request(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    ensure_chat_access(request, pending.root_session_id, allow_admin=False)
    resolved = await approval_svc.resolve_request(
        request_id,
        ApprovalDecision.APPROVED,
    )
    return MobileConfirmationActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' approved, executing...",
        request_id=request_id,
        tool_name=resolved.tool_name,
    )


@router.post(
    "/confirmations/{request_id}/deny",
    response_model=MobileConfirmationActionResponse,
)
async def deny_mobile_confirmation(
    request_id: str,
    request: Request,
) -> MobileConfirmationActionResponse:
    approval_svc = get_approval_service()
    pending = await approval_svc.get_request(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    ensure_chat_access(request, pending.root_session_id, allow_admin=False)
    resolved = await approval_svc.resolve_request(
        request_id,
        ApprovalDecision.DENIED,
    )
    return MobileConfirmationActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' denied",
        request_id=request_id,
        tool_name=resolved.tool_name,
    )


@router.get("/workbench", response_model=MobileWorkbenchResponse)
async def get_mobile_workbench(request: Request) -> MobileWorkbenchResponse:
    return MobileWorkbenchResponse(
        user_id=current_user_id(request),
        pending_confirmation_count=len(await get_mobile_confirmations(request)),
        running_task_count=0,
        recent_tasks=[],
        recent_results=[],
    )


@router.get("/tasks", response_model=list[MobileTaskSummary])
async def get_mobile_tasks(_request: Request) -> list[MobileTaskSummary]:
    return []


@router.get("/tasks/{chat_id}", response_model=MobileTaskDetailResponse)
async def get_mobile_task_detail(
    chat_id: str,
    request: Request,
) -> MobileTaskDetailResponse:
    ensure_chat_access(request, chat_id, allow_admin=False)
    raise HTTPException(status_code=501, detail="Mobile task detail not wired")


@router.get("/results/{chat_id}", response_model=list[MobileArtifactSummary])
async def get_mobile_results(
    chat_id: str,
    request: Request,
) -> list[MobileArtifactSummary]:
    ensure_chat_access(request, chat_id, allow_admin=False)
    return []
```

- [x] **Step 4: Register router under user APIs**

Modify `src/qwenpaw/app/routers/__init__.py`:

```python
from .mobile import router as mobile_router
```

Add it to the user API router block:

```python
user_api_router.include_router(mobile_router)
```

- [x] **Step 5: Run router tests**

Run:

```bash
pytest tests/unit/app/test_mobile_router.py -q
```

Expected result: all tests pass.

- [x] **Step 6: Replace skeleton task/result endpoints with real service wiring**

Use existing service paths:

- `GET /chats?channel=console` behavior from `src/qwenpaw/app/runner/api.py`.
- Approval metadata from `get_approval_service()`.
- Artifact behavior from existing workspace artifact route and `workspaceApi.listArtifacts` contract.
- Chat access through `ensure_chat_access`.

Keep the endpoint shape stable. If a dependency is hard to call directly, add a small helper in `src/qwenpaw/app/mobile/service.py` rather than importing frontend-oriented code.

- [x] **Step 7: Add ownership tests**

Add tests to `tests/unit/app/test_mobile_router.py` proving:

- `GET /mobile/confirmations` hides another user's approval.
- `POST /mobile/confirmations/{request_id}/approve` calls `ensure_chat_access(..., allow_admin=False)`.
- `GET /mobile/results/{chat_id}` calls `ensure_chat_access(..., allow_admin=False)`.

- [x] **Step 8: Run backend verification**

Run:

```bash
pytest tests/unit/app/test_mobile_models.py tests/unit/app/test_mobile_router.py -q
python -m py_compile src/qwenpaw/app/mobile/models.py src/qwenpaw/app/mobile/service.py src/qwenpaw/app/routers/mobile.py
```

Expected result: all tests pass and py_compile exits with code 0.

## Task 3: Mini-Program Scaffold

**Files:**

- Create: `miniapp/package.json`
- Create: `miniapp/project.config.json`
- Create: `miniapp/config/index.ts`
- Create: `miniapp/config/dev.ts`
- Create: `miniapp/config/prod.ts`
- Create: `miniapp/src/app.ts`
- Create: `miniapp/src/app.config.ts`
- Create: `miniapp/src/app.scss`
- Create: `miniapp/src/theme/tokens.scss`
- Create: `miniapp/src/assets/README.md`

- [x] **Step 1: Generate a Taro React TypeScript app**

Run from repo root:

```bash
npx @tarojs/cli@latest init miniapp
```

Use these choices:

- Framework: React
- Language: TypeScript
- CSS preprocessor: Sass
- Package manager: npm
- Template: default

If the CLI creates demo pages, replace them in Tasks 6-10. Keep the app under `miniapp/`.

- [x] **Step 2: Add package scripts**

Ensure `miniapp/package.json` contains these scripts:

```json
{
  "scripts": {
    "dev:weapp": "taro build --type weapp --watch",
    "build:weapp": "taro build --type weapp",
    "typecheck": "tsc --noEmit",
    "lint": "eslint ."
  }
}
```

- [x] **Step 3: Configure pages and tab bar**

Set `miniapp/src/app.config.ts` to include these pages:

```ts
export default defineAppConfig({
  pages: [
    "pages/workbench/index",
    "pages/create-task/index",
    "pages/tasks/index",
    "pages/task-detail/index",
    "pages/confirmations/index",
    "pages/knowledge/index",
    "pages/result/index",
    "pages/me/index",
    "pages/login/index",
  ],
  window: {
    backgroundTextStyle: "light",
    navigationBarBackgroundColor: "#fffaf3",
    navigationBarTitleText: "DClaw",
    navigationBarTextStyle: "black",
  },
  tabBar: {
    color: "#6f7480",
    selectedColor: "#ff5a1f",
    backgroundColor: "#ffffff",
    list: [
      { pagePath: "pages/workbench/index", text: "工作台" },
      { pagePath: "pages/tasks/index", text: "任务" },
      { pagePath: "pages/confirmations/index", text: "确认" },
      { pagePath: "pages/me/index", text: "我" },
    ],
  },
});
```

- [x] **Step 4: Add style tokens for style direction 4**

Create `miniapp/src/theme/tokens.scss`:

```scss
$color-text: #19191b;
$color-muted: #777d89;
$color-line: #eceef2;
$color-page: #fffaf3;
$color-card: #ffffff;
$color-orange: #ff5a1f;
$color-orange-deep: #ea4817;
$color-blue: #2f80ed;
$color-green: #26b99a;
$color-yellow: #ffbf34;
$radius-card: 16px;
$radius-button: 14px;
$shadow-soft: 0 12px 36px rgba(32, 28, 24, 0.1);
```

- [x] **Step 5: Add asset replacement manifest**

Create `miniapp/src/assets/README.md`:

```markdown
# DClaw Mini-Program Asset Slots

Replace these placeholders with original DClaw assets before production release.

| Slot | File |
| --- | --- |
| Logo | `dclaw-logo.png` |
| Mascot hero | `mascot-hero.png` |
| Tab center mascot | `mascot-tab.png` |
| Task sticker | `mascot-task.png` |
| Confirmation banner mascot | `mascot-confirm.png` |
| Empty state mascot | `mascot-empty.png` |
| Result cover mascot | `mascot-result.png` |
```

- [x] **Step 6: Verify scaffold build**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: TypeScript and WeChat build pass.

## Task 4: Mini-Program API Client And Auth

**Files:**

- Create: `miniapp/src/services/api.ts`
- Create: `miniapp/src/services/auth.ts`
- Create: `miniapp/src/services/mobile.ts`
- Create: `miniapp/src/services/consoleChat.ts`
- Create: `miniapp/src/stores/mobileStore.ts`
- Create: `miniapp/src/pages/login/index.tsx`
- Create: `miniapp/src/pages/login/index.scss`
- Create: `miniapp/src/pages/login/index.config.ts`

- [x] **Step 1: Implement token storage**

Create `miniapp/src/services/auth.ts`:

```ts
import Taro from "@tarojs/taro";

const TOKEN_KEY = "qwenpaw_auth_token";

export function getAuthToken(): string {
  return Taro.getStorageSync(TOKEN_KEY) || "";
}

export function setAuthToken(token: string): void {
  Taro.setStorageSync(TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  Taro.removeStorageSync(TOKEN_KEY);
}
```

- [x] **Step 2: Implement request wrapper**

Create `miniapp/src/services/api.ts`:

```ts
import Taro from "@tarojs/taro";
import { clearAuthToken, getAuthToken } from "./auth";

const API_BASE = process.env.TARO_APP_API_BASE || "";

function buildUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}/api/user${normalized}`;
}

export async function request<T>(
  path: string,
  options: Taro.request.Option = {},
): Promise<T> {
  const token = getAuthToken();
  const header: Record<string, string> = {
    ...(options.header as Record<string, string> | undefined),
  };
  if (token) {
    header.Authorization = `Bearer ${token}`;
  }

  const response = await Taro.request<T>({
    ...options,
    url: buildUrl(path),
    header,
  });

  if (response.statusCode === 401) {
    clearAuthToken();
    Taro.redirectTo({ url: "/pages/login/index" });
    throw new Error("Not authenticated");
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    const message =
      typeof response.data === "string"
        ? response.data
        : JSON.stringify(response.data);
    throw new Error(message || `Request failed: ${response.statusCode}`);
  }

  return response.data as T;
}
```

- [x] **Step 3: Implement mobile API types and calls**

Create `miniapp/src/services/mobile.ts` with TypeScript interfaces matching `src/qwenpaw/app/mobile/models.py` and functions:

```ts
import { request } from "./api";

export type MobileDisplayStatus =
  | "running"
  | "pending_confirmation"
  | "completed"
  | "failed"
  | "idle";

export interface MobileTaskSummary {
  id: string;
  session_id: string;
  name: string;
  runtime_status?: string | null;
  task_status?: string | null;
  display_status: MobileDisplayStatus;
  pending_confirmation_count: number;
  artifact_count: number;
  updated_at?: number | null;
}

export interface MobilePendingConfirmation {
  request_id: string;
  session_id: string;
  root_session_id: string;
  owner_agent_id?: string | null;
  agent_id: string;
  tool_name: string;
  severity: string;
  findings_count: number;
  findings_summary: string;
  tool_params: Record<string, unknown>;
  created_at: number;
  timeout_seconds: number;
}

export interface MobileArtifactSummary {
  name: string;
  path: string;
  size?: number | null;
  modified_time?: string | null;
  kind: string;
}

export interface MobileWorkbenchResponse {
  user_id: string;
  pending_confirmation_count: number;
  running_task_count: number;
  recent_tasks: MobileTaskSummary[];
  recent_results: MobileArtifactSummary[];
}

export function getWorkbench() {
  return request<MobileWorkbenchResponse>("/mobile/workbench");
}

export function getTasks() {
  return request<MobileTaskSummary[]>("/mobile/tasks");
}

export function getConfirmations() {
  return request<MobilePendingConfirmation[]>("/mobile/confirmations");
}

export function approveConfirmation(requestId: string) {
  return request(`/mobile/confirmations/${encodeURIComponent(requestId)}/approve`, {
    method: "POST",
  });
}

export function denyConfirmation(requestId: string) {
  return request(`/mobile/confirmations/${encodeURIComponent(requestId)}/deny`, {
    method: "POST",
  });
}

export function getResults(chatId: string) {
  return request<MobileArtifactSummary[]>(
    `/mobile/results/${encodeURIComponent(chatId)}`,
  );
}
```

- [x] **Step 4: Implement login page**

Login can reuse existing username/password auth in V1. WeChat `code2session` binding is outside this MVP because the current backend already has token auth.

Create a compact DClaw login page that calls root auth endpoint `/api/auth/login`, stores token through `setAuthToken`, and redirects to Workbench. The UI must say `登录 DClaw` and must not mention admin.

- [x] **Step 5: Verify client types**

Run:

```bash
cd miniapp
npm run typecheck
```

Expected result: TypeScript passes.

## Task 5: Shared Components And Visual System

**Files:**

- Create: `miniapp/src/components/AppShell/index.tsx`
- Create: `miniapp/src/components/AppShell/index.scss`
- Create: `miniapp/src/components/TaskCard/index.tsx`
- Create: `miniapp/src/components/TaskCard/index.scss`
- Create: `miniapp/src/components/ConfirmationCard/index.tsx`
- Create: `miniapp/src/components/ConfirmationCard/index.scss`
- Create: `miniapp/src/components/AssetImage/index.tsx`
- Create: `miniapp/src/components/AssetImage/index.scss`

- [x] **Step 1: Implement `AssetImage` slot component**

The component must accept a slot name and render a local placeholder path. Keep all slot names aligned with `miniapp/src/assets/README.md` so original static resources can replace them without changing page code.

- [x] **Step 2: Implement `AppShell`**

The shell should provide:

- Page background `#fffaf3`.
- Top safe spacing.
- Bottom safe spacing.
- No marketing hero or mobile Web cues.

- [x] **Step 3: Implement `TaskCard`**

The task card props must be:

```ts
interface TaskCardProps {
  task: MobileTaskSummary;
  onTap: (task: MobileTaskSummary) => void;
}
```

Map statuses:

- `running` -> `处理中`
- `pending_confirmation` -> `待确认`
- `completed` -> `已完成`
- `failed` -> `失败`
- `idle` -> `未开始`

- [x] **Step 4: Implement `ConfirmationCard`**

The confirmation card props must be:

```ts
interface ConfirmationCardProps {
  confirmation: MobilePendingConfirmation;
  onApprove: (requestId: string) => void;
  onDeny: (requestId: string) => void;
}
```

Button text must be `拒绝` and `确认执行`.

- [x] **Step 5: Verify layout build**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: build passes.

## Task 6: Workbench And Create Task

**Files:**

- Create: `miniapp/src/pages/workbench/index.tsx`
- Create: `miniapp/src/pages/workbench/index.scss`
- Create: `miniapp/src/pages/workbench/index.config.ts`
- Create: `miniapp/src/pages/create-task/index.tsx`
- Create: `miniapp/src/pages/create-task/index.scss`
- Create: `miniapp/src/pages/create-task/index.config.ts`
- Modify: `miniapp/src/services/consoleChat.ts`

- [x] **Step 1: Build Workbench data load**

On page show, call `getWorkbench()` and render:

- Greeting.
- Hero create-task button.
- Shortcuts: `我的任务`, `知识搜索`, `AI确认`, `待确认操作`.
- Recent task list.

Badge count comes from `pending_confirmation_count`.

- [x] **Step 2: Build Create Task page**

The page must show:

- Current context: `DClaw 助手 · 企业空间`.
- Expert team line: `默认专家团队：销售支持`.
- Prompt textarea.
- Scenario chips that insert prompt text.
- Primary action `开始执行`.

- [x] **Step 3: Submit task using existing backend semantics**

For V1, submit in two calls:

1. `POST /api/user/chats` with `channel: "console"` and `meta.mode: "task"`.
2. `POST /api/user/console/chat` with the prompt and returned chat/session ids.

The payload must preserve:

```json
{
  "channel": "console",
  "meta": {
    "mode": "task",
    "agent_id": "default",
    "active_mode": "task",
    "expert_team_id": "sales-support"
  }
}
```

- [x] **Step 4: Poll after submit**

If streaming is not reliable in WeChat, route to Task Detail and poll `/api/user/mobile/tasks/{chat_id}` plus `/api/user/console/push-messages?session_id=...`.

- [x] **Step 5: Verify**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: build passes and Workbench/Create Task pages compile.

## Task 7: Task List And Task Detail

**Files:**

- Create: `miniapp/src/pages/tasks/index.tsx`
- Create: `miniapp/src/pages/tasks/index.scss`
- Create: `miniapp/src/pages/tasks/index.config.ts`
- Create: `miniapp/src/pages/task-detail/index.tsx`
- Create: `miniapp/src/pages/task-detail/index.scss`
- Create: `miniapp/src/pages/task-detail/index.config.ts`
- Modify: `miniapp/src/services/mobile.ts`
- Modify: `miniapp/src/services/consoleChat.ts`

- [x] **Step 1: Build Task List**

Call `getTasks()` on page show. Render only employee-owned task summaries returned by backend. Use `TaskCard`.

- [x] **Step 2: Build Task Detail**

Call `GET /api/user/mobile/tasks/{chat_id}`. Render:

- Message timeline.
- Runtime status.
- Inline pending confirmation card when present.
- Artifact entry when artifacts exist.
- Bottom prompt input.

- [x] **Step 3: Implement continue task**

Send follow-up prompts to `/api/user/console/chat`. Preserve `chat_id`, `session_id`, `agent_id`, and root session context.

- [x] **Step 4: Implement stop task**

Call `/api/user/console/chat/stop?chat_id=...` and refresh detail.

- [x] **Step 5: Verify**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: build passes and task pages compile.

## Task 8: Pending Confirmation Flow

**Files:**

- Create: `miniapp/src/pages/confirmations/index.tsx`
- Create: `miniapp/src/pages/confirmations/index.scss`
- Create: `miniapp/src/pages/confirmations/index.config.ts`
- Modify: `miniapp/src/components/ConfirmationCard/index.tsx`
- Modify: `miniapp/src/services/mobile.ts`

- [x] **Step 1: Build confirmation list**

Call `getConfirmations()` on page show. Empty state text: `暂无待确认操作`.

- [x] **Step 2: Render Tool Guard fields**

Each card must show:

- Tool name.
- Risk level.
- Finding summary.
- Parameter preview.
- Countdown based on `created_at + timeout_seconds`.

- [x] **Step 3: Implement approve/deny**

Call the mobile facade:

- Approve: `POST /api/user/mobile/confirmations/{request_id}/approve`
- Deny: `POST /api/user/mobile/confirmations/{request_id}/deny`

After action, remove the card from local state and refresh Workbench badge count.

- [x] **Step 4: Verify**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: build passes and confirmation actions typecheck.

## Task 9: Knowledge Search And Result Detail

**Files:**

- Create: `miniapp/src/pages/knowledge/index.tsx`
- Create: `miniapp/src/pages/knowledge/index.scss`
- Create: `miniapp/src/pages/knowledge/index.config.ts`
- Create: `miniapp/src/pages/result/index.tsx`
- Create: `miniapp/src/pages/result/index.scss`
- Create: `miniapp/src/pages/result/index.config.ts`
- Modify: `miniapp/src/services/mobile.ts`
- Create: `miniapp/src/services/knowledge.ts`

- [x] **Step 1: Implement knowledge service**

Create `miniapp/src/services/knowledge.ts`:

```ts
import { request } from "./api";

export interface KnowledgeHit {
  id?: string;
  title?: string;
  source?: string;
  snippet?: string;
  score?: number;
}

export interface KnowledgeSearchResponse {
  hits: KnowledgeHit[];
  semantic_enabled?: boolean;
  keyword_enabled?: boolean;
}

export function searchKnowledge(q: string, scope = "all", topK = 5) {
  const query = encodeURIComponent(q);
  return request<KnowledgeSearchResponse>(
    `/workspace/knowledge/search?q=${query}&scope=${scope}&top_k=${topK}`,
  );
}
```

- [x] **Step 2: Build Knowledge Search page**

Show only hits returned by backend. If no hits, show `没有找到相关知识`. If backend reports missing semantic capability, keep keyword results visible and do not invent cloud-document content.

- [x] **Step 3: Build Result Detail page**

Call `getResults(chatId)` and render artifact file list. For V1, text/Markdown preview can be added through existing workspace raw file APIs after the artifact list is stable.

- [ ] **Step 4: Verify file behavior on real device**

Use WeChat DevTools and one real iOS or Android device. Confirm artifact open/share behavior with the official WeChat file APIs listed in "External Framework Decision".

- [x] **Step 5: Verify**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: build passes and knowledge/result pages compile.

## Task 10: Me Page And Asset Replacement

**Files:**

- Create: `miniapp/src/pages/me/index.tsx`
- Create: `miniapp/src/pages/me/index.scss`
- Create: `miniapp/src/pages/me/index.config.ts`
- Modify: `miniapp/src/assets/README.md`
- Add final static assets under `miniapp/src/assets/`

- [x] **Step 1: Build Me page**

Render:

- Employee identity from token verification or local profile cache.
- Workspace label: `DClaw 助手 · 企业空间`.
- Today's counts from Workbench response.
- Notification settings entry.
- Help/feedback entry.
- Logout button.

- [x] **Step 2: Replace placeholders with original assets**

Copy or export the production assets into `miniapp/src/assets/`:

- DClaw logo.
- Mascot hero.
- Mascot tab.
- Task sticker.
- Confirmation banner mascot.
- Empty state mascot.
- Result cover mascot.

Do not use Pencil-generated mascot images as production assets unless the user explicitly accepts them.

- [ ] **Step 3: Verify visual match**

Compare these screens against the selected style image:

- Workbench.
- Task Detail.
- Confirmation page.
- Result Detail.
- Me.

Focus on orange CTA, warm white background, rounded cards, mascot placement, compact information density, and the labels `确认` / `待确认操作`.

## Task 11: Frontend Guard And State Feedback

**Files:**

- Create: `miniapp/src/services/apiError.ts`
- Create: `miniapp/src/services/apiError.test.ts`
- Create: `miniapp/src/services/authGuard.ts`
- Create: `miniapp/src/services/authGuard.test.ts`
- Create: `miniapp/src/components/StateView/index.tsx`
- Create: `miniapp/src/components/StateView/index.scss`
- Modify protected mini-program pages to call `requireAuth()` before user API requests.

- [x] **Step 1: Write failing frontend utility tests**

Add Vitest coverage for:

- Error message extraction from FastAPI-style `detail`, `message`, `error`, and validation arrays.
- Login redirect decisions for empty, whitespace, and populated token values.

- [x] **Step 2: Implement utility functions**

Implement:

- `getResponseErrorMessage(data, statusCode)` for compact employee-facing API errors.
- `shouldRedirectToLogin(token)` for pure auth-guard decisions.
- `requireAuth()` in `auth.ts` for protected page entry and submit guards.

- [x] **Step 3: Add shared state UI**

Implement `StateView` for:

- Loading state.
- Empty state.
- Error state with optional retry action.

Use the named mascot slots so the final DClaw static assets can be replaced without changing page logic.

- [x] **Step 4: Wire protected pages**

Apply auth guard and state UI to:

- Workbench.
- Task List.
- Task Detail.
- Pending Confirmation.
- Knowledge Search.
- Result Detail.
- Me.
- Create Task submit flow.

- [x] **Step 5: Verify frontend stability slice**

Run:

```bash
cd miniapp
npm run test:run
npm run typecheck
npm run build:weapp
```

Expected result: all pass.

## Task 12: End-To-End Verification

**Files:**

- Modify only files touched by Tasks 1-11.

- [x] **Step 1: Backend checks**

Run:

```bash
pytest tests/unit/app/test_mobile_models.py tests/unit/app/test_mobile_router.py -q
python -m py_compile src/qwenpaw/app/mobile/models.py src/qwenpaw/app/mobile/service.py src/qwenpaw/app/routers/mobile.py
```

Expected result: all pass.

- [x] **Step 2: Mini-program checks**

Run:

```bash
cd miniapp
npm run typecheck
npm run build:weapp
```

Expected result: all pass.

- [x] **Step 3: Existing console smoke checks**

Because the mobile facade reuses chat, approval, and workspace behavior, run:

```bash
pytest tests/unit/app/test_chat_access.py tests/unit/app/test_console_push_messages.py tests/unit/app/test_artifact_filter.py -q
cd console && npm run test:run -- config modules/runtimeEvents modules/chat
```

Expected result: all pass.

- [ ] **Step 4: Manual MVP acceptance flows**

Verify these flows against a local backend and WeChat DevTools:

1. Employee logs in and lands on Workbench.
2. Employee creates a task from Create Task.
3. Task appears in Task List.
4. Task Detail shows runtime status and messages.
5. Tool Guard request appears as `待确认操作`.
6. Employee rejects and confirms separate requests.
7. Result Detail shows task artifacts.
8. Knowledge Search displays only backend-returned hits.
9. Me page logs out and blocks private pages without a token.

- [x] **Step 5: Diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected result: no whitespace errors. Existing unrelated AIGC Studio changes must remain untouched.

## Implementation Order

Execute in this order:

1. Task 1: backend DTOs and pure helpers.
2. Task 2: mobile facade router.
3. Task 3: Taro mini-program scaffold.
4. Task 4: API client and auth.
5. Task 5: shared components and visual system.
6. Task 6: Workbench and Create Task.
7. Task 7: Task List and Task Detail.
8. Task 8: Pending Confirmation.
9. Task 9: Knowledge Search and Result Detail.
10. Task 10: Me and asset replacement.
11. Task 11: frontend guard and state feedback.
12. Task 12: full verification.

## Non-Negotiable Acceptance Criteria

- The mini-program has no admin console entry.
- The mini-program has no mobile Web deliverable in V1.
- Task confirmation copy uses Tool Guard language, not OA approval language.
- Backend mobile endpoints are user-scoped under `/api/user/mobile/*`.
- Backend ownership checks remain enforced server-side.
- Static resource slots are replaceable with original DClaw assets.
- The first usable loop works end to end: login, create task, track task, confirm Tool Guard operation, view result artifact, search knowledge.
