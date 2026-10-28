"""Path, numeric, and result helpers independent from the inference engine."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any


RMS_FLOOR_DB = -160.0
MAX_INPUT_BYTES = 536_870_912
MAX_DURATION_SECONDS = 600.0
OUTPUT_SAMPLE_RATE = 44_100
OUTPUT_CHANNELS = 2


class CapabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def task_path(
    task_root: Path,
    relative: str,
    *,
    required_prefix: str,
) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CapabilityError(
            "AUDIO_SEPARATION.INPUT_INVALID",
            "relative path is required",
        )
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise CapabilityError(
            "AUDIO_SEPARATION.PATH_OUTSIDE_TASK",
            "path must remain inside the task root",
        )
    normalized = pure.as_posix()
    prefix = required_prefix.rstrip("/") + "/"
    if normalized != required_prefix.rstrip("/") and not normalized.startswith(
        prefix,
    ):
        raise CapabilityError(
            "AUDIO_SEPARATION.PATH_OUTSIDE_TASK",
            f"path must be inside {required_prefix}",
        )
    root = task_root.resolve()
    resolved = (root / Path(*pure.parts)).resolve()
    if root != resolved and root not in resolved.parents:
        raise CapabilityError(
            "AUDIO_SEPARATION.PATH_OUTSIDE_TASK",
            "resolved path escapes the task root",
        )
    return resolved


def finite_db(value: float) -> float:
    if not math.isfinite(value):
        raise CapabilityError(
            "AUDIO_SEPARATION.NUMERIC_INVALID",
            "audio energy is not finite",
        )
    return round(value, 6)


def rms_db_from_pcm16(samples: Any) -> float:
    count = int(samples.size)
    if count == 0:
        return RMS_FLOOR_DB
    normalized = samples.astype("float64") / 32768.0
    squared_mean = float((normalized * normalized).mean())
    if not math.isfinite(squared_mean) or squared_mean < 0:
        raise CapabilityError(
            "AUDIO_SEPARATION.NUMERIC_INVALID",
            "audio energy is not finite",
        )
    if squared_mean == 0:
        return RMS_FLOOR_DB
    return finite_db(20.0 * math.log10(math.sqrt(squared_mean)))


def write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".tmp-",
        delete=False,
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)
