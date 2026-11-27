import { useCallback, useState } from "react";

import type { CanvasPoint } from "./canvasAssetFactory";
import type { PortSide } from "./domain/componentRegistry";

export type AddMenuAnchor = {
  x: number;
  y: number;
  position: CanvasPoint;
};

export type NodeContextMenuState = {
  nodeId: string;
  x: number;
  y: number;
};

export type CanvasContextMenuState = {
  x: number;
  y: number;
  position: CanvasPoint;
};

export type QuickTemplateMenuState = {
  x: number;
  y: number;
  position: CanvasPoint;
};

export type PortMenuState = {
  nodeId: string;
  side: PortSide;
  x: number;
  y: number;
};

export function useCanvasFloatingMenus() {
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [addMenuAnchor, setAddMenuAnchor] = useState<AddMenuAnchor | null>(
    null,
  );
  const [contextMenu, setContextMenu] = useState<NodeContextMenuState | null>(
    null,
  );
  const [canvasContextMenu, setCanvasContextMenu] =
    useState<CanvasContextMenuState | null>(null);
  const [quickTemplateMenu, setQuickTemplateMenu] =
    useState<QuickTemplateMenuState | null>(null);
  const [portMenu, setPortMenu] = useState<PortMenuState | null>(null);

  const closeCanvasMenus = useCallback(() => {
    setAddMenuOpen(false);
    setAddMenuAnchor(null);
    setContextMenu(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
  }, []);

  const openAddMenu = useCallback((anchor: AddMenuAnchor) => {
    setAddMenuAnchor(anchor);
    setAddMenuOpen(true);
    setContextMenu(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
  }, []);

  const openCanvasContextMenu = useCallback((menu: CanvasContextMenuState) => {
    setCanvasContextMenu(menu);
    setAddMenuOpen(false);
    setAddMenuAnchor(null);
    setContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
  }, []);

  const openNodeContextMenu = useCallback((menu: NodeContextMenuState) => {
    setContextMenu(menu);
    setAddMenuOpen(false);
    setAddMenuAnchor(null);
    setCanvasContextMenu(null);
    setQuickTemplateMenu(null);
    setPortMenu(null);
  }, []);

  const openPortMenu = useCallback((menu: PortMenuState) => {
    setPortMenu(menu);
    setAddMenuOpen(false);
    setAddMenuAnchor(null);
    setCanvasContextMenu(null);
    setContextMenu(null);
  }, []);

  return {
    addMenuOpen,
    setAddMenuOpen,
    addMenuAnchor,
    setAddMenuAnchor,
    contextMenu,
    setContextMenu,
    canvasContextMenu,
    setCanvasContextMenu,
    quickTemplateMenu,
    setQuickTemplateMenu,
    portMenu,
    setPortMenu,
    closeCanvasMenus,
    openAddMenu,
    openCanvasContextMenu,
    openNodeContextMenu,
    openPortMenu,
  };
}
