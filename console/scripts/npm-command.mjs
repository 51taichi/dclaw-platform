export function npmInvocation(
  args,
  {
    platform = process.platform,
    nodeExecutable = process.execPath,
    npmExecutable = process.env.npm_execpath,
    commandShell = process.env.ComSpec,
  } = {},
) {
  if (npmExecutable) {
    return {
      command: nodeExecutable,
      args: [npmExecutable, ...args],
    };
  }
  if (platform === "win32") {
    return {
      command: commandShell || "cmd.exe",
      args: ["/d", "/s", "/c", "npm.cmd", ...args],
    };
  }
  return { command: "npm", args };
}
