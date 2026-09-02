import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const defaultRepositoryRoot = fileURLToPath(
  new URL("../..", import.meta.url),
);

const versionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function validateVersion(version) {
  if (!versionPattern.test(version)) {
    throw new Error(
      `Invalid desktop version "${version}". Expected MAJOR.MINOR.PATCH (for example, 1.2.3).`,
    );
  }
  return version;
}

function projectPaths(repositoryRoot) {
  const tauriDirectory = path.join(repositoryRoot, "console", "src-tauri");
  return {
    version: path.join(repositoryRoot, "VERSION"),
    tauri: path.join(tauriDirectory, "tauri.conf.json"),
    cargo: path.join(tauriDirectory, "Cargo.toml"),
  };
}

function readCargoPackageVersion(cargoContents) {
  const packageSection = cargoContents.match(
    /(^|\n)(\[package\]\s*\n)([\s\S]*?)(?=\n\[|$)/,
  );
  const version = packageSection?.[3].match(
    /^version\s*=\s*"([^"]+)"\s*$/m,
  )?.[1];
  if (!version) {
    throw new Error("Cargo.toml does not contain [package] version.");
  }
  return version;
}

function replaceCargoPackageVersion(cargoContents, version) {
  const packagePattern = /(^|\n)(\[package\]\s*\n)([\s\S]*?)(?=\n\[|$)/;
  const packageSection = cargoContents.match(packagePattern);
  if (!packageSection) {
    throw new Error("Cargo.toml does not contain a [package] section.");
  }
  if (!/^version\s*=\s*"[^"]+"\s*$/m.test(packageSection[3])) {
    throw new Error("Cargo.toml does not contain [package] version.");
  }
  const updatedBody = packageSection[3].replace(
    /^version\s*=\s*"[^"]+"\s*$/m,
    `version = "${version}"`,
  );
  return cargoContents.replace(
    packagePattern,
    `${packageSection[1]}${packageSection[2]}${updatedBody}`,
  );
}

export async function readCanonicalVersion(
  repositoryRoot = defaultRepositoryRoot,
) {
  const contents = await readFile(projectPaths(repositoryRoot).version, "utf8");
  return validateVersion(contents.trim());
}

export function incrementVersion(version, releaseType) {
  validateVersion(version);
  if (!new Set(["patch", "minor", "major"]).has(releaseType)) {
    throw new Error("Release type must be patch, minor, or major.");
  }

  let [major, minor, patch] = version.split(".").map(Number);
  if (releaseType === "major") {
    major += 1;
    minor = 0;
    patch = 0;
  } else if (releaseType === "minor") {
    minor += 1;
    patch = 0;
  } else {
    patch += 1;
  }
  return `${major}.${minor}.${patch}`;
}

export async function assertVersionsSynchronized(
  repositoryRoot = defaultRepositoryRoot,
) {
  const paths = projectPaths(repositoryRoot);
  const [canonical, tauriContents, cargoContents] = await Promise.all([
    readCanonicalVersion(repositoryRoot),
    readFile(paths.tauri, "utf8"),
    readFile(paths.cargo, "utf8"),
  ]);
  const tauriVersion = JSON.parse(tauriContents).version;
  const cargoVersion = readCargoPackageVersion(cargoContents);
  const mismatches = [];

  if (tauriVersion !== canonical) {
    mismatches.push(
      `tauri.conf.json is ${tauriVersion}; expected ${canonical}`,
    );
  }
  if (cargoVersion !== canonical) {
    mismatches.push(`Cargo.toml is ${cargoVersion}; expected ${canonical}`);
  }
  if (mismatches.length > 0) {
    throw new Error(
      `Desktop versions are not synchronized:\n- ${mismatches.join(
        "\n- ",
      )}\nRun an npm version command to synchronize them.`,
    );
  }
  return canonical;
}

export async function setDesktopVersion(
  version,
  repositoryRoot = defaultRepositoryRoot,
) {
  validateVersion(version);
  const paths = projectPaths(repositoryRoot);
  const [tauriContents, cargoContents] = await Promise.all([
    readFile(paths.tauri, "utf8"),
    readFile(paths.cargo, "utf8"),
  ]);
  const tauriConfig = JSON.parse(tauriContents);
  if (typeof tauriConfig.version !== "string") {
    throw new Error("tauri.conf.json does not contain a string version.");
  }
  tauriConfig.version = version;
  const updatedCargo = replaceCargoPackageVersion(cargoContents, version);

  await Promise.all([
    writeFile(paths.version, `${version}\n`),
    writeFile(paths.tauri, `${JSON.stringify(tauriConfig, null, 2)}\n`),
    writeFile(paths.cargo, updatedCargo),
  ]);
  return version;
}
