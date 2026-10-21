import { useEffect } from "react";
import { reportLocalHelperError, stopLocalHelper } from "./localHelper";

export function useLocalHelperLifecycle(
  authStatus: "loading" | "auth-required" | "ok",
): void {
  useEffect(() => {
    if (authStatus !== "auth-required") return;
    void stopLocalHelper().catch(reportLocalHelperError);
  }, [authStatus]);
}
