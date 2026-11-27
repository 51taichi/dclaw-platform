import { describe, it, test, expect, vi } from "vitest";
import { chatApi } from "@/api/modules/chat";
import {
  extractCopyableText,
  extractUserMessageText,
  buildModelError,
  toStoredName,
  normalizeContentUrls,
  toDisplayUrl,
  rewritePayloadMediaUrls,
  filterApprovalsForSession,
} from "./utils";
import type { CopyableResponse } from "./utils";

// toDisplayUrl depends on chatApi.filePreviewUrl, needs to be mocked
vi.mock("@/api/modules/chat", () => ({
  chatApi: {
    filePreviewUrl: vi.fn((p: string) => `http://localhost:8000${p}`),
  },
}));

vi.mock("../../api/config", () => ({
  getApiUrl: vi.fn((path: string) => `http://localhost:8000/api/user${path}`),
  getApiToken: vi.fn(() => ""),
}));

describe("filterApprovalsForSession", () => {
  const approvals = [
    { request_id: "a", root_session_id: "chat:root", session_id: "agent:a" },
    { request_id: "b", root_session_id: "uuid-1", session_id: "agent:b" },
    { request_id: "c", root_session_id: "chat:other", session_id: "agent:c" },
  ];

  it("matches approvals by root session id", () => {
    expect(filterApprovalsForSession(approvals, ["chat:root"])).toEqual([
      approvals[0],
    ]);
  });

  it("matches approvals by child session id", () => {
    expect(filterApprovalsForSession(approvals, ["agent:b"])).toEqual([
      approvals[1],
    ]);
  });

  it("supports multiple candidate ids for chat id and runtime session id", () => {
    expect(
      filterApprovalsForSession(approvals, ["uuid-missing", "chat:root"]),
    ).toEqual([approvals[0]]);
  });

  it("returns all approvals when no session id is known yet", () => {
    expect(filterApprovalsForSession(approvals, [null, ""])).toEqual(
      approvals,
    );
  });
});

// ---------------------------------------------------------------------------
// extractCopyableText
// ---------------------------------------------------------------------------
describe("extractCopyableText", () => {
  it("extracts string content from assistant role", () => {
    const response: CopyableResponse = {
      output: [
        { role: "user", content: "你好" },
        { role: "assistant", content: "你好，有什么可以帮你？" },
      ],
    };
    expect(extractCopyableText(response)).toBe("你好，有什么可以帮你？");
  });

  it("extracts text from structured content array", () => {
    const response: CopyableResponse = {
      output: [
        {
          role: "assistant",
          content: [
            { type: "text", text: "第一段" },
            { type: "text", text: "第二段" },
          ],
        },
      ],
    };
    expect(extractCopyableText(response)).toBe("第一段\n\n第二段");
  });

  it("extracts refusal type content", () => {
    const response: CopyableResponse = {
      output: [
        {
          role: "assistant",
          content: [{ type: "refusal", refusal: "无法回答此问题" }],
        },
      ],
    };
    expect(extractCopyableText(response)).toBe("无法回答此问题");
  });

  it("falls back to JSON.stringify when no assistant message is present", () => {
    const response: CopyableResponse = {
      output: [{ role: "user", content: "仅用户消息" }],
    };
    expect(extractCopyableText(response)).toBe(JSON.stringify(response));
  });

  it("returns JSON serialization when output is empty", () => {
    const response: CopyableResponse = { output: [] };
    expect(extractCopyableText(response)).toBe(JSON.stringify(response));
  });

  it("does not throw when output is undefined", () => {
    expect(() => extractCopyableText({})).not.toThrow();
  });

  it("merges multiple assistant messages with double newlines", () => {
    const response: CopyableResponse = {
      output: [
        { role: "assistant", content: "第一句" },
        { role: "assistant", content: "第二句" },
      ],
    };
    expect(extractCopyableText(response)).toBe("第一句\n\n第二句");
  });
});

// ---------------------------------------------------------------------------
// extractUserMessageText
// ---------------------------------------------------------------------------
describe("extractUserMessageText", () => {
  it("returns string content directly", () => {
    expect(extractUserMessageText({ content: "你好" })).toBe("你好");
  });

  it("extracts text type items from array content and joins with newlines", () => {
    const msg = {
      content: [
        { type: "text", text: "你好" },
        { type: "image_url", image_url: "http://..." },
        { type: "text", text: "世界" },
      ],
    };
    expect(extractUserMessageText(msg)).toBe("你好\n世界");
  });

  it("returns empty string for non-string non-array content", () => {
    expect(extractUserMessageText({ content: null })).toBe("");
    expect(extractUserMessageText({ content: 123 })).toBe("");
  });
});

// ---------------------------------------------------------------------------
// buildModelError
// ---------------------------------------------------------------------------
describe("buildModelError", () => {
  it("returns 400 status code", () => {
    const response = buildModelError();
    expect(response.status).toBe(400);
  });

  it("response body contains error and message fields", async () => {
    const response = buildModelError();
    const body = await response.json();
    expect(body).toHaveProperty("error");
    expect(body).toHaveProperty("message");
  });

  it("Content-Type is application/json", () => {
    const response = buildModelError();
    expect(response.headers.get("Content-Type")).toBe("application/json");
  });
});

// ---------------------------------------------------------------------------
// toStoredName
// ---------------------------------------------------------------------------
describe("toStoredName", () => {
  test.each([
    [
      "extracts path after /files/preview/",
      "http://host/files/preview/uploads/img.png",
      "/uploads/img.png",
    ],
    [
      "strips query parameters",
      "http://host/files/preview/img.png?token=abc",
      "/img.png",
    ],
    [
      "strips hash fragment",
      "http://host/files/preview/img.png#section",
      "/img.png",
    ],
    [
      "returns input as-is when marker is absent",
      "/local/path/file.txt",
      "/local/path/file.txt",
    ],
    [
      "correctly decodes URL-encoded path",
      "http://host/files/preview/%E4%B8%AD%E6%96%87.txt",
      "/中文.txt",
    ],
  ])("%s", (_: string, input: string, expected: string) => {
    expect(toStoredName(input)).toBe(expected);
  });
});

// ---------------------------------------------------------------------------
// normalizeContentUrls
// ---------------------------------------------------------------------------
describe("normalizeContentUrls", () => {
  it("converts image_url for image type", () => {
    const part = {
      type: "image",
      image_url: "http://host/files/preview/img.png",
    };
    const result = normalizeContentUrls(part);
    expect(result.image_url).toBe("/img.png");
  });

  it("converts file_url for file type", () => {
    const part = {
      type: "file",
      file_url: "http://host/files/preview/doc.pdf",
    };
    const result = normalizeContentUrls(part);
    expect(result.file_url).toBe("/doc.pdf");
  });

  it("converts data for audio type", () => {
    const part = { type: "audio", data: "http://host/files/preview/audio.mp3" };
    const result = normalizeContentUrls(part);
    expect(result.data).toBe("/audio.mp3");
  });

  it("does not affect text type", () => {
    const part = { type: "text", text: "hello" };
    expect(normalizeContentUrls(part)).toEqual(part);
  });

  it("does not mutate the original object (shallow copy)", () => {
    const part = {
      type: "image",
      image_url: "http://host/files/preview/img.png",
    };
    normalizeContentUrls(part);
    expect(part.image_url).toBe("http://host/files/preview/img.png");
  });
});

// ---------------------------------------------------------------------------
// toDisplayUrl
// ---------------------------------------------------------------------------
describe("toDisplayUrl", () => {
  it("returns http URL as-is", () => {
    expect(toDisplayUrl("http://cdn.com/img.png")).toBe(
      "http://cdn.com/img.png",
    );
  });

  it("returns https URL as-is", () => {
    expect(toDisplayUrl("https://cdn.com/file")).toBe("https://cdn.com/file");
  });

  it("returns empty string for undefined", () => {
    expect(toDisplayUrl(undefined)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(toDisplayUrl("")).toBe("");
  });

  it("calls chatApi.filePreviewUrl for relative paths", () => {
    expect(toDisplayUrl("/uploads/img.png")).toBe(
      "http://localhost:8000/uploads/img.png",
    );
  });

  it("strips file:// prefix then resolves full URL", () => {
    expect(toDisplayUrl("file:///uploads/img.png")).toBe(
      "http://localhost:8000/uploads/img.png",
    );
  });

  it("routes imagegen session files through workspace preview", () => {
    expect(
      toDisplayUrl(
        "file:///app/working/workspaces/default/sessions_data/1782359420083/media/imagegen/imagegen_1782365209213.png",
        "chat-123",
        "default",
      ),
    ).toBe(
      "http://localhost:8000/api/user/workspace/preview/__qwenpaw_preview__/default/chat-123/media/imagegen/imagegen_1782365209213.png",
    );
  });

  it("repairs old files-preview imagegen URLs into workspace preview URLs", () => {
    expect(
      toDisplayUrl(
        "/api/user/files/preview//app/working/workspaces/default/sessions_data/1782359420083/media/imagegen/imagegen_1782365278687.png?token=old",
        "chat-123",
        "default",
      ),
    ).toBe(
      "http://localhost:8000/api/user/workspace/preview/__qwenpaw_preview__/default/chat-123/media/imagegen/imagegen_1782365278687.png",
    );
  });

  it("routes root workspace PPT visual scheme images through workspace preview", () => {
    expect(
      toDisplayUrl(
        "file:///app/working/workspaces/default/media/ppt_visual_schemes/imagegen_1782712947438.png",
        "chat-123",
        "default",
      ),
    ).toBe(
      "http://localhost:8000/api/user/workspace/preview/__qwenpaw_preview__/default/chat-123/media/ppt_visual_schemes/imagegen_1782712947438.png",
    );
  });

  it("rewrites structured video sources with distinct chat and agent context", () => {
    vi.mocked(chatApi.filePreviewUrl).mockImplementationOnce(
      (path: string) => `http://localhost:8000/api/user/files/preview/${path}`,
    );
    const payload = {
      type: "video",
      source: {
        type: "url",
        url: "file:///app/working/sealed_agents/runtime_workspaces/luyu_traffic_operator/release/agent/aigc_studio/result.mp4",
      },
    };

    rewritePayloadMediaUrls(payload, "chat-123", "luyu_traffic_operator");

    expect(payload.source.url).toContain("chatId=chat-123");
    expect(payload.source.url).toContain("agent_id=luyu_traffic_operator");
    expect(payload.source.url).not.toContain("agent_id=chat-123");
  });
});
