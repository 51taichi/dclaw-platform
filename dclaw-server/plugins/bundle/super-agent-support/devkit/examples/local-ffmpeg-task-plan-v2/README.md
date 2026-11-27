# Complete-file video timeline

`dclaw.ffmpeg.task.plan` remains package version `0.1.0`. Input
`plan_version=2` is available with Support plugin 1.18.50 and Windows Helper
1.4.10 or later. The Host rejects version 2 on an older Helper before creating
a task. Existing `plan_version=1` requests and explicit trim ranges remain
valid on Helper 1.4.9 or later.

The example uses two previously bound MP4 files in `clips[]` order. A clip with
only `slot` means the complete file, without a guessed duration. An optional
`trim_start_ms` means that point through the actual file end; an optional
`trim_end_ms` means file start through that point. Supply both for a bounded
range with end greater than start. Unknown slots, foreign bindings and raw
FFmpeg arguments are rejected. `crop` is an independent optional pixel operation. The Helper
builds FFmpeg filters from the task-local trusted files and preserves every
frame/audio sample subject to the requested output frame rate and encoding.
`audio_policy=preserve` requires an audio stream in every input; use `mute`
when that is not true. The Agent never receives a local path or source URL.

Call `local.runtime.prepare/1`, then `local.task.start/1` with a stable
idempotency key and trusted `local_file_bindings`; use `local.task.read/1` for
the terminal result. The result Schema is unchanged: one output name, byte
size and SHA-256. A ready/accepted receipt is not a completed render.

`LOCAL_GATEWAY.DEVICE_NOT_READY` means the bound device is older than 1.4.10
or offline; update/reconnect it and retry with the same idempotency key.
`CAPABILITY.INVALID_PAYLOAD` means the plan violates the closed
Schema or has an invalid two-boundary interval; correct the request. Runtime source
or FFmpeg failure is recorded as a failed local task, not a successful file.
