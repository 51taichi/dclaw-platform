import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("login page contract", () => {
  it("keeps the mobile login flow on account and password", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("账号");
    expect(source).toContain("密码");
    expect(source).not.toContain("手机号");
    expect(source).not.toContain("验证码");
  });

  it("uses the real WeChat privacy authorization flow instead of unimplemented agreement copy", () => {
    const pageSource = readPageSource("./index.tsx");
    const styleSource = readPageSource("./index.scss");

    expect(pageSource).toContain("PrivacyAuthorization");
    expect(pageSource).not.toContain("用户协议");
    expect(pageSource).not.toContain("我已阅读并同意");
    expect(pageSource).not.toContain("login-policy");
    expect(styleSource).not.toContain("login-policy");
  });
});
