import { beforeEach, describe, expect, it, vi } from "vitest";

const taro = vi.hoisted(() => ({
  getStorageSync: vi.fn(),
  setStorageSync: vi.fn(),
  removeStorageSync: vi.fn(),
  reLaunch: vi.fn(),
}));

vi.mock("@tarojs/taro", () => ({
  default: taro,
}));

import Taro from "@tarojs/taro";

import {
  clearAuthToken,
  getStoredUsername,
  setAuthSession,
  type LoginResponse,
} from "./auth";

describe("auth session storage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("persists the login username with the token for profile pages", () => {
    const response: LoginResponse = {
      token: "token-1",
      username: "zu",
    };

    setAuthSession(response);

    expect(Taro.setStorageSync).toHaveBeenCalledWith(
      "qwenpaw_auth_token",
      "token-1",
    );
    expect(Taro.setStorageSync).toHaveBeenCalledWith("qwenpaw_username", "zu");
  });

  it("reads a trimmed stored username and clears it on logout", () => {
    vi.mocked(Taro.getStorageSync).mockReturnValueOnce("  zu  ");

    expect(getStoredUsername()).toBe("zu");

    clearAuthToken();

    expect(Taro.removeStorageSync).toHaveBeenCalledWith("qwenpaw_auth_token");
    expect(Taro.removeStorageSync).toHaveBeenCalledWith("qwenpaw_username");
  });
});
