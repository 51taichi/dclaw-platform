import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sealedAgentsApi } from "../../../api/modules/sealedAgents";
import { ApiRequestError } from "../../../api/request";
import SealedAgentsPage from "./index";

vi.mock("../../../api/modules/sealedAgents", () => ({
  sealedAgentsApi: {
    list: vi.fn(),
    uploadRelease: vi.fn(),
    uploadAvatar: vi.fn(),
    uploadBanner: vi.fn(),
    previewGrant: vi.fn(),
    acceptGrant: vi.fn(),
    cancelGrant: vi.fn(),
    activate: vi.fn(),
    setEnabled: vi.fn(),
  },
}));

const { messageError, messageSuccess } = vi.hoisted(() => ({
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}));

vi.mock("../../../hooks/useAppMessage", () => {
  const message = { error: messageError, success: messageSuccess };
  return { useAppMessage: () => ({ message }) };
});

describe("SealedAgentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([]);
  });

  it("uses the same name as the super expert navigation item", async () => {
    render(<SealedAgentsPage />);

    expect(screen.getByText("设置")).toBeInTheDocument();
    expect(screen.getByText("超级专家")).toBeInTheDocument();
    expect(
      await screen.findByText("暂无密封 Agent，可上传签名发布包开始使用"),
    ).toBeInTheDocument();
  });

  it("sorts historical versions and activates the selected release", async () => {
    const user = userEvent.setup();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([
      {
        agent_id: "luyu_traffic_operator",
        name: "陆羽",
        description: "",
        enabled: true,
        availability: "available",
        active_release_id: "release-202",
        version: "2.0.2",
        signer_id: "release-signer",
        releases: [
          release("release-2010", "2.0.10"),
          release("release-200", "2.0.0"),
          release("release-202", "2.0.2"),
          release("release-210", "2.1.0"),
        ],
        capabilities: {
          invoke: true,
          inspect: false,
          edit: false,
          clone: false,
          export: false,
          download: false,
          trace: false,
        },
      },
    ]);
    vi.mocked(sealedAgentsApi.activate).mockResolvedValue({} as never);

    render(<SealedAgentsPage />);

    const selector = await screen.findByRole("combobox", {
      name: "选择陆羽的历史版本",
    });
    expect(
      screen.queryByRole("button", { name: "激活 2.0.0" }),
    ).not.toBeInTheDocument();
    await user.click(selector);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "2.1.0",
      "2.0.10",
      "2.0.0",
    ]);

    await user.click(screen.getByRole("option", { name: "2.0.10" }));
    await user.click(screen.getByRole("button", { name: "激活" }));
    expect(sealedAgentsApi.activate).toHaveBeenCalledWith(
      "luyu_traffic_operator",
      "release-2010",
    );
  });

  it("shows the backend error when release activation fails", async () => {
    const user = userEvent.setup();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([
      {
        agent_id: "luyu_traffic_operator",
        name: "陆羽",
        description: "",
        enabled: true,
        availability: "available",
        active_release_id: "release-204",
        version: "2.0.4",
        signer_id: "release-signer",
        releases: [
          release("release-204", "2.0.4"),
          release("release-210", "2.1.0"),
        ],
        capabilities: {
          invoke: true,
          inspect: false,
          edit: false,
          clone: false,
          export: false,
          download: false,
          trace: false,
        },
      },
    ]);
    vi.mocked(sealedAgentsApi.activate).mockRejectedValue(
      new ApiRequestError(
        'sealed agent runtime validation failed - {"detail":"sealed agent runtime validation failed"}',
        400,
      ),
    );

    render(<SealedAgentsPage />);

    const selector = await screen.findByRole("combobox", {
      name: "选择陆羽的历史版本",
    });
    await user.click(selector);
    await user.click(await screen.findByRole("option", { name: "2.1.0" }));
    await user.click(screen.getByRole("button", { name: "激活" }));

    await waitFor(() =>
      expect(messageError).toHaveBeenCalledWith(
        "sealed agent runtime validation failed",
      ),
    );
    expect(messageSuccess).not.toHaveBeenCalled();
  });

  it("shows the complete official capability set and only accept-all or cancel", async () => {
    const user = userEvent.setup();
    vi.mocked(sealedAgentsApi.uploadRelease).mockResolvedValue({
      agent_id: "generic-super-expert",
      release_id: "release-1",
      package_type: "super_expert",
      signer_id: "official-release-root",
    } as never);
    vi.mocked(sealedAgentsApi.previewGrant).mockResolvedValue({
      preview_id: "preview-1",
      tenant_id: "local",
      agent_id: "generic-super-expert",
      release_id: "release-1",
      package_digest: "sha256:abc",
      package_version: "1.0.0",
      capability_digest: "sha256:def",
      capabilities: [
        ["workspace.turn.orchestrate/1", "1"],
        ["card.create", "1"],
        ["aigc.task.create", "1"],
      ],
    });
    vi.mocked(sealedAgentsApi.acceptGrant).mockResolvedValue({} as never);
    vi.mocked(sealedAgentsApi.activate).mockResolvedValue({} as never);

    render(<SealedAgentsPage />);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(input, new File(["signed"], "expert.zip"));

    expect(await screen.findByText("官方超级专家签名")).toBeInTheDocument();
    expect(
      screen.getByText("workspace.turn.orchestrate/1"),
    ).toBeInTheDocument();
    expect(screen.getByText("card.create")).toBeInTheDocument();
    expect(screen.getByText("aigc.task.create")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "全部授权并安装" }));
    expect(sealedAgentsApi.acceptGrant).toHaveBeenCalledWith(
      "generic-super-expert",
      "release-1",
    );
    expect(sealedAgentsApi.activate).toHaveBeenCalledWith(
      "generic-super-expert",
      "release-1",
    );
  });
});

function release(releaseId: string, version: string) {
  return {
    release_id: releaseId,
    version,
    content_digest: "digest",
    signer_id: "release-signer",
    state: "installed",
    installed_at: "2026-09-01T00:00:00Z",
  };
}

it("uploads an independent avatar and shows it without replacing releases", async () => {
  const user = userEvent.setup();
  const agent = {
    agent_id: "luyu",
    name: "陆羽",
    description: "",
    enabled: true,
    availability: "available" as const,
    releases: [],
    capabilities: {
      invoke: true,
      inspect: false,
      edit: false,
      clone: false,
      export: false,
      download: false,
      trace: false,
    },
  };
  vi.mocked(sealedAgentsApi.list).mockResolvedValue([agent]);
  vi.mocked(sealedAgentsApi.uploadAvatar).mockResolvedValue({
    ...agent,
    avatar: "data:image/png;base64,new",
  });
  const { container } = render(<SealedAgentsPage />);
  await user.click(await screen.findByRole("button", { name: /Expand row/ }));
  const avatarButton = await screen.findByRole("button", {
    name: "上传陆羽头像",
  });
  expect(avatarButton).toHaveClass("ant-btn");
  const profileLayout = screen.getByTestId("expert-profile");
  expect(profileLayout.children[0]).toHaveAttribute(
    "data-testid",
    "expert-name",
  );
  expect(profileLayout.children[1]).toHaveAttribute(
    "data-testid",
    "expert-description",
  );
  expect(profileLayout.children[2]).toHaveAttribute(
    "data-testid",
    "expert-avatar",
  );
  expect(profileLayout.children[3]).toContainElement(avatarButton);
  expect(profileLayout.querySelector(".ant-avatar")).toHaveStyle({
    width: "112px",
    height: "112px",
  });
  expect(screen.queryByText(/内容摘要：|Invoke-only/)).not.toBeInTheDocument();
  const input = container.querySelector(
    'input[accept="image/png,image/jpeg,image/webp"]',
  ) as HTMLInputElement;
  const file = new File(["image"], "portrait.png", { type: "image/png" });
  await user.upload(input, file);
  await waitFor(() =>
    expect(sealedAgentsApi.uploadAvatar).toHaveBeenCalledWith(
      "luyu",
      expect.any(File),
    ),
  );
  await screen.findByRole("button", { name: "更换陆羽头像" });
  expect(
    container.querySelector('img[src="data:image/png;base64,new"]'),
  ).not.toBeNull();
});

it("uploads a promotional banner with a visible size hint", async () => {
  const user = userEvent.setup();
  const agent = {
    agent_id: "luyu",
    name: "陆羽",
    description: "流量操盘手",
    enabled: true,
    availability: "available" as const,
    releases: [],
    capabilities: {
      invoke: true,
      inspect: false,
      edit: false,
      clone: false,
      export: false,
      download: false,
      trace: false,
    },
  };
  vi.mocked(sealedAgentsApi.list).mockResolvedValue([agent]);
  vi.mocked(sealedAgentsApi.uploadBanner).mockResolvedValue({
    ...agent,
    banner_image: "data:image/webp;base64,banner",
  });
  const { container } = render(<SealedAgentsPage />);
  await user.click(await screen.findByRole("button", { name: /Expand row/ }));
  expect(screen.getByText(/3:1 · 2172 × 724/)).toBeVisible();
  const bannerLayout = screen.getByTestId("banner-layout");
  expect(bannerLayout.firstElementChild).toHaveAttribute(
    "data-testid",
    "banner-preview",
  );
  expect(bannerLayout.lastElementChild).toHaveAttribute(
    "data-testid",
    "banner-controls",
  );
  const input = container.querySelector(
    '[data-testid="banner-upload"] input[type="file"]',
  ) as HTMLInputElement;
  await user.upload(
    input,
    new File(["image"], "banner.png", { type: "image/png" }),
  );
  expect(await screen.findByAltText("陆羽宣传图")).toHaveAttribute(
    "src",
    "data:image/webp;base64,banner",
  );
  expect(sealedAgentsApi.uploadBanner).toHaveBeenCalledWith(
    "luyu",
    expect.any(File),
  );
  expect(screen.getByText("更新宣传图")).toBeVisible();
});
