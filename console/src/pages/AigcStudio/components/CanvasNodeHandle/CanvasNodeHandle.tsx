import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { Plus } from "lucide-react";

import {
  NODE_HANDLE_OUTSET,
  NODE_HANDLE_SIZE,
} from "../../canvasHandleGeometry";
import type { PortSide } from "../../domain/componentRegistry";
import styles from "../../index.module.less";

type CanvasNodeHandleProps = {
  nodeId: string;
  side: PortSide;
  label: string;
  onClick: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  onMouseDown: (event: ReactMouseEvent<HTMLButtonElement>) => void;
};

const handleStyle = {
  "--aigc-node-handle-size": `${NODE_HANDLE_SIZE}px`,
  "--aigc-node-handle-outset": `${NODE_HANDLE_OUTSET}px`,
} as CSSProperties;

export function CanvasNodeHandle({
  nodeId,
  side,
  label,
  onClick,
  onMouseDown,
}: CanvasNodeHandleProps) {
  return (
    <button
      type="button"
      className={
        side === "left" ? styles.nodeHandleLeft : styles.nodeHandleRight
      }
      aria-label={label}
      data-aigc-node-handle="true"
      data-aigc-node-id={nodeId}
      data-aigc-handle-side={side}
      onClick={onClick}
      onMouseDown={onMouseDown}
      style={handleStyle}
    >
      <Plus size={14} strokeWidth={2.4} />
    </button>
  );
}
