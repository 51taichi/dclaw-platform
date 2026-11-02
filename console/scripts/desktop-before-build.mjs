import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const consoleDirectory = fileURLToPath(new URL("..", import.meta.url));
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const steps = [
  {
    command: process.execPath,
    args: ["scripts/prepare-local-helper.mjs"],
  },
  {
    command: npmCommand,
    args: ["run", "build"],
  },
];

if (process.argv.includes("--describe")) {
  process.stdout.write(`${JSON.stringify({ steps })}\n`);
  process.exit(0);
}

for (const step of steps) {
  const result = spawnSync(step.command, step.args, {
    cwd: consoleDirectory,
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
