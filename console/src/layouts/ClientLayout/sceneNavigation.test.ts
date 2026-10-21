import { describe, expect, it } from "vitest";

import { isSafeSceneUrl } from "./sceneNavigation";

describe("scene navigation", () => {
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
});
