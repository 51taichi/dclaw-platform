"""Signed package creation and defensive validation for sealed agents."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import stat
import struct
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_EXPANDED_BYTES = 400 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_COMPRESSION_RATIO = 200


class SealedPackageError(ValueError):
    """A public-safe package validation failure."""


class PublicMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(default="", max_length=2000)
    icon: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)


class SealedRuntimeDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    contract_version: str = Field(pattern=r"^[1-9][0-9]{0,7}$")
    failure_policy: Literal["fail_closed"] = "fail_closed"

    @field_validator("adapter", "contract_version", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SealedPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    agent_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
    agent_type: str
    scope: str
    entrypoint: str
    public_metadata: PublicMetadata = Field(default_factory=PublicMetadata)
    runtime: SealedRuntimeDeclaration | None = None
    signer_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def validate_supported_contract(self) -> None:
        if self.schema_version not in {1, 2}:
            raise ValueError("unsupported schema version")
        if self.schema_version == 1 and self.runtime is not None:
            raise ValueError("schema version 1 cannot declare runtime")
        if self.agent_type != "sealed" or self.scope != "global":
            raise ValueError("only sealed global agents are supported")
        entrypoint = _normalize_member_path(self.entrypoint)
        if not entrypoint.startswith("agent/"):
            raise ValueError("entrypoint must be inside agent/")


class ValidatedSealedPackage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manifest: SealedPackageManifest
    extracted_root: Path
    public_metadata: PublicMetadata


def _normalize_member_path(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SealedPackageError("unsafe package path")
    return path.as_posix()


def _payload_digest(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    normalized: list[tuple[bytes, bytes]] = []
    seen: set[str] = set()
    for raw_path, data in files.items():
        path = _normalize_member_path(raw_path)
        if path in {"manifest.json", "signature.json"}:
            continue
        if path in seen:
            raise SealedPackageError("duplicate normalized package path")
        seen.add(path)
        normalized.append((path.encode("utf-8"), data))
    for path_bytes, data in sorted(normalized, key=lambda item: item[0]):
        digest.update(struct.pack(">Q", len(path_bytes)))
        digest.update(path_bytes)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def _canonical_manifest(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_signed_package_bytes(
    manifest: Mapping[str, Any],
    files: Mapping[str, bytes],
    private_key: Ed25519PrivateKey,
) -> bytes:
    """Build the deterministic signed contract used by release tooling."""
    payload_files = {
        _normalize_member_path(path): bytes(data)
        for path, data in files.items()
    }
    manifest_payload = dict(manifest)
    manifest_payload["content_digest"] = _payload_digest(payload_files)
    try:
        validated = SealedPackageManifest.model_validate(manifest_payload)
        validated.validate_supported_contract()
    except (ValidationError, ValueError) as exc:
        raise SealedPackageError("invalid sealed package manifest") from exc
    canonical = _canonical_manifest(validated.model_dump(mode="json"))
    signature_payload = {
        "signer_id": validated.signer_id,
        "algorithm": "ed25519",
        "signature": base64.b64encode(private_key.sign(canonical)).decode("ascii"),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical)
        for path in sorted(payload_files):
            archive.writestr(path, payload_files[path])
        archive.writestr(
            "signature.json",
            _canonical_manifest(signature_payload),
        )
    return output.getvalue()


def validate_sealed_package(
    data: bytes,
    *,
    trusted_signers: Mapping[str, Ed25519PublicKey],
    staging_root: Path,
) -> ValidatedSealedPackage:
    """Verify and safely extract a signed package into a private staging root."""
    if len(data) > MAX_PACKAGE_BYTES:
        raise SealedPackageError("sealed package exceeds size limit")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise SealedPackageError("sealed package is not a zip archive")

    staging_root = Path(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="sealed_", dir=staging_root))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos, normalized = _validated_members(archive)
            by_name = dict(zip(normalized, infos))
            if "manifest.json" not in by_name or "signature.json" not in by_name:
                raise SealedPackageError("sealed package metadata is missing")
            try:
                manifest_bytes = archive.read(by_name["manifest.json"])
                manifest = SealedPackageManifest.model_validate_json(manifest_bytes)
                manifest.validate_supported_contract()
                signature = json.loads(archive.read(by_name["signature.json"]))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise SealedPackageError("invalid sealed package manifest") from exc
            if signature.get("signer_id") != manifest.signer_id:
                raise SealedPackageError("sealed package signer mismatch")
            public_key = trusted_signers.get(manifest.signer_id)
            if public_key is None:
                raise SealedPackageError("sealed package signer is not trusted")
            try:
                encoded_signature = base64.b64decode(
                    signature.get("signature", ""),
                    validate=True,
                )
                public_key.verify(
                    encoded_signature,
                    _canonical_manifest(manifest.model_dump(mode="json")),
                )
            except (InvalidSignature, ValueError, TypeError) as exc:
                raise SealedPackageError("sealed package signature is invalid") from exc

            payload: dict[str, bytes] = {}
            for path, info in zip(normalized, infos):
                if path not in {"manifest.json", "signature.json"}:
                    payload[path] = archive.read(info)
            if _payload_digest(payload) != manifest.content_digest:
                raise SealedPackageError("sealed package content digest mismatch")
            if manifest.entrypoint not in payload:
                raise SealedPackageError("sealed package entrypoint is missing")

            root = destination.resolve()
            for path, content in payload.items():
                target = (destination / path).resolve()
                if not target.is_relative_to(root):
                    raise SealedPackageError("unsafe package path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        return ValidatedSealedPackage(
            manifest=manifest,
            extracted_root=destination,
            public_metadata=manifest.public_metadata,
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _validated_members(
    archive: zipfile.ZipFile,
) -> tuple[list[zipfile.ZipInfo], list[str]]:
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > MAX_MEMBERS:
        raise SealedPackageError("sealed package has too many files")
    normalized: list[str] = []
    seen: set[str] = set()
    total = 0
    for info in infos:
        path = _normalize_member_path(info.filename)
        if path in seen:
            raise SealedPackageError("duplicate normalized package path")
        seen.add(path)
        normalized.append(path)
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG}:
            raise SealedPackageError("sealed packages may contain regular files only")
        if info.file_size > MAX_FILE_BYTES:
            raise SealedPackageError("sealed package file exceeds size limit")
        total += info.file_size
        if total > MAX_EXPANDED_BYTES:
            raise SealedPackageError("sealed package expanded size limit exceeded")
        compressed = max(info.compress_size, 1)
        if info.file_size > 1024 * 1024 and info.file_size / compressed > MAX_COMPRESSION_RATIO:
            raise SealedPackageError("sealed package compression ratio is unsafe")
    return infos, normalized
