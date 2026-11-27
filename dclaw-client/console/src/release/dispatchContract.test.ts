import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const workflowPath = resolve(
  process.cwd(),
  "../.github/workflows/dispatch-dclaw-server-image.yml",
);

describe("DClaw combined-image release policy", () => {
  it("does not dispatch image builds from client pushes", () => {
    expect(existsSync(workflowPath)).toBe(false);
  });
});
