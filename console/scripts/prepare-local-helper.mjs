import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));
const repositoryRoot = path.resolve(consoleDirectory, "..");
const serverRoot = path.resolve(
  process.env.DCLAW_SERVER_SOURCE_DIR ??
    path.join(repositoryRoot, "..", "dclaw-server"),
);
const project = path.join(
  serverRoot,
  "plugins",
  "bundle",
  "super-agent-support",
  "windows-helper",
  "DClaw.LocalHelper.csproj",
);
const output = path.join(
  consoleDirectory,
  "src-tauri",
  "resources",
  "local-helper",
);
const expectedRunnerVersion = "1.3.0";
const expectedProtocolVersion = "2";

if (process.argv.includes("--describe")) {
  process.stdout.write(
    `${JSON.stringify({
      project,
      output,
      expectedRunnerVersion,
      expectedProtocolVersion,
    })}\n`,
  );
  process.exit(0);
}

if (process.platform !== "win32") {
  process.stdout.write(
    "Skipping Windows local helper build on this platform.\n",
  );
  process.exit(0);
}
if (!fs.existsSync(project)) {
  console.error(
    `Missing DClaw local helper source: ${project}. Set DCLAW_SERVER_SOURCE_DIR to a compatible dclaw-server checkout.`,
  );
  process.exit(1);
}
const helperSource = fs.readFileSync(
  path.join(path.dirname(project), "Program.cs"),
  "utf8",
);
if (
  !helperSource.includes(`string RunnerVersion = "${expectedRunnerVersion}"`) ||
  !helperSource.includes(
    `string ProtocolVersion = "${expectedProtocolVersion}"`,
  )
) {
  console.error(
    `Local helper source must provide Runner ${expectedRunnerVersion} and protocol ${expectedProtocolVersion}.`,
  );
  process.exit(1);
}

fs.mkdirSync(output, { recursive: true });
const result = spawnSync(
  "dotnet",
  [
    "publish",
    project,
    "--configuration",
    "Release",
    "--runtime",
    "win-x64",
    "--self-contained",
    "true",
    "--output",
    output,
    "/p:PublishSingleFile=true",
    "/p:IncludeNativeLibrariesForSelfExtract=true",
    "/p:DebugType=None",
  ],
  { stdio: "inherit" },
);
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
if (result.status !== 0) process.exit(result.status ?? 1);

const executable = path.join(output, "DClaw.LocalHelper.exe");
if (!fs.existsSync(executable)) {
  console.error(`Local helper publish did not create ${executable}`);
  process.exit(1);
}
