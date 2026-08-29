# DClaw 双仓组合镜像与单命令原地升级设计

## 目标

DClaw 继续保持两个独立源码仓库：

- `51taichi/dclaw-server`：FastAPI/Python 服务端、Dockerfile 与服务端资源；
- `51taichi/dclaw-client`：React Console、网站文档与桌面客户端源码。

生产发布物仍然是一个组合 Docker 镜像。镜像内包含服务端和由指定 client 提交编译出的 Console 静态文件。生产只运行一个名为 `dclaw` 的应用容器，并继续复用现有 PostgreSQL、Redis、Docker 网络与数据卷。

日常发布的唯一入口为：

```bash
/opt/dclaw-deploy/update.sh
```

该入口适用于只改 server、只改 client、两边同时修改三种情况。它必须保留备份、版本追踪、健康检查与自动回滚，不能退化成不受保护的 `docker pull && docker run`。

## 非目标

- 不把 server 与 client 合并为一个 Git 仓库；
- 不部署第二套正式 DClaw；
- 不让 GitHub push 直接、无人值守地修改生产服务器；
- 不在普通镜像回滚时自动恢复数据库；
- 不修改现有客户域名、端口、用户、项目或数据卷；
- 不将桌面端/Tauri 构建产物放入服务器镜像。

## 发布架构

### 组合构建输入

一次发布由不可变的二元版本确定：

```text
(server_sha, client_sha)
```

构建任务必须将两个 SHA 写入 OCI image labels：

```text
cn.deepmega.dclaw.server-revision=<full server SHA>
cn.deepmega.dclaw.client-revision=<full client SHA>
```

构建上下文由以下内容组成：

```text
server repository root
├── src/
├── deploy/Dockerfile
├── scripts/
├── console/                  <- client repository console/
└── website/public/docs/      <- client repository同路径
```

构建前必须验证：

- 两个 checkout 的 `HEAD` 等于记录的完整 SHA；
- `deploy/Dockerfile`、`console/package-lock.json` 和文档目录存在；
- client Console 能完成锁文件安装与生产构建；
- 镜像中的 labels 与构建输入一致。

### 镜像仓库和标签

组合镜像发布到：

```text
ghcr.io/51taichi/dclaw
```

每次成功构建至少发布两个标签：

```text
main
server-<12位SHA>-client-<12位SHA>
```

生产拉取 `main` 用于发现更新，但部署记录必须保存拉取后的不可变 image digest、完整 server SHA 与完整 client SHA。回滚不得依赖已经变化的 `main` 标签。

如果 GHCR package 为私有，服务器使用只具有 `read:packages` 权限的凭证登录；构建使用当前 server 仓库的 `GITHUB_TOKEN` 和 `packages: write`，不保存长期 GHCR 写凭证到服务器。

## 双仓触发机制

### server main 更新

`dclaw-server` 的组合镜像 workflow 在 `main` push 时启动：

1. server SHA 使用事件自身的 `github.sha`；
2. client SHA 在任务开始时解析 `dclaw-client/main`；
3. 精确 checkout 两个 SHA；
4. 测试、组合构建并发布镜像。

### client main 更新

`dclaw-client` 的轻量 workflow 在 `main` push 时向 `dclaw-server` 发送 `repository_dispatch`，payload 包含完整 `client_sha`。server workflow 收到事件后：

1. client SHA 使用 payload 中的不可变 SHA；
2. server SHA 解析当时的 `dclaw-server/main`；
3. 精确 checkout 两个 SHA；
4. 测试、组合构建并发布镜像。

跨私有仓库访问使用两个最小权限 secret：

- server 仓库 `DCLAW_CLIENT_READ_TOKEN`：只读 client 内容；
- client 仓库 `DCLAW_SERVER_DISPATCH_TOKEN`：只允许向 server 发送 dispatch。

工作流使用 concurrency group；同一版本方向上的旧构建可取消，但已开始发布不可变标签的任务不得造成半发布状态。只有构建与验证全部成功后才更新 `main`。

工作流同时保留 `workflow_dispatch`，允许显式输入或选择 server/client SHA 进行可重复构建。

## 生产 Compose 边界

生产新增专用文件：

```text
/opt/dclaw-deploy/compose.production.yml
/opt/dclaw-deploy/production.env
/opt/dclaw-deploy/release.env
```

该 Compose project 只管理 `dclaw` 应用容器，不接管或重建当前 `dclaw-postgres`、`dclaw-redis`。它引用既有外部资源：

```text
network: dclaw-net                 external
volume:  dclaw-data               external
volume:  dclaw-secrets            external
volume:  dclaw-backups            external
port:    127.0.0.1:18088:8088
name:    dclaw
restart: unless-stopped
```

`production.env` 保存当前生产应用环境并保持 `0600`；不得写入 Git。`release.env` 只保存当前选定的不可变镜像引用与版本元数据，同样保持 `0600`。

PostgreSQL 和 Redis 仍按当前容器生命周期独立运行。任何 update、status 或 rollback 命令都禁止删除、重建或匿名替换上述外部卷和网络。

## 首次纳管

当前 `dclaw` 是手工创建的容器，不属于 Compose。首次纳管是一次显式、可回滚操作：

1. 保存 `docker inspect dclaw` 和当前环境；
2. 验证现有挂载、网络、端口和镜像摘要；
3. 创建最新 PostgreSQL custom-format dump；
4. 停止并重命名当前容器为带时间戳的 rollback 容器；
5. 使用相同资源由专用 Compose 创建同名 `dclaw`；
6. 等待最长 420 秒完成健康检查；
7. 失败时删除失败容器并恢复原 rollback 容器。

纳管成功后，后续升级均由同一个 Compose project 原地 recreate，不再手工拼接 `docker run` 参数。

## `update.sh` 行为

### 输入

默认：

```bash
/opt/dclaw-deploy/update.sh
```

拉取 GHCR 的 `main`，读取 image labels，并与当前生产 labels 比较。

可选精确发布：

```bash
/opt/dclaw-deploy/update.sh \
  --server-sha <full SHA> \
  --client-sha <full SHA>
```

精确发布只接受与镜像 labels 完全一致的不可变组合标签；不允许把用户输入直接拼成未经验证的镜像名。

### 更新步骤

1. 获取进程锁，拒绝并发 update/rollback；
2. 检查 Docker、Compose、生产容器、数据库、Redis、网络和外部卷；
3. 拉取目标镜像并验证两个 revision labels；
4. 如果 image digest 与当前相同，输出 `NO_UPDATE_REQUIRED` 并退出；
5. 保存当前镜像 ID、RepoDigest、labels、容器 inspect 与 Compose config；
6. 将当前镜像增加本地时间戳 rollback tag；
7. 创建 PostgreSQL custom-format dump并用 `pg_restore --list` 验证；
8. 原子写入新的 `release.env`；
9. 用 Compose recreate `dclaw`，保持外部资源不变；
10. 最长 420 秒轮询本地 `/api/version`，同时确认容器持续运行且未 OOM；
11. 验证公网 `https://dclaw.deepmega.cn/api/version`；
12. 验证运行镜像 ID和两个 labels等于目标；
13. 成功后记录 release manifest，输出 `UPDATE_SUCCESS`。

Workbench/SSH断开不能中止发布。脚本提供同步运行入口，同时文档给出 `nohup` 启动和日志查看方式；同一发布锁保证用户重复执行不会启动第二个升级。

### 失败处理

目标镜像启动、健康检查或公网检查失败时：

1. 保存失败容器日志；
2. 将 `release.env` 恢复为上一不可变镜像；
3. 用 Compose recreate 上一镜像；
4. 等待同样的 420 秒健康检查；
5. 输出 `UPDATE_FAILED_ROLLBACK_READY` 或明确的 `ROLLBACK_FAILED`。

普通失败回滚不自动恢复数据库，因为新版启动可能已经执行向前兼容的加表/加列迁移，而盲目恢复会丢失切换后写入。只有人工判断数据库不兼容且停止写入后，才使用对应 pre-update dump 做显式灾难恢复。

## `status.sh` 行为

`status.sh` 是只读命令，输出：

- 当前容器状态、启动时间、restart count、OOM状态；
- 当前 image ID/RepoDigest；
- 当前 server/client revision labels；
- GHCR `main` 的目标 labels（可访问时）；
- PostgreSQL、Redis、网络与三个卷状态；
- 本地与公网 API 状态；
- 最近一次成功发布与可回滚版本。

不得输出数据库密码、GHCR token、完整环境变量或 secret卷内容。

## `rollback.sh` 行为

默认回滚到最近一次成功发布前保存的不可变镜像：

```bash
/opt/dclaw-deploy/rollback.sh
```

流程与 update 共用同一锁和健康检查。脚本只切换应用镜像并保留数据库、Redis、网络与卷；显式数据库恢复使用独立命令和二次确认，不属于普通 rollback。

回滚成功输出 `ROLLBACK_SUCCESS`；失败时保留日志和两个镜像引用，不执行镜像清理。

## 安全与凭证

- GitHub跨仓 token 使用最小仓库权限，不复用个人全权限 token；
- 服务器 GHCR token 只有 `read:packages`；
- token通过 `docker login --password-stdin` 输入，不出现在命令参数和日志；
- `production.env`、`release.env`、备份、inspect 和 deployment manifests 均为 `0600`；
- 日志不得打印 `docker inspect .Config.Env`、数据库 URL或 Authorization header；
- 发布脚本不运行 `docker system prune`，不自动删除旧镜像、旧容器或备份；
- 镜像以 digest和双 SHA labels建立可审计链路。

## 测试与验收

代码仓库中的自动化至少覆盖：

1. workflow YAML可解析，server push/client dispatch/manual三种事件能解析正确 SHA；
2. 组合构建缺少 client console/docs、SHA不匹配或前端构建失败时拒绝发布；
3. 构建镜像 labels与输入一致；
4. Compose渲染后只管理 `dclaw`，并引用精确的外部网络、卷和端口；
5. update无变化时零重建；
6. update备份验证失败时不停止生产；
7. update成功时保持容器名、网络、卷和端口；
8. 启动超时、容器退出、OOM、本地/API公网失败时恢复上一镜像；
9. SSH断开后后台进程继续，重复启动被锁拒绝；
10. status输出不泄露secret；
11. rollback仅切换镜像，不修改数据库/Redis/外部卷；
12. 健康检查允许至少420秒慢启动。

生产首次纳管验收包括：

- 原域名、账号、历史会话、AIGC项目和工作区保持不变；
- `docker inspect dclaw` 显示原网络和三个原卷；
- 运行镜像双 SHA labels与发布记录一致；
- 管理接口、钱包、Agent经验库和密封 Agent页面完成冒烟测试；
- 回滚镜像与pre-update数据库dump仍可读取。

