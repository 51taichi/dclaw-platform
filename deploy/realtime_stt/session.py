"""Bounded, in-memory streaming transcription sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


class RealtimeSttProtocolError(ValueError):
    """Raised when a client violates the PCM streaming contract."""


class AudioTranscriber(Protocol):
    """Synchronous model boundary executed away from the event loop."""

    def transcribe(self, samples: np.ndarray) -> str: ...


def _is_cjk(character: str) -> bool:
    return "\u3400" <= character <= "\u9fff"


@dataclass
class StreamingTranscript:
    """Merge overlapping window hypotheses into one accumulated result."""

    text: str = ""

    def merge(self, hypothesis: str) -> str:
        candidate = " ".join(str(hypothesis or "").strip().split())
        if not candidate:
            return self.text
        if not self.text:
            self.text = candidate
            return self.text

        max_overlap = min(len(self.text), len(candidate))
        overlap = 0
        for size in range(max_overlap, 0, -1):
            if self.text.endswith(candidate[:size]):
                overlap = size
                break
        if overlap:
            self.text += candidate[overlap:]
        elif _is_cjk(self.text[-1]) and _is_cjk(candidate[0]):
            self.text += candidate
        else:
            self.text += f" {candidate}"
        return self.text


@dataclass
class StreamingSession:
    """Own one ephemeral PCM buffer and accumulated transcript."""

    transcriber: AudioTranscriber
    sample_rate: int = 16_000
    window_seconds: float = 3.0
    overlap_seconds: float = 0.4
    max_frame_bytes: int = 128 * 1024
    inference_semaphore: asyncio.Semaphore | None = None
    transcript: StreamingTranscript = field(default_factory=StreamingTranscript)
    _buffer: bytearray = field(default_factory=bytearray, init=False)

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not 0 <= self.overlap_seconds < self.window_seconds:
            raise ValueError("overlap_seconds must be smaller than window")

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    @property
    def window_bytes(self) -> int:
        return int(self.sample_rate * self.window_seconds) * 2

    @property
    def overlap_bytes(self) -> int:
        return int(self.sample_rate * self.overlap_seconds) * 2

    def feed_pcm(self, frame: bytes) -> list[dict[str, str]]:
        if len(frame) > self.max_frame_bytes:
            raise RealtimeSttProtocolError("frame_too_large")
        if len(frame) % 2:
            raise RealtimeSttProtocolError("invalid_pcm")
        self._buffer.extend(frame)
        return []

    async def _transcribe(self, audio: bytes) -> str:
        samples = np.frombuffer(audio, dtype="<i2").astype(np.float32)
        samples /= 32768.0

        async def run() -> str:
            return await asyncio.to_thread(self.transcriber.transcribe, samples)

        if self.inference_semaphore is None:
            return await run()
        async with self.inference_semaphore:
            return await run()

    async def flush(self, *, final: bool = False) -> list[dict[str, str]]:
        if final:
            audio = bytes(self._buffer)
            self._buffer.clear()
        else:
            if len(self._buffer) < self.window_bytes:
                return []
            audio = bytes(self._buffer[: self.window_bytes])
            if self.overlap_bytes:
                overlap_start = self.window_bytes - self.overlap_bytes
                self._buffer = self._buffer[overlap_start:]
            else:
                del self._buffer[: self.window_bytes]

        if audio:
            hypothesis = await self._transcribe(audio)
            self.transcript.merge(hypothesis)

        event_type = "final" if final else "partial"
        return [{"type": event_type, "text": self.transcript.text}]

    def close(self) -> None:
        self._buffer.clear()

