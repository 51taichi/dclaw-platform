#!/usr/bin/env python3
"""Run an official DevKit publish command with a short-lived local login."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse

from fetch_developer_pack import request_json


STATE_CATEGORY = re.compile(r"state_[a-z0-9_]{1,64}\Z")
PUBLISH_HTTP_ERROR = re.compile(
    r"Super Expert (?:upload|publishing) returned HTTP ([4-5][0-9]{2}): (.*)\Z",
    re.DOTALL,
)


def _state_category(value, depth=0):
    if isinstance(value, str):
        return value if STATE_CATEGORY.fullmatch(value) else None
    if isinstance(value, dict) and depth < 2:
        for key in ("code", "error_code", "category", "detail", "error"):
            found = _state_category(value.get(key), depth + 1)
            if found:
                return found
    return None


def _failure_summary(stdout, stderr, returncode):
    try:
        payload = json.loads(stdout.decode("utf-8")) if len(stdout) <= 65536 else None
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        match = PUBLISH_HTTP_ERROR.fullmatch(payload["error"])
        if match:
            detail = match.group(2)
            try:
                body = json.loads(detail)
            except (json.JSONDecodeError, RecursionError):
                body = detail
            category = _state_category(body)
            return f"HTTP {match.group(1)}" + (f", {category}" if category else "")
    status = re.search(r"HTTP [4-5][0-9]{2}\b", stderr.decode("utf-8", errors="replace"))
    return status.group(0) if status else f"exit {returncode}"


def run_official_publish(command, env, action):
    # Decode JSON explicitly so a Windows locale cannot break a completed publish call.
    result = subprocess.run(command, capture_output=True, env=env, check=False)
    if result.returncode:
        summary = _failure_summary(result.stdout, result.stderr, result.returncode)
        raise ValueError(f"official publish {action} failed: {summary}")
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except UnicodeDecodeError as exc:
        note = "; check publish list before retrying upload" if action == "upload" else ""
        raise ValueError(f"official publish {action} returned non-UTF-8 JSON{note}") from exc
    except json.JSONDecodeError as exc:
        note = "; check publish list before retrying upload" if action == "upload" else ""
        raise ValueError(f"official publish {action} returned invalid JSON{note}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Target DClaw HTTPS origin")
    parser.add_argument("--devkit", required=True, type=Path, help="Official dclaw_agent_devkit.py")
    parser.add_argument("--output", type=Path, help="Save the JSON receipt or list readback")
    parser.add_argument("--readback-output", type=Path, help="After upload, save the release list using the same login")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    register = actions.add_parser("register-signer")
    register.add_argument("--public-key", required=True, type=Path)
    upload = actions.add_parser("upload")
    upload.add_argument("--package", required=True, type=Path)
    retry = actions.add_parser("retry-activation")
    retry.add_argument("--agent-id", required=True)
    retry.add_argument("--release-id", required=True)
    args = parser.parse_args()

    url = urllib.parse.urlsplit(args.base_url)
    if (url.scheme != "https" or not url.hostname or url.username is not None
            or url.password is not None or url.path not in ("", "/")
            or url.query or url.fragment):
        parser.error("--base-url must be an HTTPS origin without credentials")
    if not args.devkit.is_file():
        parser.error("official DevKit script is missing")
    if args.action == "register-signer" and not args.public_key.is_file():
        parser.error("public key is missing")
    if args.action == "upload" and not args.package.is_file():
        parser.error("signed package is missing")
    if args.output and (args.output.exists() or args.output.is_symlink()):
        parser.error("output already exists; inspect it before retrying")
    if args.readback_output:
        if args.action != "upload" or not args.output:
            parser.error("--readback-output requires upload and --output")
        if (args.readback_output.resolve() == args.output.resolve()
                or args.readback_output.exists() or args.readback_output.is_symlink()):
            parser.error("readback output must be a different new file")
    if not sys.stdin.isatty():
        parser.error("run in an interactive terminal")

    base = args.base_url.rstrip("/")
    username = input("DClaw username: ").strip()
    password = getpass.getpass("DClaw password: ")
    if not username or not password:
        parser.error("username and password are required")
    try:
        login = request_json(base + "/api/auth/login", payload={"username": username, "password": password})
    finally:
        password = None
    token = login.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("login returned no access token")
    request_json(base + "/api/auth/verify", token=token)

    command = [sys.executable, "-B", str(args.devkit), "publish", "--base-url", base, args.action]
    if args.action == "register-signer":
        command += ["--public-key", str(args.public_key)]
    elif args.action == "upload":
        command += ["--package", str(args.package)]
    elif args.action == "retry-activation":
        command += ["--agent-id", args.agent_id, "--release-id", args.release_id]
    env = os.environ.copy()
    env["DCLAW_ACCESS_TOKEN"] = token
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    receipt = run_official_publish(command, env, args.action)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=True))
    if args.readback_output:
        list_command = [sys.executable, "-B", str(args.devkit), "publish", "--base-url", base, "list"]
        readback = run_official_publish(list_command, env, "list after upload")
        args.readback_output.parent.mkdir(parents=True, exist_ok=True)
        with args.readback_output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(readback, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(readback, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
