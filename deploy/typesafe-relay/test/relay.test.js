import assert from "node:assert/strict";
import test from "node:test";

import { handleRelayRequest } from "../src/relay.js";

const env = {
  RELAY_TOKEN: "relay-secret",
  TYPESAFE_UPSTREAM_URL: "https://api.typesafe.ai/v1/systemone",
};

test("rejects requests without the relay token", async () => {
  const response = await handleRelayRequest(
    new Request("https://relay.example/v1/systemone", {
      method: "POST",
      headers: { Authorization: "Bearer typesafe-key" },
      body: "{}",
    }),
    env,
  );

  assert.equal(response.status, 401);
});

test("forwards only the TypeSafe request and selected response headers", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async (url, init) => {
    assert.equal(url, env.TYPESAFE_UPSTREAM_URL);
    assert.equal(init.method, "POST");
    assert.equal(init.headers.Authorization, "Bearer typesafe-key");
    assert.equal(init.headers["X-DClaw-Relay-Token"], undefined);
    assert.equal(new TextDecoder().decode(init.body), '{"model":"jev-latest"}');
    return new Response('{"answers":{}}', {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-TypeSafe-Request-Id": "request-1",
        "X-Unrelated": "hidden",
      },
    });
  };

  const response = await handleRelayRequest(
    new Request("https://relay.example/v1/systemone", {
      method: "POST",
      headers: {
        Authorization: "Bearer typesafe-key",
        "Content-Type": "application/json",
        "X-DClaw-Relay-Token": env.RELAY_TOKEN,
      },
      body: '{"model":"jev-latest"}',
    }),
    env,
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-TypeSafe-Request-Id"), "request-1");
  assert.equal(response.headers.get("X-Unrelated"), null);
  assert.equal(await response.text(), '{"answers":{}}');
});

test("does not expose any other path", async () => {
  const response = await handleRelayRequest(
    new Request("https://relay.example/anything", { method: "POST" }),
    env,
  );

  assert.equal(response.status, 404);
});
