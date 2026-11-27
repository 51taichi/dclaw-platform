# Public video timeline render task

The Support plugin owns `dclaw.ffmpeg.task.plan` version `0.1.0` for all
authorized Super Agents. Windows Helper 1.4.9 or later uses the registered
`ffmpeg` public Component. No Agent-specific package is needed for this task.

Declare `local.execution.session/1`, `local.runtime.prepare/1`,
`local.task.start/1`, and `local.task.read/1` in the signed Agent release.
Declare `local.task.outputs.bind/1` when using files from a prior local task.
Wait for `local.runtime.prepare/1` to return `ready` with package version
`0.1.0`; `preparing` is not an accepted task. Existing Agent releases do not
gain these Host grants automatically.

Call `local.task.start/1` with `capability_id=dclaw.ffmpeg.task.plan`, a
stable `idempotency_key`, and `input.plan_version=1`. `input.clips` is an ordered
timeline: each item names a bound `slot`, a start and end in milliseconds, and
an optional pixel crop. `input.output` selects a safe MP4 name, even dimensions,
frames per second, and `audio_policy` (`mute` or `preserve`). `preserve` requires
an audio stream in every input. Reusing a slot is allowed. The Helper checks
trusted task-local bindings, compiles all FFmpeg arguments, invokes FFmpeg
without a shell, and writes the name, size and SHA-256 of the output. Agent
input cannot contain arguments, shell commands, filter graphs, paths or URLs.
The Host and Helper keep existing acceptance, read, cancel, idempotency, file
binding and managed-artifact contracts.

`start-request.sample.json` shows two MP4 inputs from trusted file refs.
The references are illustrative; obtain real values from
`local.task.outputs.bind/1` or an authorized file selector. The example is
only an API request, not evidence of a customer task or rendered video.
`local_ffmpeg_task_plan_api_demo.py` validates and submits the request.
The input and result Schemas are in `schemas/local-ffmpeg-task-plan-v1/`.

The Helper reports `CAPABILITY.PROCESS_FAILED` if FFmpeg exits nonzero and
`CAPABILITY.INVALID_PAYLOAD` if its result fails the published result Schema.
Read the task's terminal status before using an artifact; a Host acceptance
receipt alone does not prove that FFmpeg completed.
