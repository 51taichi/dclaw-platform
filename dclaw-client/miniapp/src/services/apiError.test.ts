import { describe, expect, it } from "vitest";

import { getResponseErrorMessage } from "./apiError";

describe("getResponseErrorMessage", () => {
  it("uses plain string responses", () => {
    expect(getResponseErrorMessage("权限不足", 403)).toBe("权限不足");
  });

  it("uses common backend error fields", () => {
    expect(getResponseErrorMessage({ detail: "任务不存在" }, 404)).toBe(
      "任务不存在",
    );
    expect(getResponseErrorMessage({ message: "知识库不可用" }, 503)).toBe(
      "知识库不可用",
    );
    expect(getResponseErrorMessage({ error: "确认已过期" }, 409)).toBe(
      "确认已过期",
    );
  });

  it("localizes invalid credential errors", () => {
    expect(
      getResponseErrorMessage(
        { detail: "Invalid username or password" },
        401,
      ),
    ).toBe("账户或密码错误");
  });

  it("summarizes validation error arrays", () => {
    expect(
      getResponseErrorMessage(
        {
          detail: [
            { msg: "chat_id 不能为空" },
            { message: "prompt 不能为空" },
          ],
        },
        422,
      ),
    ).toBe("chat_id 不能为空；prompt 不能为空");
  });

  it("falls back to the status code", () => {
    expect(getResponseErrorMessage({}, 500)).toBe("Request failed: 500");
  });
});
