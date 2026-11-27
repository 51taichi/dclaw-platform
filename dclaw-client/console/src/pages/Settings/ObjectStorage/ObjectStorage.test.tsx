import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ObjectStoragePage from "./index";

const mockRequest = vi.hoisted(() => vi.fn());

vi.mock("../../../api", () => ({
  request: mockRequest,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

const configuredResponse = {
  config: {
    provider: "aliyun_oss",
    enabled: true,
    endpoint: "https://oss-cn-hangzhou.aliyuncs.com",
    bucket: "qwenpaw-aigc",
    access_key_id: "test-ak",
    access_key_secret: "********",
    prefix: "aigc/generated",
    signed_url_ttl_seconds: 600,
    configured: true,
    updated_at: "2026-06-25T00:00:00Z",
  },
};

describe("ObjectStoragePage", () => {
  beforeEach(() => {
    mockRequest.mockReset();
    mockRequest.mockResolvedValue(configuredResponse);
  });

  it("loads the Aliyun OSS config into the form", async () => {
    render(<ObjectStoragePage />);

    expect(await screen.findByDisplayValue("qwenpaw-aigc")).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("https://oss-cn-hangzhou.aliyuncs.com"),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("********")).toBeInTheDocument();
    expect(mockRequest).toHaveBeenCalledWith("/admin/object-storage/config");
  });

  it("saves the current form and preserves a masked access key secret", async () => {
    const user = userEvent.setup();
    mockRequest
      .mockResolvedValueOnce(configuredResponse)
      .mockResolvedValueOnce(configuredResponse);
    render(<ObjectStoragePage />);

    const prefixInput = await screen.findByDisplayValue("aigc/generated");
    await user.clear(prefixInput);
    await user.type(prefixInput, "prod/aigc");
    await user.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith(
        "/admin/object-storage/config",
        expect.objectContaining({ method: "PUT" }),
      );
    });
    const saveCall = mockRequest.mock.calls.find(
      ([url, options]) =>
        url === "/admin/object-storage/config" && options?.method === "PUT",
    );
    const body = JSON.parse(saveCall?.[1]?.body as string);
    expect(body.access_key_secret).toBe("********");
    expect(body.prefix).toBe("prod/aigc");
  });

  it("tests the current Aliyun OSS form values without saving first", async () => {
    const user = userEvent.setup();
    mockRequest
      .mockResolvedValueOnce(configuredResponse)
      .mockResolvedValueOnce({
        ok: true,
        provider: "aliyun_oss",
        bucket: "qwenpaw-aigc",
        object_key: "aigc/generated/connection-tests/probe.txt",
      });
    render(<ObjectStoragePage />);

    await screen.findByDisplayValue("qwenpaw-aigc");
    await user.click(screen.getByRole("button", { name: "测试连接" }));

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith(
        "/admin/object-storage/test",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const testCall = mockRequest.mock.calls.find(
      ([url, options]) =>
        url === "/admin/object-storage/test" && options?.method === "POST",
    );
    const body = JSON.parse(testCall?.[1]?.body as string);
    expect(body.bucket).toBe("qwenpaw-aigc");
    expect(body.access_key_secret).toBe("********");
  });
});
