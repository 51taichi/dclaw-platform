from __future__ import annotations

from collections import deque

import numpy as np
import pytest

from deploy.realtime_stt.session import (
    RealtimeSttProtocolError,
    StreamingSession,
    StreamingTranscript,
)


class FakeTranscriber:
    def __init__(self, *responses: str) -> None:
        self._responses = deque(responses)
        self.calls: list[np.ndarray] = []

    def transcribe(self, samples: np.ndarray) -> str:
        self.calls.append(samples.copy())
        return self._responses.popleft() if self._responses else ""


def pcm(samples: list[int]) -> bytes:
    return np.asarray(samples, dtype="<i2").tobytes()


def test_transcript_merges_overlapping_mandarin_hypotheses() -> None:
    transcript = StreamingTranscript()

    assert transcript.merge("你好世界") == "你好世界"
    assert transcript.merge("世界很好") == "你好世界很好"


def test_transcript_separates_non_overlapping_latin_hypotheses() -> None:
    transcript = StreamingTranscript()

    assert transcript.merge("hello") == "hello"
    assert transcript.merge("world") == "hello world"


def test_feed_rejects_odd_sized_pcm() -> None:
    session = StreamingSession(FakeTranscriber(), sample_rate=4)

    with pytest.raises(RealtimeSttProtocolError, match="invalid_pcm"):
        session.feed_pcm(b"\x00")


def test_feed_rejects_oversized_frame() -> None:
    session = StreamingSession(
        FakeTranscriber(),
        sample_rate=4,
        max_frame_bytes=8,
    )

    with pytest.raises(RealtimeSttProtocolError, match="frame_too_large"):
        session.feed_pcm(b"\x00" * 10)


@pytest.mark.asyncio
async def test_flush_emits_accumulated_partial_without_duplicate_overlap() -> None:
    transcriber = FakeTranscriber("你好世界", "世界很好")
    session = StreamingSession(
        transcriber,
        sample_rate=4,
        window_seconds=1,
        overlap_seconds=0.25,
    )

    assert session.feed_pcm(pcm([1, 2, 3, 4])) == []
    assert await session.flush() == [{"type": "partial", "text": "你好世界"}]

    # One sample was retained for overlap, so three new samples complete
    # the next one-second window.
    assert session.feed_pcm(pcm([5, 6, 7])) == []
    assert await session.flush() == [{"type": "partial", "text": "你好世界很好"}]
    assert len(transcriber.calls) == 2


@pytest.mark.asyncio
async def test_final_flush_emits_tail_and_clears_audio_buffer() -> None:
    transcriber = FakeTranscriber("最后一句")
    session = StreamingSession(
        transcriber,
        sample_rate=4,
        window_seconds=2,
        overlap_seconds=0,
    )
    session.feed_pcm(pcm([1, 2, 3]))

    assert await session.flush(final=True) == [
        {"type": "final", "text": "最后一句"},
    ]
    assert session.buffered_bytes == 0


@pytest.mark.asyncio
async def test_final_flush_without_tail_returns_latest_transcript() -> None:
    session = StreamingSession(
        FakeTranscriber("你好"),
        sample_rate=2,
        window_seconds=1,
        overlap_seconds=0,
    )
    session.feed_pcm(pcm([1, 2]))
    await session.flush()

    assert await session.flush(final=True) == [
        {"type": "final", "text": "你好"},
    ]


def test_close_releases_buffered_audio() -> None:
    session = StreamingSession(FakeTranscriber(), sample_rate=4)
    session.feed_pcm(pcm([1, 2, 3]))

    session.close()

    assert session.buffered_bytes == 0
