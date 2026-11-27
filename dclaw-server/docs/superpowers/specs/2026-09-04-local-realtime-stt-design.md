# Local Realtime STT Design

## Goal

Add server-local Mandarin speech-to-text dictation to the DClaw Workbench. While the user is speaking, the input box shows incremental text. The user remains responsible for editing and sending the text. The feature does not call an LLM, does not perform TTS, does not submit messages automatically, and does not participate in billing.

## Scope and isolation

- Add realtime dictation only to the `/workbench` landing-page composer.
- Preserve the existing batch `/api/user/workspace/transcribe` endpoint and the existing Chat and Task microphone behavior.
- Do not change Agent execution, OpenAPI, scheduled tasks, model routing, or credit accounting.
- Run speech inference in a separate `dclaw-stt` container with explicit resource and session limits so inference cannot block the DClaw API process.
- Keep the feature disabled unless the deployment enables `QWENPAW_REALTIME_STT_ENABLED` and supplies an internal STT URL.
- If capture, authentication, gateway, or inference fails, preserve all manually typed text and leave normal keyboard submission available.

## Architecture

### Browser

The Workbench microphone uses a dedicated `RealtimeSpeechInput` controller. It obtains microphone permission, captures mono PCM with the browser Web Audio API, resamples audio to 16 kHz, converts samples to signed 16-bit little-endian frames, and sends frames over one authenticated WebSocket connection.

The controller maintains four states: `idle`, `connecting`, `recording`, and `stopping`. The server sends complete accumulated hypotheses, not deltas. The UI stores the text that existed before recording separately from the current hypothesis, so each partial result replaces the previous hypothesis instead of duplicating text. Stopping produces a final result and never triggers task creation or message submission.

The WebSocket URL is derived from the existing API base URL and includes the existing JWT in the `token` query parameter, matching the repository's established WebSocket authentication convention. Tokens are never logged.

### DClaw gateway

DClaw exposes `/api/user/workspace/realtime-transcribe`. The WebSocket handler validates the JWT itself because HTTP middleware does not authenticate WebSockets, resolves the authenticated user, enforces the feature flag, and proxies the session to the private STT service. The gateway limits frame size, session duration, and message types. It forwards sanitized error codes to the browser and does not log audio or tokens.

Browser-to-server protocol:

- JSON `{"type":"start","sample_rate":16000,"language":"zh"}`
- Binary signed 16-bit little-endian PCM frames
- JSON `{"type":"stop"}`

Server-to-browser protocol:

- `{"type":"ready"}`
- `{"type":"partial","text":"..."}`
- `{"type":"final","text":"..."}`
- `{"type":"error","code":"...","message":"..."}`

### STT service

`dclaw-stt` is a private FastAPI service with no published host port. It loads one configurable `faster-whisper` model and accepts at most 10 WebSocket sessions. A smaller inference semaphore bounds concurrent CPU inference separately from connected sessions.

The initial local-test defaults are Mandarin, `base` model, CPU, and `int8`. Audio is decoded directly from PCM. A session periodically transcribes bounded windows and emits an accumulated hypothesis. A final tail pass runs when the browser stops. The model name, device, compute type, window duration, maximum sessions, and inference concurrency are environment variables.

The service exposes `/health` with readiness and capacity only. It does not persist audio or transcript data. Temporary session buffers are released on stop, disconnect, timeout, and error.

## Capacity and failure behavior

- Maximum connected sessions: 10.
- Default concurrent inference jobs: 2 on CPU.
- Maximum session duration: 5 minutes.
- Maximum binary frame size: 128 KiB.
- A full service returns `capacity_exceeded` without affecting DClaw.
- A missing/unready model returns `service_unavailable`.
- A gateway connection failure returns `service_unavailable`.
- Browser permission denial returns an explicit Chinese microphone-permission message.
- Unexpected disconnect leaves the most recent hypothesis in the input box.

## Deployment

The local deployment builds a separate STT image, persists model downloads in a named volume, attaches the container only to `dclaw-net`, and passes a generated internal bearer secret to DClaw and the STT service. `dclaw` can start even if STT is unavailable. The local deploy status/doctor output reports STT separately.

The main DClaw image and its Python dependency set remain unchanged. This prevents speech dependencies from increasing or destabilizing the application runtime.

## Testing

- Unit-test transcript merge, session limits, frame validation, stop/final behavior, and cleanup with a fake transcriber.
- Unit-test gateway authentication, disabled mode, upstream errors, and token redaction.
- Unit-test browser PCM conversion/resampling and WebSocket protocol handling.
- Component-test Workbench permission errors, partial replacement, final text, manual send, and absence of automatic send.
- Regression-test the existing batch transcription endpoint.
- Build both images, start the local Compose stack, verify both health endpoints, and exercise an authenticated WebSocket session against the local stack.

## Non-goals

- Text-to-speech or spoken Agent replies.
- Automatic send after silence.
- Third-party speech APIs.
- Multilingual or Cantonese tuning.
- Adding realtime dictation to Chat, Task, mobile, or OpenAPI in this release.
