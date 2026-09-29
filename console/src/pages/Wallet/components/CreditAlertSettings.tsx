import { useEffect, useState } from "react";
import { Alert, Button, Card, Input, InputNumber, Space, Spin } from "antd";
import { billingApi } from "../../../api/modules/billing";
import styles from "./CreditAlertSettings.module.less";

const MAX_THRESHOLD = Number.MAX_SAFE_INTEGER;
const CN_MOBILE_PATTERN = /^(?:\+86)?1[3-9]\d{9}$/;

export default function CreditAlertSettings() {
  const [warning, setWarning] = useState<number | null>(null);
  const [critical, setCritical] = useState<number | null>(null);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [phoneLocked, setPhoneLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    billingApi
      .getCreditAlerts()
      .then((resource) => {
        if (!active) return;
        setWarning(resource.preferences.warning_threshold);
        setCritical(resource.preferences.critical_threshold);
        setPhoneNumber(resource.phone_number ?? "");
        setPhoneLocked(Boolean(resource.phone_number));
        setError(null);
      })
      .catch(() => active && setError("预警设置暂时不可用"))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const save = async () => {
    if (
      warning === null ||
      critical === null ||
      !Number.isInteger(warning) ||
      !Number.isInteger(critical) ||
      critical < 0 ||
      critical >= warning ||
      warning > MAX_THRESHOLD
    ) {
      setError("严重预警积分必须大于等于 0，且小于预警积分");
      return;
    }
    const trimmedPhone = phoneNumber.trim();
    if (!CN_MOBILE_PATTERN.test(trimmedPhone)) {
      setError("请输入有效的中国大陆手机号");
      return;
    }
    setSaving(true);
    try {
      const resource = await billingApi.updateCreditAlertPreferences({
        warning_threshold: warning,
        critical_threshold: critical,
      });
      setWarning(resource.preferences.warning_threshold);
      setCritical(resource.preferences.critical_threshold);
      if (!phoneLocked) {
        const phoneResource = await billingApi.updateCreditAlertPhone({
          phone_number: trimmedPhone,
        });
        setPhoneNumber(phoneResource.phone_number ?? trimmedPhone);
        setPhoneLocked(true);
      }
      setError(null);
      window.dispatchEvent(new CustomEvent("dclaw:credit-alert-changed"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "预警设置保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="积分预警提醒" size="small">
      {loading ? (
        <Spin />
      ) : error === "预警设置暂时不可用" ? (
        <Alert type="warning" message={error} />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {error && <Alert type="error" message={error} />}
          <div className={styles.formRow}>
            <Space wrap className={styles.fields}>
              <label className={styles.field}>
                预警积分
                <InputNumber
                  aria-label="预警积分"
                  max={MAX_THRESHOLD}
                  precision={0}
                  value={warning}
                  onChange={setWarning}
                />
              </label>
              <label className={styles.field}>
                严重预警积分
                <InputNumber
                  aria-label="严重预警积分"
                  max={MAX_THRESHOLD}
                  precision={0}
                  value={critical}
                  onChange={setCritical}
                />
              </label>
              <label className={styles.field}>
                客户手机号
                <Space.Compact>
                  <Input
                    aria-label="客户手机号"
                    disabled={phoneLocked}
                    placeholder="请输入手机号"
                    value={phoneNumber}
                    onChange={(event) => setPhoneNumber(event.target.value)}
                  />
                  {phoneLocked && (
                    <Button onClick={() => setPhoneLocked(false)}>
                      修改手机号
                    </Button>
                  )}
                </Space.Compact>
              </label>
            </Space>
            <Button
              className={styles.saveButton}
              type="primary"
              loading={saving}
              onClick={save}
            >
              保存预警设置
            </Button>
          </div>
        </Space>
      )}
    </Card>
  );
}
