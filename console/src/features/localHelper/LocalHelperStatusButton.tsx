import { Button, Tooltip } from "antd";
import {
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  MonitorCog,
} from "lucide-react";
import styles from "./LocalHelperStatusButton.module.less";
import { useLocalHelperStatus } from "./LocalHelperStatusContext";

export default function LocalHelperStatusButton() {
  const { state, label, check } = useLocalHelperStatus();

  const icon =
    state === "checking" ? (
      <LoaderCircle size={16} />
    ) : state === "ready" ? (
      <CircleCheck size={16} />
    ) : state !== "idle" ? (
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
        onClick={() => void check()}
      />
    </Tooltip>
  );
}
