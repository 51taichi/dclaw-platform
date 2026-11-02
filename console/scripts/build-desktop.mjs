import { spawnSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { fileURLToPath } from "node:url";

import {
  assertVersionsSynchronized,
  defaultRepositoryRoot,
} from "./desktop-version.mjs";
import { npmInvocation } from "./npm-command.mjs";

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

const updaterPublicKeyPath =
  process.env.DCLAW_UPDATER_PUBLIC_KEY_PATH ??
  path.join(consoleDirectory, "brands", profile.edition, "updater.pub");
const privateKeyFromEnvironment = Boolean(
  process.env.TAURI_SIGNING_PRIVATE_KEY,
);
const updaterPrivateKey =
  process.env.TAURI_SIGNING_PRIVATE_KEY ??
  path.join(os.homedir(), ".dclaw-release", "keys", `${profile.edition}.key`);
let updaterPrivateKeyPassword =
  process.env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD ?? "";

if (!updaterPrivateKeyPassword && process.platform === "darwin") {
  const keychainResult = spawnSync(
    "security",
    [
      "find-generic-password",
      "-w",
      "-a",
      `dclaw-updater-${profile.edition}`,
      "-s",
      "DClaw Updater Signing Key",
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  );
  if (keychainResult.status === 0) {
    updaterPrivateKeyPassword = keychainResult.stdout.trim();
  }
}

if (!fs.existsSync(updaterPublicKeyPath)) {
  console.error(`Missing updater public key: ${updaterPublicKeyPath}`);
  process.exit(1);
}
if (
  (!privateKeyFromEnvironment && !fs.existsSync(updaterPrivateKey)) ||
  !updaterPrivateKeyPassword
) {
  console.error(
    "Missing updater private key or password. On CI, set TAURI_SIGNING_PRIVATE_KEY and TAURI_SIGNING_PRIVATE_KEY_PASSWORD.",
  );
  process.exit(1);
}

const updaterPublicKey = fs.readFileSync(updaterPublicKeyPath, "utf8").trim();
if (!updaterPublicKey) {
  console.error(`Updater public key is empty: ${updaterPublicKeyPath}`);
  process.exit(1);
}

const tauriBuildConfig = JSON.stringify({
  plugins: {
    updater: {
      active: true,
      endpoints: [`${profile.apiBaseUrl.replace(/\/$/, "")}/latest.json`],
      dialog: false,
      pubkey: updaterPublicKey,
    },
  },
});

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

const tauriBuild = npmInvocation([
  "exec",
  "--",
  "tauri",
  "build",
  "--config",
  tauriBuildConfig,
  ...bundleArguments,
  ...passthroughArguments,
]);
const result = spawnSync(tauriBuild.command, tauriBuild.args, {
  cwd: consoleDirectory,
  stdio: "inherit",
  env: {
    ...process.env,
    CARGO_TARGET_DIR: cargoTargetDirectory,
    DCLAW_DESKTOP_EDITION: profile.edition,
    DCLAW_DESKTOP_BRAND_ID:
      profile.edition === "cn" ? "dclaw" : profile.edition,
    DCLAW_DESKTOP_ARTIFACT_LABEL: profile.artifactLabel,
    VITE_API_BASE_URL: profile.apiBaseUrl,
    TAURI_SIGNING_PRIVATE_KEY: updaterPrivateKey,
    TAURI_SIGNING_PRIVATE_KEY_PASSWORD: updaterPrivateKeyPassword,
  },
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
