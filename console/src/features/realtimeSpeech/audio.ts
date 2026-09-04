export const REALTIME_STT_SAMPLE_RATE = 16_000;

export function buildRealtimeSpeechUrl(
  apiUrl: string,
  token: string,
  pageUrl = window.location.href,
): string {
  const url = new URL(apiUrl, pageUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", token);
  return url.toString();
}

export function downsampleTo16Khz(
  samples: Float32Array,
  sourceRate: number,
): Float32Array {
  if (sourceRate === REALTIME_STT_SAMPLE_RATE) return samples.slice();
  if (sourceRate < REALTIME_STT_SAMPLE_RATE) {
    throw new Error("unsupported_sample_rate");
  }

  const ratio = sourceRate / REALTIME_STT_SAMPLE_RATE;
  const result = new Float32Array(Math.floor(samples.length / ratio));
  for (let outputIndex = 0; outputIndex < result.length; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(Math.floor((outputIndex + 1) * ratio), samples.length);
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) {
      sum += samples[inputIndex];
    }
    result[outputIndex] = sum / Math.max(1, end - start);
  }
  return result;
}

export function floatToPcm16(samples: Float32Array): Int16Array {
  const result = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    result[index] = value < 0 ? value * 32768 : value * 32767;
  }
  return result;
}
