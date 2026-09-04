import { getApiToken, getApiUrl } from "../../api/config";
import {
  buildRealtimeSpeechProtocols,
  buildRealtimeSpeechUrl,
  downsampleTo16Khz,
  floatToPcm16,
  REALTIME_STT_SAMPLE_RATE,
} from "./audio";

export type RealtimeSpeechState =
  | "idle"
  | "connecting"
  | "recording"
  | "processing";

export interface RealtimeSpeechControllerOptions {
  onTranscript: (text: string, final: boolean) => void;
  onStateChange: (state: RealtimeSpeechState) => void;
  onError: (message: string) => void;
}

type SpeechEvent = {
  type?: string;
  text?: string;
  message?: string;
};

export class RealtimeSpeechController {
  private readonly options: RealtimeSpeechControllerOptions;
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private mutedOutput: GainNode | null = null;
  private state: RealtimeSpeechState = "idle";
  private stopTimer: number | null = null;
  private intentionallyClosing = false;

  constructor(options: RealtimeSpeechControllerOptions) {
    this.options = options;
  }

  async start(): Promise<void> {
    if (this.state !== "idle") return;
    this.setState("connecting");
    this.intentionallyClosing = false;

    try {
      const token = getApiToken();
      if (!token) throw new Error("请先登录后再使用语音输入");
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风录音");
      }

      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const AudioContextClass =
        window.AudioContext ||
        (window as typeof window & { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!AudioContextClass) throw new Error("当前浏览器不支持实时语音输入");
      this.audioContext = new AudioContextClass();

      const url = buildRealtimeSpeechUrl(
        getApiUrl("/workspace/realtime-transcribe"),
      );
      await this.openSocket(url, buildRealtimeSpeechProtocols(token));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "无法启动语音输入";
      this.fail(message);
    }
  }

  stop(): void {
    if (this.state === "idle" || this.state === "processing") return;
    if (this.state === "connecting") {
      this.intentionallyClosing = true;
      this.cleanup();
      return;
    }

    this.stopAudioCapture();
    this.setState("processing");
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "stop" }));
      this.stopTimer = window.setTimeout(() => {
        this.fail("语音识别等待超时，请稍后重试");
      }, 8_000);
    } else {
      this.fail("语音识别连接已断开");
    }
  }

  destroy(): void {
    this.intentionallyClosing = true;
    this.cleanup();
  }

  private async openSocket(url: string, protocols: string[]): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url, protocols);
      socket.binaryType = "arraybuffer";
      this.socket = socket;

      socket.onopen = () => {
        socket.send(
          JSON.stringify({
            type: "start",
            sample_rate: REALTIME_STT_SAMPLE_RATE,
            language: "zh",
          }),
        );
        resolve();
      };
      socket.onerror = () => reject(new Error("无法连接本地语音识别服务"));
      socket.onmessage = (event) => this.handleMessage(event.data);
      socket.onclose = () => {
        if (!this.intentionallyClosing && this.state !== "idle") {
          this.fail("语音识别连接已断开");
        }
      };
    });
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== "string") return;
    let event: SpeechEvent;
    try {
      event = JSON.parse(raw) as SpeechEvent;
    } catch {
      this.fail("语音识别返回了无效数据");
      return;
    }

    if (event.type === "ready") {
      this.startAudioCapture();
      this.setState("recording");
      return;
    }
    if (event.type === "partial" || event.type === "final") {
      this.options.onTranscript(event.text || "", event.type === "final");
      if (event.type === "final") {
        this.intentionallyClosing = true;
        this.cleanup();
      }
      return;
    }
    if (event.type === "error") {
      this.fail(event.message || "语音识别失败");
    }
  }

  private startAudioCapture(): void {
    if (!this.audioContext || !this.stream) return;
    void this.audioContext.resume();
    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
    this.mutedOutput = this.audioContext.createGain();
    this.mutedOutput.gain.value = 0;
    this.processor.onaudioprocess = (event) => {
      if (this.socket?.readyState !== WebSocket.OPEN) return;
      const source = event.inputBuffer.getChannelData(0);
      const downsampled = downsampleTo16Khz(
        source,
        this.audioContext?.sampleRate || REALTIME_STT_SAMPLE_RATE,
      );
      const pcm = floatToPcm16(downsampled);
      if (pcm.byteLength) this.socket.send(pcm.buffer);
    };
    this.source.connect(this.processor);
    this.processor.connect(this.mutedOutput);
    this.mutedOutput.connect(this.audioContext.destination);
  }

  private stopAudioCapture(): void {
    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
      this.processor = null;
    }
    this.source?.disconnect();
    this.source = null;
    this.mutedOutput?.disconnect();
    this.mutedOutput = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  private fail(message: string): void {
    this.options.onError(message);
    this.intentionallyClosing = true;
    this.cleanup();
  }

  private cleanup(): void {
    if (this.stopTimer !== null) {
      window.clearTimeout(this.stopTimer);
      this.stopTimer = null;
    }
    this.stopAudioCapture();
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onmessage = null;
      this.socket.onerror = null;
      this.socket.onclose = null;
      if (
        this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING
      ) {
        this.socket.close();
      }
      this.socket = null;
    }
    if (this.audioContext) {
      void this.audioContext.close();
      this.audioContext = null;
    }
    this.setState("idle");
  }

  private setState(state: RealtimeSpeechState): void {
    this.state = state;
    this.options.onStateChange(state);
  }
}
