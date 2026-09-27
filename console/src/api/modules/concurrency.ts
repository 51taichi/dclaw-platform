import { request } from "../request";
import type { ConcurrencySnapshot } from "../../features/concurrency/types";

export function getConcurrencySnapshot(): Promise<ConcurrencySnapshot> {
  return request<ConcurrencySnapshot>("/admin/performance/concurrency", {
    includeSelectedAgent: false,
  });
}
