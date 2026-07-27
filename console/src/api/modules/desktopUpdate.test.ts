import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { desktopUpdateApi } from "./desktopUpdate";

vi.mock("@/api/request", () => ({
  request: vi.fn(),
}));

import { request } from "@/api/request";

describe("desktopUpdateApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("checks updates through the public desktop endpoint", async () => {
    await desktopUpdateApi.checkUpdate("win", "1.1.8b1");

    expect(request).toHaveBeenCalledWith(
      "/desktop/update?platform=win&version=1.1.8b1",
    );
  });
});
