"""Authenticated browser gateway for the private local STT sidecar."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
from contextlib import suppress
from typing import Any

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import resolve_authenticated_user, verify_token

logger = logging.getLogger(__name__)
realtime_stt_router = APIRouter()
_AUTH_SUBPROTOCOL_PREFIX = "dclaw-auth."


def _enabled() -> bool:
    return os.environ.get("DCLAW_REALTIME_STT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def authenticate_browser_token(token: str) -> dict[str, Any] | None:
    """Resolve a browser login token without exposing it to logs."""
    if not token:
        return None
    username = verify_token(token)
    if not username:
        return None
    return resolve_authenticated_user(username)


def browser_token_from_protocol_header(header: str) -> str:
    """Decode the login token from a WebSocket subprotocol without URL leakage."""
    for raw_protocol in header.split(","):
        protocol = raw_protocol.strip()
        if not protocol.startswith(_AUTH_SUBPROTOCOL_PREFIX):
            continue
        encoded = protocol.removeprefix(_AUTH_SUBPROTOCOL_PREFIX)
        if not encoded:
            return ""
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded = base64.b64decode(
                encoded.replace("-", "+").replace("_", "/") + padding,
                validate=True,
            )
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return ""
    return ""


async def _browser_to_upstream(websocket: WebSocket, upstream: Any) -> None:
    while True:
        event = await websocket.receive()
        event_type = event.get("type")
        if event_type == "websocket.disconnect":
            return
        if event.get("bytes") is not None:
            await upstream.send(event["bytes"])
        elif event.get("text") is not None:
            await upstream.send(event["text"])


async def _upstream_to_browser(websocket: WebSocket, upstream: Any) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)


@realtime_stt_router.websocket("/user/workspace/realtime-transcribe")
async def realtime_transcribe(websocket: WebSocket) -> None:
    """Proxy ephemeral PCM frames to the private speech service."""
    if not _enabled():
        await websocket.close(code=1008, reason="Speech input is disabled")
        return

    token = browser_token_from_protocol_header(
        websocket.headers.get("sec-websocket-protocol", ""),
    )
    if authenticate_browser_token(token) is None:
        await websocket.close(code=1008, reason="Invalid token")
        return

    upstream_url = os.environ.get(
        "DCLAW_STT_UPSTREAM_URL",
        "ws://dclaw-stt:8090/v1/transcribe",
    ).strip()
    internal_token = os.environ.get("DCLAW_STT_INTERNAL_TOKEN", "").strip()
    if not upstream_url or not internal_token:
        await websocket.close(code=1013, reason="Speech service unavailable")
        return

    try:
        async with websockets.connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {internal_token}"},
            open_timeout=5,
            close_timeout=2,
            max_size=256 * 1024,
            proxy=None,
        ) as upstream:
            await websocket.accept(subprotocol="dclaw-stt")
            browser_task = asyncio.create_task(
                _browser_to_upstream(websocket, upstream),
            )
            upstream_task = asyncio.create_task(
                _upstream_to_browser(websocket, upstream),
            )
            done, pending = await asyncio.wait(
                {browser_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - translate gateway failures safely
        logger.warning("Realtime STT session failed: %s", type(exc).__name__)
        with suppress(Exception):
            if websocket.client_state.name == "CONNECTED":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "service_unavailable",
                            "message": "Speech recognition is temporarily unavailable",
                        },
                    ),
                )
            await websocket.close(code=1011)
