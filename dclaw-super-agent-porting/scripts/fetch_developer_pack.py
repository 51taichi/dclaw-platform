#!/usr/bin/env python3
"""Fetch and verify the target DClaw Developer Pack without storing credentials."""

import argparse
import getpass
import hashlib
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("unexpected HTTP redirect")


OPENER = urllib.request.build_opener(NoRedirect)


def request_json(url, *, token=None, payload=None):
    headers = {"Accept": "application/json"}
    if payload is None:
        headers.update({"Cache-Control": "no-cache", "Pragma": "no-cache"})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers)
    with OPENER.open(request, timeout=30) as response:
        return json.load(response)


def sha256_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def safe_zip_name(name):
    return (
        isinstance(name, str)
        and bool(name)
        and not any(char in name for char in ("\\", ":", "\x00"))
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


def verify_pack(path, metadata):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP member")
        if any(not safe_zip_name(name) for name in names):
            raise ValueError("unsafe ZIP member")
        manifests = [name for name in names if name.endswith("/PACKAGE-MANIFEST.json")]
        if len(manifests) != 1:
            raise ValueError("missing or duplicate package manifest")
        prefix = manifests[0][: -len("PACKAGE-MANIFEST.json")]
        if metadata.get("archive_prefix") and prefix.rstrip("/") != metadata["archive_prefix"]:
            raise ValueError("archive prefix differs from metadata")
        for name in names:
            if not name.startswith(prefix):
                raise ValueError("unsafe or unrelated ZIP member")
        manifest = json.loads(archive.read(prefix + "PACKAGE-MANIFEST.json"))
        if manifest.get("version") != metadata.get("version"):
            raise ValueError("Pack version differs from metadata")
        for field in ("devkit_version", "standard"):
            if field in metadata and manifest.get(field) != metadata[field]:
                raise ValueError(f"{field} differs from metadata")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("package manifest has no files")
        checksums = {}
        for line in archive.read(prefix + "SHA256SUMS").decode("ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match or match[2] in checksums:
                raise ValueError("invalid SHA256SUMS")
            checksums[match[2]] = match[1]
        if checksums.get("PACKAGE-MANIFEST.json") != hashlib.sha256(
            archive.read(prefix + "PACKAGE-MANIFEST.json")
        ).hexdigest():
            raise ValueError("manifest checksum mismatch")
        listed = set()
        for entry in entries:
            name = entry["path"]
            if name in listed or not safe_zip_name(name):
                raise ValueError("invalid manifest path")
            listed.add(name)
            with archive.open(prefix + name) as stream:
                digest, size = sha256_stream(stream)
            if digest != entry["sha256"] or size != entry["size_bytes"]:
                raise ValueError(f"package member checksum mismatch: {name}")
            if checksums.get(name) != digest:
                raise ValueError(f"SHA256SUMS mismatch: {name}")
        if set(checksums) != listed | {"PACKAGE-MANIFEST.json"}:
            raise ValueError("SHA256SUMS does not match package manifest")
        if set(names) != {prefix + name for name in listed | {"PACKAGE-MANIFEST.json", "SHA256SUMS"}}:
            raise ValueError("ZIP contains files outside package manifest")
        return {
            "version": manifest["version"],
            "standard": manifest.get("standard", {}).get("version"),
            "devkit_version": manifest.get("devkit_version"),
            "files_verified": len(listed),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Target DClaw HTTPS origin")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query
            or parsed.fragment or parsed.username is not None or parsed.password is not None):
        parser.error("--base-url must be an HTTPS origin")
    if not sys.stdin.isatty():
        parser.error("interactive terminal required for local credential input")

    status = request_json(base + "/api/auth/status")
    if status.get("enabled") is not True or status.get("has_users") is not True:
        raise ValueError("target DClaw login is unavailable")

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
        raise ValueError("login did not return a token")
    request_json(base + "/api/auth/verify", token=token)
    try:
        request_json(base + "/api/user/super-expert-publishing/agents", token=token)
        publish_route_status = 200
    except urllib.error.HTTPError as exc:
        publish_route_status = exc.code
        if publish_route_status == 401:
            raise ValueError("authenticated publish route rejected the token") from exc
    metadata = request_json(base + "/api/super-agent-support/developer-pack", token=token)
    expected = metadata.get("sha256") or metadata.get("content_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Pack metadata has no valid SHA-256")
    version = metadata.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Pack metadata has no safe version")
    download_path = metadata.get("download_path")
    if not isinstance(download_path, str) or not download_path.startswith("/"):
        raise ValueError("Pack metadata has no download path")
    download_url = urllib.parse.urljoin(base + "/", download_path)
    target = urllib.parse.urlsplit(download_url)
    if (target.scheme, target.netloc) != (parsed.scheme, parsed.netloc):
        raise ValueError("download path points outside target origin")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / f"developer-pack-{version}.zip"
    if destination.exists():
        with destination.open("rb") as stream:
            existing, _ = sha256_stream(stream)
        if existing.lower() != expected.lower():
            raise ValueError(f"different file already exists: {destination}")
        details = verify_pack(destination, metadata)
    else:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=args.output_dir, prefix=".developer-pack-", suffix=".zip", delete=False) as output:
                temporary = Path(output.name)
                request = urllib.request.Request(
                    download_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                    },
                )
                with OPENER.open(request, timeout=120) as response:
                    digest = hashlib.sha256()
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if digest.hexdigest().lower() != expected.lower():
                raise ValueError("download SHA-256 differs from metadata")
            if "size_bytes" in metadata and size != metadata["size_bytes"]:
                raise ValueError("download size differs from metadata")
            details = verify_pack(temporary, metadata)
            temporary.replace(destination)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    print(json.dumps({"package": str(destination.resolve()), "sha256": expected.lower(), "publish_route_status": publish_route_status, **details}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, urllib.error.HTTPError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            print(f"HTTP {exc.code} while accessing DClaw", file=sys.stderr)
        else:
            print(f"Developer Pack fetch failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
