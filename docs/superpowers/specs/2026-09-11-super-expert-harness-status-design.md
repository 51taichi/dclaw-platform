# 超级专家 Harness 状态只读展示设计

## 目标

在 DClaw Console 的“超级专家”页面，为每个已安装超级专家展示两个不可编辑的 Harness 状态：

- Skill 智能调用；
- 完整 Agent 循环。

开关状态必须来自当前激活版本的有效配置。前端不得写死状态，也不得保存本地开关值。本期不提供修改接口，不改变普通专家页面。

## 范围

本期包含：

1. 为超级专家配置声明补充可读取的 Agent Loop 能力字段；
2. 管理端列表接口只投影两个布尔状态，不返回配置文件、Skill、提示词或运行时代码；
3. 超级专家展开区域显示两个禁用状态的 Switch 和说明文字；
4. 新陆羽包声明两个能力均已开启；
5. 后端、前端和发布包测试，以及当前本地 DClaw 的构建部署。

本期不包含：

- 通过 UI 修改 Harness 状态；
- 新增写接口；
- 为普通专家展示或开放 Harness 配置；
- 改变现有 Agent Loop 或 Skill Reader 的执行语义。

## 权威配置

### Skill 智能调用

权威字段为当前激活超级专家 `agent.json` 中：

```json
{
  "tools": {
    "builtin_tools": {
      "read_agent_skill": {
        "enabled": true
      }
    }
  }
}
```

该字段已经控制 `read_agent_skill` 是否注册，因此 UI 状态与真实运行行为一致。

### 完整 Agent 循环

当前陆羽的 `runtime.py` 会在调用 `agent.execute` 时传入 `execution_mode: "agent_loop"`，但这不是管理接口可安全读取的静态配置。为形成可验证的权威状态，在 `agent.json.orchestration` 中增加：

```json
{
  "agent_loop_enabled": true
}
```

该字段表示当前超级专家是否允许运行时请求完整 Agent Loop。现有执行路径保持不变：运行时仍需请求 `execution_mode: "agent_loop"`；未请求时继续使用 candidate 路径。若配置为 false，平台不允许把该能力显示为开启。

普通 Agent 和未声明字段的旧包不会因此获得能力。新超级专家模板可显式写入 true；既有包缺少字段时管理界面显示“未声明”。

## 后端投影

`GET /api/admin/sealed-agents` 对当前激活版本为 `package_type: "super_expert"` 的记录增加：

```json
{
  "harness_status": {
    "skill_reader_enabled": true,
    "agent_loop_enabled": true
  }
}
```

字段值从当前运行工作区的已校验 `AgentProfileConfig` 得到，避免解析源代码，也不暴露配置文件其他内容。不存在活动版本、包不是超级专家或配置无法验证时，不返回 `harness_status`。单项未声明时返回 null，前端显示“未声明”。

接口仍需管理员权限。此次不增加 PATCH、POST 或 PUT 路由。

## 前端展示

在超级专家表格的展开区域增加“Harness 能力”卡片。每项包含名称、简短说明、禁用的 Switch 和状态文字：

- true：Switch 开启，显示“已开启”；
- false：Switch 关闭，显示“已关闭”；
- null：Switch 关闭，显示“未声明”。

卡片下方显示“状态由当前激活版本配置决定，暂不支持在此调整”。前端不发送更新请求，也不在普通专家页面引入相关类型或控件。

## 版本与兼容性

- `OrchestrationConfig.agent_loop_enabled` 采用可空字段，缺失保持未声明，避免把旧包错误标记为开启或关闭；
- 现有普通 Agent、旧超级专家和 candidate 执行路径保持原状；
- 切换活动发布版本后，列表重新加载并展示新版本的状态；
- 新陆羽包升级版本，显式声明 `agent_loop_enabled: true`，Skill Reader 继续使用现有 true 配置。

## 测试

后端测试验证：

1. 两个 true 配置投影为两个开启状态；
2. false 配置投影为关闭；
3. 缺失配置投影为 null；
4. 普通密封 Agent 不返回 Harness 状态；
5. 列表接口不新增写路由或暴露内部配置。

前端测试验证：

1. 两个状态均按 API 值显示；
2. Switch 全部不可编辑；
3. null 显示“未声明”；
4. 页面没有 Harness 更新请求；
5. 普通专家页面没有相关控件。

完成后运行相关单元测试、DClaw 服务端全量测试、Console 测试与生产构建，并将构建产物同步到当前本地服务。
