import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import zh from "../../../../locales/zh.json";
import { AgentTable } from "./AgentTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "agent.name": "名称",
        "agent.id": "ID",
        "agent.description": "描述",
        "agent.workspace": "工作目录",
        "agent.modelColumn": "模型",
        "agent.modelPlaceholder": "使用全局默认",
        "agent.sealed": "密封",
        "agent.sealedWorkspace": "内部资产已密封",
        "agent.sealedManageHint": "请在超级专家页面管理版本与运行状态",
        "common.actions": "操作",
      })[key] ?? key,
  }),
}));

describe("AgentTable", () => {
  it("uses the super expert page name in the sealed-agent management hint", () => {
    expect(zh.agent.sealedManageHint).toBe(
      "请在超级专家页面管理版本与运行状态",
    );
  });

  it("lets a sealed agent change its package-independent default model", async () => {
    const user = userEvent.setup();
    const onModelChange = vi.fn();
    const { container } = render(
      <AgentTable
        agents={[
          {
            id: "luyu_traffic_operator",
            name: "陆羽",
            description: "AI 流量操盘手",
            workspace_dir: "/private/sealed/luyu",
            enabled: false,
            agent_type: "sealed",
            active_model: {
              provider_id: "volcengine-cn",
              model: "deepseek-v4-flash",
            },
            capabilities: {
              invoke: true,
              public_metadata: true,
              inspect: false,
              edit: false,
              clone: false,
              export: false,
              download: false,
              trace: false,
            },
          },
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onReorder={vi.fn()}
        modelOptions={[
          {
            label: "Volcengine / DeepSeek V4",
            value: "volcengine-cn\u0000deepseek-v4",
          },
        ]}
        savingModelAgentId={null}
        onModelChange={onModelChange}
      />,
    );

    expect(screen.getByText("密封")).toBeInTheDocument();
    expect(screen.getByText("内部资产已密封")).toBeInTheDocument();
    expect(screen.queryByText("/private/sealed/luyu")).not.toBeInTheDocument();
    expect(
      screen.getByText("请在超级专家页面管理版本与运行状态"),
    ).toBeInTheDocument();
    expect(container.querySelector(".anticon-edit")).not.toBeInTheDocument();
    expect(container.querySelector(".anticon-delete")).not.toBeInTheDocument();
    expect(container.querySelector(".lucide-eye-off")).not.toBeInTheDocument();
    expect(container.querySelector(".lucide-eye")).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("Volcengine / DeepSeek V4"));
    expect(onModelChange).toHaveBeenCalledWith("luyu_traffic_operator", {
      provider_id: "volcengine-cn",
      model: "deepseek-v4",
    });
  });

  it("keeps standard agent management actions available", () => {
    const { container } = render(
      <AgentTable
        agents={[
          {
            id: "writer",
            name: "Writer",
            description: "Writing assistant",
            workspace_dir: "/workspaces/writer",
            enabled: false,
            agent_type: "standard",
          },
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onReorder={vi.fn()}
        modelOptions={[]}
        savingModelAgentId={null}
        onModelChange={vi.fn()}
      />,
    );

    expect(screen.getByText("/workspaces/writer")).toBeInTheDocument();
    expect(container.querySelector(".anticon-edit")).toBeInTheDocument();
    expect(container.querySelector(".anticon-delete")).toBeInTheDocument();
    expect(container.querySelector(".lucide-eye")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).not.toBeDisabled();
  });

  it("marks agents with an enabled OpenAPI publication", () => {
    render(
      <AgentTable
        agents={[
          {
            id: "api-agent",
            name: "API Agent",
            description: "External application agent",
            workspace_dir: "/workspaces/api-agent",
            enabled: true,
            open_api_enabled: true,
          },
          {
            id: "desktop-agent",
            name: "Desktop Agent",
            description: "Desktop agent",
            workspace_dir: "/workspaces/desktop-agent",
            enabled: true,
            open_api_enabled: false,
          },
        ]}
        loading={false}
        reordering={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onReorder={vi.fn()}
        modelOptions={[]}
        savingModelAgentId={null}
        onModelChange={vi.fn()}
      />,
    );

    expect(screen.getByText("API")).toBeInTheDocument();
    expect(screen.getAllByText(/Agent$/)).toHaveLength(2);
  });
});
