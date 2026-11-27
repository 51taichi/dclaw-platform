import { Scissors } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";

import type { CanvasEdgeLine } from "../../canvasGeometry";
import styles from "../../index.module.less";

type CanvasEdgeLayerProps = {
  edgeLines: CanvasEdgeLine[];
  onDeleteEdge?: (edgeId: string) => void;
};

const EDGE_LONG_PRESS_MS = 500;

type EdgeCutAction = {
  edgeId: string;
  x: number;
  y: number;
};

export function CanvasEdgeLayer({
  edgeLines,
  onDeleteEdge,
}: CanvasEdgeLayerProps) {
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [edgeCutAction, setEdgeCutAction] = useState<EdgeCutAction | null>(
    null,
  );
  const clearLongPressTimer = () => {
    if (!longPressTimerRef.current) return;
    clearTimeout(longPressTimerRef.current);
    longPressTimerRef.current = null;
  };

  useEffect(() => clearLongPressTimer, []);

  const startEdgeLongPress = (
    event: PointerEvent<SVGPathElement>,
    line: CanvasEdgeLine,
  ) => {
    if (!onDeleteEdge || line.id.startsWith("draft-")) return;
    event.stopPropagation();
    const svgBounds =
      event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    const x = event.clientX - (svgBounds?.left ?? 0);
    const y = event.clientY - (svgBounds?.top ?? 0);
    clearLongPressTimer();
    longPressTimerRef.current = setTimeout(() => {
      setEdgeCutAction({ edgeId: line.id, x, y });
      longPressTimerRef.current = null;
    }, EDGE_LONG_PRESS_MS);
  };

  const cancelEdgeLongPress = (event: PointerEvent<SVGPathElement>) => {
    event.stopPropagation();
    clearLongPressTimer();
  };

  return (
    <svg className={styles.edgeLayer} data-testid="aigc-edge-layer">
      <defs>
        <filter
          id="aigc-edge-glow"
          x="-40%"
          y="-40%"
          width="180%"
          height="180%"
        >
          <feGaussianBlur stdDeviation="3.2" result="blur" />
          <feColorMatrix
            in="blur"
            type="matrix"
            values="0 0 0 0 0.12 0 0 0 0 0.63 0 0 0 0 1 0 0 0 0.92 0"
            result="glow"
          />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {edgeLines.map((line) => {
        const isDraftEdge = line.id.startsWith("draft-");
        return (
          <g key={line.id} className={styles.edgeGroup}>
            {!isDraftEdge && (
              <path
                className={styles.edgeHitArea}
                d={line.path}
                data-testid={`aigc-edge-hit-${line.id}`}
                onPointerDown={(event) => startEdgeLongPress(event, line)}
                onMouseDown={(event) => event.stopPropagation()}
                onPointerUp={cancelEdgeLongPress}
                onPointerCancel={cancelEdgeLongPress}
                onPointerLeave={cancelEdgeLongPress}
              />
            )}
          <path className={styles.edgeBase} d={line.path} />
          <path className={styles.edgeCore} d={line.path} />
          <path
            className={styles.edgeFlow}
            d={line.path}
            pathLength={1}
            filter="url(#aigc-edge-glow)"
          />
          <path
            className={styles.edgeFlowSecondary}
            d={line.path}
            pathLength={1}
            filter="url(#aigc-edge-glow)"
          />
          </g>
        );
      })}
      {edgeCutAction && (
        <foreignObject
          className={styles.edgeCutAction}
          x={edgeCutAction.x - 18}
          y={edgeCutAction.y - 18}
          width={36}
          height={36}
        >
          <button
            type="button"
            aria-label="断开连线"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onDeleteEdge?.(edgeCutAction.edgeId);
              setEdgeCutAction(null);
            }}
          >
            <Scissors size={16} />
          </button>
        </foreignObject>
      )}
    </svg>
  );
}
