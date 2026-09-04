# Local Realtime STT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local, incremental Mandarin dictation to the Workbench input while preserving manual send and isolating speech inference from the DClaw application process.

**Architecture:** A private `dclaw-stt` sidecar accepts PCM over WebSocket and emits accumulated hypotheses. An authenticated DClaw WebSocket gateway proxies the browser session to the sidecar. A focused browser controller captures/resamples PCM and updates only the Workbench landing-page composer.

**Tech Stack:** FastAPI/Starlette WebSockets, `websockets`, faster-whisper, Docker Compose, React, TypeScript, Web Audio API, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-local-realtime-stt-design.md`

## Global Constraints

- Do not modify Agent, OpenAPI, scheduled-task, model-routing, billing, or existing batch-transcription behavior.
- Speech inference must run outside the DClaw application process.
- Default capacity is 10 connected sessions and 2 concurrent CPU inference jobs.
- The browser must never auto-submit recognized text.
- Authentication tokens, audio, and transcripts must not be logged.
- Failure must preserve keyboard input and the latest visible hypothesis.

---

### Task 1: Streaming STT service core

**Files:**
- Create: `deploy/realtime_stt/app.py`
- Create: `deploy/realtime_stt/session.py`
- Create: `deploy/realtime_stt/transcriber.py`
- Create: `deploy/realtime_stt/requirements.txt`
- Create: `deploy/realtime_stt/Dockerfile`
- Test: `tests/unit/realtime_stt/test_session.py`

**Interfaces:**
- `StreamingTranscript.merge(hypothesis: str) -> str` returns the accumulated transcript without duplicate overlap.
- `StreamingSession.feed_pcm(frame: bytes) -> list[dict[str, str]]` validates and buffers signed 16-bit PCM.
- `await StreamingSession.flush(final: bool) -> list[dict[str, str]]` emits `partial` or `final` protocol events.
- `FasterWhisperTranscriber.transcribe(samples: numpy.ndarray) -> str` is the only production model boundary.

- [ ] **Step 1: Write failing unit tests** covering overlapping Mandarin hypotheses, odd-sized PCM rejection, bounded frame size, partial emission, final tail emission, and buffer cleanup.
- [ ] **Step 2: Run the focused test** with `pytest -q tests/unit/realtime_stt/test_session.py` and verify failures identify missing modules.
- [ ] **Step 3: Implement the session protocol** with dependency-injected transcription, a 16 kHz mono PCM contract, fixed windows, bounded overlap, and no persistence or logging of content.
- [ ] **Step 4: Implement the model adapter** using faster-whisper with configurable model/device/compute type and `language="zh"`, `beam_size=1`, `condition_on_previous_text=False`.
- [ ] **Step 5: Implement the private FastAPI service** with `/health` and `/v1/transcribe`, internal bearer authentication, a 10-session semaphore, a separate inference semaphore, and sanitized errors.
- [ ] **Step 6: Add a CPU image** that installs pinned service-only dependencies and starts Uvicorn on port 8090.
- [ ] **Step 7: Run the focused tests** and verify all service tests pass without downloading a model by injecting a fake transcriber.

### Task 2: Authenticated DClaw WebSocket gateway

**Files:**
- Create: `src/qwenpaw/app/routers/realtime_transcription.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Modify: `src/qwenpaw/app/_app.py`
- Test: `tests/unit/app/test_realtime_transcription_router.py`

**Interfaces:**
- Browser endpoint: `/api/user/workspace/realtime-transcribe?token=<jwt>`.
- `validate_realtime_stt_user(token: str) -> dict` verifies the JWT and resolves an existing user.
- `proxy_realtime_transcription(websocket: WebSocket, upstream_url: str) -> None` relays only accepted JSON and binary protocol messages.

- [ ] **Step 1: Write failing gateway tests** for missing/expired tokens, deleted users, disabled feature, invalid frame size, successful bidirectional relay, upstream failure, and redacted logs.
- [ ] **Step 2: Run `pytest -q tests/unit/app/test_realtime_transcription_router.py`** and verify the route/module is absent.
- [ ] **Step 3: Implement explicit WebSocket authentication** using existing token verification and user resolution helpers; close unauthorized connections with policy code 1008.
- [ ] **Step 4: Implement the upstream relay** with connect and idle timeouts, 128 KiB frame limit, five-minute session limit, internal bearer authentication, and sanitized `service_unavailable` events.
- [ ] **Step 5: Register the WebSocket route outside HTTP-only dependencies** before the SPA catch-all.
- [ ] **Step 6: Run gateway and existing batch-transcription tests** to prove old behavior remains unchanged.

### Task 3: Local deployment isolation

**Files:**
- Modify: `deploy/local/compose.local.yml`
- Modify: `deploy/local/dclaw_local.py`
- Modify: `deploy/local/local.env.example`
- Test: `tests/unit/deploy/test_local_deploy.py`

**Interfaces:**
- Environment: `QWENPAW_REALTIME_STT_ENABLED`, `QWENPAW_REALTIME_STT_URL`, `DCLAW_STT_INTERNAL_TOKEN`, `DCLAW_STT_MODEL`, `DCLAW_STT_DEVICE`, `DCLAW_STT_COMPUTE_TYPE`, `DCLAW_STT_MAX_SESSIONS`, `DCLAW_STT_INFERENCE_CONCURRENCY`.
- Local image tag: `dclaw-stt-local:<server-revision>-<fingerprint>`.

- [ ] **Step 1: Extend deployment tests** to require a secret token, private STT service, no published STT port, persistent model volume, resource limits, and independent doctor output.
- [ ] **Step 2: Run `pytest -q tests/unit/deploy/test_local_deploy.py`** and verify the new assertions fail.
- [ ] **Step 3: Extend local initialization** to generate and redact the internal token and add safe CPU defaults.
- [ ] **Step 4: Build the STT image separately** in `command_build`, write its image identity to the environment/release files, and leave the main image dependency set unchanged.
- [ ] **Step 5: Add `dclaw-stt` to Compose** on `dclaw-net` only, with a named model cache, health check, resource limits, and no hard dependency from DClaw startup health.
- [ ] **Step 6: Extend doctor/status checks** so speech readiness is visible without failing core DClaw health when the optional feature is disabled.
- [ ] **Step 7: Run deployment tests** and validate the composed configuration with `docker compose config`.

### Task 4: Browser realtime speech controller

**Files:**
- Create: `console/src/features/realtimeSpeech/audio.ts` in the client repository.
- Create: `console/src/features/realtimeSpeech/RealtimeSpeechController.ts` in the client repository.
- Test: `console/src/features/realtimeSpeech/audio.test.ts` in the client repository.
- Test: `console/src/features/realtimeSpeech/RealtimeSpeechController.test.ts` in the client repository.

**Interfaces:**
- `downsampleTo16Khz(input: Float32Array, inputRate: number) -> Int16Array`.
- `RealtimeSpeechController.start(callbacks) -> Promise<void>`.
- `RealtimeSpeechController.stop() -> Promise<void>`.
- Callbacks: `onState`, `onPartial`, `onFinal`, and `onError`.

- [ ] **Step 1: Write failing PCM tests** for 48 kHz to 16 kHz resampling, clipping, signed conversion, and empty input.
- [ ] **Step 2: Write failing controller tests** for authenticated WebSocket URL construction, start handshake, binary frames, partial/final parsing, stop without send, disconnect cleanup, and microphone denial.
- [ ] **Step 3: Run the focused Vitest files** and verify they fail because the feature modules are absent.
- [ ] **Step 4: Implement pure PCM conversion** without browser-global side effects.
- [ ] **Step 5: Implement the controller** with `getUserMedia`, `AudioContext`, a processing node, same-origin WebSocket URL conversion, existing JWT lookup, and deterministic cleanup of tracks/context/socket.
- [ ] **Step 6: Run focused tests** and TypeScript checking.

### Task 5: Workbench incremental dictation UI

**Files:**
- Modify: `console/src/pages/Workbench/index.tsx` in the client repository.
- Modify: `console/src/pages/Workbench/index.module.less` in the client repository.
- Modify: `console/src/pages/Workbench/WorkbenchPage.test.tsx` in the client repository.
- Modify: `console/src/locales/zh.json` in the client repository.
- Modify: `console/src/locales/en.json` in the client repository.

**Interfaces:**
- The microphone toggles `idle -> connecting -> recording -> stopping -> idle`.
- Each partial replaces only the recording hypothesis while preserving pre-existing text.
- The final result remains editable and does not call `createChat`.

- [ ] **Step 1: Add failing Workbench tests** for visible recording state, partial replacement without duplication, final text, manual typing preservation, no automatic task creation, permission failure, and service disconnect.
- [ ] **Step 2: Run the Workbench test** and verify the decorative microphone lacks the required behavior.
- [ ] **Step 3: Integrate the controller** with explicit status labels/tooltips, active animation, stop-on-second-click, and cleanup on unmount/navigation.
- [ ] **Step 4: Add localized errors** for unsupported browser, permission denied, capacity exceeded, service unavailable, and connection lost.
- [ ] **Step 5: Run Workbench tests, client typecheck, and production frontend build**.

### Task 6: End-to-end local verification

**Files:**
- Modify only if verification exposes a confirmed defect in files already listed above.

**Interfaces:**
- Local DClaw URL remains `http://127.0.0.1:18088`.
- STT remains private on the Compose network.

- [ ] **Step 1: Run all focused server tests** for the service, gateway, deployment, and existing transcription.
- [ ] **Step 2: Run all focused client tests** plus TypeScript checking and production build.
- [ ] **Step 3: Build local DClaw and STT images** using the existing local deployment CLI with the isolated `main` source directories.
- [ ] **Step 4: Start the local stack** and verify DClaw health remains independent from STT readiness.
- [ ] **Step 5: Verify STT health and an authenticated WebSocket session** without logging credentials or transcript content.
- [ ] **Step 6: Open `/workbench` locally** and manually verify live Mandarin text, stop behavior, editability, and manual-only send.
- [ ] **Step 7: Inspect container resource usage and logs** to confirm no restart, unbounded memory, token/audio logging, or interference with the DClaw API.

