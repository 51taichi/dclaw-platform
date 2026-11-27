import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("mini-program runtime compatibility", () => {
  it("does not reference Node process in the API client runtime code", () => {
    const apiSourcePath = fileURLToPath(new URL("./api.ts", import.meta.url));
    const apiSource = readFileSync(apiSourcePath, "utf8");

    expect(apiSource).not.toContain("process.");
  });

  it("sets a request timeout so startup requests cannot hang indefinitely", () => {
    const apiSourcePath = fileURLToPath(new URL("./api.ts", import.meta.url));
    const apiSource = readFileSync(apiSourcePath, "utf8");

    expect(apiSource).toContain("timeout:");
    expect(apiSource).toContain("DEFAULT_REQUEST_TIMEOUT_MS");
  });

  it("provides the online DClaw API base URL at build time", () => {
    const configSourcePath = fileURLToPath(
      new URL("../../config/index.ts", import.meta.url),
    );
    const apiBaseSourcePath = fileURLToPath(
      new URL("../../config/apiBase.ts", import.meta.url),
    );
    const configSource = readFileSync(configSourcePath, "utf8");
    const apiBaseSource = readFileSync(apiBaseSourcePath, "utf8");

    expect(configSource).toContain("resolveMiniappApiBase(process.env)");
    expect(apiBaseSource).toContain("https://dclaw.deepmega.cn");
  });
});
