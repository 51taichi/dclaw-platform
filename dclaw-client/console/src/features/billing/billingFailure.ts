import type { InsufficientCreditsFailure } from "../../api/types/billing";

export function parseInsufficientCreditsFailure(
  value: unknown,
): InsufficientCreditsFailure | null {
  if (
    !value ||
    typeof value !== "object" ||
    (value as { type?: unknown }).type !== "billing.error" ||
    (value as { code?: unknown }).code !== "INSUFFICIENT_CREDITS"
  ) {
    return null;
  }
  const payload = value as Record<string, unknown>;
  return {
    code: "INSUFFICIENT_CREDITS",
    available_credits: Math.max(0, Number(payload.available_credits) || 0),
    required_credits: Math.max(0, Number(payload.required_credits) || 0),
    top_up_path:
      typeof payload.top_up_path === "string" &&
      payload.top_up_path.startsWith("/")
        ? payload.top_up_path
        : "/wallet",
  };
}
