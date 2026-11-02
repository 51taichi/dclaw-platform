import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SidebarAccountMenu from "./SidebarAccountMenu";

const { getWallet, checkLocalHelper, helperStatus } = vi.hoisted(() => ({
  getWallet: vi.fn(),
  checkLocalHelper: vi.fn(),
  helperStatus: {
    state: "ready" as const,
    runnerVersion: "1.2.0",
    label: "本地助手已连接 · v1.2.0",
  },
}));

vi.mock("@/api/modules/billing", () => ({
  billingApi: { getWallet },
}));

vi.mock("@/features/localHelper/LocalHelperStatusContext", () => ({
  useLocalHelperStatus: () => ({
    ...helperStatus,
    check: checkLocalHelper,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      _key: string,
      fallbackOrOptions?:
        | string
        | { defaultValue?: string; username?: string; value?: string },
    ) => {
      if (typeof fallbackOrOptions === "string") return fallbackOrOptions;
      return (fallbackOrOptions?.defaultValue ?? "")
        .replace("{{username}}", fallbackOrOptions?.username ?? "")
        .replace("{{value}}", fallbackOrOptions?.value ?? "");
    },
  }),
}));

function renderMenu(
  overrides: Partial<React.ComponentProps<typeof SidebarAccountMenu>> = {},
) {
  const props = {
    username: "alice",
    role: "admin",
    collapsed: false,
    onOpenAccount: vi.fn(),
    onOpenWallet: vi.fn(),
    onOpenAdmin: vi.fn(),
    onLogout: vi.fn(),
    ...overrides,
  };
  render(
    <App>
      <SidebarAccountMenu {...props} />
    </App>,
  );
  return props;
}

describe("SidebarAccountMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    helperStatus.state = "ready";
    helperStatus.runnerVersion = "1.2.0";
    helperStatus.label = "本地助手已连接 · v1.2.0";
    getWallet.mockResolvedValue({
      available: 204500,
      held: 0,
      purchased: 204500,
      promotional: 0,
      package: 0,
    });
  });

  it("shows the current username and the existing account actions", async () => {
    const user = userEvent.setup();
    renderMenu();

    const trigger = screen.getByRole("button", { name: "当前账户：alice" });
    expect(trigger).toHaveTextContent("alice");
    expect(trigger).toHaveTextContent("管理员");
    expect(
      screen.getByRole("img", { name: "DClaw 默认头像" }),
    ).toBeInTheDocument();

    await user.click(trigger);

    expect(await screen.findByLabelText("账户菜单")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "DClaw 默认头像" })).toHaveLength(
      2,
    );
    expect(
      screen.getByRole("button", { name: /账户管理/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /管理后台/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /退出登录/ }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /204,500 积分/ }),
    ).toBeInTheDocument();
    expect(getWallet).toHaveBeenCalledOnce();
  });

  it("shares the local helper state and lets the user recheck it", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: "当前账户：alice" }));

    const helperButton = await screen.findByRole("button", {
      name: /本地助手.*v1\.2\.0/,
    });
    await user.click(helperButton);

    expect(checkLocalHelper).toHaveBeenCalledOnce();
  });

  it("hides admin-only actions for regular users and keeps the avatar trigger when collapsed", async () => {
    const user = userEvent.setup();
    renderMenu({ role: "user", collapsed: true });

    const trigger = screen.getByRole("button", { name: "当前账户：alice" });
    expect(trigger).not.toHaveTextContent("alice");
    await user.click(trigger);

    expect(await screen.findByLabelText("账户菜单")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /管理后台/ })).toBeNull();
  });
});
