import { describe, expect, it } from "vitest";
import { resizeTextareaToContent } from "./textareaAutosize";

function textareaWithScrollHeight(scrollHeight: number) {
  const textarea = document.createElement("textarea");
  Object.defineProperty(textarea, "scrollHeight", {
    configurable: true,
    value: scrollHeight,
  });
  return textarea;
}

describe("resizeTextareaToContent", () => {
  it("grows to fit content below the max height", () => {
    const textarea = textareaWithScrollHeight(144);

    resizeTextareaToContent(textarea, 220);

    expect(textarea.style.height).toBe("144px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  it("caps height and allows scrolling above the max height", () => {
    const textarea = textareaWithScrollHeight(360);

    resizeTextareaToContent(textarea, 220);

    expect(textarea.style.height).toBe("220px");
    expect(textarea.style.overflowY).toBe("auto");
  });

  it("can grow without a height cap", () => {
    const textarea = textareaWithScrollHeight(960);

    resizeTextareaToContent(textarea, Number.POSITIVE_INFINITY);

    expect(textarea.style.height).toBe("960px");
    expect(textarea.style.overflowY).toBe("hidden");
  });
});
