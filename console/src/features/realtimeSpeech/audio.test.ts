import { describe, expect, it } from "vitest";
import {
  buildRealtimeSpeechUrl,
  buildRealtimeSpeechProtocols,
  downsampleTo16Khz,
  floatToPcm16,
} from "./audio";

describe("realtime speech audio", () => {
  it("keeps credentials out of the websocket URL", () => {
    expect(
      buildRealtimeSpeechUrl(
        "/api/user/workspace/realtime-transcribe",
        "https://dclaw.example/workbench",
      ),
    ).toBe("wss://dclaw.example/api/user/workspace/realtime-transcribe");
  });

  it("encodes authentication in websocket subprotocols", () => {
    expect(buildRealtimeSpeechProtocols("secret.token")).toEqual([
      "dclaw-stt",
      "dclaw-auth.c2VjcmV0LnRva2Vu",
    ]);
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
