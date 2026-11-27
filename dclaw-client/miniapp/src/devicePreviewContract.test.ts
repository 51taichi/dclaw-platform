import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("physical-device preview contract", () => {
  it("provides a build script that injects a LAN API host", () => {
    const packageJson = JSON.parse(readFileSync("package.json", "utf8"));
    const scriptPath = join(process.cwd(), "scripts/build-weapp-device.mjs");

    expect(packageJson.scripts["build:weapp:device"]).toBe(
      "node scripts/build-weapp-device.mjs",
    );
    expect(existsSync(scriptPath)).toBe(true);

    const script = readFileSync(scriptPath, "utf8");
    expect(script).toContain("networkInterfaces");
    expect(script).toContain("TARO_APP_API_HOST");
    expect(script).toContain("TARO_APP_API_BASE");
  });
});
