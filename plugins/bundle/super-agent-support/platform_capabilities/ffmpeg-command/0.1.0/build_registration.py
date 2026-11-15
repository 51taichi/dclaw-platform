"""Sign the platform FFmpeg capability descriptor with an external key."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parent
SIGNER_ID = "dclaw.platform.ffmpeg-command.v1"
PACKAGE_ID = "dclaw.ffmpeg.command"
PACKAGE_VERSION = "0.1.0"
PYTHON_VERSION = "3.12.14"
FFMPEG_VERSION = "N-128100-gceb466cbcd"


def _schema(name: str) -> dict:
    path = ROOT / name
    content = path.read_bytes()
    return {
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "document": json.loads(content),
    }


def build(private_key: Path, artifact_url: str) -> tuple[dict, dict]:
    if not artifact_url.startswith("https://raw.githubusercontent.com/"):
        raise ValueError("artifact URL must be an immutable GitHub raw URL")
    artifact = ROOT / "artifact.zip"
    descriptor = {
        "descriptor_version": "1",
        "contract_version": "1",
        "capability_id": PACKAGE_ID,
        "package_id": PACKAGE_ID,
        "package_version": PACKAGE_VERSION,
        "implementation_status": "release",
        "min_runner_version": "1.4.7",
        "artifact": {
            "url": artifact_url,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
        "entrypoint": {
            "component_id": "python-runtime",
            "export": "python",
            "arguments": ["{package_root}/runner.py"],
        },
        "public_components": [
            {"component_id": "python-runtime", "version": PYTHON_VERSION},
            {"component_id": "ffmpeg", "version": FFMPEG_VERSION},
        ],
        "component_exports": [
            {
                "environment_variable": "DCLAW_COMPONENT_FFMPEG",
                "component_id": "ffmpeg",
                "export": "ffmpeg",
            },
        ],
        "schemas": {
            "input": _schema("input.schema.json"),
            "result": _schema("result.schema.json"),
            "checkpoint": _schema("checkpoint.schema.json"),
        },
        "operating_systems": ["windows-x64"],
        "permissions": {
            "workspace": "task-only",
            "network_domains": ["raw.githubusercontent.com"],
            "processes": ["python.exe", "ffmpeg.exe"],
            "browser": False,
        },
        "limits": {
            "max_runtime_seconds": 3600,
            "max_memory_mib": 4096,
            "max_disk_mib": 16384,
            "max_concurrency": 2,
            "max_output_bytes": 8589934592,
        },
        "semantics": {
            "idempotency": "One scoped idempotency key identifies one argv, binding set, and output declaration.",
            "cancellation": "Helper stops the FFmpeg process tree when the task is cancelled.",
            "recovery": "Read the existing task ID; replay only the identical input and key.",
            "cleanup": "Intermediate files stay in the task root for normal Helper cleanup.",
        },
    }
    key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("platform signer must be Ed25519")
    canonical = json.dumps(
        descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    registration = {
        "descriptor": descriptor,
        "signer_id": SIGNER_ID,
        "signature": base64.b64encode(key.sign(canonical)).decode("ascii"),
    }
    signer = {
        "signer_id": SIGNER_ID,
        "public_key": base64.b64encode(public).decode("ascii"),
    }
    return registration, signer


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: build_registration.py KEY.pem ARTIFACT_URL OUTPUT_DIR")
    registration, signer = build(Path(sys.argv[1]), sys.argv[2])
    destination = Path(sys.argv[3])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "registration.json").write_text(
        json.dumps(registration, sort_keys=True, indent=2) + "\n",
    )
    (destination / "signer-registration-request.json").write_text(
        json.dumps(signer, sort_keys=True, indent=2) + "\n",
    )
    print(json.dumps({
        "capability_id": PACKAGE_ID,
        "package_version": PACKAGE_VERSION,
        "artifact_sha256": registration["descriptor"]["artifact"]["sha256"],
        "registration_sha256": hashlib.sha256(
            (destination / "registration.json").read_bytes(),
        ).hexdigest(),
    }, sort_keys=True))
