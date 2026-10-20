import { useEffect } from "react";
import {
  ensureLocalHelper,
  getLocalHelperStatus,
  reportLocalHelperError,
  stopLocalHelper,
} from "./localHelper";

const HEALTH_CHECK_INTERVAL_MS = 30_000;

export function useLocalHelperLifecycle(
  authStatus: "loading" | "auth-required" | "ok",
): void {
  useEffect(() => {
    if (authStatus === "auth-required") {
      void stopLocalHelper().catch(reportLocalHelperError);
      return;
    }
    if (authStatus !== "ok") return;

    let cancelled = false;
    let checking = false;
    const ensure = async (validateBinding: boolean) => {
      if (cancelled || checking) return;
      checking = true;
      try {
        const status = await getLocalHelperStatus();
        if (cancelled || !status) return;
        if (validateBinding || !status.running) {
          await ensureLocalHelper();
        }
      } catch (error) {
        if (!cancelled) reportLocalHelperError(error);
      } finally {
        checking = false;
      }
    };

    void ensure(true);
    const interval = window.setInterval(
      () => void ensure(false),
      HEALTH_CHECK_INTERVAL_MS,
    );
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [authStatus]);
}
