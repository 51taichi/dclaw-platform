import { CreditCardOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useNavigate } from "react-router-dom";
import { useBillingWallet } from "./useBillingWallet";

export default function BalanceBadge() {
  const navigate = useNavigate();
  const { wallet, loading, unavailable } = useBillingWallet();
  const available = wallet?.available;
  const text =
    loading || unavailable || available === undefined
      ? "-- 积分"
      : `${available.toLocaleString()} 积分`;
  const held = wallet?.held ?? 0;

  return (
    <Tooltip title={`冻结积分 ${held}`}>
      <Button
        type={
          available !== undefined && available < 100 ? "primary" : "default"
        }
        icon={<CreditCardOutlined />}
        aria-label={
          available === undefined ? "积分余额不可用" : `可用积分 ${available}`
        }
        onClick={() => navigate("/wallet")}
      >
        <span title={`冻结积分 ${held}`}>{text}</span>
      </Button>
    </Tooltip>
  );
}
