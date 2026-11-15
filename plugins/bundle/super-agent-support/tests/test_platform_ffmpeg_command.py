"""Regression tests for the platform-owned FFmpeg command package."""

from __future__ import annotations

import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1] / "platform_capabilities" / "ffmpeg-command" / "0.1.0"
SPEC = importlib.util.spec_from_file_location("platform_ffmpeg_runner", ROOT / "runner.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _task(tmp_path: Path, arguments: list[str], *, bound: bool = True) -> Path:
    root = tmp_path / "task"
    source = root / "res" / "bindings" / "clip_01" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"input")
    request = {"arguments": arguments, "output_files": ["final.mp4"]}
    if bound:
        request["clip_01"] = "res/bindings/clip_01/source.mp4"
    (root / "input.json").write_text(json.dumps(request))
    return root


def _fake_ffmpeg(tmp_path: Path) -> Path:
    executable = tmp_path / "ffmpeg"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib,sys\n"
        "pathlib.Path(sys.argv[-1]).write_bytes(b'finished')\n",
    )
    executable.chmod(0o755)
    return executable


def test_bound_command_produces_schema_valid_result(tmp_path):
    root = _task(tmp_path, ["-i", "{input:clip_01}", "-c:v", "copy", "{output:final.mp4}"])
    result = runner.execute(root, _fake_ffmpeg(tmp_path))
    schema = json.loads((ROOT / "result.schema.json").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(result))
    assert result["outputs"][0]["size_bytes"] == 8
    assert (root / "final.mp4").read_bytes() == b"finished"


@pytest.mark.parametrize("argument", [
    "https://example.test/video.mp4", "C:\\private\\video.mp4", "../private.mp4",
    "/tmp/video.mp4", "file:secret.mp4", "pipe:1",
])
def test_raw_path_or_url_is_rejected(tmp_path, argument):
    root = _task(tmp_path, ["-i", "{input:clip_01}", argument, "{output:final.mp4}"])
    with pytest.raises(ValueError, match="raw path or URL"):
        runner.execute(root, _fake_ffmpeg(tmp_path))


def test_unbound_input_is_rejected(tmp_path):
    root = _task(tmp_path, ["-i", "{input:clip_01}", "{output:final.mp4}"], bound=False)
    with pytest.raises(ValueError, match="input slot is not bound"):
        runner.execute(root, _fake_ffmpeg(tmp_path))


def test_task_control_file_cannot_be_declared_as_output(tmp_path):
    root = _task(tmp_path, ["-i", "{input:clip_01}", "{output:result.json}"])
    request = json.loads((root / "input.json").read_text())
    request["output_files"] = ["result.json"]
    (root / "input.json").write_text(json.dumps(request))
    with pytest.raises(ValueError, match="invalid FFmpeg task input"):
        runner.execute(root, _fake_ffmpeg(tmp_path))


def test_no_shell_interpolation(tmp_path):
    root = _task(tmp_path, ["-i", "{input:clip_01}", "$(touch injected)", "{output:final.mp4}"])
    runner.execute(root, _fake_ffmpeg(tmp_path))
    assert not (root / "injected").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is unavailable")
def test_real_ffmpeg_combines_two_small_bound_videos(tmp_path):
    ffmpeg = Path(shutil.which("ffmpeg"))
    root = tmp_path / "task"
    for index, color in enumerate(("red", "blue"), start=1):
        slot = f"clip_{index:02d}"
        path = root / "res" / "bindings" / slot / f"{slot}.mp4"
        path.parent.mkdir(parents=True)
        subprocess.run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=5",
            "-t", "1", "-c:v", "mpeg4", str(path),
        ], check=True)
    request = {
        "arguments": [
            "-i", "{input:clip_01}", "-i", "{input:clip_02}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "mpeg4", "{output:final.mp4}",
        ],
        "output_files": ["final.mp4"],
        "clip_01": "res/bindings/clip_01/clip_01.mp4",
        "clip_02": "res/bindings/clip_02/clip_02.mp4",
    }
    (root / "input.json").write_text(json.dumps(request))
    result = runner.execute(root, ffmpeg)
    assert result["outputs"][0]["size_bytes"] > 0
    assert result["outputs"][0]["sha256"] == hashlib.sha256(
        (root / "final.mp4").read_bytes(),
    ).hexdigest()


def test_artifact_is_reproducible(tmp_path):
    spec = importlib.util.spec_from_file_location("ffmpeg_build", ROOT / "build_artifact.py")
    assert spec and spec.loader
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    assert build.build(first) == build.build(second)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == (ROOT / "artifact.zip").read_bytes()


def test_platform_registration_is_signed_and_matches_artifact():
    registration = json.loads((ROOT / "registration.json").read_text())
    signer = json.loads((ROOT / "signer-registration-request.json").read_text())
    descriptor = registration["descriptor"]
    schema = json.loads((ROOT.parents[2] / "schemas" / "capability-descriptor.schema.json").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(descriptor))
    assert registration["signer_id"] == signer["signer_id"]
    canonical = json.dumps(
        descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    Ed25519PublicKey.from_public_bytes(
        base64.b64decode(signer["public_key"]),
    ).verify(base64.b64decode(registration["signature"]), canonical)
    assert descriptor["artifact"]["sha256"] == hashlib.sha256(
        (ROOT / "artifact.zip").read_bytes(),
    ).hexdigest()
    for name, declaration in descriptor["schemas"].items():
        assert declaration["sha256"] == hashlib.sha256(
            (ROOT / f"{name}.schema.json").read_bytes(),
        ).hexdigest()
    devkit = ROOT.parents[2] / "devkit/schemas/local-ffmpeg-command-v1"
    for name in ("input.schema.json", "result.schema.json"):
        assert (ROOT / name).read_bytes() == (devkit / name).read_bytes()
    catalog = json.loads((ROOT.parents[2] / "devkit/operation-catalog.json").read_text())
    entry = catalog["local_task_host"]["platform_ffmpeg_command"]
    assert (entry["capability_id"], entry["package_version"]) == (
        descriptor["capability_id"], descriptor["package_version"],
    )
