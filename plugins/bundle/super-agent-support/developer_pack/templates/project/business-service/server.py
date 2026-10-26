"""Dependency-free business service template; inject secrets via environment."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if not os.environ.get("BUSINESS_API_TOKEN"):
            response = {
                "ok": False,
                "request_id": request.get("request_id", "unknown"),
                "error": {
                    "code": "CREDENTIAL_NOT_CONFIGURED",
                    "message": "Business service credential is not configured.",
                    "retryable": False,
                },
            }
            status = 503
        else:
            response = {
                "ok": True,
                "request_id": request.get("request_id", "unknown"),
                "data": {"accepted": True},
            }
            status = 200
        payload = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
