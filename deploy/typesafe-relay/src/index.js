const DEFAULT_UPSTREAM_URL = "https://api.typesafe.ai/v1/systemone";
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const RESPONSE_HEADERS = ["content-type", "retry-after", "x-typesafe-request-id"];

function jsonResponse(status, detail) {
  return Response.json({ detail }, { status });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/v1/systemone") {
      return jsonResponse(404, "Not Found");
    }
    if (request.method !== "POST") {
      return new Response(null, { status: 405, headers: { Allow: "POST" } });
    }

    const relayToken = request.headers.get("X-DClaw-Relay-Token");
    if (!env.RELAY_TOKEN || relayToken !== env.RELAY_TOKEN) {
      return jsonResponse(401, "Relay authentication required");
    }
    const authorization = request.headers.get("Authorization");
    if (!authorization?.startsWith("Bearer ")) {
      return jsonResponse(401, "TypeSafe API key required");
    }

    const declaredLength = Number(request.headers.get("Content-Length") || 0);
    if (declaredLength > MAX_BODY_BYTES) {
      return jsonResponse(413, "Request body too large");
    }
    const body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return jsonResponse(413, "Request body too large");
    }

    const upstreamUrl = env.TYPESAFE_UPSTREAM_URL || DEFAULT_UPSTREAM_URL;
    const upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: authorization,
        "Content-Type": "application/json",
      },
      body,
    });
    const headers = new Headers();
    for (const name of RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
