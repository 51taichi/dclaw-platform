import { describe, expect, it } from "vitest";
import { AuthApiError, AuthNetworkError } from "../../api/modules/auth";
import { getLoginErrorMessage } from "./loginError";

const translate = (key: string, options?: { seconds: number }) =>
  options ? `${key}:${options.seconds}` : key;

describe("getLoginErrorMessage", () => {
  it("distinguishes invalid credentials", () => {
    expect(
      getLoginErrorMessage(new AuthApiError("hidden", 401), translate),
    ).toBe("login.invalidCredentials");
  });

  it("shows the retry delay for rate limits", () => {
    expect(
      getLoginErrorMessage(new AuthApiError("hidden", 429, 45), translate),
    ).toBe("login.tooManyAttemptsWithRetry:45");
  });

  it("distinguishes network failures", () => {
    expect(getLoginErrorMessage(new AuthNetworkError(), translate)).toBe(
      "login.networkError",
    );
  });

  it("distinguishes server failures", () => {
    expect(
      getLoginErrorMessage(new AuthApiError("hidden", 503), translate),
    ).toBe("login.serviceUnavailable");
  });

  it("uses a neutral fallback for unexpected failures", () => {
    expect(getLoginErrorMessage(new Error("unexpected"), translate)).toBe(
      "login.failed",
    );
  });
});
