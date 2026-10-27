import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("chat message layout styles", () => {
  it("keeps nested user request bubbles at row width", async () => {
    const css = await readFile(
      resolve(process.cwd(), "src/styles/layout.css"),
      "utf8",
    );

    expect(css).toMatch(
      /\.qwenpaw-chat-anywhere-message-list\s+:is\(\.qwenpaw-bubble-end,\s*\.qwenpaw-bubble-user\)\s*>\s*\.qwenpaw-bubble-content-wrapper\s*>\s*:is\(\.qwenpaw-bubble-end,\s*\.qwenpaw-bubble-user\)\s*{[^}]*\bwidth:\s*100%;[^}]*}/,
    );
  });
});
