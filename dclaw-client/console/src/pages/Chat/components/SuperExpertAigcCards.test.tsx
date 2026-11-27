import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimeEvent } from "../../../api/modules/runtimeEvents";
import { SuperExpertAigcCards } from "./SuperExpertAigcCards";

const listCards = vi.hoisted(() => vi.fn());
const dismissTask = vi.hoisted(() => vi.fn());
const getTask = vi.hoisted(() => vi.fn());
const command = vi.hoisted(() => vi.fn());
const runtimeEvents = vi.hoisted(() => ({ current: [] as RuntimeEvent[] }));
vi.mock("../../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: { listCards, dismissTask, getTask, command },
}));
vi.mock("../../../contexts/RuntimeEventContext", () => ({
  useRuntimeEvents: () => ({
    events: runtimeEvents.current,
    fallbackPolling: false,
  }),
}));

function snapshot(status: string) {
  return {
    cards: [
      {
        material_task_id: "m1",
        title: "开场视频",
        instruction: "按向导生成",
        status,
        binding: {
          installation_id: "i1",
          conversation_id: "c1",
          agent_task_id: "a1",
          content_revision: 1,
          material_task_id: "m1",
          canvas_id: "cv1",
          node_id: "n1",
        },
      },
    ],
  };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}`}</output>
  );
}

describe("conversation card status refresh", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    runtimeEvents.current = [];
    localStorage.clear();
    dismissTask.mockResolvedValue(undefined);
  });
  it("opens an in-progress material task immediately without refetching it", async () => {
    localStorage.setItem("dclaw:aigc-card-introduced:c1", "true");
    listCards.mockResolvedValue(snapshot("IN_PROGRESS"));
    render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "继续制作" }));

    expect(await screen.findByTestId("location")).toHaveTextContent(
      "/aigc-studio?task=m1",
    );
    expect(getTask).not.toHaveBeenCalled();
    expect(command).not.toHaveBeenCalled();
  });
  it("defaults to compact cards, expands and remembers the choice across remounts", async () => {
    localStorage.setItem("dclaw:aigc-card-introduced:c1", "true");
    listCards.mockResolvedValue(snapshot("IN_PROGRESS"));
    const view = render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await screen.findByText("开场视频");
    expect(
      screen.getByRole("button", { name: "展开素材任务" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("按向导生成")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开素材任务" }));
    expect(screen.getByText("按向导生成")).toBeInTheDocument();
    view.unmount();
    render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await screen.findByText("按向导生成");
    fireEvent.click(screen.getByRole("button", { name: "收起素材任务" }));
    expect(screen.queryByText("按向导生成")).not.toBeInTheDocument();
    expect(screen.getByText("制作中")).toBeInTheDocument();
  });
  it("projects a newly created runtime card immediately and guides only once", async () => {
    listCards.mockResolvedValue({ cards: [] });
    const view = render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(listCards).toHaveBeenCalledTimes(1));

    runtimeEvents.current = [
      {
        id: "event-1",
        type: "super_expert_event",
        scope: "session",
        status: "WAITING_TO_START",
        payload: {
          envelope: {
            event_type: "aigc.task.created",
            installation_id: "i1",
            conversation_id: "c1",
            agent_task_id: "a1",
            content_revision: 1,
            material_task_id: "m-live",
            canvas_id: "cv1",
            node_id: "n1",
            payload: {
              title: "动态素材任务",
              instruction: "点击开始制作",
            },
          },
        },
      },
    ];
    view.rerender(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );

    expect(await screen.findByText("动态素材任务")).toBeInTheDocument();
    expect(
      screen.getByText("新素材任务已创建，点击卡片开始制作"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "收起素材任务" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem("dclaw:aigc-card-introduced:c1")).toBe("true");

    view.unmount();
    render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    expect(await screen.findByText("动态素材任务")).toBeInTheDocument();
    expect(
      screen.queryByText("新素材任务已创建，点击卡片开始制作"),
    ).not.toBeInTheDocument();
  });
  it("refreshes authoritative status on window focus without an SSE event", async () => {
    listCards
      .mockResolvedValueOnce(snapshot("IN_PROGRESS"))
      .mockResolvedValue(snapshot("ACCEPTED"));
    render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await screen.findByText("制作中");
    fireEvent.focus(window);
    expect(await screen.findByText("已审核")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /查看成果/ })).toHaveAttribute(
      "href",
      "/aigc-studio?task=m1",
    );
  });
  it("ignores an old conversation's delayed refresh", async () => {
    let resolveOld!: (value: ReturnType<typeof snapshot>) => void;
    listCards.mockResolvedValueOnce(snapshot("IN_PROGRESS"));
    const view = render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await screen.findByText("制作中");
    listCards.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    fireEvent.focus(window);
    await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
    listCards.mockResolvedValue({ cards: [] });
    view.rerender(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c2" />
      </MemoryRouter>,
    );
    resolveOld(snapshot("ACCEPTED"));
    await waitFor(() =>
      expect(screen.queryByText("开场视频")).not.toBeInTheDocument(),
    );
  });

  it("confirms and persistently dismisses a material task card", async () => {
    localStorage.setItem("dclaw:aigc-card-introduced:c1", "true");
    localStorage.setItem("dclaw:aigc-card-shelf:expanded", "true");
    listCards.mockResolvedValue(snapshot("IN_PROGRESS"));
    render(
      <MemoryRouter>
        <SuperExpertAigcCards conversationId="c1" />
      </MemoryRouter>,
    );
    await screen.findByText("开场视频");

    fireEvent.click(
      screen.getByRole("button", { name: "删除素材任务：开场视频" }),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText("删除这张素材任务卡片？").length,
      ).toBeGreaterThan(0),
    );
    const confirmDialog = screen.getByRole("dialog");
    fireEvent.click(
      within(confirmDialog).getByRole("button", { name: /删\s*除/ }),
    );

    await waitFor(() => expect(dismissTask).toHaveBeenCalledWith("m1"));
    await waitFor(() =>
      expect(screen.queryByText("开场视频")).not.toBeInTheDocument(),
    );
  });
});
