"""Local faster-whisper transcription boundary."""

from __future__ import annotations

from typing import Any

import numpy as np


class FasterWhisperTranscriber:
    """Load one local Whisper model and expose a small synchronous API."""

    def __init__(
        self,
        *,
        model: str,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        # Keep the heavyweight optional dependency outside the protocol/core tests.
        from faster_whisper import WhisperModel

        self._model: Any = WhisperModel(
            model,
            device=device,
            compute_type=compute_type,
        )

    def transcribe(self, samples: np.ndarray) -> str:
        segments, _ = self._model.transcribe(
            samples,
            language="zh",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return "".join(segment.text for segment in segments).strip()
