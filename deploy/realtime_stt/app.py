"""Private WebSocket service for local Mandarin speech recognition."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .session import RealtimeSttProtocolError, StreamingSession
from .transcriber import FasterWhisperTranscriber


@dataclass(frozen=True)
class SttSettings:
    internal_token: str
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    sample_rate: int = 16_000
    window_seconds: float = 3.0
    overlap_seconds: float = 0.4
    max_sessions: int = 10
    inference_concurrency: int = 2
    max_session_seconds: int = 300

    @classmethod
    def from_environment(cls) -> "SttSettings":
        return cls(
            internal_token=os.environ.get("DCLAW_STT_INTERNAL_TOKEN", ""),
            model=os.environ.get("DCLAW_STT_MODEL", "base"),
            device=os.environ.get("DCLAW_STT_DEVICE", "cpu"),
            compute_type=os.environ.get("DCLAW_STT_COMPUTE_TYPE", "int8"),
            max_sessions=int(os.environ.get("DCLAW_STT_MAX_SESSIONS", "10")),
            inference_concurrency=int(
                os.environ.get("DCLAW_STT_INFERENCE_CONCURRENCY", "2"),
            ),
            max_session_seconds=int(
                os.environ.get("DCLAW_STT_MAX_SESSION_SECONDS", "300"),
            ),
        )


def create_app(
    *,
    settings: SttSettings | None = None,
    transcriber_factory: Callable[[], object] | None = None,
) -> FastAPI:
    config = settings or SttSettings.from_environment()

    state_lock = asyncio.Lock()
    inference_semaphore = asyncio.Semaphore(config.inference_concurrency)
    active_sessions = 0
    transcriber: object | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal transcriber
        if not config.internal_token:
            raise RuntimeError("DCLAW_STT_INTERNAL_TOKEN is required")
        if transcriber_factory is not None:
            transcriber = transcriber_factory()
        else:
            transcriber = await asyncio.to_thread(
                FasterWhisperTranscriber,
                model=config.model,
                device=config.device,
                compute_type=config.compute_type,
            )
        yield
        transcriber = None

    app = FastAPI(title="DClaw local realtime STT", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, int | bool]:
        return {
            "ready": transcriber is not None,
            "active_sessions": active_sessions,
            "max_sessions": config.max_sessions,
        }

    @app.websocket("/v1/transcribe")
    async def transcribe_socket(websocket: WebSocket) -> None:
        nonlocal active_sessions
        authorization = websocket.headers.get("authorization", "")
        expected = f"Bearer {config.internal_token}"
        if not hmac.compare_digest(authorization, expected):
            await websocket.close(code=1008)
            return

        async with state_lock:
            if active_sessions >= config.max_sessions:
                await websocket.close(code=1013)
                return
            active_sessions += 1

        await websocket.accept()
        session: StreamingSession | None = None
        try:
            while True:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=config.max_session_seconds,
                )
                if message.get("type") == "websocket.disconnect":
                    break

                if message.get("bytes") is not None:
                    if session is None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "start_required",
                                "message": "Start the transcription session first",
                            },
                        )
                        break
                    try:
                        session.feed_pcm(message["bytes"])
                        for event in await session.flush():
                            await websocket.send_json(event)
                    except RealtimeSttProtocolError as exc:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": str(exc),
                                "message": "Invalid audio stream",
                            },
                        )
                        break
                    continue

                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "Invalid control message",
                        },
                    )
                    break

                message_type = payload.get("type")
                if message_type == "start":
                    if (
                        payload.get("sample_rate") != config.sample_rate
                        or payload.get("language") != "zh"
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "unsupported_audio",
                                "message": "Only 16 kHz Mandarin PCM is supported",
                            },
                        )
                        break
                    if session is not None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "already_started",
                                "message": "Transcription session already started",
                            },
                        )
                        break
                    if transcriber is None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "not_ready",
                                "message": "Speech recognition is not ready",
                            },
                        )
                        break
                    session = StreamingSession(
                        transcriber=transcriber,  # type: ignore[arg-type]
                        sample_rate=config.sample_rate,
                        window_seconds=config.window_seconds,
                        overlap_seconds=config.overlap_seconds,
                        inference_semaphore=inference_semaphore,
                    )
                    await websocket.send_json({"type": "ready"})
                elif message_type == "stop":
                    if session is None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "start_required",
                                "message": "Start the transcription session first",
                            },
                        )
                        break
                    for event in await session.flush(final=True):
                        await websocket.send_json(event)
                    await websocket.close(code=1000)
                    break
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "Invalid control message",
                        },
                    )
                    break
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            if session is not None:
                session.close()
            async with state_lock:
                active_sessions -= 1

    return app


app = create_app()
