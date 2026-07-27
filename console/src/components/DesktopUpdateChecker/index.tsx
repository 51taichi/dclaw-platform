import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import { rootApi } from "@/api/modules/root";
import {
  desktopUpdateApi,
  type DesktopUpdatePlatform,
  type DesktopUpdateResponse,
} from "@/api/modules/desktopUpdate";
import { isDesktopApp } from "@/utils/env";
import { openExternalLink } from "@/utils/openExternalLink";

const DISMISSED_KEY = "dclaw_desktop_update_dismissed_version";

function detectDesktopUpdatePlatform(): DesktopUpdatePlatform | null {
  if (typeof navigator === "undefined") {
    return null;
  }
  const text = `${navigator.platform || ""} ${
    navigator.userAgent || ""
  }`.toLowerCase();
  if (text.includes("win")) return "win";
  if (text.includes("mac")) return "mac";
  return null;
}

function rememberDismissed(version: string) {
  sessionStorage.setItem(DISMISSED_KEY, version);
}

function wasDismissed(version: string): boolean {
  return sessionStorage.getItem(DISMISSED_KEY) === version;
}

export function useDesktopUpdateCheck() {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const [checking, setChecking] = useState(false);
  const [lastResult, setLastResult] = useState<DesktopUpdateResponse | null>(
    null,
  );

  const showUpdateModal = useCallback(
    (result: DesktopUpdateResponse) => {
      modal.confirm({
        title: t("desktopUpdate.updateAvailable", "Desktop update available"),
        content: (
          <div>
            <p>
              {t("desktopUpdate.newVersion", "New version")}: {result.version}
            </p>
            {result.release_notes ? <p>{result.release_notes}</p> : null}
          </div>
        ),
        okText: t("desktopUpdate.download", "Download"),
        cancelText: t("common.cancel", "Cancel"),
        onOk: () => {
          openExternalLink(result.download_url);
          rememberDismissed(result.version);
        },
        onCancel: () => rememberDismissed(result.version),
      });
    },
    [modal, t],
  );

  const checkForUpdates = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      const platform = detectDesktopUpdatePlatform();
      if (!platform) {
        if (!silent) {
          message.info(
            t(
              "desktopUpdate.unsupportedPlatform",
              "Desktop updates are only available for Windows and macOS.",
            ),
          );
        }
        return null;
      }

      setChecking(true);
      try {
        const { version } = await rootApi.getVersion();
        const result = await desktopUpdateApi.checkUpdate(platform, version);
        setLastResult(result);
        if (result.has_update && result.download_url) {
          if (!silent || !wasDismissed(result.version)) {
            showUpdateModal(result);
          }
        } else if (!silent) {
          message.success(
            t(
              "desktopUpdate.noUpdate",
              "You are already using the latest desktop version.",
            ),
          );
        }
        return result;
      } catch (error) {
        if (!silent) {
          message.error(
            error instanceof Error
              ? error.message
              : t("desktopUpdate.checkFailed", "Failed to check updates."),
          );
        }
        return null;
      } finally {
        setChecking(false);
      }
    },
    [message, showUpdateModal, t],
  );

  return { checking, lastResult, checkForUpdates };
}

export function DesktopUpdateChecker() {
  const { checkForUpdates } = useDesktopUpdateCheck();

  useEffect(() => {
    if (isDesktopApp()) {
      void checkForUpdates({ silent: true });
    }
  }, [checkForUpdates]);

  return null;
}
