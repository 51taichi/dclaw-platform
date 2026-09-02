import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertVersionsSynchronized,
  defaultRepositoryRoot,
} from "./desktop-version.mjs";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));

const profiles = {
  cn: {
    edition: "cn",
    apiBaseUrl: "https://dclaw.deepmega.cn",
    artifactLabel: "CN",
    cargoTargetDirectory: "src-tauri/target/desktop-cn",
    windowsBundleTargets: ["nsis", "msi"],
  },
};

const edition = process.argv[2];
const profile = profiles[edition];

if (!profile) {
  console.error(`Unknown desktop edition: ${edition ?? "(missing)"}`);
  console.error("Expected: cn");
  process.exit(1);
}

if (process.argv.includes("--describe")) {
  process.stdout.write(`${JSON.stringify(profile)}\n`);
  process.exit(0);
}

const checkVersionOnly = process.argv.includes("--check-version-only");
const versionRoot = process.env.DCLAW_VERSION_ROOT ?? defaultRepositoryRoot;

try {
  const desktopVersion = await assertVersionsSynchronized(versionRoot);
  console.log(`Version: ${desktopVersion}`);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}

if (checkVersionOnly) {
  process.exit(0);
}

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const cargoTargetDirectory = path.resolve(
  consoleDirectory,
  profile.cargoTargetDirectory,
);
const passthroughArguments = process.argv
  .slice(3)
  .filter((argument) => argument !== "--check-version-only");
const bundleArguments =
  process.platform === "win32" &&
  !passthroughArguments.some(
    (argument) => argument === "--bundles" || argument.startsWith("--bundles="),
  )
    ? ["--bundles", profile.windowsBundleTargets.join(",")]
    : [];

console.log(`Building DClaw Desktop (${profile.artifactLabel})`);
console.log(`API: ${profile.apiBaseUrl}`);
console.log(`Artifacts: ${cargoTargetDirectory}`);

const result = spawnSync(
  npmCommand,
  ["exec", "--", "tauri", "build", ...bundleArguments, ...passthroughArguments],
  {
    cwd: consoleDirectory,
    stdio: "inherit",
    env: {
      ...process.env,
      CARGO_TARGET_DIR: cargoTargetDirectory,
      DCLAW_DESKTOP_EDITION: profile.edition,
      DCLAW_DESKTOP_ARTIFACT_LABEL: profile.artifactLabel,
      VITE_API_BASE_URL: profile.apiBaseUrl,
    },
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
