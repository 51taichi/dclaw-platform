import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Progress } from "antd";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch, exit } from "@tauri-apps/plugin-process";
import { isDesktopApp } from "@/utils/env";
import { DESKTOP_UPDATE_REQUIRED_EVENT } from "@/desktop/httpGate";
import styles from "./index.module.less";

type GateState = "checking" | "downloading" | "installing" | "ready" | "error";
const CHECK_TIMEOUT_MS = 10_000;

async function checkWithTimeout(): Promise<Update | null> {
  return Promise.race([
    check(),
    new Promise<never>((_, reject) =>
      window.setTimeout(
        () => reject(new Error("检查更新超时，请检查网络后重试")),
        CHECK_TIMEOUT_MS,
      ),
    ),
  ]);
}

export function DesktopUpdateGate({ children }: { children: ReactNode }) {
  // Development builds must remain usable before release signing keys exist.
  const desktop =
    !import.meta.env.DEV && isDesktopApp() && "__TAURI_INTERNALS__" in window;
  const [state, setState] = useState<GateState>(desktop ? "checking" : "ready");
  const [message, setMessage] = useState("正在检查客户端版本…");
  const [progress, setProgress] = useState(0);

  const runUpdateGate = useCallback(async () => {
    if (!desktop) return;
    setState("checking");
    setMessage("正在检查客户端版本…");
    setProgress(0);
    try {
      const update = await checkWithTimeout();
      if (!update) {
        setState("ready");
        return;
      }
      setState("downloading");
      setMessage(`正在更新 v${update.currentVersion} → v${update.version}`);
      let downloaded = 0;
      let total = 0;
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (total > 0)
            setProgress(Math.min(100, Math.round((downloaded / total) * 100)));
        }
        if (event.event === "Finished") {
          setProgress(100);
          setState("installing");
          setMessage("更新安装完成，正在重新启动…");
        }
      });
      await relaunch();
    } catch (error) {
      setState("error");
      setMessage(
        error instanceof Error ? error.message : "客户端更新失败，请重试",
      );
    }
  }, [desktop]);

  useEffect(() => {
    void runUpdateGate();
    const forceUpdate = () => void runUpdateGate();
    window.addEventListener(DESKTOP_UPDATE_REQUIRED_EVENT, forceUpdate);
    return () =>
      window.removeEventListener(DESKTOP_UPDATE_REQUIRED_EVENT, forceUpdate);
  }, [runUpdateGate]);

  if (state === "ready") return <>{children}</>;
  return (
    <main className={styles.gate}>
      <img className={styles.logo} src="/dclaw-logo-light.svg" alt="" />
      <div className={styles.message}>{message}</div>
      {state === "downloading" || state === "installing" ? (
        <Progress
          percent={progress}
          status="active"
          showInfo={state === "downloading"}
        />
      ) : null}
      {state === "error" ? (
        <div className={styles.actions}>
          <Button type="primary" onClick={() => void runUpdateGate()}>
            重试
          </Button>
          <Button onClick={() => void exit(0)}>退出</Button>
        </div>
      ) : null}
    </main>
  );
}
