import { describe, expect, it } from "vitest";

import {
  DEFAULT_MINIAPP_API_BASE,
  resolveMiniappApiBase,
} from "./apiBase";

describe("mini-program API base config", () => {
  it("defaults to the online DClaw API domain", () => {
    expect(DEFAULT_MINIAPP_API_BASE).toBe("https://dclaw.deepmega.cn");
    expect(resolveMiniappApiBase({})).toBe(DEFAULT_MINIAPP_API_BASE);
  });

  it("allows an explicit API base override for custom local services", () => {
    expect(
      resolveMiniappApiBase({
        TARO_APP_API_BASE: "http://127.0.0.1:8088",
      }),
    ).toBe("http://127.0.0.1:8088");
  });

  it("can still build a local Docker API URL from host and port overrides", () => {
    expect(
      resolveMiniappApiBase({
        TARO_APP_API_HOST: "127.0.0.1",
        QWENPAW_SAAS_HOST_PORT: "28088",
      }),
    ).toBe("http://127.0.0.1:28088");
  });
});
