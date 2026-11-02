import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import {
  ensureLocalHelper,
  getLocalEnvironmentStatus,
  getLocalHelperStatus,
  waitForLocalHelperConnection,
} from "@/desktop/localHelper";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import { localAssistantMode } from "./mode";

export type LocalHelperCheckState =
  | "idle"
  | "checking"
  | "ready"
  | "unavailable"
  | "not-installed"
  | "update-required"
  | "protocol-incompatible"
  | "error";

interface LocalHelperStatusValue {
  state: LocalHelperCheckState;
  runnerVersion: string;
  label: string;
  check: (notify?: boolean) => Promise<void>;
}

const LocalHelperStatusContext = createContext<LocalHelperStatusValue | null>(
  null,
);

export function LocalHelperStatusProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const selectedAgent = useAgentStore((store) => store.selectedAgent);
  const agent = useAgentStore((store) =>
    store.agents.find((item) => item.id === store.selectedAgent),
  );
  const mode = useMemo(() => localAssistantMode(agent), [agent]);
  const [state, setState] = useState<LocalHelperCheckState>("idle");
  const [runnerVersion, setRunnerVersion] = useState("");
  const checkingRef = useRef(false);
  const autoCheckedRef = useRef(new Set<string>());

  const check = useCallback(
    async (notify = true) => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      setState("checking");
      let failureState: LocalHelperCheckState = "error";
      try {
        const detected = await getLocalHelperStatus();
        if (!detected) {
          failureState = "unavailable";
          throw new Error(
            t(
              "header.localHelperWindowsOnly",
              "请在 Windows DClaw 客户端中检测本地助手。",
            ),
          );
        }
        const started = await ensureLocalHelper();
        if (!started.available) {
          failureState = "unavailable";
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
          failureState = "update-required";
          throw new Error(
            t("header.localHelperUpdateRequired", {
              defaultValue:
                "本地助手版本过低，请重新检测并下载 Runner v{{version}}。",
              version: environment.minimum_runner_version,
            }),
          );
        }
        if (environment.state === "protocol_incompatible") {
          failureState = "protocol-incompatible";
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
        setRunnerVersion("");
        setState(failureState);
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
      : state === "unavailable"
      ? t("header.localHelperUnavailable", "本地助手不可用")
      : state === "not-installed"
      ? t("header.localHelperNotInstalled", "本地助手未安装")
      : state === "update-required"
      ? t("header.localHelperNeedsUpdate", "本地助手需要升级")
      : state === "protocol-incompatible"
      ? t("header.localHelperIncompatible", "本地助手不兼容")
      : state === "error"
      ? t("header.localHelperRetry", "本地助手异常，点击重试")
      : t("header.localHelperCheck", "检测本地助手");

  return (
    <LocalHelperStatusContext.Provider
      value={{ state, runnerVersion, label, check }}
    >
      {children}
    </LocalHelperStatusContext.Provider>
  );
}

export function useLocalHelperStatus() {
  const context = useContext(LocalHelperStatusContext);
  if (!context) {
    throw new Error(
      "useLocalHelperStatus must be used within LocalHelperStatusProvider",
    );
  }
  return context;
}
