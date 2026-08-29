# 我的Agent经验库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员和 Agent 绑定用户通过同一个组件及同一组角色感知接口维护 OpenAPI 专属经验库。

**Architecture:** 服务端新增中立的 `/api/open-api-knowledge` 路由，将发布对象授权和 Mindspace 操作集中到共享模块；管理员与普通用户的差异只由服务端可见范围决定。客户端新增统一 API 模块和 `AgentExperienceLibrary` 组件，OpenAPI 后台与用户知识库页面均挂载该组件。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy repository、pytest、React 18、TypeScript、Ant Design、Vitest、Testing Library、Less Modules

**Spec:** `docs/superpowers/specs/2026-08-29-agent-experience-library-design.md`

## Global Constraints

- 用户界面名称固定为“我的Agent经验库”。
- 管理员和普通用户必须调用同一组 `/api/open-api-knowledge` 接口。
- 普通用户只能维护 `bound_user_id == current_user.id` 的发布对象。
- 管理员维持当前 `owner_user_id == current_user.id` 的可维护范围，不扩大跨租户权限。
- 无权访问与对象不存在统一返回 HTTP 404。
- 每次读取、上传、重建和删除都必须重新进行服务端授权。
- 禁用的 OpenAPI 发布对象仍允许维护经验库。
- 不修改数据库表、不改变 `knowledge_base_id`、不改变密封 Agent 内部资产权限。
- 旧管理员知识接口本次保留，但客户端不再调用。
- 保留 dclaw-server 和 dclaw-client 工作区中与本功能无关的现有改动。

---

## File Structure

### dclaw-server

- Create `src/qwenpaw/app/open_api/knowledge.py`：发布对象授权、目标展示信息和 Mindspace 服务构造的唯一实现。
- Create `src/qwenpaw/app/routers/open_api_knowledge.py`：统一列表、上传、重建和删除路由。
- Modify `src/qwenpaw/app/routers/open_api_admin.py`：旧管理员知识路由委托共享模块，避免保留第二套知识操作逻辑。
- Modify `src/qwenpaw/app/routers/__init__.py`：在已认证 API router 下注册统一路由。
- Create `tests/unit/app/test_open_api_knowledge.py`：角色范围、404 防枚举和文档操作测试。
- Modify `tests/unit/app/test_open_api_admin.py`：确认旧路由仍保持管理员兼容行为。

### dclaw-client

- Create `console/src/api/modules/agentExperienceLibrary.ts`：统一接口客户端与上传实现。
- Modify `console/src/api/index.ts`：导出统一 API。
- Create `console/src/components/AgentExperienceLibrary/index.tsx`：共享经验库管理组件。
- Create `console/src/components/AgentExperienceLibrary/index.module.less`：共享组件样式。
- Create `console/src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`：选择、空状态、上传、重建、删除与错误测试。
- Modify `console/src/pages/Settings/OpenApi/index.tsx`：后台知识页签改为挂载共享组件，移除页面内知识状态与处理函数。
- Modify `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`：验证后台挂载共享组件，保留其他 OpenAPI 行为测试。
- Modify `console/src/pages/Library/TencentDocPage/index.tsx`：增加“我的Agent经验库”范围并挂载共享组件。
- Modify `console/src/pages/Library/TencentDocPage/TencentDocPage.module.less`：新增经验库容器的响应式样式。
- Create `console/src/pages/Library/TencentDocPage/TencentDocPage.test.tsx`：验证用户入口与原知识库范围不回归。

---

### Task 1: 统一发布对象授权与列表接口

**Files:**
- Create: `src/qwenpaw/app/open_api/knowledge.py`
- Create: `src/qwenpaw/app/routers/open_api_knowledge.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/app/test_open_api_knowledge.py`

**Interfaces:**
- Consumes: `get_open_api_repository().list_publications(enabled_only=False)`、`request.state.user_id`、`request.state.role`。
- Produces: `list_accessible_publications(request: Request) -> list[dict[str, Any]]`、`require_accessible_publication(publication_id: str, request: Request) -> dict[str, Any]`、`GET /api/open-api-knowledge/publications`。

- [ ] **Step 1: 写普通用户、管理员和越权对象的失败测试**

```python
def test_user_lists_only_bound_publications(monkeypatch):
    repo = _repo_with_publications(
        {"id": "mine", "owner_user_id": "admin", "bound_user_id": "7"},
        {"id": "other", "owner_user_id": "admin", "bound_user_id": "8"},
    )
    _patch_repo(monkeypatch, repo)

    rows = open_api_knowledge.list_experience_publications(
        _request(user_id="7", role="user")
    )

    assert [row["id"] for row in rows] == ["mine"]


def test_admin_lists_only_owned_publications(monkeypatch):
    repo = _repo_with_publications(
        {"id": "mine", "owner_user_id": "admin-1", "bound_user_id": "7"},
        {"id": "other", "owner_user_id": "admin-2", "bound_user_id": "7"},
    )
    _patch_repo(monkeypatch, repo)

    rows = open_api_knowledge.list_experience_publications(
        _request(user_id="admin-1", role="admin")
    )

    assert [row["id"] for row in rows] == ["mine"]


def test_inaccessible_publication_is_reported_as_not_found(monkeypatch):
    _patch_repo(monkeypatch, _repo_with_publications(
        {"id": "private", "owner_user_id": "admin", "bound_user_id": "8"}
    ))

    with pytest.raises(HTTPException) as exc_info:
        knowledge.require_accessible_publication(
            "private", _request(user_id="7", role="user")
        )

    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: 运行测试并确认因统一模块和路由尚不存在而失败**

Run: `pytest -q tests/unit/app/test_open_api_knowledge.py`

Expected: FAIL，导入 `open_api_knowledge` 或 `require_accessible_publication` 失败。

- [ ] **Step 3: 实现集中授权函数**

在 `src/qwenpaw/app/open_api/knowledge.py` 实现：

```python
def can_manage_publication(publication: dict[str, Any], request: Request) -> bool:
    user_id = str(getattr(request.state, "user_id", "") or "")
    if not user_id:
        return False
    if getattr(request.state, "role", None) == "admin":
        return str(publication.get("owner_user_id") or "") == user_id
    return str(publication.get("bound_user_id") or "") == user_id


def require_accessible_publication(
    publication_id: str,
    request: Request,
) -> dict[str, Any]:
    publication = get_open_api_repository().get_publication(publication_id)
    if publication is None or not can_manage_publication(publication, request):
        raise HTTPException(status_code=404, detail="Open API publication not found")
    return publication
```

列表使用同一个 `can_manage_publication` 过滤器，不单独复制条件。返回数据增加 `target_name`：普通 Agent 从 `load_config().agents.profiles[target_id]` 的名称字段获取；专家团从 `get_expert_team_template(target_id).name` 获取；缺失时回退到 publication name，再回退到 target ID。不得读取或返回密封 Agent 的工作区、提示词、Skill 或源码字段。

- [ ] **Step 4: 实现统一列表路由并注册**

```python
router = APIRouter(prefix="/open-api-knowledge", tags=["open-api-knowledge"])


@router.get("/publications")
def list_experience_publications(request: Request) -> list[dict[str, Any]]:
    return list_accessible_publications(request)
```

在 `src/qwenpaw/app/routers/__init__.py` 将该 router 注册到普通认证 router，而不是 `admin_api_router`。复用项目现有认证中间件，不新增匿名访问路径。

- [ ] **Step 5: 运行授权测试并确认通过**

Run: `pytest -q tests/unit/app/test_open_api_knowledge.py`

Expected: PASS，管理员、绑定用户和非绑定用户断言全部通过。

- [ ] **Step 6: 提交服务端授权与列表接口**

```bash
git add src/qwenpaw/app/open_api/knowledge.py src/qwenpaw/app/routers/open_api_knowledge.py src/qwenpaw/app/routers/__init__.py tests/unit/app/test_open_api_knowledge.py
git commit -m "feat: add role-aware agent experience publications"
```

---

### Task 2: 统一经验库文档操作并保留旧管理员兼容路由

**Files:**
- Modify: `src/qwenpaw/app/open_api/knowledge.py`
- Modify: `src/qwenpaw/app/routers/open_api_knowledge.py`
- Modify: `src/qwenpaw/app/routers/open_api_admin.py`
- Modify: `tests/unit/app/test_open_api_knowledge.py`
- Modify: `tests/unit/app/test_open_api_admin.py`

**Interfaces:**
- Consumes: `require_accessible_publication()`、`MindspaceService`、`MindspaceScope.PERSONAL`。
- Produces: `publication_knowledge_service(publication) -> MindspaceService` 及统一 docs 路由。

- [ ] **Step 1: 写列表、上传、重建、删除以及权限变化后的失败测试**

```python
def test_bound_user_can_list_documents(monkeypatch):
    _patch_publication(monkeypatch, bound_user_id="7")
    service = _patch_knowledge_service(monkeypatch, docs=[FakeDoc("doc-1")])

    rows = open_api_knowledge.list_documents(
        "pub-1", _request(user_id="7", role="user")
    )

    assert rows == [{"id": "doc-1", "name": "doc-1.txt"}]
    assert service.list_scope == MindspaceScope.PERSONAL


def test_non_bound_user_cannot_upload(monkeypatch):
    _patch_publication(monkeypatch, bound_user_id="8")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(open_api_knowledge.upload_document(
            "pub-1",
            _request(user_id="7", role="user"),
            FakeUploadFile("guide.txt", b"content"),
        ))

    assert exc_info.value.status_code == 404


def test_permission_is_rechecked_before_delete(monkeypatch):
    publication = _patch_publication(monkeypatch, bound_user_id="7")
    assert open_api_knowledge.list_documents(
        "pub-1", _request(user_id="7", role="user")
    ) == []
    publication["bound_user_id"] = "8"

    with pytest.raises(HTTPException) as exc_info:
        open_api_knowledge.delete_document(
            "pub-1", "doc-1", _request(user_id="7", role="user")
        )

    assert exc_info.value.status_code == 404
```

另外分别断言禁用 publication 可以操作、找不到 doc 返回 404、删除返回 `{"deleted": True, "id": "doc-1"}`。

- [ ] **Step 2: 运行新增测试并确认新路由尚未实现**

Run: `pytest -q tests/unit/app/test_open_api_knowledge.py`

Expected: FAIL，缺少 `list_documents`、`upload_document`、`sync_document` 或 `delete_document`。

- [ ] **Step 3: 将 Mindspace 构造迁移到共享模块**

把 `open_api_admin.py` 中 `_publication_agent_id` 和 `_publication_knowledge_service` 的逻辑迁移为：

```python
def publication_knowledge_service(
    publication: dict[str, Any],
) -> MindspaceService:
    agent_id = publication_agent_id(publication)
    profile = _require_agent_profile(agent_id)
    return MindspaceService(
        global_root=Path(WORKING_DIR) / "mindspace",
        agent_workspace=Path(profile.workspace_dir).expanduser(),
        agent_id=agent_id,
        user_id=str(publication["knowledge_base_id"]),
        exclusive_personal=True,
    )
```

专家团继续映射到 leader Agent；所有读写固定使用 `MindspaceScope.PERSONAL` 和独占 `knowledge_base_id`。

- [ ] **Step 4: 实现统一文档路由**

路由路径必须精确为：

```python
@router.get("/publications/{publication_id}/docs")
@router.post("/publications/{publication_id}/docs")
@router.post("/publications/{publication_id}/docs/{doc_id}/sync")
@router.delete("/publications/{publication_id}/docs/{doc_id}")
```

每个处理函数第一步调用 `require_accessible_publication(publication_id, request)`，然后获取 `publication_knowledge_service(publication)`。上传保留现有 category、tags、MIME、扩展名规范化和 `asyncio.to_thread` 行为。

- [ ] **Step 5: 让旧管理员知识路由委托共享操作**

保留旧 URL 和函数名以兼容外部消费者，但函数体只负责 `_require_admin(request)`，随后调用共享的授权/文档操作函数。删除 `open_api_admin.py` 内重复的 Mindspace 构造和文档处理实现。

兼容测试必须继续验证非管理员访问旧 `/admin` 路由返回 403，而不是获得新用户权限。

- [ ] **Step 6: 运行统一接口与管理员回归测试**

Run: `pytest -q tests/unit/app/test_open_api_knowledge.py tests/unit/app/test_open_api_admin.py`

Expected: PASS。

- [ ] **Step 7: 提交统一文档操作**

```bash
git add src/qwenpaw/app/open_api/knowledge.py src/qwenpaw/app/routers/open_api_knowledge.py src/qwenpaw/app/routers/open_api_admin.py tests/unit/app/test_open_api_knowledge.py tests/unit/app/test_open_api_admin.py
git commit -m "feat: unify agent experience document operations"
```

---

### Task 3: 客户端统一 API 与共享经验库组件

**Files:**
- Create: `console/src/api/modules/agentExperienceLibrary.ts`
- Modify: `console/src/api/index.ts`
- Create: `console/src/components/AgentExperienceLibrary/index.tsx`
- Create: `console/src/components/AgentExperienceLibrary/index.module.less`
- Create: `console/src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`

**Interfaces:**
- Consumes: `/api/open-api-knowledge` 服务端契约、`useAppMessage()`。
- Produces: `agentExperienceLibraryApi`、`AgentExperiencePublication`、`AgentExperienceDocument`、`AgentExperienceLibrary` React 组件。

- [ ] **Step 1: 写共享组件的失败测试**

```tsx
it("shows readable agent publication labels and loads its documents", async () => {
  api.listPublications.mockResolvedValue([
    {
      id: "pub-1",
      public_id: "support_agent",
      name: "客服入口",
      target_type: "agent",
      target_id: "agent-1",
      target_name: "客服专家",
      status: "enabled",
      knowledge_base_id: "openapi-pub-1",
    },
  ]);
  api.listDocuments.mockResolvedValue([
    { id: "doc-1", name: "产品手册.pdf", status: "ready" },
  ]);

  render(<AgentExperienceLibrary />);

  expect(await screen.findByText("客服专家 · 客服入口 · support_agent"))
    .toBeInTheDocument();
  expect(await screen.findByText("产品手册.pdf")).toBeInTheDocument();
});

it("shows guidance instead of upload when no publication is accessible", async () => {
  api.listPublications.mockResolvedValue([]);
  render(<AgentExperienceLibrary />);
  expect(await screen.findByText("暂无可维护的 Agent 经验库"))
    .toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "上传文档" }))
    .not.toBeInTheDocument();
});
```

再添加：禁用状态仍出现上传按钮；重建只禁用当前行；删除需要确认；上传锁防止重复；文档请求 404 后重新拉取 publications 并清空旧文档。

- [ ] **Step 2: 运行组件测试并确认导入失败**

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`

Expected: FAIL，组件或 API 模块不存在。

- [ ] **Step 3: 实现统一 API 模块**

```ts
export interface AgentExperiencePublication {
  id: string;
  public_id: string;
  name: string;
  target_type: "agent" | "expert_team";
  target_id: string;
  target_name: string;
  status: "enabled" | "disabled";
  knowledge_base_id: string;
}

export const agentExperienceLibraryApi = {
  listPublications: () =>
    request<AgentExperiencePublication[]>("/open-api-knowledge/publications"),
  listDocuments: (publicationId: string) =>
    request<AgentExperienceDocument[]>(
      `/open-api-knowledge/publications/${encodeURIComponent(publicationId)}/docs`,
    ),
  syncDocument: (publicationId: string, docId: string) =>
    request<AgentExperienceDocument>(
      `/open-api-knowledge/publications/${encodeURIComponent(publicationId)}/docs/${encodeURIComponent(docId)}/sync`,
      { method: "POST" },
    ),
  deleteDocument: (publicationId: string, docId: string) =>
    request<{ deleted: boolean; id: string }>(
      `/open-api-knowledge/publications/${encodeURIComponent(publicationId)}/docs/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    ),
};
```

上传使用 `getApiUrl`、`buildAuthHeaders` 和 `FormData`，路径与 listDocuments 相同，方法为 POST。

- [ ] **Step 4: 实现共享组件状态模型**

组件内部持有：

```ts
const [publications, setPublications] = useState<AgentExperiencePublication[]>([]);
const [selectedPublicationId, setSelectedPublicationId] = useState<string>();
const [documents, setDocuments] = useState<AgentExperienceDocument[]>([]);
const [loading, setLoading] = useState(false);
const [uploading, setUploading] = useState(false);
const [busyDocumentIds, setBusyDocumentIds] = useState<Set<string>>(new Set());
```

发布项标签固定为 `${target_name} · ${name} · ${public_id}`。组件使用 Ant Design `Select`、`Alert`、`Button`、`Table`、`Tag`、`Popconfirm` 和系统现有 `useAppMessage`。404 处理调用 `reloadPublications()`；其他错误不清空当前 documents。

- [ ] **Step 5: 实现统一响应式样式**

复用设置页的 24px/16px 页面节奏、10px 卡片圆角、Ant Design token CSS variables 和 760px 移动断点。共享组件不能设置外层页面 padding，由宿主页面控制。

- [ ] **Step 6: 运行共享组件测试**

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`

Expected: PASS。

- [ ] **Step 7: 提交客户端共享组件**

```bash
cd '/Users/moxi/Desktop/codex space/dclaw-client'
git add console/src/api/modules/agentExperienceLibrary.ts console/src/api/index.ts console/src/components/AgentExperienceLibrary
git commit -m "feat: add shared agent experience library"
```

---

### Task 4: 管理后台迁移到共享组件

**Files:**
- Modify: `console/src/pages/Settings/OpenApi/index.tsx`
- Modify: `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`
- Modify: `console/src/api/modules/openApi.ts`

**Interfaces:**
- Consumes: `<AgentExperienceLibrary />`。
- Produces: 后台“专属知识库”页签不再拥有独立知识状态或调用管理员知识接口。

- [ ] **Step 1: 写后台挂载共享组件的失败测试**

不要断言 mock 元素存在。使用真实共享组件并只 mock其外部 API：

```tsx
it("uses the unified experience API in the admin knowledge tab", async () => {
  experienceApi.listPublications.mockResolvedValue([publication]);
  experienceApi.listDocuments.mockResolvedValue([]);
  render(<OpenApiPage />);

  await userEvent.click(screen.getByRole("tab", { name: "专属知识库" }));

  expect(await screen.findByText("客服专家 · 客服入口 · support_agent"))
    .toBeInTheDocument();
  expect(mockOpenApiApi.listKnowledgeDocuments).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: 运行 OpenAPI 页面测试并确认仍调用旧逻辑或没有共享组件**

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/pages/Settings/OpenApi/OpenApi.test.tsx`

Expected: FAIL，统一经验库内容未出现。

- [ ] **Step 3: 替换后台知识页签**

将知识页签 children 替换为：

```tsx
<AgentExperienceLibrary />
```

从 `OpenApiPage` 删除 `knowledgeDocs`、`knowledgeBusy`、文件 input ref、知识 columns 以及上传/重建/删除处理函数。顶部“专属知识文档”概览如果统一列表接口不提供聚合文档数，改为“已启用发布”并由 publications 计算，不为了保留旧数字发起重复文档请求。

- [ ] **Step 4: 移除客户端旧管理员知识方法**

从 `openApiApi` 删除 `listKnowledgeDocuments`、`uploadKnowledgeDocument`、`syncKnowledgeDocument`、`deleteKnowledgeDocument` 以及私有上传 helper。保留 `OpenApiKnowledgeDocument` 类型直到确认无其他消费者；若 `rg "OpenApiKnowledgeDocument" console/src` 只剩旧模块，则一起删除该类型。

- [ ] **Step 5: 运行 OpenAPI 与共享组件测试**

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/pages/Settings/OpenApi/OpenApi.test.tsx src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`

Expected: PASS。

- [ ] **Step 6: 提交管理员迁移**

```bash
cd '/Users/moxi/Desktop/codex space/dclaw-client'
git add console/src/pages/Settings/OpenApi console/src/api/modules/openApi.ts console/src/api/types/openApi.ts
git commit -m "refactor: reuse experience library in open api admin"
```

---

### Task 5: 用户知识库新增“我的Agent经验库”入口

**Files:**
- Modify: `console/src/pages/Library/TencentDocPage/index.tsx`
- Modify: `console/src/pages/Library/TencentDocPage/TencentDocPage.module.less`
- Create: `console/src/pages/Library/TencentDocPage/TencentDocPage.test.tsx`

**Interfaces:**
- Consumes: `<AgentExperienceLibrary />`。
- Produces: `KnowledgeScope = "personal" | "enterprise" | "all" | "agent-experience"` 和用户入口。

- [ ] **Step 1: 写用户入口失败测试**

```tsx
it("opens 我的Agent经验库 without loading personal knowledge", async () => {
  const user = userEvent.setup();
  render(<TencentDocPage />);

  await user.click(screen.getByText("我的Agent经验库"));

  expect(await screen.findByText("客服专家 · 客服入口 · support_agent"))
    .toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "关联云文档" }))
    .not.toBeInTheDocument();
});
```

测试中保持真实 `AgentExperienceLibrary`，只 mock request 边界；同时保留一个个人知识库范围测试，确认“我的知识库”仍加载 `/workspace/knowledge/docs?scope=personal`。

- [ ] **Step 2: 运行用户页面测试并确认入口不存在**

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/pages/Library/TencentDocPage/TencentDocPage.test.tsx`

Expected: FAIL，找不到“我的Agent经验库”。

- [ ] **Step 3: 扩展知识范围并避免触发旧数据流**

```ts
type KnowledgeScope = "personal" | "enterprise" | "all" | "agent-experience";
```

Segmented 增加：

```tsx
{ value: "agent-experience", label: "我的Agent经验库" }
```

所有加载个人/企业知识、检索、上传和云文档副作用在 `activeScope === "agent-experience"` 时提前返回，避免共享组件之外的无关请求。

- [ ] **Step 4: 挂载共享组件并隐藏个人知识操作**

在页头范围选择器下方增加明确分支：

```tsx
{activeScope === "agent-experience" ? (
  <div className={styles.agentExperiencePanel}>
    <AgentExperienceLibrary />
  </div>
) : (
  <>
    {renderKnowledgeStats()}
    {renderKnowledgeSearchAndDocuments()}
  </>
)}
```

在页面内提取 `renderKnowledgeStats()` 与 `renderKnowledgeSearchAndDocuments()` 两个局部渲染函数，函数体分别移动现有统计区、搜索/文档区及其弹窗 JSX，不改变其事件处理函数。经验库模式下隐藏“上传本地文档”和“关联云文档”，由共享组件提供自己的上传入口。

- [ ] **Step 5: 添加页面容器样式并运行测试**

`.agentExperiencePanel` 使用现有页面内容宽度，不增加重复 padding；移动端宽度 100%。

Run: `cd '/Users/moxi/Desktop/codex space/dclaw-client/console' && npm run test:run -- src/pages/Library/TencentDocPage/TencentDocPage.test.tsx src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`

Expected: PASS。

- [ ] **Step 6: 提交用户入口**

```bash
cd '/Users/moxi/Desktop/codex space/dclaw-client'
git add console/src/pages/Library/TencentDocPage
git commit -m "feat: add my agent experience library entry"
```

---

### Task 6: 完整回归、安全验证与文档同步

**Files:**
- Modify: `docs/open-api-user-manual.zh.md`
- Modify: `docs/dclaw-capability-overview.zh.md`
- Test: `tests/unit/app/test_open_api_knowledge.py`
- Test: `tests/unit/app/test_open_api_admin.py`
- Test: `console/src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx`
- Test: `console/src/pages/Settings/OpenApi/OpenApi.test.tsx`
- Test: `console/src/pages/Library/TencentDocPage/TencentDocPage.test.tsx`

**Interfaces:**
- Consumes: Tasks 1–5 的统一服务端与客户端实现。
- Produces: 可审计的验证证据与用户文档。

- [ ] **Step 1: 更新用户文档**

在 OpenAPI 用户手册中明确：管理员创建发布并绑定用户；绑定用户在“知识库 → 我的Agent经验库”维护专属文档；禁用接口不影响经验库维护；用户不能创建发布、Key 或查看调用记录。

在能力概览中增加统一接口及权限公式：

```text
普通用户：publication.bound_user_id == current_user.id
管理员：publication.owner_user_id == current_user.id
```

- [ ] **Step 2: 运行服务端相关测试**

Run: `pytest -q tests/unit/app/test_open_api_knowledge.py tests/unit/app/test_open_api_admin.py tests/unit/app/sealed_agents/test_open_api_sealed.py`

Expected: PASS，0 failures。

- [ ] **Step 3: 运行服务端格式与静态检查**

执行仓库已有的 Python 编译检查：

```bash
python -m compileall -q \
  src/qwenpaw/app/open_api/knowledge.py \
  src/qwenpaw/app/routers/open_api_knowledge.py \
  src/qwenpaw/app/routers/open_api_admin.py \
  tests/unit/app/test_open_api_knowledge.py \
  tests/unit/app/test_open_api_admin.py
```

Expected: exit 0 且无输出。

- [ ] **Step 4: 运行客户端相关测试**

```bash
cd '/Users/moxi/Desktop/codex space/dclaw-client/console'
npm run test:run -- \
  src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx \
  src/pages/Settings/OpenApi/OpenApi.test.tsx \
  src/pages/Library/TencentDocPage/TencentDocPage.test.tsx \
  src/layouts/ClientLayout.test.tsx
```

Expected: PASS，0 failures。

- [ ] **Step 5: 运行客户端 Lint、格式和生产构建**

```bash
npx eslint \
  src/api/modules/agentExperienceLibrary.ts \
  src/components/AgentExperienceLibrary/index.tsx \
  src/components/AgentExperienceLibrary/AgentExperienceLibrary.test.tsx \
  src/pages/Settings/OpenApi/index.tsx \
  src/pages/Library/TencentDocPage/index.tsx
npx prettier --check \
  src/api/modules/agentExperienceLibrary.ts \
  src/components/AgentExperienceLibrary \
  src/pages/Settings/OpenApi \
  src/pages/Library/TencentDocPage
npm run build
```

Expected: 全部 exit 0。允许记录仓库已有的 Vite 分包警告，但不得出现新增 TypeScript、ESLint 或构建错误。

- [ ] **Step 6: 验证未扩展密封 Agent 资产权限**

Run: `pytest -q tests/unit/app/sealed_agents/test_open_api_sealed.py`

Expected: PASS；统一 publication 列表只返回 target name、发布字段和知识库运维字段，不返回 prompt、skills、workspace、source、download 或 trace。

- [ ] **Step 7: 提交文档与最终验证修正**

服务端：

```bash
git add docs/open-api-user-manual.zh.md docs/dclaw-capability-overview.zh.md
git commit -m "docs: explain agent experience library ownership"
```

验证修正仅限下列客户端功能文件，另在 dclaw-client 中提交：

```bash
git add \
  console/src/api/modules/agentExperienceLibrary.ts \
  console/src/api/modules/openApi.ts \
  console/src/components/AgentExperienceLibrary \
  console/src/pages/Settings/OpenApi \
  console/src/pages/Library/TencentDocPage
git commit -m "fix: complete agent experience library integration"
```

- [ ] **Step 8: 最终差异审计**

分别在两个仓库执行：

```bash
git diff --check
git status --short
git log --oneline --decorate -8
```

确认提交只包含本计划文件，不覆盖两个仓库中用户已有的未提交改动。推送或合并前使用 `superpowers:verification-before-completion` 重新运行完整验证。
