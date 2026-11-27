# Audio Source Separation Component 1.0.0

This plugin-owned public Component provides deterministic Windows x64 CPU
voice/background separation with Demucs 4.0.1 and the fixed `htdemucs` model.
It returns technical audio facts only. Agent-specific quality thresholds and
workflow decisions remain in the sealed Super Agent.

The process accepts a read-only task binding under `res/bindings/`, writes only
under `res/`, and emits 44.1 kHz stereo PCM16 WAV files. RMS is calculated over
all interleaved samples after PCM16 quantization using
`20 * log10(sqrt(mean((sample / 32768)^2)))`; exact zero energy is reported as
`-160.0` dBFS. NaN and infinity fail with `AUDIO_SEPARATION.NUMERIC_INVALID`.

Limits: 512 MiB input, 600 seconds duration, one CPU inference process. Runner
enforces the capability package memory, disk, output, concurrency, cancellation
and runtime limits. The component never downloads models or dependencies at
runtime.
