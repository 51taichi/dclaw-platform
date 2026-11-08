# DClaw Framework 演示页

`index.html` 是可离线打开的单文件架构演示页，不需要启动 DClaw Server 或其他本地服务。

## 使用

直接用浏览器打开 `index.html`。页面包含三个视图：

- 平台总览
- Super Agent Support
- OpenAPI 应用

点击任意架构节点，会在当前视图下方显示该节点的职责说明。

## 内容维护

页面内容、样式和交互均已内嵌到 `index.html`。新增内容时，优先保持以下边界：

- DClaw Core 负责稳定的平台通用能力。
- Plugin 扩展能力，不替换 Core。
- Super Agent 负责业务意图、决策、编排和验收。
- OpenAPI 为外部应用提供程序化入口，并复用同一 Agent Runtime。

更新架构图时应同时检查桌面宽度和 320px 移动宽度，避免节点、标签或页签横向溢出。
