import { describe, expect, it } from "vitest";
import {
  buildRealtimeSpeechUrl,
  downsampleTo16Khz,
  floatToPcm16,
} from "./audio";

describe("realtime speech audio", () => {
  it("builds an authenticated websocket URL without changing the API path", () => {
    expect(
      buildRealtimeSpeechUrl(
        "/api/user/workspace/realtime-transcribe",
        "secret token",
        "https://dclaw.example/workbench",
      ),
    ).toBe(
      "wss://dclaw.example/api/user/workspace/realtime-transcribe?token=secret+token",
    );
  });

  it("downsamples browser audio to 16 kHz", () => {
    const source = new Float32Array([0, 0.25, 0.5, 0.75, 1, 0.75]);
    const result = downsampleTo16Khz(source, 48_000);

    expect(Array.from(result)).toEqual([0.25, 0.8333333134651184]);
  });

  it("converts normalized samples to little-endian PCM16", () => {
    const result = floatToPcm16(new Float32Array([-1, 0, 1]));

    expect(Array.from(result)).toEqual([-32768, 0, 32767]);
  });
});
