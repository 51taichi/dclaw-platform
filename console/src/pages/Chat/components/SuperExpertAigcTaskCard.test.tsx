import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  projectSuperExpertAigcCards,
  SuperExpertAigcTaskCard,
  type SuperExpertAigcTaskCardProjection,
} from "./SuperExpertAigcTaskCard";

const labels: Record<SuperExpertAigcTaskCardProjection["status"], string> = {
  WAITING_TO_START: "等待开始",
  IN_PROGRESS: "制作中",
  PAUSED: "已暂停",
  SUBMITTED: "待完成",
  REVIEWING: "待完成",
  REVISION_REQUIRED: "需要修改",
  ACCEPTED: "已完成",
  CANCELLED: "已取消",
  INVALIDATED: "已失效",
};

function projection(
  status: SuperExpertAigcTaskCardProjection["status"],
): SuperExpertAigcTaskCardProjection {
  return {
    cardId: "card-1",
    materialTaskId: "task-1",
    title: "生成首条口播视频",
    instruction: "按照右侧向导完成视频制作。",
    status,
  };
}

describe("SuperExpertAigcTaskCard", () => {
  it("has one entry while producing, not a duplicate workflow link", () => {
    render(
      <SuperExpertAigcTaskCard
        projection={projection("IN_PROGRESS")}
        onCommand={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("opens accepted results read-only instead of restarting production", () => {
    render(
      <SuperExpertAigcTaskCard
        projection={projection("ACCEPTED")}
        onCommand={vi.fn()}
      />,
    );
    expect(screen.getByRole("link", { name: "查看成果" })).toHaveAttribute(
      "href",
      "/aigc-studio?task=task-1",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("已完成");
    expect(
      screen.queryByText("按照右侧向导完成视频制作。"),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/素材任务已完成/)).toBeInTheDocument();
  });

  it("projects completed history without a runtime status", () => {
    const cards = projectSuperExpertAigcCards([
      {
        id: "event-1",
        type: "super_expert_event",
        scope: "session",
        session_id: "chat-1",
        payload: {
          envelope: {
            event_type: "aigc.asset.completed",
            material_task_id: "task-1",
          },
        },
      },
    ]);

    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("ACCEPTED");
  });

  it("keeps historical reviewing tasks actionable from chat", () => {
    render(
      <SuperExpertAigcTaskCard
        projection={projection("REVIEWING")}
        onCommand={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: "查看详情" })).toHaveAttribute(
      "href",
      "/aigc-studio?task=task-1",
    );
    expect(screen.getByRole("status")).toHaveTextContent("待完成");
  });
  for (const [status, label] of Object.entries(labels)) {
    it(`renders ${status}`, () => {
      render(
        <SuperExpertAigcTaskCard
          projection={projection(
            status as SuperExpertAigcTaskCardProjection["status"],
          )}
          onCommand={vi.fn()}
        />,
      );
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText("生成首条口播视频")).toBeInTheDocument();
    });
  }

  it("starts once on a double click", async () => {
    const user = userEvent.setup();
    const onCommand = vi.fn().mockResolvedValue(undefined);
    render(
      <SuperExpertAigcTaskCard
        projection={projection("WAITING_TO_START")}
        onCommand={onCommand}
      />,
    );
    const action = screen.getByRole("button", { name: "开始制作" });
    await user.dblClick(action);
    expect(onCommand).toHaveBeenCalledTimes(1);
    expect(onCommand).toHaveBeenCalledWith("resume", "task-1");
  });

  it("exposes an icon delete action without opening the task", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const onCommand = vi.fn();
    render(
      <SuperExpertAigcTaskCard
        projection={projection("IN_PROGRESS")}
        onCommand={onCommand}
        onDelete={onDelete}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "删除素材任务：生成首条口播视频" }),
    );
    expect(onDelete).toHaveBeenCalledWith("task-1");
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("renders text as text rather than agent supplied HTML", () => {
    render(
      <SuperExpertAigcTaskCard
        projection={{
          ...projection("WAITING_TO_START"),
          title: '<img src=x onerror="alert(1)">',
        }}
        onCommand={vi.fn()}
      />,
    );
    expect(
      screen.getByText('<img src=x onerror="alert(1)">'),
    ).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});
