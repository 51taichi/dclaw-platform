import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import styles from "../../index.module.less";
import { AigcModelsSection, type PolicyState } from "./AigcModelsSection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { count?: number }) =>
      values?.count === undefined ? key : `${key} ${values.count}`,
  }),
}));

const ref = (index: number) => ({
  provider_id: "mxapi",
  model_id: `image-${index}`,
});

const fixture = (): PolicyState => ({
  inventory: {
    categories: {
      text: [],
      image: [
        ...Array.from({ length: 20 }, (_, index) => ({
          ...ref(index),
          provider_name: "MXAPI",
          model_name: `Image ${index}`,
          category: "image" as const,
          selectable: true,
          reasons: [],
          selected: true,
          is_default: index === 0,
        })),
        {
          provider_id: "other",
          model_id: "unpriced",
          provider_name: "Other",
          model_name: "Unpriced Model",
          category: "image" as const,
          selectable: false,
          reasons: ["unpriced"],
          selected: false,
          is_default: false,
        },
      ],
      video: [],
      audio: [],
    },
    uncategorized: [],
  },
  policies: null,
  drafts: {
    text: { version: null, models: [], defaultModel: null },
    image: {
      version: 1,
      models: Array.from({ length: 20 }, (_, index) => ref(index)),
      defaultModel: ref(0),
    },
    video: { version: null, models: [], defaultModel: null },
    audio: { version: null, models: [], defaultModel: null },
  },
  dirtyCategories: new Set(["image"]),
  loading: false,
  error: null,
  refresh: vi.fn(),
  addModel: vi.fn(),
  removeModel: vi.fn(),
  setDefault: vi.fn(),
  reorderModels: vi.fn(),
  saveCategory: vi.fn(),
});

describe("AigcModelsSection", () => {
  it("renders the three usable categories and caps each summary at three models", () => {
    render(<AigcModelsSection state={fixture()} />);

    expect(
      screen.getByText("models.aigc.title").closest(".ant-card"),
    ).toHaveClass(styles.slotSection);
    expect(screen.getByText("models.aigc.textTitle")).toBeInTheDocument();
    expect(screen.getByText("models.aigc.imageTitle")).toBeInTheDocument();
    expect(screen.getByText("models.aigc.videoTitle")).toBeInTheDocument();
    expect(screen.queryByText("models.aigc.audioTitle")).not.toBeInTheDocument();
    expect(screen.queryByText("models.aigc.description")).not.toBeInTheDocument();
    expect(
      screen.queryByText("models.aigc.textDescription"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("models.aigc.imageDescription"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("models.aigc.videoDescription"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("models.aigc.audioDescription"),
    ).not.toBeInTheDocument();
    const imageCard = screen
      .getByText("models.aigc.imageTitle")
      .closest("section");
    expect(imageCard).not.toBeNull();
    expect(within(imageCard!).getAllByTestId("selected-model")).toHaveLength(3);
    expect(
      within(imageCard!).getByText("models.aigc.viewAll 20"),
    ).toBeInTheDocument();

    const footer = within(imageCard!).getByText(
      "models.aigc.selectedCount 20",
    ).parentElement;
    expect(footer).not.toBeNull();
    expect(window.getComputedStyle(footer!).position).toBe("absolute");
    expect(window.getComputedStyle(footer!).bottom).toBe("16px");
  });

  it("shows unavailable inventory with a reason and disabled option", async () => {
    const user = userEvent.setup();
    render(<AigcModelsSection state={fixture()} />);

    const imageCard = screen
      .getByText("models.aigc.imageTitle")
      .closest("section");
    await user.click(
      within(imageCard!).getByRole("button", { name: /models\.aigc\.manage/ }),
    );
    const combobox = screen.getByRole("combobox");
    await user.click(combobox);
    await user.type(combobox, "Unpriced Model");

    expect(
      screen.getByRole("option", {
        name: /Unpriced Model.*models\.aigc\.reasons\.unpriced/,
      }),
    ).toBeInTheDocument();
    expect(
      document.querySelector(".ant-select-item-option-disabled"),
    ).toHaveTextContent(/Unpriced Model.*models\.aigc\.reasons\.unpriced/);
  });
});
