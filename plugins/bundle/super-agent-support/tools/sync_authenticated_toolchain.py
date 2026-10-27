#!/usr/bin/env python3
"""Download and freeze one authenticated Super Agent toolchain release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import zipfile


CHUNK_SIZE = 1024 * 1024
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")
STANDARD_MARKER = re.compile(r"^当前版本：`([^`]+)`", re.MULTILINE)


class ToolchainSyncError(RuntimeError):
    """Raised when a production toolchain cannot be trusted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _headers(token: str | None = None, **extra: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra)
    return headers


def _request_bytes(
    url: str,
    *,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes, str]:
    request = Request(url, headers=_headers(token, **(headers or {})))
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310
            return (
                response.status,
                dict(response.headers.items()),
                response.read(),
                response.geturl(),
            )
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read(), exc.geturl()


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainSyncError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ToolchainSyncError(f"{label} must return a JSON object")
    return value


def _same_origin(base_url: str, candidate: str) -> bool:
    base = urlparse(base_url)
    other = urlparse(candidate)
    return (base.scheme, base.hostname, base.port) == (
        other.scheme,
        other.hostname,
        other.port,
    )


def _download_url(base_url: str, path: Any, label: str) -> str:
    if not isinstance(path, str) or not path.startswith(
        "/api/super-agent-support/",
    ):
        raise ToolchainSyncError(f"{label} download_path is not a support route")
    result = urljoin(base_url.rstrip("/") + "/", path)
    if not _same_origin(base_url, result):
        raise ToolchainSyncError(f"{label} download_path changed origin")
    return result


def _download(
    url: str,
    target: Path,
    *,
    token: str,
    base_url: str,
) -> str:
    request = Request(url, headers=_headers(token, Accept="application/zip"))
    digest = hashlib.sha256()
    try:
        with urlopen(request, timeout=300) as response:  # noqa: S310
            if response.status != 200:
                raise ToolchainSyncError(
                    f"download returned HTTP {response.status}: {url}",
                )
            if not _same_origin(base_url, response.geturl()):
                raise ToolchainSyncError("download redirected to another origin")
            with target.open("wb") as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    output.write(chunk)
    except HTTPError as exc:
        raise ToolchainSyncError(
            f"download returned HTTP {exc.code}: {url}",
        ) from exc
    return digest.hexdigest()


def _safe_archive(archive: zipfile.ZipFile, label: str) -> list[str]:
    names: list[str] = []
    normalized: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ToolchainSyncError(f"{label} contains an unsafe path: {name!r}")
        folded = name.casefold()
        if folded in normalized:
            raise ToolchainSyncError(
                f"{label} contains a case-insensitive duplicate: {name}",
            )
        normalized.add(folded)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ToolchainSyncError(f"{label} contains a symbolic link: {name}")
        if info.flag_bits & 0x1:
            raise ToolchainSyncError(f"{label} contains an encrypted entry: {name}")
        leaf = path.name
        if (
            "__MACOSX" in path.parts
            or "__pycache__" in path.parts
            or leaf == ".DS_Store"
            or leaf.startswith("._")
            or leaf.endswith(".pyc")
        ):
            raise ToolchainSyncError(f"{label} contains platform metadata: {name}")
        names.append(name)
    return names


def _inspect_developer_pack(path: Path, metadata: dict[str, Any]) -> int:
    version = metadata.get("version")
    standard = metadata.get("standard")
    devkit_version = metadata.get("devkit_version")
    prefix = metadata.get("archive_prefix")
    if not isinstance(standard, dict):
        raise ToolchainSyncError("developer-pack standard metadata is missing")
    if prefix != f"dclaw-super-agent-developer-pack-{version}":
        raise ToolchainSyncError("developer-pack archive_prefix is inconsistent")
    with zipfile.ZipFile(path) as archive:
        names = _safe_archive(archive, "developer-pack")
        expected_prefix = prefix + "/"
        if not names or any(not name.startswith(expected_prefix) for name in names):
            raise ToolchainSyncError("developer-pack has an unexpected root")
        if metadata.get("file_count") != len(names):
            raise ToolchainSyncError("developer-pack file_count does not match ZIP")
        manifest_name = expected_prefix + "PACKAGE-MANIFEST.json"
        manifest = _json_object(archive.read(manifest_name), "PACKAGE-MANIFEST.json")
        if (
            manifest.get("version") != version
            or manifest.get("standard") != standard
            or manifest.get("devkit_version") != devkit_version
        ):
            raise ToolchainSyncError("developer-pack manifest version mismatch")
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                raise ToolchainSyncError("developer-pack manifest entry is invalid")
            member = expected_prefix + str(item.get("path", ""))
            try:
                data = archive.read(member)
            except KeyError as exc:
                raise ToolchainSyncError(
                    f"developer-pack manifest member is missing: {member}",
                ) from exc
            if (
                len(data) != item.get("size_bytes")
                or hashlib.sha256(data).hexdigest() != item.get("sha256")
            ):
                raise ToolchainSyncError(
                    f"developer-pack manifest member mismatch: {member}",
                )
        standard_data = archive.read(
            expected_prefix
            + "standard/super-agent-development-standard-v1.zh-CN.md",
        ).decode("utf-8")
        match = STANDARD_MARKER.search(standard_data)
        if not match or match.group(1) != standard.get("version"):
            raise ToolchainSyncError("developer-pack standard version mismatch")
        if (
            archive.read(expected_prefix + "devkit/VERSION").decode().strip()
            != devkit_version
        ):
            raise ToolchainSyncError("developer-pack embedded DevKit mismatch")
    return len(names)


def _inspect_devkit(path: Path, metadata: dict[str, Any]) -> int:
    version = metadata.get("version")
    prefix = f"dclaw-super-agent-devkit-{version}/"
    with zipfile.ZipFile(path) as archive:
        names = _safe_archive(archive, "devkit")
        if not names or any(not name.startswith(prefix) for name in names):
            raise ToolchainSyncError("devkit has an unexpected root")
        if archive.read(prefix + "VERSION").decode().strip() != version:
            raise ToolchainSyncError("devkit VERSION does not match metadata")
        checksums = archive.read(prefix + "CHECKSUMS.sha256").decode("ascii")
        for line in checksums.splitlines():
            if not line.strip():
                continue
            digest, member = line.split(None, 1)
            member = member.strip().lstrip("*")
            data = archive.read(prefix + member)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ToolchainSyncError(f"devkit checksum mismatch: {member}")
    return len(names)


def _require_version(value: Any, expected: str, label: str) -> None:
    if value != expected:
        raise ToolchainSyncError(
            f"{label} mismatch: expected {expected}, received {value}",
        )


def _validate_existing(
    path: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    stored = _json_object(
        (path / "production-receipt.json").read_bytes(),
        "existing production receipt",
    )
    stored_stable = json.loads(json.dumps(stored))
    receipt_stable = json.loads(json.dumps(receipt))
    stored_stable.get("source", {}).pop("downloaded_at_epoch", None)
    receipt_stable.get("source", {}).pop("downloaded_at_epoch", None)
    if stored_stable != receipt_stable:
        raise ToolchainSyncError(
            "immutable toolchain directory already exists with another receipt: "
            f"{path}",
        )
    for name, record in receipt["artifacts"].items():
        if _sha256(path / name) != record["sha256"]:
            raise ToolchainSyncError(f"existing toolchain artifact changed: {name}")
    return stored


def _make_read_only(root: Path) -> None:
    for path in root.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sync_toolchain(
    *,
    base_url: str,
    output_root: Path,
    token: str,
    expected_plugin_version: str,
    expected_standard_version: str,
    expected_pack_version: str,
    expected_devkit_version: str,
    server_revision: str,
    client_revision: str,
    image_id: str,
    allow_http: bool = False,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and not (allow_http and parsed.scheme == "http"):
        raise ToolchainSyncError("base URL must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ToolchainSyncError("base URL must not contain credentials")
    for value, pattern, label in (
        (server_revision, HEX_40, "server revision"),
        (client_revision, HEX_40, "client revision"),
        (image_id, IMAGE_ID, "image ID"),
    ):
        if not pattern.fullmatch(value):
            raise ToolchainSyncError(f"invalid {label}")
    for value in (
        expected_plugin_version,
        expected_standard_version,
        expected_pack_version,
        expected_devkit_version,
    ):
        if not VERSION.fullmatch(value):
            raise ToolchainSyncError(f"invalid expected version: {value}")
    if not token.strip():
        raise ToolchainSyncError("authentication token is empty")

    support = base_url + "/api/super-agent-support"
    private_status, _, _, _ = _request_bytes(support + "/health")
    if private_status != 401:
        raise ToolchainSyncError(
            f"private health without authentication returned {private_status}",
        )
    jwk_status, jwk_headers, jwk_data, _ = _request_bytes(
        support + "/business-identities/verification-keys",
    )
    if jwk_status != 200:
        raise ToolchainSyncError(f"verification keys returned {jwk_status}")
    jwk = _json_object(jwk_data, "verification keys")
    if not jwk.get("issuer") or not isinstance(jwk.get("keys"), list):
        raise ToolchainSyncError("verification keys contract is incomplete")
    etag = next(
        (value for key, value in jwk_headers.items() if key.lower() == "etag"),
        "",
    )
    if not etag:
        raise ToolchainSyncError("verification keys response has no ETag")
    conditional_status, _, _, _ = _request_bytes(
        support + "/business-identities/verification-keys",
        headers={"If-None-Match": etag},
    )
    if conditional_status != 304:
        raise ToolchainSyncError(
            f"conditional verification keys returned {conditional_status}",
        )

    responses: dict[str, tuple[dict[str, Any], bytes]] = {}
    for key, endpoint in (
        ("health", "/health"),
        ("developer-pack", "/developer-pack"),
        ("developer-kit", "/developer-kit"),
    ):
        status, _, data, _ = _request_bytes(support + endpoint, token=token)
        if status != 200:
            raise ToolchainSyncError(f"authenticated {key} returned {status}")
        responses[key] = (_json_object(data, key), data)
    health, health_data = responses["health"]
    pack, pack_data = responses["developer-pack"]
    devkit, devkit_data = responses["developer-kit"]
    _require_version(health.get("version"), expected_plugin_version, "plugin")
    _require_version(pack.get("version"), expected_pack_version, "developer pack")
    standard = pack.get("standard")
    if not isinstance(standard, dict):
        raise ToolchainSyncError("developer pack standard metadata is missing")
    _require_version(
        standard.get("version"),
        expected_standard_version,
        "development standard",
    )
    _require_version(
        pack.get("devkit_version"),
        expected_devkit_version,
        "embedded DevKit",
    )
    _require_version(devkit.get("version"), expected_devkit_version, "DevKit")

    directory_name = (
        f"standard-{expected_standard_version}-"
        f"pack-{expected_pack_version}-devkit-{expected_devkit_version}"
    )
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".toolchain-", dir=output_root))
    final = output_root / directory_name
    try:
        pack_path = temporary / "developer-pack.zip"
        devkit_path = temporary / "devkit.zip"
        pack_digest = _download(
            _download_url(base_url, pack.get("download_path"), "developer-pack"),
            pack_path,
            token=token,
            base_url=base_url,
        )
        devkit_digest = _download(
            _download_url(base_url, devkit.get("download_path"), "devkit"),
            devkit_path,
            token=token,
            base_url=base_url,
        )
        _require_version(pack_digest, pack.get("content_sha256"), "pack SHA-256")
        _require_version(devkit_digest, devkit.get("sha256"), "DevKit SHA-256")
        pack_entries = _inspect_developer_pack(pack_path, pack)
        devkit_entries = _inspect_devkit(devkit_path, devkit)

        (temporary / "health.json").write_bytes(health_data)
        (temporary / "developer-pack.json").write_bytes(pack_data)
        (temporary / "developer-kit.json").write_bytes(devkit_data)
        (temporary / "verification-keys.json").write_bytes(jwk_data)
        (temporary / "SHA256SUMS").write_text(
            f"{pack_digest}  developer-pack.zip\n"
            f"{devkit_digest}  devkit.zip\n",
            encoding="ascii",
        )
        receipt = {
            "schema_version": "dclaw.super-agent-toolchain-receipt/1",
            "source": {
                "base_url": base_url,
                "authenticated_download": True,
                "downloaded_at_epoch": int(time.time()),
                "contains_credentials": False,
            },
            "release": {
                "server_revision": server_revision,
                "client_revision": client_revision,
                "image_id": image_id,
            },
            "contracts": {
                "standard_version": expected_standard_version,
                "support_plugin_version": expected_plugin_version,
                "developer_pack_version": expected_pack_version,
                "devkit_version": expected_devkit_version,
            },
            "artifacts": {
                "developer-pack.zip": {
                    "sha256": pack_digest,
                    "entry_count": pack_entries,
                    "metadata_file": "developer-pack.json",
                },
                "devkit.zip": {
                    "sha256": devkit_digest,
                    "entry_count": devkit_entries,
                    "metadata_file": "developer-kit.json",
                },
            },
            "route_checks": {
                "private_route_without_auth": private_status,
                "verification_keys": jwk_status,
                "verification_keys_conditional": conditional_status,
                "authenticated_health": 200,
            },
            "archive_hygiene": {
                "appledouble_entries": 0,
                "ds_store_entries": 0,
                "macosx_entries": 0,
                "python_bytecode_entries": 0,
                "python_cache_entries": 0,
            },
        }
        _write_json(temporary / "production-receipt.json", receipt)
        if final.exists():
            stored_receipt = _validate_existing(final, receipt)
            shutil.rmtree(temporary)
            return {
                "status": "reused",
                "path": str(final),
                **stored_receipt,
            }
        _make_read_only(temporary)
        os.replace(temporary, final)
        return {"status": "created", "path": str(final), **receipt}
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _token(args: argparse.Namespace) -> str:
    if args.token_file:
        token_path = args.token_file.expanduser().resolve()
        if os.name != "nt" and stat.S_IMODE(token_path.stat().st_mode) & 0o077:
            raise ToolchainSyncError(
                "token file must not be accessible by group/others",
            )
        return token_path.read_text(encoding="utf-8").strip()
    return os.environ.get(args.token_env, "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--token-env", default="DCLAW_AUTH_TOKEN")
    parser.add_argument("--expected-plugin-version", required=True)
    parser.add_argument("--expected-standard-version", required=True)
    parser.add_argument("--expected-pack-version", required=True)
    parser.add_argument("--expected-devkit-version", required=True)
    parser.add_argument("--server-revision", required=True)
    parser.add_argument("--client-revision", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--allow-http", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = sync_toolchain(
            base_url=args.base_url,
            output_root=args.output_root,
            token=_token(args),
            expected_plugin_version=args.expected_plugin_version,
            expected_standard_version=args.expected_standard_version,
            expected_pack_version=args.expected_pack_version,
            expected_devkit_version=args.expected_devkit_version,
            server_revision=args.server_revision,
            client_revision=args.client_revision,
            image_id=args.image_id,
            allow_http=args.allow_http,
        )
    except (OSError, ToolchainSyncError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
