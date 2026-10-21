import { beforeEach, describe, expect, it, vi } from "vitest";

const { openExternalLink } = vi.hoisted(() => ({
  openExternalLink: vi.fn(),
}));

vi.mock("../../utils/openExternalLink", () => ({ openExternalLink }));

import { isSafeSceneUrl, openSceneInExternalBrowser } from "./sceneNavigation";

describe("scene navigation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("accepts HTTPS scene URLs", () => {
    expect(
      isSafeSceneUrl(
        "https://service.example.com/console/?workspace=customer-1",
      ),
    ).toBe(true);
  });

  it.each([
    "http://service.example.com/console/",
    "javascript:alert(1)",
    "not-a-url",
  ])("rejects unsafe scene URL %s", (url) => {
    expect(isSafeSceneUrl(url)).toBe(false);
  });

  it("opens any configured scene in the default browser", () => {
    const scenes = [
      {
        key: "customer-service",
        title: "AI客服",
        url: "https://service.example.com/console",
      },
      {
        key: "douyin-agent",
        title: "Agent抖音机器人",
        url: "https://douyin.example.com/admin",
      },
    ];

    expect(openSceneInExternalBrowser(scenes, "douyin-agent")).toBe(true);
    expect(openExternalLink).toHaveBeenCalledOnce();
    expect(openExternalLink).toHaveBeenCalledWith(
      "https://douyin.example.com/admin",
    );
  });

  it("does not open unknown or unsafe scene URLs", () => {
    const scenes = [
      {
        key: "unsafe",
        title: "不安全地址",
        url: "javascript:alert(1)",
      },
    ];

    expect(openSceneInExternalBrowser(scenes, "missing")).toBe(false);
    expect(openSceneInExternalBrowser(scenes, "unsafe")).toBe(false);
    expect(openExternalLink).not.toHaveBeenCalled();
  });
});
