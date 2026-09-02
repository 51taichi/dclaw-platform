# DClaw 跨平台本地 Docker 部署设计

## 目标

从当前 Mac 上的 `dclaw-server`、`dclaw-client` 和陆羽源码构建一个可重复部署的完整本地环境；Mac 验收通过后，同一套 Compose 和镜像可迁移到 Windows 11 + Docker Desktop/WSL2 及 Linux 服务器。局域网设备可通过宿主机 18088 端口访问。

## 已确认决策

- Compose 项目名固定为 `dclaw-production`。
- 应用、网络和卷统一使用 `dclaw` 命名，不再新增 `qwenpaw` 部署名。
- 完整栈包含 DClaw、PostgreSQL 16 和 Redis 7。
- DClaw 前端与后端构建在同一个应用镜像中；镜像从当前 server/client 工作树组装，不使用旧公共镜像。
- 大模型通过火山或 MXAPI 调用，不运行本地推理服务。
- 本地与局域网入口为 `http://<host>:18088`；第一版不配置公网和 HTTPS。
- DClaw 必须启用登录认证；PostgreSQL 和 Redis 不映射宿主机端口。
- 陆羽以正式签名超级专家包安装、整包授权和激活，不使用源码挂载绕过发布流程。

## 组件与边界

### 构建上下文组装器

本地构建脚本接收 server、client 两个仓库路径，将 server 文件和 `client/console`、`client/website/public/docs` 复制到临时构建上下文。临时目录在构建结束后删除，不修改两个源仓库。

镜像标签包含 server/client Git SHA；工作树有未提交变更时附加内容指纹，保证镜像可追溯且不会伪装成纯提交版本。

### Compose 运行栈

- `dclaw`：当前源码构建的应用镜像，端口 `${DCLAW_BIND_HOST:-0.0.0.0}:${DCLAW_HOST_PORT:-18088}:8088`。
- `dclaw-postgres`：PostgreSQL 16，仅加入 `dclaw-net`。
- `dclaw-redis`：Redis 7，AOF 持久化，仅加入 `dclaw-net`。
- 五个命名卷：`dclaw-data`、`dclaw-secrets`、`dclaw-backups`、`dclaw-postgres`、`dclaw-redis`。

应用使用 PostgreSQL 作为数据库后端、Redis 作为运行时后端。应用只在数据库和 Redis 健康后启动，并提供 `/api/version` 健康检查。

### 配置与秘密

非秘密默认值放入版本控制中的环境模板。实际 `.env` 由初始化命令生成、权限收紧并被 Git 忽略。管理员密码、数据库密码、火山/MXAPI 密钥和陆羽签名私钥不得写入镜像或 Compose。

模型供应商首次配置优先通过 DClaw 管理界面完成；部署脚本只负责验证至少存在一个可用模型，不猜测或代填用户密钥。

### 陆羽发布

部署工具使用陆羽仓库的 `scripts/build_release_manifest.py` 和 `scripts/build_sealed_release.py` 构建签名包。安装、能力预览、整包授权、激活和首轮运行通过 DClaw 标准发布/Runner 链路完成。签名私钥保存在宿主机部署秘密目录，不进入应用数据卷。

## 运维命令

统一入口提供 `init`、`build`、`start`、`stop`、`restart`、`status`、`logs`、`doctor`、`backup`、`restore`、`upgrade`、`rollback` 和 `install-luyu`。macOS/Linux 使用 shell 包装器，Windows 使用 PowerShell 包装器；核心行为由 Compose 和跨平台 Python 工具实现，避免维护两套逻辑。

## 备份与恢复

备份包含 PostgreSQL custom-format dump、Redis数据、DClaw 数据卷、秘密卷的加密前原始归档和部署元数据。备份创建后必须验证数据库 dump 可列出、归档可读取。升级前强制备份；回滚同时恢复镜像引用和选定备份。

## 安全边界

- 18088 只面向可信家庭/办公局域网；路由器不得做公网端口映射。
- 登录认证默认开启，初始化拒绝弱默认密码。
- 数据库和 Redis 无宿主机端口。
- 日志和 doctor 输出不得显示 API Key、数据库密码或签名私钥。
- 所有超级专家能力仍由签名 Manifest 和整包授权约束。

## 验收标准

1. Apple Silicon Mac 可从当前源码构建镜像并启动三个健康容器。
2. 本机 `localhost:18088` 与宿主机局域网 IP 均能获得 DClaw HTTP 响应。
3. 容器重建后数据库、会话、工作区和 Redis 状态不因容器删除而丢失。
4. 火山或 MXAPI 至少一个模型可完成普通会话。
5. 陆羽签名包可安装、14 项能力整包授权、激活并完成首轮确定性编排。
6. 卡片到 AIGC、审核、修改重提、返回会话的关键闭环通过。
7. 未声明或未授权 Agent 不能调用超级专家能力；运行时异常失败关闭。
8. 备份可验证，恢复到临时验证环境后核心数据可读。
9. Windows 只需 Docker Desktop/WSL2、仓库/发布包和环境文件即可复用同一 Compose。

## 非目标

- 第一版不部署本地大模型。
- 第一版不开放公网，不配置域名、TLS 或反向代理。
- 第一版不把陆羽做成独立容器。
- 第一版不自动生成或托管用户的火山/MXAPI 凭据。
