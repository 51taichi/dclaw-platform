import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { getApiUrl, getApiToken, setAuthToken, clearAuthToken } from "./config";

// VITE_API_BASE_URL / TOKEN are declared globals in config.ts — set via globalThis
const setViteBase = (v: string) => {
  (globalThis as any).VITE_API_BASE_URL = v;
};
const setToken = (v: string) => {
  (globalThis as any).TOKEN = v;
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getApiUrl", () => {
  beforeEach(() => {
    setViteBase("");
    delete window.__DCLAW_DESKTOP_API_BASE_URL__;
  });

  it("prepends /api prefix when base is empty", () => {
    expect(getApiUrl("/models")).toBe("/api/models");
  });

  it("auto-prepends / when path does not start with /", () => {
    expect(getApiUrl("models")).toBe("/api/models");
  });

  it("correctly concatenates when base URL is set", () => {
    setViteBase("http://localhost:8088");
    expect(getApiUrl("/models")).toBe("http://localhost:8088/api/models");
  });

  it("uses desktop runtime API base URL before build-time base URL", () => {
    setViteBase("http://localhost:8088");
    window.__DCLAW_DESKTOP_API_BASE_URL__ = "https://dclaw.deepmega.cn/";
    expect(getApiUrl("/models")).toBe("https://dclaw.deepmega.cn/api/models");
  });

  it("correctly handles nested paths", () => {
    expect(getApiUrl("/models/openai/config")).toBe(
      "/api/models/openai/config",
    );
  });

  it("routes AIGC Studio APIs through the user API namespace", () => {
    expect(getApiUrl("/aigc-studio/capabilities")).toBe(
      "/api/user/aigc-studio/capabilities",
    );
  });

  it("routes runtime event stream APIs through the user API namespace", () => {
    expect(getApiUrl("/runtime/events/stream?session_id=s1")).toBe(
      "/api/user/runtime/events/stream?session_id=s1",
    );
  });

  it("routes Open API admin APIs through the admin API namespace", () => {
    expect(getApiUrl("/open-api/publications")).toBe(
      "/api/admin/open-api/publications",
    );
    expect(getApiUrl("/open-api/keys?publication_id=pub-1")).toBe(
      "/api/admin/open-api/keys?publication_id=pub-1",
    );
  });

  it("keeps Open API knowledge APIs in the root namespace", () => {
    expect(getApiUrl("/open-api-knowledge/publications")).toBe(
      "/api/open-api-knowledge/publications",
    );
  });

  it("keeps explicit Web Search admin APIs in the admin namespace", () => {
    expect(getApiUrl("/admin/web-search/config")).toBe(
      "/api/admin/web-search/config",
    );
  });

  it("keeps existing model APIs at their original root namespace", () => {
    expect(getApiUrl("/models")).toBe("/api/models");
  });
});

describe("getApiToken", () => {
  const memoryStorage = new Map<string, string>();

  beforeEach(() => {
    memoryStorage.clear();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => memoryStorage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) =>
        memoryStorage.set(key, value),
      ),
      removeItem: vi.fn((key: string) => memoryStorage.delete(key)),
      clear: vi.fn(() => memoryStorage.clear()),
    });
    setToken("");
  });

  it("returns token from localStorage when present", () => {
    localStorage.setItem("qwenpaw_auth_token", "stored-token");
    expect(getApiToken()).toBe("stored-token");
  });

  it("falls back to TOKEN global variable when localStorage has no token", () => {
    setToken("build-time-token");
    expect(getApiToken()).toBe("build-time-token");
  });

  it("returns empty string when neither is set", () => {
    expect(getApiToken()).toBe("");
  });
});

describe("setAuthToken / clearAuthToken", () => {
  const memoryStorage = new Map<string, string>();

  beforeEach(() => {
    memoryStorage.clear();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => memoryStorage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) =>
        memoryStorage.set(key, value),
      ),
      removeItem: vi.fn((key: string) => memoryStorage.delete(key)),
      clear: vi.fn(() => memoryStorage.clear()),
    });
  });

  it("setAuthToken writes to localStorage", () => {
    setAuthToken("my-token");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBe("my-token");
  });

  it("clearAuthToken removes token from localStorage", () => {
    localStorage.setItem("qwenpaw_auth_token", "my-token");
    clearAuthToken();
    expect(localStorage.getItem("qwenpaw_auth_token")).toBeNull();
  });

  it("getApiToken returns empty string after clearAuthToken", () => {
    setToken("");
    setAuthToken("my-token");
    clearAuthToken();
    expect(getApiToken()).toBe("");
  });
});
