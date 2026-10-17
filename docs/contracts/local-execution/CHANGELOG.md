# DClaw Local Execution Standard Changelog

## 1.1 - 2026-10-17

- 明确 DClaw 桌面版是唯一用户登录入口，本地助手不提供独立登录。
- 将本地助手定义为按 MCP 调用加载能力的通用本机工具箱，业务逻辑全部归超级 Agent。
- 固定 `%LocalAppData%\DClawLocalTool` 平台根目录。
- 规定按 Agent 显示名称、任务目录、客户成品和 `res` 过程资源分层。
- 禁止新超级 Agent 创建独立 Runner、独立本地助手或第二套业务状态机。

## 1.0 - 2026-10-13

- 固定 DClaw、超级 Agent、本地能力网关、Runner、能力包和第三方服务的责任边界。
- 定义八个通用 `local_*` MCP 工具。
- 提供八个工具的机器可校验请求 Schema。
- 固定公共客户端键 `local_capability_gateway`，禁止新 Agent 使用业务缩写工具名。
- 定义可定位责任层、组件、操作和 trace 的错误信封。
- 规定同 major 向下兼容、相邻 major 并存和旧工具兼容入口。
- 指定大字报超级 Agent 为首个 V1 参考实现。
- 增加新任务会话可直接执行的超级专家开发与跨平台迁移操作标准。
