import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

import worker from "./index.js";

const MAX_BODY_BYTES = 2 * 1024 * 1024;

function writeResponse(response, result) {
  response.statusCode = result.status;
  for (const [name, value] of result.headers) {
    response.setHeader(name, value);
  }
  result.arrayBuffer().then(
    (body) => response.end(Buffer.from(body)),
    () => {
      response.statusCode = 502;
      response.end('{"detail":"Relay response failed"}');
    },
  );
}

async function readBody(request) {
  const declaredLength = Number(request.headers["content-length"] || 0);
  if (declaredLength > MAX_BODY_BYTES) {
    throw new RangeError("Request body too large");
  }

  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > MAX_BODY_BYTES) {
      throw new RangeError("Request body too large");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

export function createRelayServer(env = process.env) {
  return createServer(async (incoming, outgoing) => {
    try {
      const method = incoming.method || "GET";
      const headers = new Headers();
      for (const [name, value] of Object.entries(incoming.headers)) {
        if (Array.isArray(value)) {
          for (const item of value) headers.append(name, item);
        } else if (value !== undefined) {
          headers.set(name, value);
        }
      }

      const forwardedProto = headers.get("x-forwarded-proto") || "http";
      const host = headers.get("host") || "relay.local";
      const init = { method, headers };
      if (method !== "GET" && method !== "HEAD") {
        init.body = await readBody(incoming);
      }

      const request = new Request(
        `${forwardedProto}://${host}${incoming.url || "/"}`,
        init,
      );
      const result = await worker.fetch(request, env);
      writeResponse(outgoing, result);
    } catch (error) {
      const status = error instanceof RangeError ? 413 : 502;
      outgoing.statusCode = status;
      outgoing.setHeader("Content-Type", "application/json");
      outgoing.end(
        JSON.stringify({
          detail: status === 413 ? "Request body too large" : "Relay request failed",
        }),
      );
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const host = process.env.HOST || "0.0.0.0";
  const port = Number(process.env.PORT || 8787);
  const server = createRelayServer();
  server.listen(port, host, () => {
    console.log(`TypeSafe relay listening on ${host}:${port}`);
  });
  process.on("SIGTERM", () => server.close());
  process.on("SIGINT", () => server.close());
}
