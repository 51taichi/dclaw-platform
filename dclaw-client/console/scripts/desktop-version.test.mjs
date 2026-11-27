import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  assertVersionsSynchronized,
  incrementVersion,
  readCanonicalVersion,
  setDesktopVersion,
} from "./desktop-version.mjs";

async function createFixture({
  canonical = "1.1.10",
  tauri = canonical,
  cargo = canonical,
  cargoLock = canonical,
} = {}) {
  const root = await mkdtemp(path.join(tmpdir(), "dclaw-version-"));
  const tauriDirectory = path.join(root, "console", "src-tauri");
  await mkdir(tauriDirectory, { recursive: true });
  await writeFile(path.join(root, "VERSION"), `${canonical}\n`);
  await writeFile(
    path.join(tauriDirectory, "tauri.conf.json"),
    `${JSON.stringify({ productName: "DClaw", version: tauri }, null, 2)}\n`,
  );
  await writeFile(
    path.join(tauriDirectory, "Cargo.toml"),
    `[package]\nname = "dclaw"\nversion = "${cargo}"\n\n[dependencies]\nserde = "1"\n`,
  );
  await writeFile(
    path.join(tauriDirectory, "Cargo.lock"),
    `version = 4\n\n[[package]]\nname = "dclaw"\nversion = "${cargoLock}"\ndependencies = [\n "serde",\n]\n\n[[package]]\nname = "serde"\nversion = "1.0.0"\n`,
  );
  return root;
}

test("increments semantic versions by the selected release type", () => {
  assert.equal(incrementVersion("1.1.10", "patch"), "1.1.11");
  assert.equal(incrementVersion("1.1.10", "minor"), "1.2.0");
  assert.equal(incrementVersion("1.1.10", "major"), "2.0.0");
});

test("rejects invalid versions and release types", () => {
  assert.throws(
    () => incrementVersion("v1.2.3", "patch"),
    /MAJOR\.MINOR\.PATCH/,
  );
  assert.throws(
    () => incrementVersion("1.2.3", "build"),
    /patch, minor, or major/,
  );
});

test("reads and validates the canonical version", async () => {
  const root = await createFixture();
  assert.equal(await readCanonicalVersion(root), "1.1.10");

  await writeFile(path.join(root, "VERSION"), "1.1\n");
  await assert.rejects(readCanonicalVersion(root), /MAJOR\.MINOR\.PATCH/);
});

test("reports every desktop version mismatch", async () => {
  const root = await createFixture({
    tauri: "1.1.9",
    cargo: "1.1.8",
    cargoLock: "1.1.7",
  });
  await assert.rejects(assertVersionsSynchronized(root), (error) => {
    assert.match(error.message, /tauri\.conf\.json.*1\.1\.9/);
    assert.match(error.message, /Cargo\.toml.*1\.1\.8/);
    assert.match(error.message, /Cargo\.lock.*1\.1\.7/);
    return true;
  });
});

test("sets and synchronizes all desktop version files", async () => {
  const root = await createFixture();
  await setDesktopVersion("1.3.5", root);

  assert.equal(await readCanonicalVersion(root), "1.3.5");
  assert.equal(await assertVersionsSynchronized(root), "1.3.5");

  const tauri = JSON.parse(
    await readFile(
      path.join(root, "console", "src-tauri", "tauri.conf.json"),
      "utf8",
    ),
  );
  assert.equal(tauri.version, "1.3.5");

  const cargo = await readFile(
    path.join(root, "console", "src-tauri", "Cargo.toml"),
    "utf8",
  );
  assert.match(cargo, /\[package\][\s\S]*version = "1\.3\.5"/);
  assert.match(cargo, /serde = "1"/);

  const cargoLock = await readFile(
    path.join(root, "console", "src-tauri", "Cargo.lock"),
    "utf8",
  );
  assert.match(cargoLock, /name = "dclaw"\nversion = "1\.3\.5"/);
  assert.match(cargoLock, /name = "serde"\nversion = "1\.0\.0"/);
});
