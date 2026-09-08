# 本地 DClaw 与陆羽发布记录

日期：2026-09-06。用户明确授权更新本地 DClaw、重打包上传陆羽；随后确认按既有容器内发布流程继续，保留异常旧卡片，仅迁移有效工作流。

## 已部署

- DClaw：`dclaw-local:s9b897da1-c9c2e271c-ee683ea2381f`。从现有后端及前端目录构建，包含目录中既有未提交修复；不是只部署架构提交，也没有自动提交这些原有修改。
- STT：`dclaw-stt-local:s9b897da1-0a5de1b34b52`。两容器均 healthy；PostgreSQL、Redis 未重建或清空。
- 陆羽：`2.10.29`，build `luyu-2.10.29-20260906`；release `30d0deb433c9435b8cd4a2cfb442d52c`，availability `available`，runtime validation `valid`。
- 发布前活动陆羽版本是 `2.10.27`，release `8aac06c8096a4cd5868fb992c1e54463`；该版本及旧运行状态均保留。未批量复制旧会话状态到新安装命名空间，建议新建会话测试。
- 签名包：`/Users/moxi/.dclaw-local/luyu-traffic-operator-agent-2.10.29-local.zip`，sidecar 校验通过。内部 release manifest SHA256：`7a586df87d92c40fe085b2e19014b938e8b7d672e91c3d7d2baee0aa29df1c24`。

## 备份与迁移

- 备份目录：`/Users/moxi/.dclaw-local/backups/update-20260906-JzPPui`，包含 PostgreSQL dump、工作目录/secret volume 压缩备份、原环境配置、迁移报告和前后发布状态。目录受本机权限保护，不公开分享。
- 本地回滚镜像：`dclaw-local:rollback-20260906-jzppui`，保留旧容器现场代码修改；不以原基础镜像冒充现场快照。
- 停应用写入后通过现有 schema 初始化流程创建所需表，再预检、迁移、重复预检。5 张旧卡片中：1 个有效预建工作流迁移；2 个合法旧单节点任务跳过；2 个已知异常原样保留。重复预检 eligible=0、unchanged=1。
- 已知异常：`material-manual-smoke-ade4e77670` 为手工工作流，需独立对账；`material-workflow-smoke-06b750edc1` 的原画布不存在。不伪造蓝图、重建丢失画布或删除记录，不宣称这两张旧卡片可继续制作。
- 迁移前后 12 个任务/画布/Job/资产 JSON 文件 SHA256 一致；没有生成新素材、扣生成费用、修改业务审核或补造阶段 PASS。

## 发布与验证

- 陆羽完整测试 1261 项通过，production Harness 部署校验通过。版本更新初次测试有 3 个旧 built_at 预期失败，同步版本身份预期后全量重跑通过；未改变业务逻辑。
- 前端卡片、向导与任务路由定向测试：7 文件、52 项通过；Docker 前端构建成功。
- 复用之前的容器内维护方式：确认现有用户 id=1 的 role=admin，签发 30 分钟令牌，走正式管理 HTTP API 安装、整包授权、运行时校验与激活，结束后撤销令牌。没有改密码、关闭认证或绕过包签名/能力授权校验。
- DClaw 共享 Canvas Service、专家 Service 安装文件 SHA256 与本地源码一致；陆羽签名发布目录逐文件摘要与 manifest 一致。运行目录除系统管理的 agent.json/skill.json 外逐文件一致；原 11 个陆羽 Skill 定义不变，skill.json 由既有系统默认 Skill 同步增加两个内置 Skill 和注册时间版本，不将其误报为签名包漂移。
- `/api/version`、原任务页及 AIGC 页面 HTTP 200；首页引用的 8 个 JS/CSS 资源全部 HTTP 200。这证明部署和静态入口可用，不等于浏览器完整创作/审核验收。

## 测试入口与边界

打开 `http://127.0.0.1:18088`，强制刷新，新建任务并选择陆羽后测试。不要以旧异常卡片判断新流程。

本次未执行真实模型业务对话、付费图片/视频生成、素材审核或内容发布；这些操作留给用户测试。旧会话、旧卡片与旧安装数据保留，但没有宣称跨安装状态自动迁移或所有旧卡片已恢复。
