from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tarfile

import numpy as np
import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"
COMPONENT_ROOT = (
    PLUGIN_ROOT
    / "public_components"
    / "audio-source-separation"
    / "1.0.0"
)


def _contract_module():
    path = (
        COMPONENT_ROOT
        / "src"
        / "dclaw_audio_source_separation"
        / "contract.py"
    )
    spec = importlib.util.spec_from_file_location(
        "dclaw_audio_source_separation_contract_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder_module():
    path = PLUGIN_ROOT / "tools" / "build_audio_source_separation_component.py"
    spec = importlib.util.spec_from_file_location(
        "dclaw_audio_source_separation_builder_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audio_source_separation_schemas_and_locked_inputs_are_valid():
    for name in ("input", "result", "checkpoint"):
        schema = json.loads(
            (COMPONENT_ROOT / f"{name}.schema.json").read_text(
                encoding="utf-8",
            ),
        )
        Draft202012Validator.check_schema(schema)

    lock = json.loads(
        (COMPONENT_ROOT / "component-lock.json").read_text(encoding="utf-8"),
    )
    assert lock["component_id"] == "audio-source-separation"
    assert lock["component_version"] == "1.0.0"
    assert lock["platform"] == "windows-x64"
    filenames = [item["filename"] for item in lock["inputs"]]
    assert len(filenames) == len(set(filenames))
    assert "955717e8-8726e21a.th" in filenames
    for item in lock["inputs"]:
        assert item["url"].startswith("https://")
        assert len(item["sha256"]) == 64
        int(item["sha256"], 16)
        assert item["license"]


def test_component_builder_copies_only_python_sources(tmp_path):
    builder = _builder_module()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (source / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "nested" / "module.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "module.pyc").write_bytes(b"cache")
    (source / ".DS_Store").write_bytes(b"metadata")
    (source / "notes.txt").write_text("temporary", encoding="utf-8")

    builder._copy_package_sources(source, destination)

    assert sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    ) == ["__init__.py", "nested/module.py"]


def test_demucs_extraction_retains_the_locked_license(tmp_path):
    builder = _builder_module()
    archive_path = tmp_path / "demucs-4.0.1.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, payload in (
            ("demucs-4.0.1/LICENSE", b"MIT license text\n"),
            ("demucs-4.0.1/demucs/__init__.py", b"VERSION = '4.0.1'\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    destination = tmp_path / "python"
    builder._extract_demucs(archive_path, destination)

    assert (destination / "demucs" / "__init__.py").is_file()
    assert (
        destination
        / "demucs-4.0.1.dist-info"
        / "licenses"
        / "LICENSE"
    ).read_bytes() == b"MIT license text\n"


def test_task_paths_are_confined_to_read_only_bindings_and_res(tmp_path):
    contract = _contract_module()
    task_root = tmp_path / "task"
    bound = task_root / "res" / "bindings" / "voice" / "sample.wav"
    bound.parent.mkdir(parents=True)
    bound.write_bytes(b"sample")

    assert contract.task_path(
        task_root,
        "res/bindings/voice/sample.wav",
        required_prefix="res/bindings",
    ) == bound.resolve()
    with pytest.raises(contract.CapabilityError) as escaped:
        contract.task_path(
            task_root,
            "res/bindings/../../secret.txt",
            required_prefix="res/bindings",
        )
    assert escaped.value.code == "AUDIO_SEPARATION.PATH_OUTSIDE_TASK"
    with pytest.raises(contract.CapabilityError):
        contract.task_path(
            task_root,
            "/absolute.wav",
            required_prefix="res/bindings",
        )


def test_pcm16_rms_is_finite_and_has_a_fixed_silence_floor():
    contract = _contract_module()
    silence = np.zeros((1024, 2), dtype=np.int16)
    assert contract.rms_db_from_pcm16(silence) == -160.0

    half_scale = np.full((1024, 2), 16384, dtype=np.int16)
    assert contract.rms_db_from_pcm16(half_scale) == pytest.approx(
        -6.0206,
        abs=1e-5,
    )


def test_component_export_schema_requires_scoped_environment_names():
    schema = json.loads(
        (
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json"
        ).read_text(encoding="utf-8"),
    )
    export_schema = dict(schema["properties"]["component_exports"])
    export_schema["$defs"] = schema["$defs"]
    validator = Draft202012Validator(export_schema)
    validator.validate(
        [
            {
                "environment_variable": (
                    "DCLAW_COMPONENT_AUDIO_SEPARATOR_MODEL_ROOT"
                ),
                "component_id": "audio-source-separation",
                "export": "model_root",
            },
        ],
    )
    assert list(
        validator.iter_errors(
            [
                {
                    "environment_variable": "MODEL_ROOT",
                    "component_id": "audio-source-separation",
                    "export": "model_root",
                },
            ],
        ),
    )
