import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

function describeEdition(edition) {
  const result = spawnSync(
    process.execPath,
    ["scripts/build-desktop.mjs", edition, "--describe"],
    {
      cwd: new URL("..", import.meta.url),
      encoding: "utf8",
    },
  );

  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

function describeEditionThroughNpm(scriptName) {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(
    npmCommand,
    ["run", scriptName, "--", "--describe"],
    {
      cwd: new URL("..", import.meta.url),
      encoding: "utf8",
    },
  );

  assert.equal(result.status, 0, result.stderr);
  const jsonLine = result.stdout
    .split("\n")
    .find((line) => line.startsWith("{"));
  assert.ok(jsonLine, result.stdout);
  return JSON.parse(jsonLine);
}

test("domestic desktop build targets the domestic API", () => {
  assert.deepEqual(describeEdition("cn"), {
    edition: "cn",
    apiBaseUrl: "https://dclaw.deepmega.cn",
    artifactLabel: "CN",
    cargoTargetDirectory: "src-tauri/target/desktop-cn",
    windowsBundleTargets: ["nsis", "msi"],
  });
});

test("overseas desktop builds are rejected until that edition is supported", () => {
  const result = spawnSync(
    process.execPath,
    ["scripts/build-desktop.mjs", "global", "--describe"],
    {
      cwd: new URL("..", import.meta.url),
      encoding: "utf8",
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Unknown desktop edition: global/);
});

test("npm domestic build command selects the domestic profile", () => {
  assert.equal(
    describeEditionThroughNpm("desktop:build:cn").apiBaseUrl,
    "https://dclaw.deepmega.cn",
  );
});

test("desktop build rejects unsynchronized versions before invoking Tauri", () => {
  const root = mkdtempSync(path.join(tmpdir(), "dclaw-build-version-"));
  const tauriDirectory = path.join(root, "console", "src-tauri");
  mkdirSync(tauriDirectory, { recursive: true });
  writeFileSync(path.join(root, "VERSION"), "1.1.10\n");
  writeFileSync(
    path.join(tauriDirectory, "tauri.conf.json"),
    '{"version":"1.1.9"}\n',
  );
  writeFileSync(
    path.join(tauriDirectory, "Cargo.toml"),
    '[package]\nname = "dclaw"\nversion = "1.1.10"\n',
  );

  const result = spawnSync(
    process.execPath,
    ["scripts/build-desktop.mjs", "cn", "--check-version-only"],
    {
      cwd: new URL("..", import.meta.url),
      encoding: "utf8",
      env: { ...process.env, DCLAW_VERSION_ROOT: root },
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Desktop versions are not synchronized/);
  assert.doesNotMatch(`${result.stdout}${result.stderr}`, /tauri build/);
});
