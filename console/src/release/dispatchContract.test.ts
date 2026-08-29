import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const workflowPath = resolve(
  process.cwd(),
  "../.github/workflows/dispatch-dclaw-server-image.yml",
);

describe("DClaw combined-image dispatch workflow", () => {
  it("dispatches the immutable client main SHA to dclaw-server", () => {
    const workflow = readFileSync(workflowPath, "utf8");

    expect(workflow).toContain("branches: [main]");
    expect(workflow).toContain("event_type=dclaw_client_main");
    expect(workflow).toContain(
      "client_payload[client_sha]=${{ github.sha }}",
    );
    expect(workflow).toContain("DCLAW_SERVER_DISPATCH_TOKEN");
    expect(workflow).not.toContain("docker build");
  });
});
