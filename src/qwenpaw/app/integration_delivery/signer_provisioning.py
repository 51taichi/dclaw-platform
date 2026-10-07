"""Provision the server-owned signer used for sealed delivery updates."""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from ...constant import SECRET_DIR, WORKING_DIR


class IntegrationDeliverySignerError(RuntimeError):
    """Signing material cannot be provisioned without unsafe replacement."""


@dataclass(frozen=True)
class IntegrationDeliverySignerStatus:
    signer_id: str
    signer_file_configured: bool
    signer_file_mode: str | None
    trusted: bool
    official_for_super_expert: bool

    @property
    def ready(self) -> bool:
        return (
            self.signer_file_configured
            and self.signer_file_mode == "0600"
            and self.trusted
            and self.official_for_super_expert
        )

    def public_view(self) -> dict[str, Any]:
        return {"ready": self.ready, **asdict(self)}


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationDeliverySignerError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise IntegrationDeliverySignerError(f"{label} is invalid")
    return payload


def _private_key(path: Path, signer_id: str) -> Ed25519PrivateKey:
    payload = _read_json_object(path, label="integration delivery signer")
    if payload.get("signerId") != signer_id:
        raise IntegrationDeliverySignerError(
            "integration delivery signer identity does not match",
        )
    try:
        raw = base64.b64decode(payload["privateKey"], validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationDeliverySignerError(
            "integration delivery signer is invalid",
        ) from exc


def _registry(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = _read_json_object(path, label=f"signer registry {path.name}")
    signers = payload.get("signers")
    if not isinstance(signers, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in signers.items()
    ):
        raise IntegrationDeliverySignerError(
            f"signer registry {path.name} is invalid",
        )
    return dict(signers)


def _atomic_json(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        if temporary.exists():
            temporary.unlink()


def _encoded_public_key(private: Ed25519PrivateKey) -> str:
    return base64.b64encode(private.public_key().public_bytes_raw()).decode(
        "ascii",
    )


def integration_delivery_signer_status(
    *,
    secret_dir: Path = Path(SECRET_DIR),
    sealed_root: Path = Path(WORKING_DIR) / "sealed_agents",
    signer_id: str = "integration-delivery",
) -> IntegrationDeliverySignerStatus:
    signer_path = Path(secret_dir) / "integration_delivery_signer.json"
    private = _private_key(signer_path, signer_id) if signer_path.is_file() else None
    encoded_public = _encoded_public_key(private) if private is not None else None
    trusted = _registry(Path(sealed_root) / "trusted_signers.json")
    official = _registry(
        Path(sealed_root) / "official_super_expert_signers.json",
    )
    mode = (
        f"{signer_path.stat().st_mode & 0o777:04o}"
        if signer_path.is_file()
        else None
    )
    return IntegrationDeliverySignerStatus(
        signer_id=signer_id,
        signer_file_configured=private is not None,
        signer_file_mode=mode,
        trusted=trusted.get(signer_id) == encoded_public,
        official_for_super_expert=official.get(signer_id) == encoded_public,
    )


def provision_integration_delivery_signer(
    *,
    secret_dir: Path = Path(SECRET_DIR),
    sealed_root: Path = Path(WORKING_DIR) / "sealed_agents",
    signer_id: str = "integration-delivery",
) -> IntegrationDeliverySignerStatus:
    if not signer_id.strip():
        raise IntegrationDeliverySignerError("signer identity is required")
    secret_root = Path(secret_dir)
    signer_root = Path(sealed_root)
    secret_root.mkdir(parents=True, exist_ok=True)
    signer_root.mkdir(parents=True, exist_ok=True)
    lock_path = secret_root / ".integration_delivery_signer.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        signer_path = secret_root / "integration_delivery_signer.json"
        if signer_path.exists():
            private = _private_key(signer_path, signer_id)
            private_is_new = False
        else:
            private = Ed25519PrivateKey.generate()
            private_is_new = True
        encoded_public = _encoded_public_key(private)
        registry_names = (
            "trusted_signers.json",
            "official_super_expert_signers.json",
        )
        registries = {
            name: _registry(signer_root / name) for name in registry_names
        }
        for name, signers in registries.items():
            existing = signers.get(signer_id)
            if existing is not None and existing != encoded_public:
                raise IntegrationDeliverySignerError(
                    f"signer identity conflicts with {name}",
                )
        if private_is_new:
            _atomic_json(
                signer_path,
                {
                    "privateKey": base64.b64encode(
                        private.private_bytes_raw(),
                    ).decode("ascii"),
                    "signerId": signer_id,
                },
                mode=0o600,
            )
        signer_path.chmod(0o600)
        for name, signers in registries.items():
            signers[signer_id] = encoded_public
            _atomic_json(
                signer_root / name,
                {"signers": signers},
                mode=0o644,
            )
    return integration_delivery_signer_status(
        secret_dir=secret_root,
        sealed_root=signer_root,
        signer_id=signer_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision or check the integration delivery signer",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--provision", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--secret-dir", type=Path, default=Path(SECRET_DIR))
    parser.add_argument(
        "--sealed-root",
        type=Path,
        default=Path(WORKING_DIR) / "sealed_agents",
    )
    parser.add_argument("--signer-id", default="integration-delivery")
    args = parser.parse_args(argv)
    try:
        status = (
            provision_integration_delivery_signer(
                secret_dir=args.secret_dir,
                sealed_root=args.sealed_root,
                signer_id=args.signer_id,
            )
            if args.provision
            else integration_delivery_signer_status(
                secret_dir=args.secret_dir,
                sealed_root=args.sealed_root,
                signer_id=args.signer_id,
            )
        )
    except IntegrationDeliverySignerError as exc:
        print(json.dumps({"ready": False, "error": str(exc)}))
        return 1
    print(json.dumps(status.public_view(), sort_keys=True))
    return 0 if status.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
