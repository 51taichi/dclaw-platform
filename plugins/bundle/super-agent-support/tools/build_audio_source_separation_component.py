#!/usr/bin/env python3
"""Build the locked Windows audio source separation Component and capability."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from urllib.request import urlopen
import zipfile


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    PLUGIN_ROOT
    / "public_components"
    / "audio-source-separation"
    / "1.0.0"
)
COMPONENT_BASE_URL = (
    "https://dclaw.rouhigh.com/agent-artifacts/"
    "super-agent-components/v1/windows-x64"
)
CAPABILITY_BASE_URL = (
    "https://dclaw.rouhigh.com/agent-artifacts/"
    "super-agent-capabilities/v1/windows-x64"
)
FIXED_TIME = (2026, 10, 28, 0, 0, 0)


class BuildError(RuntimeError):
    """A locked build input or output is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"JSON root must be an object: {path}")
    return value


def _ensure_input(cache: Path, item: dict, download: bool) -> Path:
    destination = cache / item["filename"]
    if not destination.is_file() and download:
        cache.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        with urlopen(item["url"], timeout=120) as response, temporary.open(
            "wb",
        ) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        temporary.replace(destination)
    if not destination.is_file():
        raise BuildError(f"locked input is missing: {item['filename']}")
    if _sha256(destination) != item["sha256"]:
        raise BuildError(f"locked input digest mismatch: {item['filename']}")
    return destination


def _extract_wheel(path: Path, destination: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            pure = PurePosixPath(entry.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise BuildError(f"wheel path is unsafe: {entry.filename}")
            if entry.is_dir():
                continue
            target_parts = pure.parts
            for marker in ("purelib", "platlib"):
                if len(target_parts) >= 3 and target_parts[0].endswith(
                    ".data",
                ) and target_parts[1] == marker:
                    target_parts = target_parts[2:]
                    break
            target = destination.joinpath(*target_parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _extract_demucs(path: Path, destination: Path) -> None:
    prefix = PurePosixPath("demucs-4.0.1/demucs")
    license_name = PurePosixPath("demucs-4.0.1/LICENSE")
    license_written = False
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts:
                raise BuildError(f"sdist path is unsafe: {member.name}")
            if member.isfile() and pure == license_name:
                source = archive.extractfile(member)
                if source is None:
                    raise BuildError("Demucs license is unreadable")
                target = (
                    destination
                    / "demucs-4.0.1.dist-info"
                    / "licenses"
                    / "LICENSE"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                license_written = True
                continue
            if not member.isfile() or pure.parts[: len(prefix.parts)] != (
                prefix.parts
            ):
                continue
            relative = PurePosixPath(*pure.parts[len(prefix.parts) :])
            if not relative.parts:
                continue
            target = destination / "demucs" / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise BuildError(f"sdist member is unreadable: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if not license_written:
        raise BuildError("Demucs license is missing from the locked sdist")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy_package_sources(source: Path, destination: Path) -> None:
    source_files = sorted(
        path for path in source.rglob("*.py") if path.is_file()
    )
    if not source_files:
        raise BuildError("Component package source is empty")
    for path in source_files:
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _archive_tree(root: Path, output: Path) -> tuple[int, int]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    unpacked = sum(path.stat().st_size for path in files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output.stat().st_size, unpacked


def _spdx(lock: dict) -> dict:
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "dclaw-audio-source-separation-1.0.0-windows-x64",
        "documentNamespace": (
            "https://dclaw.rouhigh.com/sbom/public-components/"
            "audio-source-separation/1.0.0/windows-x64"
        ),
        "creationInfo": {
            "created": "2026-10-28T00:00:00Z",
            "creators": ["Organization: DClaw"],
        },
        "packages": [
            {
                "name": item["name"],
                "SPDXID": "SPDXRef-Package-" + str(index),
                "versionInfo": item["version"],
                "downloadLocation": item["url"],
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": item["sha256"],
                    },
                ],
                "licenseDeclared": item["license"],
                "licenseConcluded": item["license"],
                "filesAnalyzed": False,
                "copyrightText": "NOASSERTION",
            }
            for index, item in enumerate(lock["inputs"], 1)
        ],
    }


def _license_evidence(lock: dict) -> dict:
    return {
        "component_id": lock["component_id"],
        "component_version": lock["component_version"],
        "review_status": "approved-for-redistribution",
        "reviewed_at": "2026-10-28T00:00:00Z",
        "aggregate_spdx": "LicenseRef-DClaw-Audio-Separation-Third-Party",
        "packages": [
            {
                **{
                    key: item[key]
                    for key in (
                        "name",
                        "version",
                        "license",
                        "url",
                        "sha256",
                    )
                },
                "license_evidence": (
                    {
                        "kind": "embedded-dist-info",
                        "location": "python/*-dist-info/licenses/",
                    }
                    if item["kind"] == "wheel"
                    else {
                        "kind": "embedded-and-upstream",
                        "location": (
                            "python/demucs-4.0.1.dist-info/licenses/LICENSE"
                        ),
                        "url": (
                            "https://raw.githubusercontent.com/"
                            "facebookresearch/demucs/v4.0.1/LICENSE"
                        ),
                        "sha256": (
                            "cf9b17822d1fcd4ff32ccbe14183386fb3adf6f2ff92dc184130823f7fc28173"
                        ),
                    }
                ),
            }
            for item in lock["inputs"]
        ],
        "notes": (
            "The artifact redistributes unmodified wheels, Demucs source, and "
            "the fixed htdemucs model. License notices embedded in wheels are "
            "retained in their dist-info directories."
        ),
    }


def build(
    *,
    cache: Path,
    output_dir: Path,
    component_base_url: str,
    capability_base_url: str,
    download: bool,
) -> dict:
    lock = _json(SOURCE_ROOT / "component-lock.json")
    inputs = {
        item["filename"]: _ensure_input(cache, item, download)
        for item in lock["inputs"]
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="dclaw-audio-separation-build-",
    ) as temporary_value:
        stage = Path(temporary_value) / "component"
        python_root = stage / "python"
        model_root = stage / "models"
        python_root.mkdir(parents=True)
        model_root.mkdir(parents=True)
        for item in lock["inputs"]:
            path = inputs[item["filename"]]
            if item["kind"] == "wheel":
                _extract_wheel(path, python_root)
            elif item["kind"] == "sdist":
                _extract_demucs(path, python_root)
            elif item["kind"] == "model":
                shutil.copy2(path, model_root / path.name)
        _copy_package_sources(
            SOURCE_ROOT / "src" / "dclaw_audio_source_separation",
            python_root / "dclaw_audio_source_separation",
        )
        (model_root / "htdemucs.yaml").write_text(
            "models: ['955717e8']\n",
            encoding="ascii",
        )
        component_manifest = {
            "component_id": lock["component_id"],
            "component_version": lock["component_version"],
            "platform": lock["platform"],
            "engine": lock["engine"],
            "inputs": [
                {
                    "filename": item["filename"],
                    "sha256": item["sha256"],
                }
                for item in lock["inputs"]
            ],
        }
        _write_json(stage / "COMPONENT-MANIFEST.json", component_manifest)
        _write_json(stage / "LICENSES.json", _license_evidence(lock))
        artifact_name = (
            "audio-source-separation-windows-x64-1.0.0.zip"
        )
        artifact_path = output_dir / artifact_name
        artifact_size, unpacked_size = _archive_tree(stage, artifact_path)

    sbom_path = output_dir / "audio-source-separation-sbom.spdx.json"
    license_path = output_dir / "audio-source-separation-license-evidence.json"
    _write_json(sbom_path, _spdx(lock))
    _write_json(license_path, _license_evidence(lock))
    component_url = (
        component_base_url.rstrip("/")
        + "/audio-source-separation/1.0.0/"
    )
    descriptor = {
        "descriptor_version": "1",
        "component_id": "audio-source-separation",
        "display_name": "Audio Source Separation",
        "platform": "windows-x64",
        "component_version": "1.0.0",
        "status": "available",
        "provides": ["audio.source-separation", "audio.rms-snr"],
        "dependencies": [
            {"component_id": "python-runtime", "version": "3.12.14"},
            {
                "component_id": "ffmpeg",
                "version": "N-128100-gceb466cbcd",
            },
        ],
        "artifact": {
            "url": component_url + artifact_name,
            "sha256": _sha256(artifact_path),
            "size_bytes": artifact_size,
            "unpacked_size_bytes": unpacked_size,
            "archive_format": "zip",
        },
        "exports": {"python_root": "python", "model_root": "models"},
        "path_entries": [],
        "environment_paths": {"PYTHONPATH": ["python"]},
        "sbom": {
            "url": component_url + sbom_path.name,
            "sha256": _sha256(sbom_path),
        },
        "license": {
            "spdx": "LicenseRef-DClaw-Audio-Separation-Third-Party",
            "evidence_url": component_url + license_path.name,
            "evidence_sha256": _sha256(license_path),
        },
        "cache_key": "audio-source-separation/windows-x64/1.0.0",
        "rollback_version": "1.0.0",
        "notes": (
            "CPU voice/background separation and deterministic PCM16 RMS/SNR facts."
        ),
    }
    descriptor_path = output_dir / (
        "audio-source-separation-windows-x64-available.json"
    )
    _write_json(descriptor_path, descriptor)

    capability_stage = output_dir / ".capability-stage"
    if capability_stage.exists():
        shutil.rmtree(capability_stage)
    capability_stage.mkdir()
    for name in ("input", "result", "checkpoint"):
        shutil.copy2(
            SOURCE_ROOT / f"{name}.schema.json",
            capability_stage / f"{name}.schema.json",
        )
    capability_artifact_name = (
        "dclaw-audio-source-separation-capability-1.0.0.zip"
    )
    capability_artifact = output_dir / capability_artifact_name
    capability_size, _ = _archive_tree(
        capability_stage,
        capability_artifact,
    )
    shutil.rmtree(capability_stage)
    schemas = {}
    for name in ("input", "result", "checkpoint"):
        schema_path = SOURCE_ROOT / f"{name}.schema.json"
        schemas[name] = {
            "path": f"{name}.schema.json",
            "sha256": _sha256(schema_path),
            "document": _json(schema_path),
        }
    capability_url = (
        capability_base_url.rstrip("/")
        + "/dclaw-audio-source-separation/1.0.0/"
    )
    capability_descriptor = {
        "descriptor_version": "1",
        "contract_version": "1",
        "capability_id": "dclaw.audio.source-separation",
        "package_id": "dclaw.audio.source-separation.package",
        "package_version": "1.0.0",
        "implementation_status": "release",
        "min_runner_version": "1.3.0",
        "artifact": {
            "url": capability_url + capability_artifact_name,
            "sha256": _sha256(capability_artifact),
            "size_bytes": capability_size,
        },
        "entrypoint": {
            "component_id": "python-runtime",
            "export": "python",
            "arguments": ["-m", "dclaw_audio_source_separation"],
        },
        "public_components": [
            {"component_id": "python-runtime", "version": "3.12.14"},
            {
                "component_id": "audio-source-separation",
                "version": "1.0.0",
            },
        ],
        "component_exports": [
            {
                "environment_variable": (
                    "DCLAW_COMPONENT_AUDIO_SEPARATOR_MODEL_ROOT"
                ),
                "component_id": "audio-source-separation",
                "export": "model_root",
            },
        ],
        "schemas": schemas,
        "operating_systems": ["windows-x64"],
        "permissions": {
            "workspace": "task-only",
            "network_domains": [],
            "processes": ["python.exe", "ffmpeg.exe", "ffprobe.exe"],
            "browser": False,
        },
        "limits": {
            "max_runtime_seconds": 1800,
            "max_memory_mib": 8192,
            "max_disk_mib": 4096,
            "max_concurrency": 1,
            "max_output_bytes": 2147483648,
        },
        "semantics": {
            "idempotency": (
                "The same immutable input and fixed Component version produce "
                "the same named outputs within the documented numeric tolerance."
            ),
            "cancellation": (
                "Runner terminates the process tree and reports cancelled; a "
                "later retry removes abandoned temporary output directories."
            ),
            "recovery": (
                "Retry from the original read-only binding; no partial output "
                "directory is promoted."
            ),
            "cleanup": (
                "Promote only voice.wav and background.wav; remove temporary "
                "directories on normal completion or handled failure."
            ),
        },
    }
    capability_descriptor_path = output_dir / (
        "dclaw-audio-source-separation-capability-descriptor.json"
    )
    _write_json(capability_descriptor_path, capability_descriptor)
    return {
        "status": "built",
        "component_artifact": str(artifact_path),
        "component_sha256": _sha256(artifact_path),
        "component_size_bytes": artifact_size,
        "component_descriptor": str(descriptor_path),
        "capability_artifact": str(capability_artifact),
        "capability_sha256": _sha256(capability_artifact),
        "capability_descriptor": str(capability_descriptor_path),
        "sbom": str(sbom_path),
        "license_evidence": str(license_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--component-base-url", default=COMPONENT_BASE_URL)
    parser.add_argument("--capability-base-url", default=CAPABILITY_BASE_URL)
    args = parser.parse_args()
    try:
        result = build(
            cache=args.cache_dir,
            output_dir=args.output_dir,
            component_base_url=args.component_base_url,
            capability_base_url=args.capability_base_url,
            download=args.download,
        )
    except (BuildError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
