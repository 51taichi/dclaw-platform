import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));

test("every desktop build prepares the local helper before the frontend", () => {
  const result = spawnSync(
    process.execPath,
    ["scripts/desktop-before-build.mjs", "--describe"],
    { cwd: consoleDirectory, encoding: "utf8" },
  );

  assert.equal(result.status, 0, result.stderr);
  const description = JSON.parse(result.stdout);
  assert.deepEqual(description.steps[0].args, [
    "scripts/prepare-local-helper.mjs",
  ]);
  assert.deepEqual(description.steps[1].args.slice(-2), ["run", "build"]);
});
