import assert from "node:assert/strict";
import { request } from "node:http";
import test from "node:test";

import { createRelayServer } from "../src/server.js";

function post(port, headers = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = request(
      {
        host: "127.0.0.1",
        port,
        path: "/v1/systemone",
        method: "POST",
        headers,
      },
      (incoming) => {
        const chunks = [];
        incoming.on("data", (chunk) => chunks.push(chunk));
        incoming.on("end", () =>
          resolve({
            status: incoming.statusCode,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    outgoing.on("error", reject);
    outgoing.end('{"model":"jev-latest"}');
  });
}

test("serves the relay handler over HTTP", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async () =>
    new Response('{"answers":{}}', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  const server = createRelayServer({
    RELAY_TOKEN: "relay-secret",
    TYPESAFE_UPSTREAM_URL: "https://api.typesafe.ai/v1/systemone",
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const result = await post(server.address().port, {
    Authorization: "Bearer typesafe-key",
    "Content-Type": "application/json",
    "X-DClaw-Relay-Token": "relay-secret",
  });

  assert.equal(result.status, 200);
  assert.equal(result.body, '{"answers":{}}');
});

test("rejects an oversized declared body before forwarding", async (t) => {
  const server = createRelayServer({ RELAY_TOKEN: "relay-secret" });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());

  const result = await post(server.address().port, {
    "Content-Length": String(2 * 1024 * 1024 + 1),
  });

  assert.equal(result.status, 413);
});
