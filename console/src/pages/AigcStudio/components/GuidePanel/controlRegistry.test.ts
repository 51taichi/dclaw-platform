import { afterEach, describe, expect, it } from "vitest";

import { resolveControl } from "./controlRegistry";

describe("resolveControl", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("resolves duplicate control ids only inside the bound physical node", () => {
    for (const nodeId of ["video-1", "video-2"]) {
      const node = document.createElement("div");
      node.dataset.aigcNodeId = nodeId;
      const button = document.createElement("button");
      button.dataset.platformControlId = "aigc.video.generate-submit";
      node.append(button);
      document.body.append(node);
    }

    const control = resolveControl("aigc.video.generate-submit", "video-2");

    expect(control?.closest("[data-aigc-node-id]")?.getAttribute("data-aigc-node-id"))
      .toBe("video-2");
  });

  it("does not fall through to another node when the bound control is missing", () => {
    const node = document.createElement("div");
    node.dataset.aigcNodeId = "video-1";
    const button = document.createElement("button");
    button.dataset.platformControlId = "aigc.video.generate-submit";
    node.append(button);
    document.body.append(node);

    expect(resolveControl("aigc.video.generate-submit", "video-2")).toBeNull();
  });
});
