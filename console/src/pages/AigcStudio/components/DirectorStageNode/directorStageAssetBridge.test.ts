import { describe, expect, it } from "vitest";

import { dataUrlToFile } from "./directorStageAssetBridge";

describe("directorStageAssetBridge", () => {
  it("converts a png data url into a named File", async () => {
    const file = await dataUrlToFile(
      "data:image/png;base64,aGVsbG8=",
      "director-stage.png",
    );

    expect(file.name).toBe("director-stage.png");
    expect(file.type).toBe("image/png");
    expect(await file.text()).toBe("hello");
  });
});
