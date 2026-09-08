import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ModelsPage from ".";

// Replace the suite's partial design-system stub with its underlying real controls.
vi.mock("@agentscope-ai/design", async () => await import("antd"));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../api", () => ({
  default: {
    listAllProviders: vi.fn().mockResolvedValue([
      {
        id: "example",
        name: "Example Provider",
        api_key_prefix: "",
        chat_model: "OpenAIChatModel",
        models: [
          {
            id: "example-model",
            name: "Example Model",
            supports_multimodal: false,
            supports_image: false,
            supports_video: false,
            generate_kwargs: {},
          },
        ],
        extra_models: [],
        is_custom: false,
        is_local: false,
        support_model_discovery: false,
        support_connection_check: true,
        freeze_url: true,
        require_api_key: true,
        api_key: "masked",
        base_url: "https://example.com/v1",
        generate_kwargs: {},
      },
    ]),
    getActiveModels: vi
      .fn()
      .mockResolvedValue({ active_llm: null, active_embedding: null }),
  },
}));
vi.mock("@/api/modules/aigcModelPolicy", () => ({
  aigcModelPolicyApi: {
    getInventory: vi
      .fn()
      .mockResolvedValue({
        categories: { text: [], image: [], video: [], audio: [] },
        uncategorized: [],
      }),
    getPolicies: vi.fn().mockResolvedValue({ categories: {} }),
  },
}));

describe("ModelsPage tabs", () => {
  it("uses the same admin tab spacing as the token usage page", async () => {
    const { container } = render(<ModelsPage />);
    const providerTab = await screen.findByRole("tab", {
      name: "models.providersTitle",
    });
    const tabs = providerTab.closest<HTMLElement>(".ant-tabs");
    const tabNav = tabs?.querySelector<HTMLElement>(".ant-tabs-nav");
    const content = tabs?.parentElement;

    expect(container).toContainElement(tabs);
    expect(content).not.toBeNull();
    expect(tabNav).not.toBeNull();
    expect(getComputedStyle(content!).paddingLeft).toBe("16px");
    expect(getComputedStyle(content!).paddingRight).toBe("16px");
    expect(getComputedStyle(tabNav!).marginLeft).toBe("0px");
    expect(getComputedStyle(tabNav!).marginRight).toBe("0px");
  });

  it("starts on providers with search and add controls, not model configuration", async () => {
    render(<ModelsPage />);
    expect(
      await screen.findByRole("tab", { name: "models.providersTitle" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByPlaceholderText("models.searchPlaceholder"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: /models.addProvider/ }),
    ).toBeVisible();
    expect(screen.queryByText("models.defaultLlm")).not.toBeInTheDocument();
  });

  it("groups chat, embeddings and AIGC configuration without audio", async () => {
    const user = userEvent.setup();
    render(<ModelsPage />);
    await user.click(
      await screen.findByRole("tab", { name: "models.configurationTab" }),
    );
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("models.defaultLlm")).toBeVisible();
    expect(within(panel).getByText("models.defaultEmbedding")).toBeVisible();
    expect(
      await within(panel).findByText("models.aigc.textTitle"),
    ).toBeVisible();
    expect(
      within(panel).queryByText("models.aigc.audioTitle"),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByPlaceholderText("models.searchPlaceholder"),
    ).not.toBeInTheDocument();
  });

  it("preserves provider search and the unsaved configuration selection across tab switches", async () => {
    const user = userEvent.setup();
    render(<ModelsPage />);
    await screen.findByRole("tab", { name: "models.providersTitle" });
    await user.type(
      screen.getByPlaceholderText("models.searchPlaceholder"),
      "Example",
    );
    await user.click(
      screen.getByRole("tab", { name: "models.configurationTab" }),
    );
    const providerSelect = within(screen.getByRole("tabpanel")).getAllByRole(
      "combobox",
    )[0];
    fireEvent.mouseDown(providerSelect);
    await user.click(await screen.findByTitle("Example Provider"));
    await user.click(
      screen.getByRole("tab", { name: "models.providersTitle" }),
    );
    expect(screen.getByPlaceholderText("models.searchPlaceholder")).toHaveValue(
      "Example",
    );
    await user.click(
      screen.getByRole("tab", { name: "models.configurationTab" }),
    );
    expect(
      within(screen.getByRole("tabpanel")).getByTitle("Example Provider"),
    ).toBeVisible();
  });
});
