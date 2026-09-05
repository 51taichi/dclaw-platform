# 平台能力 Service 边界改造验证记录

日期：2026-09-06。执行方式：用户确认在当前会话、现有目录逐项实施，保留全部已有修改。

## 当前进度

Task 1–7 的本地代码、独立审查、相关测试与交付记录已完成。Task 6 提交 `f86b5ce`；前置兼容挂载独立提交 `ade867e`。后续核实并纠正两处测试夹具后，现有目录完整测试 **3888 passed、25 skipped、0 failed、58 warnings / 307.15 秒**。此前六项失败的诊断与解决经过保留如下，不再作为当前测试阻断。保留当前分支，不合并、推送或部署。未迁移生产数据、未调用付费生成。陆羽 S0–S4 未编辑，未重新执行其真实模型回归。以下 Task 分节保留各检查点当时的结果，当前结论以本节和最终验收汇总为准。

## 最终验收汇总（本地源码）

- 最终全仓回归在用户指定的现有目录运行，保留全部原有修复和本机构建文件：**3888 passed、25 skipped、0 failed / 307.15 秒**。不是纯提交导出目录的全量验证，也不是生产部署验收。25 项跳过为 22 项未配置 PostgreSQL、1 项缺少 lark_oapi、1 项手动契约覆盖元测试、1 项既有已移除 schema 类型测试；没有新增 skip/xfail。
- 现有目录（保留全部原有修复）的相关回归：**405 passed / 19.61 秒**。独立提交候选（不含其他原有修复）的同一测试路径集合：**373 passed / 20.08 秒**。均只有既有 dashscope 弃用警告。数量差异来自原有未提交测试，未删除测试来改变预期。
- 独立候选应用启动：**2 passed / 42.92 秒**，环境无生产配置或凭据，使用隔离存储。静态依赖与两个独立核心子进程覆盖普通画布创建、工作流约束、终态与资产投影恢复；不代表完整 HTTP 应用在专家源码物理缺失时仍可运行供应商生成。
- 通知失败/重试增补检查 **1 passed**：实际 Job 文件及钱包、账单、用量订单、执行、用量项表快照不变。事件回传不发起生成，不冒充客户提交或审核通过。
- 独立候选最初 **370 passed / 2 failed**：两项前端兼容前缀返回 404。独立审查用 HEAD 路由同样复现，定位到此前未提交的兼容挂载。仅此 9 行原有修复作为前置提交 `ade867e` 保留，认证仍为 `require_user`；HEAD 加该修复单独验证 **3 passed**。其他卡片恢复、会话模型、媒体审核上下文、计费等原有修复没有夹带进架构候选。
- 最终独立审查针对设计第 9 节核对实际候选，重点测试 **58 passed**，未发现新的 Critical/Important。24 个 Task 6 候选文件逐字核对独立 index；源码唯一 Service、调用方向和原 HTTP 签名保持。
- 既有三节点向导测试用模拟 Job 元数据依次投影 `copy.generate → keyframe.generate → clip.generate → workflow.submit`；任务状态测试覆盖提交、修改、重提、通过及重复事件。它们不是可播放视频或真实专家审核证据。

### 全仓测试及基线失败（历史检查点，已由最终回归更新）

对独立候选执行完整 `pytest -q --tb=short --maxfail=10`，实际跑到 100%：**3824 passed、25 skipped、6 failed、58 warnings / 310.80 秒**。使用清理后的环境、临时 `QWENPAW_WORKING_DIR` 和仓库导出的源码，不导入本机生产配置。跳过包括未配置的 PostgreSQL、缺失的可选 SDK/formatter 和既有移除 schema 的测试；没有新增 skip/xfail。

将同 6 项在所有本轮架构改造之前的 `3225c52` 独立导出目录、同样隔离环境中重新运行，**6 failed / 2.97 秒**，错误逐项一致：

| 测试 | 当前失败原因 |
| --- | --- |
| `test_copy_workspace_md_files_does_not_install_bootstrap_by_default` | 导出源码没有被 git 忽略的 AGENTS.md 模板 |
| `test_presentation_builder_strict_qa_rejects_empty_slides` | 隔离 PATH 没有 soffice/libreoffice 与 pdftoppm |
| `test_presentation_builder_auto_routes_roadmap_bullets_to_visual_layouts` | 隔离 PATH 没有 soffice/libreoffice |
| `test_open_api_billing_upgrade_is_idempotent_and_preserves_history` | 旧计费表缺 `event_type`，索引创建失败 |
| `test_console_spa_index_disables_browser_cache` | 导出源码没有被 git 忽略的 console 构建文件，返回 404 |
| `test_mobile_tasks_match_web_task_list_across_enabled_agents` | 测试中的 `legal` Agent 无法由既有请求上下文取得，返回 404 |

此处仅证明相同环境的改造前基线可复现，不宣称这些模块在线上正常。没有为了全绿修改计费、移动端、模板或放松断言；全仓集成/合并暂停，后续需独立处理基线和测试环境。保留当前分支与全部用户原有修改，不推送、不自动清理目录。

提交前对 64 个既有文件做 SHA256 指纹核对：除本轮计划/报告的明确更新外，其余内容保持不变。选择性暂存只迁入已审查的架构块，旧卡片/会话/审核相关差异保留在工作区新位置。

### 六项失败的后续只读诊断

在现有目录保留全部文件，仍使用空环境和临时 `QWENPAW_WORKING_DIR`，仅把已安装的 Codex 渲染工具目录加入 PATH，重跑上述六项：**4 passed、2 failed / 4.56 秒**。模板复制、console 静态入口及两个演示文稿测试均通过；没有修改测试断言或生产代码。这四项是独立源码导出/隔离 PATH 的环境差异，不需要据此更改 AIGC 实现，也不代表纯源码发布包已经包含模板和 console 构建。

剩余两项：

- 移动端：测试只替换 `routers.mobile.load_config`，但实际调用的 `agent_context.get_agent_for_request` 使用另一个模块的 `load_config`，得到没有 `legal` 的真实临时配置。仅在诊断进程内让后者读取同一测试配置后，原测试断言 **1 passed / 2.13 秒**。该探针不修改文件、不降低生产身份校验，不计入正式测试修复；建议仅补完整 fixture。
- 计费升级：测试构造的旧 `billing_ledger_entries` 只有 id/business_type/business_key/created_at，`create_all → _ensure_open_api_billing_columns → _ensure_open_api_billing_indexes` 却创建依赖 event_type/status/wallet_id 的索引。前述改造前版本与现有目录均复现。修复前需进一步核对受支持的历史表结构，再决定补兼容迁移还是纠正非真实历史 fixture；不能直接跳过索引或猜测补写财务事实。

这两项不属于已批准的 AIGC Service 解耦实现。下一步建议单独授权其最小兼容/测试修复，不改价格、扣费计算、授权边界，不执行生产迁移。当前仅更新诊断记录，原业务文件未编辑。

### 两项测试夹具修正（后续核实）

以上只读诊断中的计费原因已进一步核实，不需要修改生产迁移：`beb37fc` 的最初账本表已经包含 wallet_id、event_type、status、credit_delta 等字段；`4babcc9` 引入 OpenAPI 测试时使用了四列简化表，`43e547b` 的用量排名索引暴露了该夹具缺口。没有证据表明受支持的历史账本曾采用这张四列表。

- `test_open_api_schema.py` 改用独立写出的历史标量列定义，不从当前生产 metadata 自动生成；保留原迁移、唯一性、外键和历史断言，另检查排名索引与原财务值不变。不新增生产补列，不猜测补写财务事实。
- `test_mobile_router.py` 让 agent_context 的配置读取使用同一测试配置，仍执行真实的 Agent 存在性、启用状态和用户范围校验，没有替换授权函数。
- 修复前定向重跑 **2 failed / 3.45 秒**；修正后两个完整测试文件 **19 passed / 2.49 秒**，一条既有警告。独立复核也运行 **19 passed**，未发现 Critical/Important，确认未降低原断言或掩盖生产缺陷。
- 两处仅为验收夹具纠正，未修改生产 schema、移动端路由或 agent_context；不需要扩展到生产兼容修复。先前“需单独授权兼容修复”的建议由本次历史核实替代。

修正后的全仓命令（空环境，无生产凭据；PATH 仅添加已安装的渲染工具，未安装新依赖）：

```bash
env -i \
  PATH=/Users/moxi/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override:/usr/bin:/bin:/usr/sbin:/sbin \
  QWENPAW_WORKING_DIR=/tmp/dclaw-boundary-index.u2iYfE/current-full-runtime \
  .venv/bin/python -m pytest -q --tb=short --maxfail=10 -rs --disable-warnings
```

退出码 0，实际运行至 100%，**3888 passed、25 skipped、58 warnings / 307.15 秒**。提交前对 62 个非计划/报告的既有修改文件再次核对 SHA256，零差异；仅选择性提交上述两个测试文件与计划/报告。全仓成功覆盖当前工作目录，不将其中原有业务修复夹带到本轮提交。

### 尚未验收 / 发布边界

- 真实 AIGC 生成、真实模型审核、原任务会话的浏览器闭环均未在本次重构中执行。
- PostgreSQL 并发和 Windows 文件锁未实测；已测试 SQLite、macOS 文件锁及真实子进程并发。
- 尚未部署；旧工作流须在维护窗口备份、初始化核心表并执行独立 dry-run。冲突不能猜测补齐或直接放行，迁移方法见本文末部。
- 同画布多卡片、跨卡素材版本依赖、其他模块能力开放不在此次改造范围内。专家消费者开关只控制事件适配，不是整个专家 API 的禁用开关。

### 原会话验收入口

原有测试会话：`http://127.0.0.1:18088/task/f2294f76-4e08-4d83-8bb4-aad52344488e`（来自用户测试记录，不表示当前服务已运行或该会话已恢复）。上线验收必须从该会话或新的授权测试会话点击实际卡片，不手工拼一个画布链接替代：核对原任务绑定 → 按向导制作 → 提交 → 由发起专家审核 → 返回同一会话查看真实状态。未完成前不得宣称线上闭环通过。

## Task 5：结果恢复与投递保护

- 原通知/画布投影失败会把成功变成失败，两个真实路由隔离案例先复现失败；现改为先持久化终态与通用事件，再补写 JSON 和发送 UI 通知。终态、领域事件和执行完成标记同一 SQL 事务提交；事件插入中断会整体回滚，已保存成功不允许降级为失败。
- 供应商已返回、结果数据库不可用的隔离案例，首次复现未受控异常；现在保留需对账的执行标记，同 Job 重试不再次调用生成。此项尚不是供应商查询恢复完成，见下方剩余项。
- 早期独立审查发现历史无主画布入口已授权、恢复却永久拒绝投影。增加失败测试后，把可信入口的 allow_ownerless 权限保存在结果记录中；默认严格访问不变，不向专家入口开放无主资源兼容权限。
- 两个恢复失败测试复现同 Job 的旧失败快照覆盖新成功、队首坏记录饿死后续任务；改为 SQL 锁内重读最新结果和按最近尝试时间轮转。待恢复记录不被删除或假标记成功。
- 文件投影新增 compare_and_write，所有资源写/删使用同一跨进程文件锁。真实进程并发计数测试通过；用户在合并期间编辑画布的测试先失败，再验证旧投影不覆盖新编辑、下次恢复保留编辑并补齐输出。
- 第二轮独立审查复现跨 Job 的旧成果覆盖同节点的新成果。增加“旧任务后完成”和“旧投影后恢复”两个失败测试后，加入核心节点成果头：按任务创建时间选择当前成果，旧 Job/Asset 保留，但不替换新节点输出。无日期历史任务先于有日期任务；同时间戳按成功提交顺序处理。
- 通用事件消费者按需逐条领取，每批最多 100 条；有限租约、过期重领、旧 token 不能 ACK、不同消费者独立回执；5/15/60/300 秒退避，超时失败保留待重试，取消不吞掉事件。异常正文和本地私有素材路径不进入通用事件。
- 最新广域回归 **342 passed、15.52 秒**，一条已有 dashscope 弃用警告；git diff --check 通过。包括 Task 1–4 的全部相关回归、结果恢复、事件投递和 RuntimeEventBus 路由。SQLite 与 macOS 本地多进程文件锁实测；PostgreSQL、Windows 文件锁和线上闭环未实测。
- 后续独立复核发现两项 Important，均先增加失败测试：开始生成的 UI 通知错误使未调用供应商的 attempt 滞留；历史无主画布按管理员分成果头仍会发生旧结果覆盖。现隔离 running 通知，在调用供应商前的本地失败/取消释放执行占位；成果头改为全局物理 canvas/node 维度，访问仍使用原结果 owner 和受信无主兼容权限。
- 上述修复后最新广域回归 **345 passed、14.06 秒**，已有警告不变，git diff --check 通过。没有把尚未完成的供应商查询恢复或原会话事件适配列为通过。
- 两项定向独立复核均关闭，审查方运行 **9 passed**，另行验证取消发生在供应商调用前时可安全重试且仅生成一次。本结论只覆盖这两项修复，不作 Task 5 总体验收。

### Task 5 后续完成与验收

- 五个已有 MXAPI 适配器（Seedance、Grok、Jimeng、GPT Image、Nano2）接入持久提交意图与已受理任务 ID；恢复只查询同一任务，不再次 POST 生成。未知受理结果保留需对账；明确拒绝与终态失败分别保存。没有现成查询能力的提供商不宣称支持自动恢复。
- 同一 Job 的命令摘要、owner、租约和 token 共同约束恢复；过期 worker 即使未被接替也不能落盘。只查询恢复保留资源/工作流归属检查，不要求重新发布模型或重签已失效输入；新生成仍执行原模型政策与发布校验。
- 取消结果持久化并隔离旧 attempt；正在重跑的历史失败任务仍能取消。通知、模型查找和 Seedream 异步输入预处理后再次检查取消，避免取消后开始新的付费调用。不能撤销已经被外部供应商接受的请求，不宣称供应商恰好执行一次。
- 通用持久事件接到原 RuntimeEventBus；通知故障可重试，旧版本事件不会倒退 UI。应用启动/关闭组装恢复 worker；投影逐条在线程执行，停止时等待当前原子投影完成，不继续后续批次，不阻塞事件循环。
- 上述新增行为逐项先失败后修复；独立增量复核未发现新的 Important，复核方 provider recovery/runtime delivery **26 passed**。
- 最终广域相关回归 **371 passed、15.29 秒**，一条已有 dashscope 弃用警告；`git diff --check` 通过。隔离真实应用启动 **2 passed、41.95 秒**，使用清理后的环境和临时存储，不连接生产数据。

仍未完成：Task 6 原专家/原会话事件适配与 Service 迁出；Task 7 独立运行、接口兼容整体验收。SQLite 与 macOS 多进程文件锁已测试，PostgreSQL、Windows 和线上真实素材审核未实测。本批不得作为完整可部署版本。

本轮没有更改陆羽 S0–S4、模型发布政策、计费或真实素材审核；模拟供应商返回值只用于故障注入，不冒充真实生成和真实审核成功。

## Task 6 第一部分：专家应用 Service 与创建适配器迁出

- `SuperExpertPlatformService` 从 HTTP 路由迁入 `super_experts/service.py`，只有一个实现；旧路由保持类型 re-export 和既有 HTTP 路径。默认工厂移到 `super_experts/composition.py`，runner 直接使用该工厂。
- 专家卡片对应的创建、空画布、编译图落盘适配、未使用资源补偿及工作流上下文查询移到 `super_experts/aigc_adapter.py`。核心系统路由不再持有专家专属 provision 函数，也不反向调用新适配器。适配器通过显式注入的核心 Canvas/Asset Service 工作，没有 HTTP 自调用或另一套资源实现。
- 两项新边界测试先 **2 failed**（新模块缺失），迁移后暴露 grants 类型注解带入 sealed package/FastAPI 的非必要导入；改为 TYPE_CHECKING 后通过。独立子进程禁止 HTTP 路由/FastAPI 导入，实际创建画布、读取预填节点、拒绝跨 owner、确认未创建生成 Job。默认 composition 属应用组装层，其经 grants 引入既有 sealed policy 的 FastAPI 依赖不属于核心，未扩大修改该包。
- 调整原测试的内部入口及依赖注入夹具，保留原权限、画布、审核和回传断言。广域相关回归 **373 passed、15.08 秒**；runner 独立回归 **5 passed、1.66 秒**；一条已有 dashscope 弃用警告。迁移后的隔离应用启动 **2 passed、41.45 秒**。独立复核 **124 passed**，未发现新的 Critical/Important。
- 本部分尚未提交：原平台路由与 runner 中存在用户已有未提交修复，迁移时原样保留；不得把整个文件差异一并暂存。Task 5 已单独提交 `cab6a0f`。
- Task 6 仍缺：核心事件到原安装/专家/会话/卡片的可靠适配、过期/撤权/乱序边界，以及可选消费者启动接线；外层审核入口对系统路由辅助函数的调用也仍待清理。Task 7 整体验收未完成，不宣称已全面解耦或线上闭环成功。

## Task 6 第二部分：原会话事件适配、顺序与并发保护

- 新事件适配器首先得到 10 个缺失模块失败，再逐步实现。只消费核心生成进度，按真实安装 release/digest、grant、会话 owner/agent/tenant、画布/节点/工作流 revision 与输出资产快照查验原绑定；不自动提交素材、不写 ACCEPTED、不创建生成 Job。会话支持公共 chat ID 与内部 session ID，歧义拒绝回传。
- 事件先持久化、后通知；总线故障保留同一事件 ID 重试。安装停用、原归属失配、任务取消、版本失效或素材丢失时记录 blocked，不转投另一个专家或会话。`QWENPAW_SUPER_EXPERT_AIGC_EVENTS_ENABLED` 可关闭专家消费者，核心恢复消费者照常组装。
- 顺序失败测试复现旧 Job 消息覆盖新成功；增加核心节点成果头读取。独立审查进一步复现“旧消息已过检查，新消息抢先发出”的并发窗口。新增同节点交错测试先失败，再用跨进程节点锁覆盖 fresh 检查、事件保存和异步通知，修复后通过。
- 独立审查复现事件仓库跨实例整文档覆盖导致已确认事件丢失。线程交错测试先失败；`append` 和 `save_review_receipt` 完整读改写使用共享文件锁。锁实现提取至 `storage/json_file_lock.py`，核心资源存储复用，未复制另一套锁。线程混合事件/回执写入及两个真实子进程并发写入通过。
- 同步文件等待阻塞主循环的测试先失败；现在后台线程持锁，主循环负责异步发布，取消/超时在 finally 释放并 drain 当前写入。定向组合 **57 passed**。独立复核 **44 passed**，两项 Important 均关闭，取消中写入及重领没有新 Important。
- 审核入口不再 import 系统 AIGC 路由。公共素材源组合、artifact root 解析和错误映射移到应用层 `runtime/aigc_media.py`，底层仍是同一个 Asset Service；系统入口保留历史授权兼容，专家入口要求明确 owner。三例新包装测试先失败，再通过；相关路由/共享素材测试 **165 passed**，独立复核同为 **165 passed**，未发现新的 Critical/Important。
- 本轮广域相关回归 **403 passed、19.85 秒**（含 runner），一条已有 dashscope 弃用警告；隔离应用启动 **2 passed、42.79 秒**。未调用外部付费生成或真实模型审核，未修改部署配置及陆羽 S0–S4；工作区原有部署/计费修改保持原样。
- 新增跨用户并发回传及 Job 文件不变验收时，第一次因测试段落插入位置错误出现 NameError，已修正测试归属；不是生产代码回归，不将该失败算为 TDD RED。
- 当前 Task 6 差异仍未提交：平台 Service 迁移包含原文件里用户已有修改，需按迁移前后来源分离暂存，不能整体提交脏目录。本节更新覆盖上一节“仍缺”中的已实现项，不代表最终接口/线上闭环验收完成。

## Task 7 增补验收进展

- 新增 `test_aigc_core_without_experts.py`：两个独立 Python 进程均禁止导入专家组件、HTTP 路由与 FastAPI；第一进程通过核心 Service 创建普通画布和完整受管三节点图，保存隔离成果元数据；第二进程重启读取图、Job/资产投影和通用事件，仍拒绝错误模型与跨 owner 访问。**1 passed、0.77 秒**，属增补验收而非 RED。
- 使用元数据夹具验证依赖、持久化与访问边界，不冒充真实视频可播放或业务审核通过。最终接口契约核对、完整测试重跑、交付整理及选择性提交仍待完成；未部署、未迁移生产数据。
- 后续汇总回归 **405 passed、18.22 秒**，包含跨用户并发回传、独立核心重启和 runner；一条已有 dashscope 弃用警告，`git diff --check` 通过。跨用户回传仅更新各自原会话，Job 文件和业务任务状态未改变。
- 接口 AST 对照 HEAD：系统 32 个路由、平台原 5 个路由的路径/装饰器/参数保持；三个迁移的请求 DTO 定义保持。首次全量平台路由相等断言因工作区原有的 3 个新增端点失败，核实为 `list_super_expert_cards`、`get_conversation_route`、`execute_frontend_super_expert_command`，本轮保留，未删除或回滚；不能以 HEAD 全量覆盖现有工作区。
- 本轮接口源码对照加既有路由/工作流/闭环状态测试通过，但尚不等价于浏览器真实素材审核验收。剩余为交付文档最终整理与按原始修改来源选择性提交；未启动生产服务、未运行线上迁移。

## Task 1

- 扩展基线 189 passed（AIGC 路由、平台路由、素材任务、工作流任务及编译器），4.92 秒。
- 新资源测试首次 15 failed，均因计划中的独立模块尚不存在；随后实现共享模块。
- 中间回归 9 failed、147 passed：旧测试初始化直接清理已移动的私有 `_JSON_CACHE`。改为清理按 root 缓存的存储工厂；没有改变业务断言、权限或审核预期。
- 兼容回归 172 passed、4.15 秒：资源存储、独立导入边界、AIGC 路由、平台路由、编译器及工作流集成。
- 增补静态依赖扫描后最终 173 passed、3.64 秒；提交 `e0e080e`。
- 验证覆盖：独立进程禁止导入 HTTP/专家模块后读写核心资源；路径越界；原子替换失败保留旧文件；跨 root 缓存隔离；读取返回值修改不影响缓存；损坏文档；删除后不返回缓存。
- 已有 dashscope 弃用警告保留；测试成功不代表真实 AIGC 或线上闭环验收。

现有反向执行绑定查询尚未移除，按 Task 3/4 先建立并迁移核心权威约束后再切换，不能直接删除校验。

## Task 2

- 新共享服务测试首次 5 failed（模块不存在），能力目录新增测试首次 2 failed（模块不存在）；素材来源和旧创建入口委托测试首次 7 failed（方法缺失、旧入口尚未调用共享 Service），随后实现。
- 画布 CRUD、编译图落盘、资产归属、实际模态/节点绑定/文件来源与能力目录移到共享层。旧入口保留薄适配；专家 Service 从路由迁出及组装在 Task 6，不将此处兼容包装当作最终依赖清理完成。
- 两种目录入口使用同一目录构建函数；保留已发布模型、模型政策和提供商可用性筛选。创建和资产测试记录两种入口实际进入同一 Service。
- 独立进程阻止导入 FastAPI、路由与专家模块后，创建/读取画布并投影能力目录成功。此项为增补验收，未宣称首次 RED。
- 保留历史无主资源仅在系统管理员/禁用认证上下文可读的规则，专家严格归属解析不继承该兼容路径。
- 创建补偿只清理匹配归属且未产生 Job/Asset 的画布；补充测试覆盖保留已使用资源、错绑定拒绝及重复清理。跨存储可恢复操作记录仍属 Task 3，不宣称当前补偿已具备并发原子性。
- 扩大回归首次 1 failed、268 passed：旧闭环夹具先创建素材卡片，再创建任务，与工作区原有的“任务必须存在”校验冲突。隔离子进程只还原本轮目录 import 仍重现同一失败；加载提交版（没有该原有脏修改）的平台类则 2 passed。仅把夹具顺序改成先任务后卡片，不改生产 Gate 和原业务断言。
- 修正夹具后 **269 passed、4.21 秒**，1 条已有 dashscope 弃用警告：

```bash
.venv/bin/python -m pytest tests/unit/aigc tests/unit/app/aigc tests/unit/app/super_experts tests/unit/app/test_super_expert_aigc_tasks.py tests/unit/app/test_super_expert_grants.py tests/unit/routers/test_aigc_studio.py tests/unit/routers/test_aigc_studio_provider_filter.py tests/unit/routers/test_aigc_model_policy.py tests/unit/routers/test_super_expert_platform.py tests/integration/test_super_expert_aigc_workflow.py tests/integration/test_luyu_aigc_closed_loop.py -q
```

上述闭环测试使用隔离任务仓库和模拟素材 ID，验证状态/事件，不是读取真实视频后的陆羽审核或线上闭环验收。

### 检查点 A 审查

- 独立只读审查：无 Critical/Important；审查方独立运行相关测试 106 passed。
- 发现一个 P3：云端审核不应无条件创建本地工作区。新增测试先得到 1 failed，再改为仅本地素材解析工作区；云端直接使用已有签名来源。
- 修正后同一广域回归 **270 passed、5.49 秒**，已有警告不变。另补“迁移前保留原权威执行约束查询”特征断言，边界测试 3 passed、0.43 秒；Task 4 会将其替换为禁止反向依赖的断言，不永久豁免。
- 当前仍保留 `provision_super_expert_*` 旧路径包装以及原权威绑定反查，分别由 Task 6、Task 3–4 迁移；当前成果不能单独作为全面解耦上线版本。
- 提交前最终完整相关回归：**271 passed、4.07 秒**，`git diff --cached --check` 通过。所有既有脏修改仍留在原处，本轮只暂存平台路由中的单行目录 import，没有夹带其原有卡片、审核与会话回传修改。

## Task 3

- 新核心绑定测试首次 11 failed（模块不存在），实现后 11 passed。恢复测试首次 6 failed（缺少 Service），随后纠正夹具遗漏的必需 asset_resolver 参数，完成后 17 passed。新增平台恢复测试先 1 failed，接入后通过；并发及已修改/已删除画布测试为增补验收，不虚称 RED。
- 新增核心约束表和 PREPARED/APPLIED 操作日志；仅复用启动期建表机制，请求不执行 DDL。冻结 DTO 保存 owner、canvas、workflow revision、逻辑/物理节点及 provider/model/capability，整组冲突回滚。
- 核心在文件写入之前持久化稳定资源 ID 和完整快照；文件/绑定/完成标记处中断后，重建 Service 仍恢复同一图。未完成操作的核心绑定查询拒绝执行；实际生成入口的查询切换留在 Task 4。
- 默认平台工厂接入新核心创建路径。若核心 APPLIED 后外围卡片绑定失败，保留该已完成核心资源，重试修复原绑定，不删除日志已经指向的画布。旧未登记日志路径仍保留原精确补偿。未重试的外围失败可能留下无卡片核心资源，本阶段不增加自动清理任务。
- 独立审查发现并复现两项 Important：重试依赖当前模型目录；PREPARED 文件恢复可能覆盖并发用户编辑。新增测试先得到 2 failed、80 passed，再改为编译前按摘要恢复已接收命令、已存在匹配画布不重复写回。复核两项均关闭，无新 Critical/Important；审查方独立运行 42 passed。
- 恢复不会绕过生成时的模型政策、提供商可用性或素材归属校验；本阶段只恢复已接受的资源创建，不启动生成。
- 提交前广域相关回归：**294 passed、6.57 秒**，1 条已有 dashscope 弃用警告。测试使用临时 SQLite 与 JSON 目录；未配置测试 PostgreSQL，故 PostgreSQL 并发语义尚未实测。
- 旧专家绑定反查仍保留到 Task 4 迁移/切换完成；现版本不具备单独部署条件，也不代表线上 AIGC 审核闭环完成。平台路由与测试仅暂存本轮新增的核心接入/恢复块，保留原有未提交修复。

## Task 4 / 检查点 B

- 新迁移与查询切换测试首次 **10 failed**：迁移模块缺失、旧校验仍接受未迁移的可编辑模型字段。实现迁移后 8 passed、2 failed；再切换系统查询到核心记录，两项通过。
- 静态边界测试从“迁移前保留反查”改为禁止反向 import，先 1 failed、2 passed，再移除反向查询。动态子进程禁用 FastAPI、路由、专家模块后，可登记与读取核心绑定并拒绝错误模型；后者为增补验收。
- 离线迁移默认 dry-run，不执行 DDL、不改任务/画布/资产文件；真实旧平台夹具创建三节点工作流后，apply 两次第二次 unchanged，原文件字节保持不变。核心绑定整组冲突回滚，检查 owner、workflow revision、逻辑/物理节点对应及节点类型；约束来自持久蓝图，不信任画布模型参数。
- 命令行测试先 2 failed（脚本不存在），实现后通过；默认预检零写入，拒绝不存在的 SQLite 文件而不自动创建空库，错误输出不带数据库连接串或异常正文。缺表只报 CORE_SCHEMA_NOT_INITIALIZED，不在工具或请求内偷偷建表。
- 生成校验切换引入必需数据库依赖，既有路由夹具未初始化新表，首次 39 failed、106 passed，返回 503。补充每测试隔离 SQLAlchemy Engine/schema，并为工作流模型约束测试登记真实核心记录；原业务断言保留，随后相关 113 passed。数据库不可用时生产路径仍拒绝生成，不靠放行修复测试。
- 独立审查复现两项 Important：更换物理节点 ID 并删除所有标记可绕过约束；PREBUILT 缺蓝图被误计为正常 skip。增加 3 个失败案例后，改为核心整画布受管识别、缺节点绑定拒绝执行、先验证 binding/workflow 一致性再处理 LEGACY。最终审查均关闭，无新 Critical/Important；审查方执行 46 passed。
- 另补旧 queued Job 的前台/后台执行测试，首次均未拦截；现在 `/run` 在状态写入和供应商调用前复用同一提交校验。已成功/取消的任务保持原有直接返回行为。模型三元组比对统一调用核心 validate_execution，没有再写一套比对规则。
- 最终广域相关回归：**313 passed、14.97 秒**，1 条已有 dashscope 弃用警告；git diff --check 通过。SQLite 与隔离 JSON 验证，不宣称 PostgreSQL 或真实视频审核已验收。

### 迁移范围与上线前提

本阶段仅自动迁移拥有完整、同 revision、PREBUILT_WORKFLOW 蓝图的旧任务。合法 LEGACY 单节点任务原本没有不可变蓝图，保留原行为并统计 skipped；MANUAL_BUILD、缺蓝图、缺节点、归属/版本冲突必须进入 conflicts，不能猜参数后强行登记。人工搭建旧任务需单独对账后才能切换，不把 conflict 当作迁移成功。

离线预检示例（仅展示占位路径，未执行线上迁移）：

```bash
.venv/bin/python scripts/migrate_aigc_execution_bindings.py \
  --legacy-root /path/to/sealed_agents/platform \
  --studio-root /path/to/aigc_studio \
  --database-url sqlite:////path/to/existing-database.sqlite
```

必须先进入维护窗口、停止应用写入、备份并通过现有 schema 初始化流程建好新表，再运行预检；消除 conflicts 后才可对批准的目标显式加 --apply。工具退出码：0 无冲突、1 有资源冲突、2 输入/存储错误。未提供在线双写迁移或自动清理功能。

旧 provision_super_expert_* 包装及专家应用 Service 迁出仍属 Task 6；持久结果/事件与回传属 Task 5–6，最终整体验收属 Task 7。当前代码不应单独部署，原任务会话 → 卡片 → AIGC → 审核回传的线上闭环不在本批成功声明内。
