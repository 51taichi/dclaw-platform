import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Tooltip } from "antd";
import {
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  MonitorCog,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ensureLocalHelper,
  getLocalEnvironmentStatus,
  waitForLocalHelperConnection,
} from "@/desktop/localHelper";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import styles from "./LocalHelperStatusButton.module.less";
import { localAssistantMode } from "./mode";

type CheckState = "idle" | "checking" | "ready" | "error";

export default function LocalHelperStatusButton() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const agent = useAgentStore((state) =>
    state.agents.find((item) => item.id === state.selectedAgent),
  );
  const mode = useMemo(() => localAssistantMode(agent), [agent]);
  const [state, setState] = useState<CheckState>("idle");
  const [runnerVersion, setRunnerVersion] = useState("");
  const checkingRef = useRef(false);
  const autoCheckedRef = useRef(new Set<string>());

  const check = useCallback(
    async (notify: boolean) => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      setState("checking");
      try {
        const started = await ensureLocalHelper();
        if (!started.available) {
          throw new Error(
            started.status
              ? t(
                  "header.localHelperPluginUnavailable",
                  "平台尚未启用本地助手支持，请联系管理员。",
                )
              : t(
                  "header.localHelperWindowsOnly",
                  "请在 Windows DClaw 客户端中检测本地助手。",
                ),
          );
        }
        const status = started.status?.connected
          ? started.status
          : await waitForLocalHelperConnection();
        if (!status?.connected) {
          throw new Error(
            t(
              "header.localHelperConnectFailed",
              "本地助手已启动，但尚未连接到 DClaw，请稍后重试。",
            ),
          );
        }
        const environment = await getLocalEnvironmentStatus();
        if (environment.state === "runner_update_required") {
          throw new Error(
            t("header.localHelperUpdateRequired", {
              defaultValue:
                "本地助手版本过低，请将 DClaw 客户端升级到支持 Runner v{{version}} 的版本。",
              version: environment.minimum_runner_version,
            }),
          );
        }
        if (environment.state === "protocol_incompatible") {
          throw new Error(
            t(
              "header.localHelperProtocolIncompatible",
              "本地助手协议不兼容，请联系管理员。",
            ),
          );
        }
        if (environment.state !== "ready") {
          throw new Error(
            t(
              "header.localHelperConnectFailed",
              "本地助手已启动，但尚未连接到 DClaw，请稍后重试。",
            ),
          );
        }
        setRunnerVersion(status.runnerVersion);
        setState("ready");
        if (notify) {
          void message.success(t("header.localHelperReady", "本地助手已连接"));
        }
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        setState("error");
        void message.error(detail);
      } finally {
        checkingRef.current = false;
      }
    },
    [message, t],
  );

  useEffect(() => {
    if (mode !== "required" || autoCheckedRef.current.has(selectedAgent)) {
      return;
    }
    autoCheckedRef.current.add(selectedAgent);
    void check(false);
  }, [check, mode, selectedAgent]);

  const label =
    state === "checking"
      ? t("header.localHelperChecking", "正在检测本地助手")
      : state === "ready"
      ? t("header.localHelperReadyWithVersion", {
          defaultValue: "本地助手已连接 · v{{version}}",
          version: runnerVersion,
        })
      : state === "error"
      ? t("header.localHelperRetry", "本地助手异常，点击重试")
      : t("header.localHelperCheck", "检测本地助手");

  const icon =
    state === "checking" ? (
      <LoaderCircle size={16} />
    ) : state === "ready" ? (
      <CircleCheck size={16} />
    ) : state === "error" ? (
      <CircleAlert size={16} />
    ) : (
      <MonitorCog size={16} />
    );

  return (
    <Tooltip title={label}>
      <Button
        className={`${styles.button} ${styles[state] ?? ""}`}
        icon={icon}
        aria-label={label}
        disabled={state === "checking"}
        onClick={() => void check(true)}
      />
    </Tooltip>
  );
}
