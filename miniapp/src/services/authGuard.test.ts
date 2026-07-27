import { describe, expect, it } from "vitest";

import { shouldRedirectToLogin } from "./authGuard";

describe("shouldRedirectToLogin", () => {
  it("redirects when the token is empty or whitespace", () => {
    expect(shouldRedirectToLogin("")).toBe(true);
    expect(shouldRedirectToLogin("   ")).toBe(true);
  });

  it("keeps the user on the current page when a token exists", () => {
    expect(shouldRedirectToLogin("employee-token")).toBe(false);
    expect(shouldRedirectToLogin("  employee-token  ")).toBe(false);
  });
});
