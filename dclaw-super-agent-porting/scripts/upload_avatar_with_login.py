#!/usr/bin/env python3
"""Update a sealed DClaw expert avatar with an interactive admin login."""

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fetch_developer_pack import OPENER, request_json


MAX_IMAGE_BYTES = 2 * 1024 * 1024


def find_agent(payload, agent_id):
    agents = payload if isinstance(payload, list) else payload.get("agents", [])
    if not isinstance(agents, list):
        raise ValueError("admin agent list has an unexpected shape")
    matches = [agent for agent in agents if isinstance(agent, dict) and agent.get("agent_id") == agent_id]
    if len(matches) != 1:
        raise ValueError(f"expected one admin record for {agent_id}; found {len(matches)}")
    return matches[0]


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "avatar.png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "avatar.jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", "avatar.webp"
    raise ValueError("avatar must be PNG, JPEG, or WebP")


def upload_avatar(base, token, agent_id, data):
    mime_type, filename = image_type(data)
    boundary = "dclaw-avatar-" + uuid.uuid4().hex
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("ascii")
    body = prefix + data + f"\r\n--{boundary}--\r\n".encode("ascii")
    path = "/api/admin/sealed-agents/" + urllib.parse.quote(agent_id, safe="") + "/avatar"
    request = urllib.request.Request(
        base + path,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with OPENER.open(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="DClaw HTTPS origin")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urllib.parse.urlsplit(base)
    if url.scheme != "https" or not url.netloc or url.path or url.query or url.fragment:
        parser.error("--base-url must be an HTTPS origin")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.agent_id):
        parser.error("--agent-id is invalid")
    if args.output.exists():
        parser.error("output already exists; inspect it before retrying")
    data = args.file.read_bytes()
    if not 1 <= len(data) <= MAX_IMAGE_BYTES:
        parser.error("avatar must be nonempty and at most 2 MB")
    image_type(data)
    if not sys.stdin.isatty():
        parser.error("run in an interactive terminal")

    username = input("DClaw admin username: ").strip()
    password = getpass.getpass("DClaw admin password: ")
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
    before = find_agent(request_json(base + "/api/admin/sealed-agents", token=token), args.agent_id)
    response = upload_avatar(base, token, args.agent_id, data)
    after = find_agent(request_json(base + "/api/admin/sealed-agents", token=token), args.agent_id)
    if response.get("agent_id") != args.agent_id or not after.get("avatar") or after["avatar"] != response.get("avatar"):
        raise ValueError("upload returned, but admin list did not confirm the avatar")
    if after.get("active_release_id") != before.get("active_release_id"):
        raise ValueError("active release changed during avatar update")
    result = {
        "agent_id": args.agent_id,
        "avatar_file_sha256": hashlib.sha256(data).hexdigest(),
        "avatar_bytes": len(data),
        "avatar_readback_match": True,
        "active_release_id": after.get("active_release_id"),
        "active_release_unchanged": True,
        "avatar_reference_sha256": hashlib.sha256(after["avatar"].encode("utf-8")).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(f"Avatar upload failed: HTTP {exc.code}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Avatar upload failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
