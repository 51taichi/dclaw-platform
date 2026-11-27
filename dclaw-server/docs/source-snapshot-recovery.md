# DClaw 源码快照下载与本地对比流程

本文档记录在 Git 仓库不可用时，如何从服务器部署目录或 Docker 容器中获取 DClaw/QwenPaw 源码快照，并下载到本地用于后续差异对比和代码合并。

## 1. 已确认的服务器信息

服务器上目前存在以下关键目录和容器：

| 类型 | 名称/路径 | 说明 |
| --- | --- | --- |
| 当前较新的源码目录 | `/opt/qwenpaw` | 优先使用；包含后端、Web 控制台、小程序、官网等源码。 |
| 较旧源码目录 | `/opt/dclaw` | 旧版本目录，不优先使用。 |
| 运行容器 | `dclaw` | 镜像为 `dclaw-local:latest`，端口 `127.0.0.1:18088->8088`。 |
| 官方容器 | `dclaw-official` | 主要是 Next.js 构建产物，不是当前项目完整源码。 |
| 数据服务 | `dclaw-postgres` / `dclaw-redis` | 运行数据服务，不用于源码恢复。 |

已验证：

- `/opt/qwenpaw/console` 存在 Web 控制台前端源码。
- `/opt/qwenpaw/miniapp` 存在小程序源码。
- `/opt/qwenpaw/website` 存在官网/文档站源码。
- `dclaw:/app/src` 容器内存在 Python 后端源码。
- `dclaw:/app/src/qwenpaw/console` 只有前端构建产物，不是 React/TypeScript 源码。

## 2. 推荐获取方式

优先从服务器宿主机的 `/opt/qwenpaw` 打包源码，而不是从 Docker 容器中恢复。

原因：

- `/opt/qwenpaw` 包含完整项目结构；
- Docker 容器里的前端通常只有构建后的 `index.html`、`assets/*.js`、`assets/*.css`；
- 直接打包宿主机源码更完整，也更容易和本地项目对比。

## 3. 服务器打包命令

在服务器上执行：

```bash
cd /opt
tar --exclude='qwenpaw/console/node_modules' \
    --exclude='qwenpaw/console/dist' \
    --exclude='qwenpaw/console/.vite' \
    --exclude='qwenpaw/miniapp/node_modules' \
    --exclude='qwenpaw/miniapp/dist' \
    --exclude='qwenpaw/website/node_modules' \
    --exclude='qwenpaw/website/dist' \
    --exclude='qwenpaw/venv' \
    --exclude='qwenpaw/working' \
    --exclude='qwenpaw/working.backups' \
    --exclude='qwenpaw/working.secret' \
    --exclude='qwenpaw/logs' \
    -czf qwenpaw-source-snapshot.tar.gz \
    qwenpaw
```

这个包会包含：

- 后端源码；
- Web 控制台源码；
- 小程序源码；
- 官网/文档站源码；
- 项目配置文件；
- Docker / 部署配置。

这个包会排除：

- `node_modules`
- `dist`
- `.vite`
- Python 虚拟环境 `venv`
- 运行工作目录 `working`
- 备份目录 `working.backups`
- 敏感目录 `working.secret`
- 日志目录 `logs`

## 4. 本地下载命令

在本地 Mac 终端执行：

```bash
scp root@47.121.183.91:/opt/qwenpaw-source-snapshot.tar.gz .
```

如果当前终端在用户主目录 `~`，文件会下载到：

```text
/Users/moxi/qwenpaw-source-snapshot.tar.gz
```

也可以直接下载到当前项目目录：

```bash
scp root@47.121.183.91:/opt/qwenpaw-source-snapshot.tar.gz "/Users/moxi/Desktop/codex space/d1paw-repo/"
```

下载后文件路径为：

```text
/Users/moxi/Desktop/codex space/d1paw-repo/qwenpaw-source-snapshot.tar.gz
```

## 5. 服务器临时包清理

确认本地已经下载完成后，可以在服务器上删除临时压缩包：

```bash
rm -f /opt/qwenpaw-source-snapshot.tar.gz
```

确认是否删除：

```bash
ls -lh /opt/qwenpaw-source-snapshot.tar.gz
```

如果提示 `No such file or directory`，表示临时包已删除。

注意：这里只清理临时源码包，不清理系统日志、shell history、审计记录或服务器上的正式项目目录。

不要删除：

```text
/opt/qwenpaw
/opt/dclaw
Docker 容器
Postgres / Redis 容器
系统日志
shell history
```

## 6. 本地解压建议

不要直接覆盖当前项目目录。建议先解压到临时目录：

```bash
mkdir -p /private/tmp/qwenpaw-source-snapshot
tar -xzf "/Users/moxi/Desktop/codex space/d1paw-repo/qwenpaw-source-snapshot.tar.gz" \
    -C /private/tmp/qwenpaw-source-snapshot
```

解压后目录通常是：

```text
/private/tmp/qwenpaw-source-snapshot/qwenpaw
```

## 7. 本地差异对比流程

当前本地项目目录：

```text
/Users/moxi/Desktop/codex space/d1paw-repo
```

服务器快照目录：

```text
/private/tmp/qwenpaw-source-snapshot/qwenpaw
```

推荐先对比文件清单：

```bash
diff -qr \
  "/Users/moxi/Desktop/codex space/d1paw-repo" \
  "/private/tmp/qwenpaw-source-snapshot/qwenpaw" \
  | head -200
```

也可以针对重点目录对比：

```bash
diff -qr \
  "/Users/moxi/Desktop/codex space/d1paw-repo/src" \
  "/private/tmp/qwenpaw-source-snapshot/qwenpaw/src" \
  | head -200
```

```bash
diff -qr \
  "/Users/moxi/Desktop/codex space/d1paw-repo/console/src" \
  "/private/tmp/qwenpaw-source-snapshot/qwenpaw/console/src" \
  | head -200
```

```bash
diff -qr \
  "/Users/moxi/Desktop/codex space/d1paw-repo/miniapp/src" \
  "/private/tmp/qwenpaw-source-snapshot/qwenpaw/miniapp/src" \
  | head -200
```

## 8. 推荐合并策略

不要一次性覆盖整个本地项目。建议按模块合并：

1. 先对比后端 `src/qwenpaw`。
2. 再对比 Web 前端 `console/src`。
3. 再对比小程序 `miniapp/src`。
4. 最后对比配置文件，例如：
   - `pyproject.toml`
   - `docker-compose.yml`
   - `deploy/Dockerfile`
   - `console/package.json`
   - `console/package-lock.json`
   - `miniapp/package.json`
   - `website/package.json`

合并前先看差异：

```bash
diff -u \
  "/Users/moxi/Desktop/codex space/d1paw-repo/console/package.json" \
  "/private/tmp/qwenpaw-source-snapshot/qwenpaw/console/package.json"
```

确认后再复制单个文件或单个目录。

## 9. 如果只想拿 Web 前端

服务器上只打包 Web 控制台：

```bash
cd /opt
tar --exclude='qwenpaw/console/node_modules' \
    --exclude='qwenpaw/console/dist' \
    --exclude='qwenpaw/console/.vite' \
    -czf qwenpaw-console-src.tar.gz \
    qwenpaw/console
```

本地下载：

```bash
scp root@47.121.183.91:/opt/qwenpaw-console-src.tar.gz .
```

服务器清理：

```bash
rm -f /opt/qwenpaw-console-src.tar.gz
```

## 10. 如果只想从容器拿后端源码

通常不优先推荐，因为 `/opt/qwenpaw` 更完整。但如果只需要容器内正在运行的后端源码，可以在服务器执行：

```bash
mkdir -p /opt/dclaw-recovery
docker cp dclaw:/app/src /opt/dclaw-recovery/src
docker cp dclaw:/app/scripts /opt/dclaw-recovery/scripts
docker cp dclaw:/app/pyproject.toml /opt/dclaw-recovery/pyproject.toml
docker cp dclaw:/app/setup.py /opt/dclaw-recovery/setup.py
docker cp dclaw:/app/README.md /opt/dclaw-recovery/README.md
cd /opt
tar -czf dclaw-recovery-src.tar.gz dclaw-recovery
```

本地下载：

```bash
scp root@47.121.183.91:/opt/dclaw-recovery-src.tar.gz .
```

服务器清理：

```bash
rm -f /opt/dclaw-recovery-src.tar.gz
rm -rf /opt/dclaw-recovery
```

## 11. 关键结论

后续定期同步时，优先使用：

```text
/opt/qwenpaw
```

而不是：

```text
/opt/dclaw
dclaw:/app/src/qwenpaw/console
dclaw-official
```

原因：

- `/opt/qwenpaw` 是目前发现的较新完整源码目录；
- `/opt/dclaw` 是旧版本目录；
- `dclaw` 容器中的前端是构建产物；
- `dclaw-official` 是 Next.js 构建产物，没有发现完整源码。

