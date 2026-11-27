"""DClaw task entrypoint for voice/background source separation."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import wave

from .contract import (
    CapabilityError,
    MAX_DURATION_SECONDS,
    MAX_INPUT_BYTES,
    OUTPUT_CHANNELS,
    OUTPUT_SAMPLE_RATE,
    finite_db,
    rms_db_from_pcm16,
    task_path,
    write_json_atomically,
)


def _audio_metadata(path: Path) -> dict:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels:format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = json.loads(completed.stdout)
        stream = value["streams"][0]
        duration = float(value["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise CapabilityError(
            "AUDIO_SEPARATION.UNSUPPORTED_AUDIO",
            "audio metadata is incomplete",
        ) from None
    except (OSError, subprocess.SubprocessError):
        raise CapabilityError(
            "AUDIO_SEPARATION.UNSUPPORTED_AUDIO",
            "ffprobe could not inspect the input",
        ) from None
    if not math.isfinite(duration) or duration <= 0:
        raise CapabilityError(
            "AUDIO_SEPARATION.UNSUPPORTED_AUDIO",
            "audio duration is invalid",
        )
    if duration > MAX_DURATION_SECONDS:
        raise CapabilityError(
            "AUDIO_SEPARATION.DURATION_LIMIT",
            "audio duration exceeds 600 seconds",
        )
    if sample_rate <= 0 or channels <= 0:
        raise CapabilityError(
            "AUDIO_SEPARATION.UNSUPPORTED_AUDIO",
            "audio stream is invalid",
        )
    return {
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
    }


def _load_model(model_root: Path):
    try:
        import torch
        from demucs.pretrained import get_model

        torch.manual_seed(0)
        torch.set_num_threads(1)
        model = get_model("htdemucs", repo=model_root)
        model.cpu()
        model.eval()
        return model
    except Exception as exc:
        raise CapabilityError(
            "AUDIO_SEPARATION.MODEL_UNAVAILABLE",
            f"fixed source-separation model could not load: {type(exc).__name__}",
        ) from exc


def _separate(input_path: Path, model_root: Path):
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.audio import AudioFile

        model = _load_model(model_root)
        wav = AudioFile(input_path).read(
            streams=0,
            samplerate=model.samplerate,
            channels=model.audio_channels,
        ).contiguous()
        if wav.numel() == 0:
            raise CapabilityError(
                "AUDIO_SEPARATION.UNSUPPORTED_AUDIO",
                "decoded audio is empty",
            )
        reference = wav.mean(0)
        reference_mean = reference.mean()
        reference_std = reference.std()
        if not torch.isfinite(reference_mean) or not torch.isfinite(reference_std):
            raise CapabilityError(
                "AUDIO_SEPARATION.NUMERIC_INVALID",
                "decoded audio is not finite",
            )
        if float(reference_std) <= 1e-8:
            silence = torch.zeros_like(wav)
            return silence, silence, model.samplerate
        normalized = (wav - reference_mean) / reference_std
        with torch.inference_mode():
            sources = apply_model(
                model,
                normalized[None],
                device="cpu",
                shifts=0,
                split=True,
                overlap=0.25,
                progress=False,
                num_workers=0,
            )[0]
        sources = sources * reference_std + reference_mean
        if not torch.isfinite(sources).all():
            raise CapabilityError(
                "AUDIO_SEPARATION.NUMERIC_INVALID",
                "separated audio is not finite",
            )
        vocals_index = model.sources.index("vocals")
        voice = sources[vocals_index]
        background = torch.zeros_like(voice)
        for index, source in enumerate(sources):
            if index != vocals_index:
                background += source
        return voice, background, model.samplerate
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(
            "AUDIO_SEPARATION.SEPARATION_FAILED",
            f"source separation failed: {type(exc).__name__}",
        ) from exc


def _write_pcm16(path: Path, audio, sample_rate: int):
    import numpy as np
    import torch

    if audio.ndim != 2:
        raise CapabilityError(
            "AUDIO_SEPARATION.NUMERIC_INVALID",
            "separated audio shape is invalid",
        )
    if audio.shape[0] == 1:
        audio = audio.expand(OUTPUT_CHANNELS, -1)
    elif audio.shape[0] != OUTPUT_CHANNELS:
        audio = audio[:OUTPUT_CHANNELS]
    pcm = (
        torch.clamp(audio, -1.0, 1.0)
        .mul(32767.0)
        .round()
        .to(torch.int16)
        .transpose(0, 1)
        .contiguous()
        .cpu()
        .numpy()
    )
    if not np.isfinite(pcm).all():
        raise CapabilityError(
            "AUDIO_SEPARATION.NUMERIC_INVALID",
            "PCM output is not finite",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(OUTPUT_CHANNELS)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes(order="C"))
    return pcm


def _execute(task_root: Path, task_input: dict) -> dict:
    input_path = task_path(
        task_root,
        task_input.get("input_path"),
        required_prefix="res/bindings",
    )
    if not input_path.is_file():
        raise CapabilityError(
            "AUDIO_SEPARATION.INPUT_NOT_BOUND",
            "bound input file does not exist",
        )
    if input_path.stat().st_size > MAX_INPUT_BYTES:
        raise CapabilityError(
            "AUDIO_SEPARATION.INPUT_TOO_LARGE",
            "input exceeds 512 MiB",
        )
    output_relative = task_input.get("output_directory", "res/separation")
    output_root = task_path(
        task_root,
        output_relative,
        required_prefix="res",
    )
    if "bindings" in Path(output_relative).parts[:2]:
        raise CapabilityError(
            "AUDIO_SEPARATION.PATH_OUTSIDE_TASK",
            "output cannot overwrite read-only bindings",
        )
    metadata = _audio_metadata(input_path)
    model_value = os.environ.get(
        "DCLAW_COMPONENT_AUDIO_SEPARATOR_MODEL_ROOT",
    )
    if not model_value:
        raise CapabilityError(
            "AUDIO_SEPARATION.MODEL_UNAVAILABLE",
            "signed model export is not bound",
        )
    model_root = Path(model_value).resolve()
    if not model_root.is_dir():
        raise CapabilityError(
            "AUDIO_SEPARATION.MODEL_UNAVAILABLE",
            "signed model root does not exist",
        )
    temporary = output_root.parent / (
        output_root.name + ".tmp-" + uuid.uuid4().hex
    )
    try:
        voice, background, sample_rate = _separate(input_path, model_root)
        voice_pcm = _write_pcm16(temporary / "voice.wav", voice, sample_rate)
        background_pcm = _write_pcm16(
            temporary / "background.wav",
            background,
            sample_rate,
        )
        voice_db = rms_db_from_pcm16(voice_pcm)
        background_db = rms_db_from_pcm16(background_pcm)
        snr_db = finite_db(voice_db - background_db)
        if output_root.exists():
            shutil.rmtree(output_root)
        temporary.replace(output_root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    duration = voice_pcm.shape[0] / float(sample_rate)
    return {
        "status": "succeeded",
        "voice_track_relative_path": (
            output_root.relative_to(task_root).as_posix() + "/voice.wav"
        ),
        "background_track_relative_path": (
            output_root.relative_to(task_root).as_posix() + "/background.wav"
        ),
        "voice_rms_db": voice_db,
        "background_rms_db": background_db,
        "snr_db": snr_db,
        "duration_seconds": round(duration, 6),
        "sample_rate": int(sample_rate),
        "channels": OUTPUT_CHANNELS,
        "input_duration_seconds": round(metadata["duration_seconds"], 6),
        "input_sample_rate": metadata["sample_rate"],
        "input_channels": metadata["channels"],
        "engine": "demucs-4.0.1-htdemucs",
        "rms_algorithm": "pcm16-interleaved-all-channels-dbfs-floor--160",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--continue", dest="continuation", action="store_true")
    args = parser.parse_args()
    task_root = args.task_root.resolve()
    result_path = task_root / "result.json"
    try:
        task_input = json.loads((task_root / "input.json").read_text("utf-8"))
        if not isinstance(task_input, dict):
            raise CapabilityError(
                "AUDIO_SEPARATION.INPUT_INVALID",
                "input root must be an object",
            )
        result = _execute(task_root, task_input)
    except CapabilityError as exc:
        result = {
            "status": "failed",
            "error": {"code": exc.code, "message": str(exc)},
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {
            "status": "failed",
            "error": {
                "code": "AUDIO_SEPARATION.INPUT_INVALID",
                "message": type(exc).__name__,
            },
        }
    write_json_atomically(result_path, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
