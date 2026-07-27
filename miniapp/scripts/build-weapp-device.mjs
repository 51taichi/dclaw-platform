import { spawnSync } from "node:child_process";
import { networkInterfaces } from "node:os";

function isPrivateIPv4(address) {
  return (
    address.startsWith("10.") ||
    address.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[0-1])\./.test(address)
  );
}

function resolveLanHost() {
  if (process.env.TARO_APP_API_HOST) {
    return process.env.TARO_APP_API_HOST;
  }

  const candidates = Object.values(networkInterfaces())
    .flat()
    .filter(
      (entry) =>
        entry &&
        entry.family === "IPv4" &&
        !entry.internal &&
        entry.address !== "127.0.0.1",
    );

  const selected = candidates.find((entry) => isPrivateIPv4(entry.address)) ||
    candidates[0];

  if (!selected) {
    console.error(
      "[build-weapp-device] No LAN IPv4 address found. Set TARO_APP_API_HOST manually.",
    );
    process.exit(1);
  }

  return selected.address;
}

const host = resolveLanHost();
const port =
  process.env.TARO_APP_API_PORT ||
  process.env.QWENPAW_SAAS_HOST_PORT ||
  "18088";
const apiBase = process.env.TARO_APP_API_BASE || `http://${host}:${port}`;

console.log(`[build-weapp-device] TARO_APP_API_BASE=${apiBase}`);

const result = spawnSync("npm", ["run", "build:weapp"], {
  stdio: "inherit",
  env: {
    ...process.env,
    TARO_APP_API_BASE: apiBase,
    TARO_APP_API_HOST: host,
    TARO_APP_API_PORT: port,
  },
});

process.exit(result.status ?? 1);
