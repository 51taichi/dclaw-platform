import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ATTACHMENT_FILES_CARD,
  AttachmentFilesCard,
  buildUserRequestCards,
  resolveRequestAttachmentUrl,
} from ".";

describe("buildUserRequestCards", () => {
  it("hides server paths, upload summaries, and extracted document text", () => {
    const serverPath =
      "/app/working/sealed_agents/runtime_workspaces/luyu/agent/media/report.pdf";
    const cards = buildUserRequestCards([
      { type: "text", text: "已上传附件：客户方案.pdf" },
      {
        type: "file",
        filename: "客户方案.pdf",
        file_url: serverPath,
      },
      {
        type: "text",
        text: "[附件正文开始：客户方案.pdf]\n内部提取正文\n[附件正文结束：客户方案.pdf]",
      },
    ]);

    expect(cards).toEqual([
      {
        code: ATTACHMENT_FILES_CARD,
        data: [{ name: "客户方案.pdf", url: serverPath, size: undefined }],
      },
    ]);
    expect(JSON.stringify(cards)).toContain(serverPath);
    expect(JSON.stringify(cards)).not.toContain("内部提取正文");
  });

  it("converts legacy attachment markdown without exposing its path as text", () => {
    const serverPath = "/app/working/media/customer-plan.pdf";
    const cards = buildUserRequestCards([
      {
        type: "text",
        text: `请分析这份方案\n\n📎 [customer-plan.pdf](${serverPath})`,
      },
    ]);

    expect(cards[0]).toEqual({
      code: "Text",
      data: { content: "请分析这份方案", raw: true },
    });
    expect(cards[1]).toEqual({
      code: ATTACHMENT_FILES_CARD,
      data: [{ name: "customer-plan.pdf", url: serverPath }],
    });
    expect(JSON.stringify(cards[0])).not.toContain(serverPath);
  });
});

describe("AttachmentFilesCard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows only the file name and opens the protected file URL", () => {
    const url = "/api/user/files/preview/report.pdf?chatId=chat-1";
    const open = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<AttachmentFilesCard data={[{ name: "客户方案.pdf", url }]} />);

    expect(screen.getByText("📎 [客户方案.pdf]")).toBeInTheDocument();
    expect(screen.queryByText(url)).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "打开文件 客户方案.pdf" }),
    );
    expect(open).toHaveBeenCalledWith(url, "_blank", "noopener,noreferrer");
  });
});

describe("resolveRequestAttachmentUrl", () => {
  it("adds chat and agent context to an existing protected preview URL", () => {
    expect(
      resolveRequestAttachmentUrl(
        "/api/user/files/preview/report.pdf?token=session-token",
        "chat-1",
        "luyu_dclaw_agent",
      ),
    ).toBe(
      "/api/user/files/preview/report.pdf?token=session-token&chatId=chat-1&agent_id=luyu_dclaw_agent",
    );
  });
});
