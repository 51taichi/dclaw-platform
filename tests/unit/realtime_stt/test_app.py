from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from deploy.realtime_stt.app import SttSettings, create_app


class FakeTranscriber:
    def transcribe(self, samples: np.ndarray) -> str:
        return "测试语音" if samples.size else ""


@contextmanager
def client(*, token: str = "internal-secret", max_sessions: int = 10):
    settings = SttSettings(
        internal_token=token,
        sample_rate=4,
        window_seconds=1,
        overlap_seconds=0,
        max_sessions=max_sessions,
        inference_concurrency=1,
        max_session_seconds=30,
    )
    with TestClient(
        create_app(settings=settings, transcriber_factory=FakeTranscriber),
    ) as test_client:
        yield test_client


def test_health_reports_ready_without_exposing_configuration() -> None:
    with client() as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "active_sessions": 0,
        "max_sessions": 10,
    }


def test_websocket_rejects_missing_internal_token() -> None:
    with client() as test_client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_client.websocket_connect("/v1/transcribe"):
                pass

    assert exc.value.code == 1008


def test_websocket_streams_partial_and_final_transcript() -> None:
    with client() as test_client:
        with test_client.websocket_connect(
            "/v1/transcribe",
            headers={"Authorization": "Bearer internal-secret"},
        ) as websocket:
            websocket.send_json(
                {"type": "start", "sample_rate": 4, "language": "zh"},
            )
            assert websocket.receive_json() == {"type": "ready"}

            websocket.send_bytes(np.asarray([1, 2, 3, 4], dtype="<i2").tobytes())
            assert websocket.receive_json() == {
                "type": "partial",
                "text": "测试语音",
            }

            websocket.send_json({"type": "stop"})
            assert websocket.receive_json() == {
                "type": "final",
                "text": "测试语音",
            }


def test_websocket_returns_sanitized_protocol_error() -> None:
    with client() as test_client:
        with test_client.websocket_connect(
            "/v1/transcribe",
            headers={"Authorization": "Bearer internal-secret"},
        ) as websocket:
            websocket.send_json(
                {"type": "start", "sample_rate": 4, "language": "zh"},
            )
            websocket.receive_json()
            websocket.send_bytes(b"\x00")

            assert websocket.receive_json() == {
                "type": "error",
                "code": "invalid_pcm",
                "message": "Invalid audio stream",
            }


def test_websocket_rejects_unsupported_start_contract() -> None:
    with client() as test_client:
        with test_client.websocket_connect(
            "/v1/transcribe",
            headers={"Authorization": "Bearer internal-secret"},
        ) as websocket:
            websocket.send_json(
                {"type": "start", "sample_rate": 48_000, "language": "en"},
            )

            assert websocket.receive_json() == {
                "type": "error",
                "code": "unsupported_audio",
                "message": "Only 16 kHz Mandarin PCM is supported",
            }
