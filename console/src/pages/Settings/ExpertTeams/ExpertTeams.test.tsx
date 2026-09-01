import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expertTeamsApi } from "../../../api/modules/expertTeams";
import ExpertTeamsAdminPage from "./index";

vi.mock("../../../api/modules/expertTeams", () => ({
  expertTeamsApi: {
    listAdminExpertTeams: vi.fn(),
    updateAdminExpertTeam: vi.fn(),
    createAdminExpertTeam: vi.fn(),
    deleteAdminExpertTeam: vi.fn(),
  },
}));

describe("ExpertTeamsAdminPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(expertTeamsApi.listAdminExpertTeams).mockResolvedValue([]);
  });

  it("removes the explanatory hint and keeps the table spaced below the header", async () => {
    render(<ExpertTeamsAdminPage />);

    expect(
      screen.queryByText("维护公开专家团模板，用户在专家中心召唤。"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创建专家团" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("专家团列表")).toHaveStyle({
      marginTop: "16px",
    });
  });
});
