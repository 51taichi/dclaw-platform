import { useEffect, useMemo, useRef } from "react";
import type {
  MouseEvent as ReactMouseEvent,
  WheelEvent as ReactWheelEvent,
} from "react";
import { Focus, Map as MapIcon, MousePointer2 } from "lucide-react";
import type { useTranslation } from "react-i18next";

import type {
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { translatedNodeType } from "../../canvasNodeUtils";
import styles from "../../index.module.less";

export type CanvasBounds = {
  minX: number;
  minY: number;
  width: number;
  height: number;
};

type CanvasMinimapProps = {
  minimapOpen: boolean;
  viewportScale: number;
  viewport: AigcCanvas["viewport"];
  visibleWidth: number;
  visibleHeight: number;
  nodes: AigcCanvasNode[];
  selectedNode: AigcCanvasNode | undefined;
  selectedNodeId: string | null;
  canvasBounds: CanvasBounds;
  t: ReturnType<typeof useTranslation>["t"];
  onFitViewport: () => void;
  onCenterSelectedNode: () => void;
  onToggleMinimap: () => void;
  onUpdateViewportScale: (scale: number) => void;
  onCenterNode: (node: AigcCanvasNode) => void;
  onMoveViewport: (viewport: AigcCanvas["viewport"]) => void;
};

type MinimapWorld = {
  minX: number;
  minY: number;
  width: number;
  height: number;
  viewportLeft: number;
  viewportTop: number;
  viewportWidth: number;
  viewportHeight: number;
  viewportCenterX: number;
  viewportCenterY: number;
  scale: number;
};

type MinimapDragState = {
  offsetX: number;
  offsetY: number;
  world: MinimapWorld;
};

const clampRatio = (value: number) => Math.min(1, Math.max(0, value));

export function CanvasMinimap({
  minimapOpen,
  viewportScale,
  viewport,
  visibleWidth,
  visibleHeight,
  nodes,
  selectedNode,
  selectedNodeId,
  canvasBounds,
  t,
  onFitViewport,
  onCenterSelectedNode,
  onToggleMinimap,
  onUpdateViewportScale,
  onCenterNode,
  onMoveViewport,
}: CanvasMinimapProps) {
  const minimapCanvasRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<MinimapDragState | null>(null);
  const minimapLabel = t("aigcStudio.minimap.canvasMap", "画布小地图");
  const zoomRatio = Math.round(viewportScale * 100);
  const minimapWorld = useMemo<MinimapWorld>(() => {
    const scale = Math.max(0.1, viewport.zoom ?? viewportScale);
    const safeVisibleWidth = Math.max(1, visibleWidth);
    const safeVisibleHeight = Math.max(1, visibleHeight);
    const viewportWidth = safeVisibleWidth / scale;
    const viewportHeight = safeVisibleHeight / scale;
    const viewportLeft = -((viewport.x ?? 0) / scale);
    const viewportTop = -((viewport.y ?? 0) / scale);
    const viewportCenterX = viewportLeft + viewportWidth / 2;
    const viewportCenterY = viewportTop + viewportHeight / 2;
    const contentMinX = Math.min(canvasBounds.minX, viewportLeft);
    const contentMinY = Math.min(canvasBounds.minY, viewportTop);
    const contentMaxX = Math.max(
      canvasBounds.minX + canvasBounds.width,
      viewportLeft + viewportWidth,
    );
    const contentMaxY = Math.max(
      canvasBounds.minY + canvasBounds.height,
      viewportTop + viewportHeight,
    );
    const padding = Math.max(
      80,
      Math.min(260, Math.max(canvasBounds.width, canvasBounds.height) * 0.08),
    );
    return {
      minX: contentMinX - padding,
      minY: contentMinY - padding,
      width: Math.max(1, contentMaxX - contentMinX + padding * 2),
      height: Math.max(1, contentMaxY - contentMinY + padding * 2),
      viewportLeft,
      viewportTop,
      viewportWidth,
      viewportHeight,
      viewportCenterX,
      viewportCenterY,
      scale,
    };
  }, [
    canvasBounds.height,
    canvasBounds.minX,
    canvasBounds.minY,
    canvasBounds.width,
    viewport.x,
    viewport.y,
    viewport.zoom,
    viewportScale,
    visibleHeight,
    visibleWidth,
  ]);

  const viewportStyle = {
    left: `${
      ((minimapWorld.viewportLeft - minimapWorld.minX) / minimapWorld.width) *
      100
    }%`,
    top: `${
      ((minimapWorld.viewportTop - minimapWorld.minY) / minimapWorld.height) *
      100
    }%`,
    width: `${(minimapWorld.viewportWidth / minimapWorld.width) * 100}%`,
    height: `${(minimapWorld.viewportHeight / minimapWorld.height) * 100}%`,
  };

  const minimapPointFromClient = (
    clientX: number,
    clientY: number,
    world: MinimapWorld,
  ) => {
    const rect = minimapCanvasRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    return {
      x:
        world.minX +
        clampRatio((clientX - rect.left) / rect.width) * world.width,
      y:
        world.minY +
        clampRatio((clientY - rect.top) / rect.height) * world.height,
    };
  };

  const moveViewportFromMinimap = (
    clientX: number,
    clientY: number,
    dragState: MinimapDragState,
  ) => {
    const point = minimapPointFromClient(clientX, clientY, dragState.world);
    if (!point) return;
    const centerX = point.x - dragState.offsetX;
    const centerY = point.y - dragState.offsetY;
    onMoveViewport({
      ...viewport,
      x: visibleWidth / 2 - centerX * dragState.world.scale,
      y: visibleHeight / 2 - centerY * dragState.world.scale,
      zoom: dragState.world.scale,
    });
  };

  const handleMinimapMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const point = minimapPointFromClient(
      event.clientX,
      event.clientY,
      minimapWorld,
    );
    if (!point) return;
    const insideViewport =
      point.x >= minimapWorld.viewportLeft &&
      point.x <= minimapWorld.viewportLeft + minimapWorld.viewportWidth &&
      point.y >= minimapWorld.viewportTop &&
      point.y <= minimapWorld.viewportTop + minimapWorld.viewportHeight;
    const dragState: MinimapDragState = {
      offsetX: insideViewport ? point.x - minimapWorld.viewportCenterX : 0,
      offsetY: insideViewport ? point.y - minimapWorld.viewportCenterY : 0,
      world: minimapWorld,
    };
    dragStateRef.current = dragState;
    moveViewportFromMinimap(event.clientX, event.clientY, dragState);
  };

  const handleMinimapWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onUpdateViewportScale(viewportScale * Math.exp(-event.deltaY * 0.002));
  };

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState) return;
      event.preventDefault();
      moveViewportFromMinimap(event.clientX, event.clientY, dragState);
    };
    const handleMouseUp = () => {
      dragStateRef.current = null;
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  });

  return (
    <>
      <div
        className={styles.minimapDock}
        data-aigc-floating-panel
        data-testid="aigc-minimap-dock"
        onClick={(event) => event.stopPropagation()}
        onWheel={handleMinimapWheel}
      >
        <button
          type="button"
          aria-label={t("aigcStudio.minimap.fitAll", "适配全部")}
          onClick={onFitViewport}
        >
          <Focus size={15} />
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.minimap.centerSelected", "回到选中")}
          onClick={onCenterSelectedNode}
          disabled={!selectedNode}
        >
          <MousePointer2 size={15} />
        </button>
        <button
          type="button"
          aria-label={minimapLabel}
          title={minimapLabel}
          data-tooltip={minimapLabel}
          className={minimapOpen ? styles.minimapActive : ""}
          onClick={onToggleMinimap}
        >
          <MapIcon size={15} />
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.minimap.zoomOut", "缩小")}
          onClick={() => onUpdateViewportScale(viewportScale - 0.1)}
        >
          -
        </button>
        <span data-testid="aigc-zoom-ratio">{zoomRatio}%</span>
        <button
          type="button"
          aria-label={t("aigcStudio.minimap.zoomIn", "放大")}
          onClick={() => onUpdateViewportScale(viewportScale + 0.1)}
        >
          +
        </button>
      </div>

      {minimapOpen && (
        <div
          className={styles.minimapPanel}
          data-aigc-floating-panel
          data-testid="aigc-minimap"
          onClick={(event) => event.stopPropagation()}
          onWheel={handleMinimapWheel}
        >
          <div
            ref={minimapCanvasRef}
            className={styles.minimapCanvas}
            data-testid="aigc-minimap-canvas"
            onMouseDown={handleMinimapMouseDown}
          >
            {nodes.map((node) => (
              <button
                type="button"
                key={node.id}
                aria-label={t(
                  "aigcStudio.minimap.centerNode",
                  "定位节点 {{title}}",
                  {
                    title: String(
                      node.data.title ?? translatedNodeType(t, node.type),
                    ),
                  },
                )}
                className={`${styles.minimapNode} ${
                  selectedNodeId === node.id ? styles.minimapNodeActive : ""
                }`}
                onClick={() => onCenterNode(node)}
                style={{
                  left: `${
                    ((node.position.x - minimapWorld.minX) /
                      minimapWorld.width) *
                    100
                  }%`,
                  top: `${
                    ((node.position.y - minimapWorld.minY) /
                      minimapWorld.height) *
                    100
                  }%`,
                }}
              />
            ))}
            <div
              className={styles.minimapViewport}
              data-testid="aigc-minimap-viewport"
              style={viewportStyle}
            />
          </div>
        </div>
      )}
    </>
  );
}
