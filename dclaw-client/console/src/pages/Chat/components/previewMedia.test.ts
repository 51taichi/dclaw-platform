import { describe, expect, it } from "vitest";
import { getMediaPreviewKind, getMediaMimeType } from "./previewMedia";

describe("previewMedia", () => {
  it("detects common audio and video formats case-insensitively", () => {
    expect(getMediaPreviewKind("voice.MP3")).toBe("audio");
    expect(getMediaPreviewKind("mix.final.flac")).toBe("audio");
    expect(getMediaPreviewKind("clips/intro.MP4")).toBe("video");
    expect(getMediaPreviewKind("clips/trailer.webm")).toBe("video");
  });

  it("detects media paths with query strings, hashes, and encoded names", () => {
    expect(getMediaPreviewKind("audio/%E8%AF%AD%E9%9F%B3.m4a?v=1")).toBe(
      "audio",
    );
    expect(getMediaPreviewKind("video/demo.mov#preview")).toBe("video");
  });

  it("returns browser-friendly mime types when known", () => {
    expect(getMediaMimeType("voice.wav")).toBe("audio/wav");
    expect(getMediaMimeType("movie.mkv")).toBe("video/x-matroska");
    expect(getMediaMimeType("notes.md")).toBeUndefined();
  });
});
