import { useEffect, useState } from "react";
import { Alert, Button, Card, InputNumber, Space, Spin } from "antd";
import { billingApi } from "../../../api/modules/billing";

const MAX_THRESHOLD = Number.MAX_SAFE_INTEGER;

export default function CreditAlertSettings() {
  const [warning, setWarning] = useState<number | null>(null);
  const [critical, setCritical] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    billingApi.getCreditAlerts()
      .then((resource) => {
        if (!active) return;
        setWarning(resource.preferences.warning_threshold);
        setCritical(resource.preferences.critical_threshold);
        setError(null);
      })
      .catch(() => active && setError("预警设置暂时不可用"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  const save = async () => {
    if (
      warning === null || critical === null || !Number.isInteger(warning) ||
      !Number.isInteger(critical) || critical < 0 || critical >= warning ||
      warning > MAX_THRESHOLD
    ) {
      setError("严重预警积分必须大于等于 0，且小于预警积分");
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
      {loading ? <Spin /> : error === "预警设置暂时不可用" ? (
        <Alert type="warning" message={error} />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>余额达到对应积分时显示醒目提醒；默认值为 5,000 和 1,000。</div>
          {error && <Alert type="error" message={error} />}
          <Space wrap>
            <label>
              预警积分
              <InputNumber
                aria-label="预警积分" max={MAX_THRESHOLD} precision={0}
                value={warning} onChange={setWarning}
              />
            </label>
            <label>
              严重预警积分
              <InputNumber
                aria-label="严重预警积分" max={MAX_THRESHOLD} precision={0}
                value={critical} onChange={setCritical}
              />
            </label>
          </Space>
          <Button type="primary" loading={saving} onClick={save}>保存预警设置</Button>
        </Space>
      )}
    </Card>
  );
}
