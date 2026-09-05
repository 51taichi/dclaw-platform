# 平台能力 Service 边界改造验证记录

日期：2026-09-06。执行方式：用户确认在当前会话、现有目录逐项实施，保留全部已有修改。

## 当前进度

Task 1–3 已完成共享 Service、核心工作流执行绑定和可恢复操作记录，并通过独立审查。Task 4–7 尚未完成。未部署、未迁移生产数据、未调用付费生成。陆羽 S0–S4 未编辑。

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
