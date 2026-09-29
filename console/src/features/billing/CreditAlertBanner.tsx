import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Space } from "antd";
import { useNavigate } from "react-router-dom";
import { billingApi } from "../../api/modules/billing";
import type { CreditAlertResource } from "../../api/types/billing";
import styles from "./CreditAlertBanner.module.less";

const REFRESH_INTERVAL_MS = 60_000;

export default function CreditAlertBanner() {
  const navigate = useNavigate();
  const [resource, setResource] = useState<CreditAlertResource | null>(null);
  const [dismissing, setDismissing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setResource(await billingApi.getCreditAlerts());
    } catch {
      setResource(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const listener = () => void refresh();
    window.addEventListener("dclaw:billing-settled", listener);
    window.addEventListener("dclaw:credit-alert-changed", listener);
    const timer = window.setInterval(listener, REFRESH_INTERVAL_MS);
    return () => {
      window.removeEventListener("dclaw:billing-settled", listener);
      window.removeEventListener("dclaw:credit-alert-changed", listener);
      window.clearInterval(timer);
    };
  }, [refresh]);

  const alert = resource?.alert;
  if (!alert) return null;
  const critical = alert.tier === "critical";

  const dismiss = async () => {
    setDismissing(true);
    try {
      await billingApi.dismissCreditAlert(alert.tier);
      await refresh();
    } catch {
      // Keep the confirmed server resource visible when dismissal fails.
    } finally {
      setDismissing(false);
    }
  };

  return (
    <Alert
      className={`${styles.banner} ${critical ? styles.critical : styles.warning}`}
      type={critical ? "error" : "warning"}
      showIcon
      message={critical ? "积分严重不足" : "积分不足提醒"}
      description={`当前可用积分 ${alert.available.toLocaleString()}，已达到 ${alert.threshold.toLocaleString()} 积分预警线，请及时充值。`}
      action={(
        <Space wrap>
          <Button size="small" onClick={() => navigate("/wallet")}>去充值</Button>
          <Button size="small" loading={dismissing} onClick={() => void dismiss()}>不再提醒</Button>
        </Space>
      )}
    />
  );
}
