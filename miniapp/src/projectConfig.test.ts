import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

interface WeappConditionItem {
  pathName?: string;
}

interface WeappProjectConfig {
  appid?: string;
  setting?: Record<string, unknown>;
  condition?: {
    miniprogram?: {
      list?: WeappConditionItem[];
    };
  };
}

interface WeappAppConfig {
  pages?: string[];
}

function readJson<T>(relativePath: string): T {
  const filePath = fileURLToPath(new URL(relativePath, import.meta.url));
  return JSON.parse(readFileSync(filePath, "utf8")) as T;
}

function listFiles(relativePath: string): string[] {
  const root = fileURLToPath(new URL(relativePath, import.meta.url));
  const files: string[] = [];

  function walk(directory: string) {
    for (const entry of readdirSync(directory)) {
      const fullPath = join(directory, entry);
      if (statSync(fullPath).isDirectory()) {
        walk(fullPath);
        continue;
      }
      files.push(fullPath);
    }
  }

  walk(root);
  return files;
}

describe("WeChat developer tools project config", () => {
  it("uses the registered DClaw mini-program AppID", () => {
    const projectConfig = readJson<WeappProjectConfig>(
      "../project.config.json",
    );

    expect(projectConfig.appid).toBe("wx35997eba21d6f985");
  });

  it("declares at least one mini-program launch condition for the generated pages", () => {
    const projectConfig = readJson<WeappProjectConfig>(
      "../project.config.json",
    );
    const appConfig = readJson<WeappAppConfig>("../dist/app.json");
    const launchConditions = projectConfig.condition?.miniprogram?.list || [];

    expect(appConfig.pages).toContain("pages/workbench/index");
    expect(launchConditions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          pathName: "pages/workbench/index",
        }),
      ]),
    );
  });

  it("does not put launch condition flags inside setting", () => {
    const projectConfig = readJson<WeappProjectConfig>(
      "../project.config.json",
    );

    expect(projectConfig.setting || {}).not.toHaveProperty("condition");
  });

  it("uses a root-relative Taro base template import in generated page WXML", () => {
    const wxmlFiles = listFiles("../dist/pages").filter((filePath) =>
      filePath.endsWith(".wxml"),
    );

    expect(wxmlFiles.length).toBeGreaterThan(0);
    for (const filePath of wxmlFiles) {
      const source = readFileSync(filePath, "utf8");

      expect(source).toContain('<import src="/base.wxml"/>');
      expect(source).not.toMatch(/<import src="\.\.\/.*base\.wxml"\s*\/>/);
    }
  });

  it("keeps test source files out of copied mini-program assets", () => {
    const copiedAssetFiles = listFiles("../dist/assets");

    expect(
      copiedAssetFiles.map((filePath) => filePath.split("/").pop()),
    ).not.toContain("assetContract.test.ts");
  });
});
