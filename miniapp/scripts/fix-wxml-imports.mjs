import {
  existsSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const miniappRoot = fileURLToPath(new URL("..", import.meta.url));
const pagesRoot = join(miniappRoot, "dist", "pages");
const relativeBaseImportPattern =
  /<import src="\.\.\/(?:\.\.\/)*base\.wxml"\s*\/>/g;

function listWxmlFiles(directory) {
  const files = [];

  function walk(currentDirectory) {
    for (const entry of readdirSync(currentDirectory)) {
      const fullPath = join(currentDirectory, entry);
      if (statSync(fullPath).isDirectory()) {
        walk(fullPath);
        continue;
      }
      if (fullPath.endsWith(".wxml")) {
        files.push(fullPath);
      }
    }
  }

  walk(directory);
  return files;
}

if (!existsSync(pagesRoot)) {
  console.warn("[fix-wxml-imports] dist/pages does not exist, skipped");
  process.exit(0);
}

let updatedCount = 0;
for (const filePath of listWxmlFiles(pagesRoot)) {
  const source = readFileSync(filePath, "utf8");
  const updated = source.replace(
    relativeBaseImportPattern,
    '<import src="/base.wxml"/>',
  );

  if (updated !== source) {
    writeFileSync(filePath, updated);
    updatedCount += 1;
  }
}

console.log(`[fix-wxml-imports] normalized ${updatedCount} page WXML imports`);
