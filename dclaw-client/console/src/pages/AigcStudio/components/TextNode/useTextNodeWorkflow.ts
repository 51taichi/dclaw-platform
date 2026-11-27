import { useCallback, type Dispatch, type SetStateAction } from "react";

import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import type { TextFormatAction, TextTryAction, Translate } from "./types";

type UseTextNodeWorkflowArgs = {
  activeCanvas: AigcCanvas | null;
  commitCanvas: (canvas: AigcCanvas) => void;
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  setSelectedNodeId: Dispatch<SetStateAction<string | null>>;
  setEditingTextNodeId: Dispatch<SetStateAction<string | null>>;
  setTextModelMenuNodeId: Dispatch<SetStateAction<string | null>>;
  setContextMenu: (value: null) => void;
  runTextNode?: (node: AigcCanvasNode, canvas: AigcCanvas) => void | Promise<void>;
  runCreatedNode?: (
    node: AigcCanvasNode,
    canvas: AigcCanvas,
  ) => void | Promise<void>;
  t: Translate;
};

const connectNodes = (source: string, target: string): AigcCanvasEdge => ({
  id: `edge-${source}-${target}`,
  source,
  target,
  sourceHandle: "right",
  targetHandle: "left",
});

export function useTextNodeWorkflow({
  activeCanvas,
  commitCanvas,
  updateNodeData,
  setSelectedNodeId,
  setEditingTextNodeId,
  setTextModelMenuNodeId,
  setContextMenu,
  runTextNode,
  runCreatedNode,
  t,
}: UseTextNodeWorkflowArgs) {
  const closeFloatingMenus = useCallback(() => {
    setContextMenu(null);
    setTextModelMenuNodeId(null);
  }, [setContextMenu, setTextModelMenuNodeId]);

  const handleBeginGeneratedEdit = useCallback(
    (nodeId: string) => {
      setSelectedNodeId(nodeId);
      setEditingTextNodeId(nodeId);
    },
    [setEditingTextNodeId, setSelectedNodeId],
  );

  const handleToggleTextModelMenu = useCallback(
    (nodeId: string) => {
      setTextModelMenuNodeId((current) => (current === nodeId ? null : nodeId));
    },
    [setTextModelMenuNodeId],
  );

  const handleSelectTextModel = useCallback(
    (targetNode: AigcCanvasNode, model: AigcCapabilityInfo) => {
      updateNodeData(targetNode.id, {
        modelLabel: model.model_name,
        providerId: model.provider_id,
        providerName: model.provider_name,
        modelId: model.model_id,
        modelCapability: model.capability,
      });
      setTextModelMenuNodeId(null);
    },
    [setTextModelMenuNodeId, updateNodeData],
  );

  const handleTextFormat = useCallback(
    (node: AigcCanvasNode, action: TextFormatAction) => {
      if (!activeCanvas) return;
      const currentText = String(node.data.text ?? "");

      if (action === "duplicate") {
        const copyId = `prompt-copy-${Date.now().toString(36)}`;
        const copy: AigcCanvasNode = {
          ...node,
          id: copyId,
          position: {
            x: node.position.x + 36,
            y: node.position.y + 36,
          },
          data: {
            ...node.data,
            title: `${String(
              node.data.title ?? t("aigcStudio.textNode.title", "文本节点"),
            )} 副本`,
          },
        };
        commitCanvas({
          ...activeCanvas,
          nodes: [...activeCanvas.nodes, copy],
        });
        setSelectedNodeId(copyId);
        return;
      }

      if (action === "clear") {
        updateNodeData(node.id, {
          blockStyle: "paragraph",
          bold: false,
          italic: false,
          listStyle: null,
        });
        return;
      }

      if (["h1", "h2", "h3", "paragraph"].includes(action)) {
        updateNodeData(node.id, { blockStyle: action });
        return;
      }

      if (action === "bold" || action === "italic") {
        updateNodeData(node.id, { [action]: !node.data[action] });
        return;
      }

      if (action === "list" || action === "bullet") {
        updateNodeData(node.id, {
          listStyle: node.data.listStyle === action ? null : action,
        });
        return;
      }

      if (action === "rule") {
        updateNodeData(node.id, {
          text: `${currentText}${currentText ? "\n" : ""}---\n`,
        });
        return;
      }

      updateNodeData(node.id, { expanded: node.data.expanded !== true });
    },
    [activeCanvas, commitCanvas, setSelectedNodeId, t, updateNodeData],
  );

  const handleTextComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      if (!activeCanvas) return;
      const prompt = String(node.data.composerText ?? "").trim();
      if (!prompt) return;
      setEditingTextNodeId(null);
      const nodeSnapshot: AigcCanvasNode = {
        ...node,
        data: {
          ...node.data,
          textMode: "generated",
          text: prompt,
          lastRunPrompt: prompt,
          showTryOptions: false,
        },
      };
      const updatedCanvas = {
        ...activeCanvas,
        nodes: activeCanvas.nodes.map((item) =>
          item.id === node.id ? nodeSnapshot : item,
        ),
      };
      void runTextNode?.(nodeSnapshot, updatedCanvas);
    },
    [activeCanvas, runTextNode, setEditingTextNodeId],
  );

  const handleTextTry = useCallback(
    (node: AigcCanvasNode, action: TextTryAction) => {
      if (!activeCanvas) return;
      const seed = `${Date.now().toString(36)}-${
        activeCanvas.nodes.length + 1
      }`;
      const updateTextNode = (
        data: Record<string, unknown>,
        position = node.position,
      ): AigcCanvasNode => ({
        ...node,
        position,
        data: {
          ...node.data,
          ...data,
          showTryOptions: false,
        },
      });

      if (action === "write") {
        const updated = {
          ...activeCanvas,
          nodes: activeCanvas.nodes.map((item) =>
            item.id === node.id
              ? updateTextNode({ textMode: "write", text: "" })
              : item,
          ),
        };
        commitCanvas(updated);
        setSelectedNodeId(node.id);
        closeFloatingMenus();
        return;
      }

      if (action === "text_to_video") {
        const videoId = `text-video-${seed}`;
        const sourceText = t(
          "aigcStudio.textNode.samples.textToVideo",
          "高级广告镜头，黑色背景中一款高端腕表悬浮出现，镜头从极近距离微距开始，缓慢拉远，金属表面光泽细腻，细节清晰，柔光灯打亮轮廓，商业广告级质感，干净构图，慢速旋转展示。",
        );
        const updated = {
          ...activeCanvas,
          nodes: [
            ...activeCanvas.nodes.map((item) =>
              item.id === node.id
                ? updateTextNode({
                    textMode: "text_to_video",
                    text: sourceText,
                  })
                : item,
            ),
            {
              id: videoId,
              type: "video_generate",
              position: { x: node.position.x + 430, y: node.position.y - 8 },
              data: {
                title: t("aigcStudio.textNode.targets.video", "视频"),
                text: sourceText,
              },
            },
          ],
          edges: [...activeCanvas.edges, connectNodes(node.id, videoId)],
        };
        commitCanvas(updated);
        setSelectedNodeId(videoId);
        closeFloatingMenus();
        const videoNode = updated.nodes.find((item) => item.id === videoId);
        if (videoNode) {
          void runCreatedNode?.(videoNode, updated);
        }
        return;
      }

      if (action === "image_to_prompt") {
        const imageId = `image-prompt-source-${seed}`;
        const promptInput = t(
          "aigcStudio.textNode.composer.imageToPrompt",
          "根据图片生成结构化中文提示词，包括主体描述、环境、光影、镜头语言、风格关键词。",
        );
        const imageNode: AigcCanvasNode = {
          id: imageId,
          type: "reference_asset",
          position: { x: node.position.x - 390, y: node.position.y },
          data: {
            title: t("aigcStudio.textNode.sources.image", "图片"),
            text: "",
            previewKind: "keyframe",
          },
        };
        const updated = {
          ...activeCanvas,
          nodes: [
            imageNode,
            ...activeCanvas.nodes.map((item) =>
              item.id === node.id
                ? updateTextNode({
                    textMode: "image_to_prompt",
                    text: "",
                    composerText: promptInput,
                    referenceThumb: true,
                  })
                : item,
            ),
          ],
          edges: [...activeCanvas.edges, connectNodes(imageId, node.id)],
        };
        commitCanvas(updated);
        setSelectedNodeId(node.id);
        closeFloatingMenus();
        return;
      }

      const audioId = `text-audio-${seed}`;
      const musicText = t(
        "aigcStudio.textNode.samples.textToMusic",
        "生成一首现代品牌电子音乐（约 110 BPM），干净有力的低频贝斯，清晰电子鼓点，整体风格高级、未来感强。开场节奏型贝斯与简洁合成器音色建立律动。",
      );
      const updated = {
        ...activeCanvas,
        nodes: [
          ...activeCanvas.nodes.map((item) =>
            item.id === node.id
              ? updateTextNode({
                  textMode: "text_to_music",
                  text: musicText,
                })
              : item,
          ),
          {
            id: audioId,
            type: "audio_generate",
            position: { x: node.position.x + 430, y: node.position.y },
            data: {
              title: t("aigcStudio.textNode.targets.audio", "音频"),
              audioMode: "music",
              modelCapability: "text_to_audio",
              text: musicText,
            },
          },
        ],
        edges: [...activeCanvas.edges, connectNodes(node.id, audioId)],
      };
      commitCanvas(updated);
      setSelectedNodeId(audioId);
      closeFloatingMenus();
      const audioNode = updated.nodes.find((item) => item.id === audioId);
      if (audioNode) {
        void runCreatedNode?.(audioNode, updated);
      }
    },
    [
      activeCanvas,
      closeFloatingMenus,
      commitCanvas,
      runCreatedNode,
      setSelectedNodeId,
      t,
    ],
  );

  return {
    handleBeginGeneratedEdit,
    handleSelectTextModel,
    handleTextComposerSubmit,
    handleTextFormat,
    handleTextTry,
    handleToggleTextModelMenu,
  };
}
