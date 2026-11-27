import assert from "node:assert/strict";
import test from "node:test";

import { npmInvocation } from "./npm-command.mjs";

test("uses the npm CLI through Node when npm exposes its entry point", () => {
  assert.deepEqual(
    npmInvocation(["run", "build"], {
      platform: "win32",
      nodeExecutable: "node.exe",
      npmExecutable: "npm-cli.js",
    }),
    {
      command: "node.exe",
      args: ["npm-cli.js", "run", "build"],
    },
  );
});

test("uses cmd.exe for npm.cmd only as the Windows fallback", () => {
  assert.deepEqual(
    npmInvocation(["run", "build"], {
      platform: "win32",
      nodeExecutable: "node.exe",
      npmExecutable: "",
      commandShell: "cmd.exe",
    }),
    {
      command: "cmd.exe",
      args: ["/d", "/s", "/c", "npm.cmd", "run", "build"],
    },
  );
});
