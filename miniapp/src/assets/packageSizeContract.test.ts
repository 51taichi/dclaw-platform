import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readSource(relativePath: string) {
  const sourcePath = fileURLToPath(new URL(relativePath, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("mini-program package size contract", () => {
  it("uses mini-program-safe optimized PNG mascot runtime assets and excludes oversized PNG masters", () => {
    const assetImageSource = readSource("../components/AssetImage/index.tsx");
    const configSource = readSource("../../config/index.ts");

    expect(assetImageSource).toContain(
      'mascotHero: "mascot-hero-runtime.png"',
    );
    expect(assetImageSource).toContain(
      'mascotTask: "mascot-task-runtime.png"',
    );
    expect(assetImageSource).toContain(
      'mascotLogin: "mascot-login-runtime.png"',
    );
    expect(assetImageSource).not.toContain(".webp");
    expect(configSource).toContain('"**/mascot-hero.png"');
    expect(configSource).toContain('"**/mascot-task.png"');
    expect(configSource).not.toContain('"**/mascot-*.png"');
  });
});
