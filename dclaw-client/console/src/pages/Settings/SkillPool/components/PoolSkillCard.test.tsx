import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PoolSkillSpec } from "../../../../api/types";
import { PoolSkillCard } from "./PoolSkillCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

vi.mock("@agentscope-ai/design", () => ({
  Button: ({
    children,
    onClick,
    ...props
  }: React.PropsWithChildren<{ onClick?: React.MouseEventHandler }>) => (
    <button onClick={onClick} {...props}>
      {children}
    </button>
  ),
  Card: ({ children, ...props }: React.PropsWithChildren) => (
    <div {...props}>{children}</div>
  ),
  Checkbox: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input type="checkbox" {...props} />
  ),
  Tooltip: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("../../../Agent/Skills/components", () => ({
  getSkillVisual: () => <span data-testid="skill-visual" />,
}));

const renderCard = (skill: Partial<PoolSkillSpec>) => {
  const fullSkill = {
    name: "editable-ppt-visual-builder",
    description: "PPT skill",
    content: "",
    source: "builtin",
    protected: false,
    tags: [],
    config: { is_default: true },
    client_visible: false,
    ...skill,
  } as PoolSkillSpec;

  return render(
    <PoolSkillCard
      skill={fullSkill}
      isSelected={false}
      batchModeEnabled={false}
      onToggleSelect={vi.fn()}
      onEdit={vi.fn()}
      onBroadcast={vi.fn()}
      onToggleHidden={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
};

describe("PoolSkillCard badge layout", () => {
  it("keeps source/default/hidden badges outside the title heading", () => {
    const { container } = renderCard({});

    const heading = screen.getByRole("heading", {
      name: "editable-ppt-visual-builder",
    });
    expect(within(heading).queryByText(/默认/)).not.toBeInTheDocument();
    expect(within(heading).queryByText("已隐藏")).not.toBeInTheDocument();

    const badgeRow = container.querySelector('[class*="badgeRow"]');
    expect(badgeRow).toBeInTheDocument();
    expect(within(badgeRow as HTMLElement).getByText(/默认/)).toBeInTheDocument();
    expect(
      within(badgeRow as HTMLElement).getByText("已隐藏"),
    ).toBeInTheDocument();
  });

  it("shows the owner user on private skills", () => {
    renderCard({
      visibility: "private",
      owner_user_id: "owner-user-1",
      config: {},
      client_visible: true,
    });

    expect(screen.getByText(/owner-user-1/)).toBeInTheDocument();
  });
});
