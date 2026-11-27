import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Chat interaction wiring contract", () => {
  it("portals interaction cards into a response and sends their output as normal input", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/pages/Chat/index.tsx"),
      "utf8",
    );
    const responseCardSource = readFileSync(
      resolve(
        process.cwd(),
        "src/pages/Chat/components/RuntimeProgressCard.tsx",
      ),
      "utf8",
    );
    const cardIndex = source.indexOf("<InlineSuperExpertInteractionCards");
    const composerIndex = source.indexOf("<WorkbenchInput", cardIndex);

    expect(cardIndex).toBeGreaterThan(0);
    expect(composerIndex).toBeGreaterThan(cardIndex);
    expect(source).toContain("onBlockingChange={setInteractionBlocked}");
    expect(source).toContain("disabled={interactionBlocked}");
    expect(source).toContain("onSubmitAsUserInput={(text) =>");
    expect(source).toContain(
      "(chatRef.current?.input.submit as any)({ query: text });",
    );
    expect(source).not.toContain("onContinuationComplete=");
    expect(responseCardSource).toContain("data-super-expert-interaction-slot");
  });
});
