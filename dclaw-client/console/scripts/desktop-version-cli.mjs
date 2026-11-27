#!/usr/bin/env node
import {
  assertVersionsSynchronized,
  incrementVersion,
  readCanonicalVersion,
  setDesktopVersion,
} from "./desktop-version.mjs";

const [action, value, ...extraArguments] = process.argv.slice(2);

try {
  if (extraArguments.length > 0) {
    throw new Error("Too many arguments.");
  }

  if (action === "show") {
    if (value !== undefined)
      throw new Error("The show command takes no value.");
    console.log(await assertVersionsSynchronized());
  } else if (["patch", "minor", "major"].includes(action)) {
    if (value !== undefined)
      throw new Error(`The ${action} command takes no value.`);
    const current = await readCanonicalVersion();
    const next = incrementVersion(current, action);
    await setDesktopVersion(next);
    console.log(`${current} -> ${next}`);
  } else if (action === "set") {
    if (value === undefined)
      throw new Error("The set command requires a version.");
    const current = await readCanonicalVersion();
    await setDesktopVersion(value);
    console.log(`${current} -> ${value}`);
  } else {
    throw new Error(
      "Usage: desktop-version-cli.mjs show|patch|minor|major|set [version]",
    );
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
