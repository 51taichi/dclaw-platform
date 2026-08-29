import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
        "agent.sealedManageHint": "请在密封/Agent页面管理版本与运行状态",
        "common.actions": "操作",
      })[key] ?? key,
  }),
}));

describe("AgentTable", () => {
  it("renders a sealed agent as locked instead of exposing management actions", () => {
    const { container } = render(
      <AgentTable
        agents={[
          {
            id: "luyu_traffic_operator",
            name: "陆羽",
            description: "AI 流量操盘手",
            enabled: true,
            agent_type: "sealed",
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
      />,
    );

    expect(screen.getByText("密封")).toBeInTheDocument();
    expect(screen.getByText("内部资产已密封")).toBeInTheDocument();
    expect(
      screen.getByText("请在密封/Agent页面管理版本与运行状态"),
    ).toBeInTheDocument();
    expect(container.querySelector(".anticon-edit")).not.toBeInTheDocument();
    expect(container.querySelector(".anticon-delete")).not.toBeInTheDocument();
    expect(container.querySelector(".lucide-eye-off")).not.toBeInTheDocument();
    expect(container.querySelector(".lucide-eye")).not.toBeInTheDocument();
  });
});
