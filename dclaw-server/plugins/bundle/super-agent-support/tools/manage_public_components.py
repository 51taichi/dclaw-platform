#!/usr/bin/env python3
"""Headless public Component registry client for the support plugin."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA


class ComponentClientError(RuntimeError):
    """The registry request or local signing input is invalid."""


def _canonical(descriptor: dict[str, Any]) -> bytes:
    return json.dumps(
        descriptor,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentClientError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ComponentClientError(f"JSON root must be an object: {path}")
    return value


def _request(
    method: str,
    url: str,
    *,
    access_token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    encoded = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:  # nosec B310
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ComponentClientError(
            f"registry returned HTTP {exc.code}: {detail}",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ComponentClientError(f"registry request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise ComponentClientError("registry response must be a JSON object")
    return result


def _base(value: str) -> str:
    return value.rstrip("/") + "/api/super-agent-support"


def _signature(args: argparse.Namespace, descriptor: dict[str, Any]) -> str:
    if args.signature_file:
        try:
            signature = Path(args.signature_file).read_text(encoding="utf-8").strip()
            base64.b64decode(signature, validate=True)
            return signature
        except (OSError, ValueError) as exc:
            raise ComponentClientError("signature file is invalid") from exc
    if not args.private_key:
        raise ComponentClientError("register requires --signature-file or --private-key")
    try:
        private_key = serialization.load_pem_private_key(
            Path(args.private_key).read_bytes(),
            password=None,
        )
        return base64.b64encode(
            private_key.sign(_canonical(descriptor), ECDSA(hashes.SHA256())),
        ).decode("ascii")
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        raise ComponentClientError("P-256 private key is invalid") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query or register DClaw public Components without a UI.",
    )
    parser.add_argument("--base-url", required=True, help="DClaw HTTPS base URL")
    parser.add_argument(
        "--access-token",
        default=os.environ.get("DCLAW_ACCESS_TOKEN", ""),
        help="authenticated DClaw access token; defaults to DCLAW_ACCESS_TOKEN",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("get", help="return the complete registry")
    register = commands.add_parser("register", help="sign and register one variant")
    register.add_argument("--descriptor", required=True)
    register.add_argument("--signer-id", required=True)
    signature = register.add_mutually_exclusive_group(required=True)
    signature.add_argument("--signature-file")
    signature.add_argument("--private-key")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        base = _base(args.base_url)
        if args.command == "get":
            result = _request(
                "GET",
                base + "/component-registry",
                access_token=args.access_token,
            )
        else:
            descriptor = _read_object(Path(args.descriptor))
            component_id = descriptor.get("component_id")
            platform = descriptor.get("platform")
            if not isinstance(component_id, str) or not isinstance(platform, str):
                raise ComponentClientError(
                    "descriptor component_id and platform are required",
                )
            result = _request(
                "PUT",
                base
                + "/admin/component-registry/"
                + component_id
                + "/variants/"
                + platform,
                access_token=args.access_token,
                body={
                    "descriptor": descriptor,
                    "signer_id": args.signer_id,
                    "signature": _signature(args, descriptor),
                },
            )
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except ComponentClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
