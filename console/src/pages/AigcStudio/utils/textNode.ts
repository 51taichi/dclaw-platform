import type { AigcCanvasNode } from "../../../api/modules/aigcStudio";

export function isScriptSourceTextNode(node: AigcCanvasNode) {
  return node.type === "prompt" && node.data.previewKind === "script";
}

export function isTextWriteMode(node: AigcCanvasNode) {
  return (
    node.type === "prompt" &&
    (node.data.textMode === "write" || isScriptSourceTextNode(node))
  );
}

export function isGeneratedTextNode(node: AigcCanvasNode) {
  const textMode = String(node.data.textMode ?? "blank");
  return (
    node.type === "prompt" &&
    !node.data.previewKind &&
    node.data.showTryOptions !== true &&
    String(node.data.text ?? "").trim().length > 0 &&
    textMode !== "write"
  );
}
