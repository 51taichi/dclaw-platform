import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));

test("desktop builds run the frontend with the required heap limit", () => {
  const result = spawnSync(
    process.execPath,
    ["scripts/desktop-before-build.mjs", "--describe"],
    { cwd: consoleDirectory, encoding: "utf8" },
  );

  assert.equal(result.status, 0, result.stderr);
  const description = JSON.parse(result.stdout);
  assert.equal(description.steps.length, 1);
  assert.deepEqual(description.steps[0].args.slice(-2), ["run", "build"]);
  assert.equal(description.steps[0].maxOldSpaceSizeMb, 4096);
});
