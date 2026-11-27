import { describe, expect, it } from "vitest";

import { getRequestFailureMessage } from "./apiError";

describe("getRequestFailureMessage", () => {
  it("turns request timeout failures into a useful local debug hint", () => {
    expect(getRequestFailureMessage({ errMsg: "request:fail timeout" })).toBe(
      "请求超时，请确认 DClaw 后端已启动并可访问",
    );
  });

  it("keeps useful failure messages from rejected request errors", () => {
    expect(
      getRequestFailureMessage(new Error("request:fail url not in domain list")),
    ).toBe("request:fail url not in domain list");
  });

  it("falls back when the rejected value is unknown", () => {
    expect(getRequestFailureMessage(null)).toBe("网络请求失败");
  });
});
