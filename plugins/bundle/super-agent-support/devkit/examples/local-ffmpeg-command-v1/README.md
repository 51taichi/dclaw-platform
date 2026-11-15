# Platform FFmpeg command task

The platform owns the registered `dclaw.ffmpeg.command` package version
`0.1.0`. It uses the signed `python-runtime` 3.12.14 and `ffmpeg`
N-128100-gceb466cbcd public Components on Windows x64. The Agent does not
publish a private FFmpeg package for ordinary command tasks.

Declare `local.execution.session/1`, `local.runtime.prepare/1`,
`local.task.start/1`, and `local.task.read/1` in the signed Agent release.
Declare `local.task.outputs.bind/1` when using files from a prior local task.
Wait for `local.runtime.prepare/1` to return `ready` with package version
`0.1.0`; `preparing` is not an accepted task. Existing Agent releases do not
gain these Host grants automatically.

Call `local.task.start/1` with `capability_id=dclaw.ffmpeg.command`, a stable
`idempotency_key`, and `input.arguments` as an argv array. Do not send a shell
command string. Each bound file is referenced as an exact argument token
`{input:slot}` where `slot` is a `local_file_bindings` key. Each declared
output is referenced once as `{output:filename}`. The Runner maps tokens to
verified task-local paths, invokes FFmpeg with no shell, and writes output
name, size, and SHA-256 to `result.json`. It rejects raw paths and URLs in
argument tokens. The Host and Helper retain the existing task acceptance,
read, cancel, idempotency, file binding, and managed-artifact contracts.

`start-request.sample.json` shows two MP4 inputs from trusted file refs.
The references are illustrative; obtain real values from
`local.task.outputs.bind/1` or an authorized file selector. The example is
only an API request, not evidence of a customer task or rendered video.
`local_ffmpeg_command_api_demo.py` validates and submits the request. The
input and result Schemas are in `schemas/local-ffmpeg-command-v1/`.

The package reports `CAPABILITY.PROCESS_FAILED` if FFmpeg exits nonzero and
`CAPABILITY.INVALID_PAYLOAD` if its result fails the signed result Schema.
Read the task's terminal status before using an artifact; a Host acceptance
receipt alone does not prove that FFmpeg completed.
