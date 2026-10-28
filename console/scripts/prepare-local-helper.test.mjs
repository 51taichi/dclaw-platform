import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));

test("local helper build resolves the plugin-owned source and client resource", () => {
  const result = spawnSync(
    process.execPath,
    ["scripts/prepare-local-helper.mjs", "--describe"],
    { cwd: consoleDirectory, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  const paths = JSON.parse(result.stdout);
  assert.equal(
    paths.project,
    path.resolve(
      consoleDirectory,
      "..",
      "..",
      "dclaw-server",
      "plugins/bundle/super-agent-support/windows-helper/DClaw.LocalHelper.csproj",
    ),
  );
  assert.equal(
    paths.output,
    path.join(consoleDirectory, "src-tauri/resources/local-helper"),
  );
  assert.equal(paths.expectedRunnerVersion, "1.3.0");
  assert.equal(paths.expectedProtocolVersion, "2");
});
