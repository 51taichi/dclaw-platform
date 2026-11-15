"""Run a declared FFmpeg argv against task-scoped files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


INPUT = re.compile(r"\{input:([a-z][a-z0-9_]{0,63})\}")
OUTPUT = re.compile(r"\{output:([A-Za-z0-9][A-Za-z0-9._-]{0,127})\}")
OUTPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RESERVED_OUTPUTS = {
    "input.json", "continuation.json", "result.json", "checkpoint.json",
    "task-state.json", "capability.id", "agent.name", "stdout.log", "stderr.log",
}


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("task path escapes task root")
    return candidate


def execute(task_root: Path, ffmpeg: Path) -> dict:
    request = json.loads((task_root / "input.json").read_text(encoding="utf-8"))
    arguments = request.get("arguments")
    output_files = request.get("output_files")
    if (
        not isinstance(arguments, list) or not 1 <= len(arguments) <= 128
        or any(not isinstance(item, str) or not item or len(item) > 2048 for item in arguments)
        or not isinstance(output_files, list) or not 1 <= len(output_files) <= 8
        or any(not isinstance(item, str) or not OUTPUT_NAME.fullmatch(item) for item in output_files)
        or len(output_files) != len(set(output_files))
        or any(item.lower() in RESERVED_OUTPUTS for item in output_files)
    ):
        raise ValueError("invalid FFmpeg task input")
    if not ffmpeg.is_file():
        raise FileNotFoundError("registered FFmpeg executable is unavailable")

    used_inputs: set[str] = set()
    used_outputs: set[str] = set()
    expanded: list[str] = []
    for index, argument in enumerate(arguments):
        input_match = INPUT.fullmatch(argument)
        output_match = OUTPUT.fullmatch(argument)
        if input_match:
            slot = input_match.group(1)
            relative = request.get(slot)
            if not isinstance(relative, str):
                raise ValueError("input slot is not bound")
            path = _inside(task_root, relative)
            expected = (task_root / "res" / "bindings" / slot).resolve()
            if not path.is_relative_to(expected) or not path.is_file():
                raise ValueError("input slot is outside its binding")
            used_inputs.add(slot)
            expanded.append(str(path))
        elif output_match:
            name = output_match.group(1)
            if name not in output_files or name in used_outputs:
                raise ValueError("output is not declared once")
            used_outputs.add(name)
            expanded.append(str(_inside(task_root, name)))
        else:
            if (
                any(character in argument for character in ("\x00", "\r", "\n", "\\"))
                or ".." in argument or "://" in argument or "file:" in argument
                or argument.startswith(("/", "~", "file:", "pipe:"))
                or re.match(r"^[A-Za-z]:", argument)
                or re.search(r"(?:^|[=:])/[A-Za-z]", argument)
                or (index > 0 and arguments[index - 1] == "-i")
            ):
                raise ValueError("raw path or URL is not allowed")
            expanded.append(argument)
    if used_outputs != set(output_files):
        raise ValueError("declared output is missing from arguments")
    bound_slots = {
        key for key in request
        if key not in {"arguments", "output_files"}
    }
    if used_inputs != bound_slots:
        raise ValueError("input bindings do not match command")

    with (task_root / "res" / ".ffmpeg.stderr.log").open("wb") as error_log:
        completed = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y", *expanded],
            cwd=task_root, check=False, stdout=subprocess.DEVNULL,
            stderr=error_log, timeout=3600,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"FFmpeg exited with code {completed.returncode}")
    outputs = []
    for name in output_files:
        path = _inside(task_root, name)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("declared FFmpeg output is missing or empty")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        outputs.append({
            "name": name,
            "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        })
    result = {"outputs": outputs}
    (task_root / "result.json").write_text(
        json.dumps(result, sort_keys=True), encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--task-root":
        raise SystemExit(2)
    executable = os.environ.get("DCLAW_COMPONENT_FFMPEG")
    if not executable:
        raise SystemExit("registered FFmpeg component is unavailable")
    execute(Path(sys.argv[2]), Path(executable))
