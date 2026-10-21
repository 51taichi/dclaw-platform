import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocalHelperLifecycle } from "./useLocalHelperLifecycle";

const { ensureLocalHelper, getLocalHelperStatus, stopLocalHelper } = vi.hoisted(
  () => ({
    ensureLocalHelper: vi.fn(),
    getLocalHelperStatus: vi.fn(),
    stopLocalHelper: vi.fn(),
  }),
);

vi.mock("./localHelper", () => ({
  ensureLocalHelper,
  getLocalHelperStatus,
  stopLocalHelper,
  reportLocalHelperError: vi.fn(),
}));

function LifecycleHarness({
  status,
}: {
  status: "loading" | "auth-required" | "ok";
}) {
  useLocalHelperLifecycle(status);
  return null;
}

describe("useLocalHelperLifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stopLocalHelper.mockResolvedValue(undefined);
  });

  it("does not probe or start the optional helper after login", () => {
    render(<LifecycleHarness status="ok" />);

    expect(getLocalHelperStatus).not.toHaveBeenCalled();
    expect(ensureLocalHelper).not.toHaveBeenCalled();
    expect(stopLocalHelper).not.toHaveBeenCalled();
  });

  it("still stops a previously started helper after logout", async () => {
    const view = render(<LifecycleHarness status="ok" />);
    view.rerender(<LifecycleHarness status="auth-required" />);

    await waitFor(() => expect(stopLocalHelper).toHaveBeenCalledOnce());
    expect(getLocalHelperStatus).not.toHaveBeenCalled();
    expect(ensureLocalHelper).not.toHaveBeenCalled();
  });
});
