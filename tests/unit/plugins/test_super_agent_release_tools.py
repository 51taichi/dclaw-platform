# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import zipfile

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).parents[3]
TOOLS = ROOT / "plugins" / "bundle" / "super-agent-support" / "tools"


def _module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_sandbox_compose_keeps_existing_server_settings(tmp_path):
    module = _module(
        "support_public_sandbox_compose", "configure_public_sandbox.py",
    )
    working = tmp_path / "working"
    for name in (
        "plugins/dclaw.super-agent-support", "sealed_agents",
        "workspace_runtime_state", "super-agent-sandbox",
    ):
        (working / name).mkdir(parents=True)
    compose = tmp_path / "compose.yaml"
    original = {
        "services": {"dclaw-server": {
            "image": "dclaw-server:base", "network_mode": "bridge",
            "environment": {"AUTH_PASSWORD": "keep-existing-value"},
            "volumes": ["/host/data:/app/working"],
        }},
    }
    compose.write_text(yaml.safe_dump(original), encoding="utf-8")
    backup = tmp_path / "compose.backup.yaml"
    module.configure(
        compose, backup_path=backup,
        sandbox_image="dclaw-server:sandbox", working_host_path=working,
    )
    assert yaml.safe_load(backup.read_text()) == original
    updated = yaml.safe_load(compose.read_text())
    server = updated["services"]["dclaw-server"]
    assert server["environment"] == {
        "AUTH_PASSWORD": "keep-existing-value",
        "DCLAW_SUPER_AGENT_SANDBOX_SOCKET": module.SOCKET,
    }
    assert server["image"] == "dclaw-server:base"
    assert server["volumes"] == ["/host/data:/app/working"]
    sandbox = updated["services"][module.SERVICE]
    assert sandbox["network_mode"] == "none"
    assert sandbox["read_only"] is True
    assert sandbox["cap_add"] == ["SYS_ADMIN"]
    assert all(volume.endswith(":ro") for volume in sandbox["volumes"][:2])
    assert sandbox["volumes"][0] == f"{working}/plugins:/app/working/plugins:ro"


def test_standalone_plugin_release_contains_canonical_standard(
    tmp_path,
    monkeypatch,
):
    release = _module("support_plugin_release", "build_plugin_release.py")
    plugin_root = ROOT / "plugins" / "bundle" / "super-agent-support"
    standard_path = ROOT / "docs" / "super-agent-development-standard-v1.zh-CN.md"

    def working_tree_git_bytes(*args):
        if args[0] == "show":
            return standard_path.read_bytes()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(plugin_root.rglob("*")):
                if path.is_file() and not {
                    "__pycache__", "bin", "obj"
                }.intersection(path.relative_to(plugin_root).parts):
                    archive.write(
                        path,
                        (
                            "super-agent-support/"
                            + path.relative_to(plugin_root).as_posix()
                        ),
                    )
        return output.getvalue()

    monkeypatch.setattr(release, "_git_bytes", working_tree_git_bytes)
    output = tmp_path / "support-plugin.zip"
    helper = tmp_path / "DClaw.LocalHelper.exe"
    helper.write_bytes(b"MZ\x00signed-helper-fixture")
    metadata = release.build(output, windows_helper_binary=helper)
    assert metadata["plugin_version"] == "1.18.34"
    assert metadata["standard_version"] == "2.48"
    assert metadata["windows_helper_version"] == "1.4.5"
    with zipfile.ZipFile(output) as archive:
        standard = archive.read(release.STANDARD_IN_PLUGIN)
        assert b"2.35" in standard
        assert archive.read(release.HELPER_EXECUTABLE_IN_PLUGIN) == (
            helper.read_bytes()
        )
        helper_manifest = json.loads(
            archive.read(release.HELPER_MANIFEST_IN_PLUGIN),
        )
        assert helper_manifest == {
            "executable": "DClaw.LocalHelper.exe",
            "platform": "windows-x64",
            "protocol_version": "2",
            "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
            "size_bytes": len(helper.read_bytes()),
            "version": "1.4.5",
        }
        archive.extractall(tmp_path / "extracted")
    root = tmp_path / "extracted" / "super-agent-support"
    spec = importlib.util.spec_from_file_location(
        "standalone_pack_archive", root / "developer_pack" / "archive.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload, pack_metadata = module.build_archive(root)
    assert payload
    assert pack_metadata["standard"]["version"] == "2.48"


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def _release_archives():
    pack_version = "1.5.2"
    standard_version = "2.9"
    devkit_version = "1.4.1"
    prefix = f"dclaw-super-agent-developer-pack-{pack_version}"
    public_files = {
        "VERSION": (pack_version + "\n").encode(),
        "devkit/VERSION": (devkit_version + "\n").encode(),
        "standard/super-agent-development-standard-v1.zh-CN.md": (
            f"当前版本：`{standard_version}`\n"
        ).encode(),
    }
    manifest = {
        "name": "dclaw-super-agent-developer-pack",
        "version": pack_version,
        "standard": {
            "id": "dclaw.super-agent-development",
            "version": standard_version,
        },
        "devkit_version": devkit_version,
        "files": [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(public_files.items())
        ],
    }
    pack_files = {
        **public_files,
        "PACKAGE-MANIFEST.json": json.dumps(manifest).encode(),
        "SHA256SUMS": b"",
    }
    pack = _zip({f"{prefix}/{name}": data for name, data in pack_files.items()})
    pack_metadata = {
        "name": "dclaw-super-agent-developer-pack",
        "version": pack_version,
        "standard": manifest["standard"],
        "devkit_version": devkit_version,
        "archive_prefix": prefix,
        "file_count": len(pack_files),
        "download_path": "/api/super-agent-support/developer-pack/download",
        "content_sha256": hashlib.sha256(pack).hexdigest(),
    }

    kit_prefix = f"dclaw-super-agent-devkit-{devkit_version}"
    wheel = b"locked-wheel"
    kit_files = {
        "VERSION": (devkit_version + "\n").encode(),
        "wheelhouse/example.whl": wheel,
        "CHECKSUMS.sha256": (
            hashlib.sha256(wheel).hexdigest()
            + "  wheelhouse/example.whl\n"
        ).encode(),
    }
    devkit = _zip(
        {f"{kit_prefix}/{name}": data for name, data in kit_files.items()},
    )
    devkit_metadata = {
        "name": "dclaw-super-agent-devkit",
        "version": devkit_version,
        "download_path": "/api/super-agent-support/developer-kit/v1.zip",
        "sha256": hashlib.sha256(devkit).hexdigest(),
    }
    return pack, pack_metadata, devkit, devkit_metadata


def test_sync_toolchain_creates_one_immutable_credential_free_release(
    tmp_path,
    monkeypatch,
):
    tool = _module(
        "sync_authenticated_toolchain_test",
        "sync_authenticated_toolchain.py",
    )
    pack, pack_metadata, devkit, devkit_metadata = _release_archives()
    token = "temporary-secret-token"
    base = "https://dclaw.example"
    support = base + "/api/super-agent-support"

    def fake_request(url, *, token=None, headers=None):
        if url == support + "/health" and token is None:
            return 401, {}, b'{"detail":"Not authenticated"}', url
        if url.endswith("/business-identities/verification-keys"):
            if headers and headers.get("If-None-Match") == '"keys"':
                return 304, {"ETag": '"keys"'}, b"", url
            return (
                200,
                {"ETag": '"keys"'},
                b'{"issuer":"https://issuer.example","keys":[]}',
                url,
            )
        assert token == "temporary-secret-token"
        if url == support + "/health":
            data = {"plugin": "dclaw.super-agent-support", "version": "1.10.2"}
        elif url == support + "/developer-pack":
            data = pack_metadata
        elif url == support + "/developer-kit":
            data = devkit_metadata
        else:
            raise AssertionError(url)
        return 200, {}, json.dumps(data).encode(), url

    def fake_download(url, target, *, token, base_url):
        assert token == "temporary-secret-token"
        assert base_url == base
        data = pack if url.endswith("/developer-pack/download") else devkit
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(tool, "_request_bytes", fake_request)
    monkeypatch.setattr(tool, "_download", fake_download)
    kwargs = {
        "base_url": base,
        "output_root": tmp_path,
        "token": token,
        "expected_plugin_version": "1.10.2",
        "expected_standard_version": "2.9",
        "expected_pack_version": "1.5.2",
        "expected_devkit_version": "1.4.1",
        "server_revision": "a" * 40,
        "client_revision": "b" * 40,
        "image_id": "sha256:" + "c" * 64,
    }

    created = tool.sync_toolchain(**kwargs)
    reused = tool.sync_toolchain(**kwargs)

    release = Path(created["path"])
    assert created["status"] == "created"
    assert reused["status"] == "reused"
    assert stat.S_IMODE(release.stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o444
        for path in release.iterdir()
        if path.is_file()
    )
    combined = b"".join(
        path.read_bytes() for path in release.iterdir() if path.is_file()
    )
    assert token.encode() not in combined
    receipt = json.loads((release / "production-receipt.json").read_text())
    assert receipt["source"]["contains_credentials"] is False
    assert receipt["contracts"] == {
        "developer_pack_version": "1.5.2",
        "devkit_version": "1.4.1",
        "standard_version": "2.9",
        "support_plugin_version": "1.10.2",
    }


def test_toolchain_archive_rejects_platform_metadata(tmp_path):
    tool = _module("sync_archive_rejection_test", "sync_authenticated_toolchain.py")
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("root/._contract.json", b"metadata")
    with zipfile.ZipFile(path) as archive:
        with pytest.raises(tool.ToolchainSyncError, match="platform metadata"):
            tool._safe_archive(archive, "test")


def test_plugin_archive_embeds_current_standard_and_is_reproducible(tmp_path):
    tool = _module("build_plugin_archive_test", "build_plugin_archive.py")
    plugin_root = ROOT / "plugins" / "bundle" / "super-agent-support"
    standard = ROOT / "docs" / "super-agent-development-standard-v1.zh-CN.md"
    helper = tmp_path / "DClaw.LocalHelper.exe"
    helper.write_bytes(b"MZ\x00hot-install-helper-fixture")

    first, metadata = tool.build_archive(
        plugin_root,
        standard,
        windows_helper_binary=helper,
    )
    second, repeated = tool.build_archive(
        plugin_root,
        standard,
        windows_helper_binary=helper,
    )

    assert first == second
    assert metadata == repeated
    assert metadata["plugin_id"] == "dclaw.super-agent-support"
    assert metadata["version"] == "1.18.34"
    assert metadata["windows_helper_version"] == "1.4.5"
    assert metadata["sha256"] == hashlib.sha256(first).hexdigest()
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = set(archive.namelist())
        embedded = archive.read(metadata["standard_path"])
        packaged_helper = archive.read(
            tool.HELPER_EXECUTABLE_PATH.as_posix(),
        )
        helper_manifest = json.loads(
            archive.read(tool.HELPER_MANIFEST_PATH.as_posix()),
        )
        helper_project = archive.read(
            "windows-helper/DClaw.LocalHelper.csproj",
        )
        helper_program = archive.read(
            "windows-helper/Program.cs",
        )
    assert embedded == standard.read_bytes()
    assert "plugin.json" in names
    assert "windows-helper/LocalAssistantUi.cs" in names
    assert "windows-helper/Assets/DClaw-Bot-icon.png" in names
    assert "windows-helper/TaskHistory.cs" in names
    assert b"<OutputType>WinExe</OutputType>" in helper_project
    assert b"LocalAssistantUi.Run" in helper_program
    assert packaged_helper == helper.read_bytes()
    assert helper_manifest["sha256"] == hashlib.sha256(
        helper.read_bytes(),
    ).hexdigest()
    assert not any(
        "__pycache__" in name
        or "/bin/" in name
        or "/obj/" in name
        or name.endswith(".pyc")
        for name in names
    )


def test_component_signer_trust_tool_is_atomic_and_idempotent(tmp_path):
    tool = _module(
        "manage_component_signers_test",
        "manage_component_signers.py",
    )
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_path = tmp_path / "component-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )
    state_dir = tmp_path / "state"

    first = tool.set_signer(
        state_dir,
        "official-components",
        public_key_path,
    )
    second = tool.set_signer(
        state_dir,
        "official-components",
        public_key_path,
    )
    listed = tool.list_signers(state_dir)
    removed = tool.remove_signer(state_dir, "official-components")

    assert first["status"] == "updated"
    assert second["status"] == "unchanged"
    assert listed == {
        "trusted_signer_ids": ["official-components"],
        "count": 1,
    }
    assert removed["status"] == "removed"
    assert tool.list_signers(state_dir)["count"] == 0
    assert (state_dir / tool.TRUST_FILENAME).stat().st_mode & 0o777 == 0o600


def test_register_super_expert_signer_is_atomic_and_idempotent(tmp_path):
    tool = _module(
        "register_super_expert_signer_test",
        "register_super_expert_signer.py",
    )
    public = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    encoded = base64.b64encode(public).decode("ascii")
    fingerprint = hashlib.sha256(public).hexdigest()

    first = tool.register_signer(
        sealed_root=tmp_path,
        signer_id="agent-release-v1",
        public_key_base64=encoded,
        expected_fingerprint=fingerprint,
    )
    second = tool.register_signer(
        sealed_root=tmp_path,
        signer_id="agent-release-v1",
        public_key_base64=encoded,
        expected_fingerprint=fingerprint,
    )

    assert first["status"] == "registered"
    assert set(first["changed_registries"]) == {
        "trusted_signers.json",
        "official_super_expert_signers.json",
    }
    assert second["status"] == "already-registered"
    for name in tool.REGISTRIES:
        registry = json.loads((tmp_path / name).read_text())
        assert registry["signers"] == {"agent-release-v1": encoded}
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o644


def test_register_super_expert_signer_rejects_conflict(tmp_path):
    tool = _module(
        "register_super_expert_signer_conflict",
        "register_super_expert_signer.py",
    )
    first = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    second = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    registry = {"signers": {"agent-release-v1": base64.b64encode(first).decode()}}
    (tmp_path / "trusted_signers.json").write_text(json.dumps(registry))

    with pytest.raises(tool.SignerRegistrationError, match="conflicts"):
        tool.register_signer(
            sealed_root=tmp_path,
            signer_id="agent-release-v1",
            public_key_base64=base64.b64encode(second).decode(),
            expected_fingerprint=hashlib.sha256(second).hexdigest(),
        )

    assert json.loads((tmp_path / "trusted_signers.json").read_text()) == registry
    assert not (tmp_path / "official_super_expert_signers.json").exists()
