import type {
  AigcCanvasEdge,
  AigcCanvasNode,
  CanvasPayload,
} from "../../api/modules/aigcStudio";
import { nodeTitle, type Translate } from "./canvasNodeUtils";
import {
  SCRIPT_SHOTS,
  SCRIPT_STORY_SOURCE_TEXT,
} from "./components/ScriptNode/scriptNodeState";
import {
  nodeDefinition,
  type TemplateVariant,
} from "./domain/componentRegistry";

export const DEFAULT_EDGES = [
  { id: "edge-1", source: "prompt-1", target: "image-1" },
  { id: "edge-2", source: "image-1", target: "video-1" },
  { id: "edge-3", source: "reference-1", target: "video-1" },
];

type TemplateParts = {
  nodes: AigcCanvasNode[];
  edges: AigcCanvasEdge[];
  selectedNodeId: string;
};

export function getDefaultNodes(t: Translate): AigcCanvasNode[] {
  return [
    {
      id: "prompt-1",
      type: "prompt",
      position: { x: 80, y: 90 },
      data: {
        title: t("aigcStudio.defaultNodes.prompt.title", "营销提示词"),
        text: t(
          "aigcStudio.defaultNodes.prompt.text",
          "带有清晰品牌氛围的电影感产品片创意。",
        ),
      },
    },
    {
      id: "image-1",
      type: "image_generate",
      position: { x: 360, y: 80 },
      data: {
        title: t("aigcStudio.defaultNodes.image.title", "主视觉图片"),
        text: t(
          "aigcStudio.defaultNodes.image.text",
          "基于选中的提示词生成图片变体。",
        ),
      },
    },
    {
      id: "video-1",
      type: "video_generate",
      position: { x: 610, y: 250 },
      data: {
        title: t("aigcStudio.defaultNodes.video.title", "动态片段"),
        text: t(
          "aigcStudio.defaultNodes.video.text",
          "使用生成的关键帧和参考素材生成视频。",
        ),
      },
    },
    {
      id: "reference-1",
      type: "reference_asset",
      position: { x: 160, y: 310 },
      data: {
        title: t("aigcStudio.defaultNodes.reference.title", "参考素材板"),
        text: t(
          "aigcStudio.defaultNodes.reference.text",
          "收集角色、物体、风格和品牌资产。",
        ),
      },
    },
  ];
}

export function defaultCanvasPayload(
  t: Translate,
  name: string,
): CanvasPayload {
  return {
    name,
    nodes: getDefaultNodes(t),
    edges: DEFAULT_EDGES,
    viewport: { x: 0, y: 0, zoom: 1 },
    thumbnail: null,
    meta: { version: 1 },
  };
}

export function emptyCanvasPayload(name: string): CanvasPayload {
  return {
    name,
    nodes: [],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    thumbnail: null,
    meta: { version: 1 },
  };
}

function nodeGridPosition(nodeCount: number) {
  return {
    x: 120 + (nodeCount % 4) * 240,
    y: 120 + Math.floor(nodeCount / 4) * 180,
  };
}

function generatedNodeId(type: string, nodeCount: number) {
  return `${type}-${Date.now().toString(36)}-${nodeCount + 1}`;
}

export function createNodeForType(
  t: Translate,
  type: string,
  nodeCount: number,
): AigcCanvasNode {
  const definition = nodeDefinition(type);
  if (type === "prompt") {
    return {
      id: generatedNodeId(type, nodeCount),
      type,
      position: nodeGridPosition(nodeCount),
      data: {
        title: t("aigcStudio.textNode.title", "文本节点"),
        text: "",
        textMode: "blank",
        showTryOptions: true,
      },
    };
  }
  if (type === "image_generate") {
    return {
      id: generatedNodeId(type, nodeCount),
      type,
      position: nodeGridPosition(nodeCount),
      data: {
        title: t("aigcStudio.imageNode.title", "图片节点"),
        text: "",
        imageMode: "blank",
        showTryOptions: true,
        aspectRatio: "16:9",
        resolution: "2K",
        imageCount: 1,
      },
    };
  }
  if (type === "video_generate") {
    return {
      id: generatedNodeId(type, nodeCount),
      type,
      position: nodeGridPosition(nodeCount),
      data: {
        title: t("aigcStudio.videoNode.title", "视频节点"),
        text: "",
        videoMode: "blank",
        showTryOptions: true,
        aspectRatio: "16:9",
        videoResolution: "720P",
        videoDuration: 5,
        videoAudio: true,
        videoCount: 1,
        activeVideoTab: "text_to_video",
      },
    };
  }
  if (type === "script_generate") {
    return {
      id: generatedNodeId(type, nodeCount),
      type,
      position: nodeGridPosition(nodeCount),
      data: {
        title: t("aigcStudio.templateNodes.storyGenerate.title", "脚本生成器"),
        text: t(
          "aigcStudio.templateNodes.storyGenerate.text",
          "根据上传的脚本生成一个完整的故事脚本",
        ),
        scriptMode: "idle",
        scriptView: "script",
        scriptInputKind: "script",
        scriptPrompt: t(
          "aigcStudio.scriptNode.defaultPrompt",
          "根据我上传的脚本生成一个完整的故事脚本",
        ),
        selectedShotIds: SCRIPT_SHOTS.map((shot) => shot.id),
      },
    };
  }
  if (type === "reference_note") {
    return {
      id: generatedNodeId(type, nodeCount),
      type,
      position: nodeGridPosition(nodeCount),
      data: {
        title: t("aigcStudio.nodeLibrary.referenceNode.title", "参考节点"),
        text: "",
        placeholder: t(
          "aigcStudio.referenceNode.hint",
          "双击输入参考说明（不参与生成）",
        ),
        participatesInGeneration: false,
        showTryOptions: false,
      },
    };
  }
  const defaultNode = getDefaultNodes(t).find((node) => node.type === type);
  return {
    id: generatedNodeId(type, nodeCount),
    type,
    position: nodeGridPosition(nodeCount),
    data: defaultNode?.data ?? {
      title:
        type === "audio_generate"
          ? t("aigcStudio.nodeType.audio_generate", "音频生成")
          : type === "script_generate"
          ? t("aigcStudio.nodeType.script_generate", "脚本生成")
          : nodeTitle(t, type),
      text: definition
        ? t(definition.descriptionKey, definition.descriptionFallback)
        : "",
    },
  };
}

const edge = (source: string, target: string): AigcCanvasEdge => ({
  id: `edge-${source}-${target}`,
  source,
  target,
  sourceHandle: "right",
  targetHandle: "left",
});

export function createTemplateParts(
  t: Translate,
  variant: TemplateVariant,
  nodeCount: number,
): TemplateParts {
  const seed = `${variant}-${Date.now().toString(36)}-${nodeCount + 1}`;

  if (variant === "story") {
    const sourceId = `story-source-${seed}`;
    const targetId = `story-generate-${seed}`;
    return {
      selectedNodeId: targetId,
      nodes: [
        {
          id: sourceId,
          type: "prompt",
          position: { x: 130, y: 170 },
          data: {
            title: t("aigcStudio.textNode.title", "文本"),
            text: SCRIPT_STORY_SOURCE_TEXT,
            textMode: "write",
            previewKind: "script",
          },
        },
        {
          id: targetId,
          type: "script_generate",
          position: { x: 500, y: 170 },
          data: {
            title: t(
              "aigcStudio.templateNodes.storyGenerate.title",
              "脚本生成器",
            ),
            text: t(
              "aigcStudio.templateNodes.storyGenerate.text",
              "根据上传的脚本生成一个完整的故事脚本",
            ),
            scriptMode: "idle",
            scriptView: "script",
            scriptInputKind: "script",
            scriptPrompt: t(
              "aigcStudio.scriptNode.defaultPrompt",
              "根据我上传的脚本生成一个完整的故事脚本",
            ),
            selectedShotIds: SCRIPT_SHOTS.map((shot) => shot.id),
          },
        },
      ],
      edges: [edge(sourceId, targetId)],
    };
  }

  if (variant === "character") {
    const sourceId = `character-source-${seed}`;
    const targetId = `character-turnaround-${seed}`;
    return {
      selectedNodeId: targetId,
      nodes: [
        {
          id: sourceId,
          type: "reference_asset",
          position: { x: 80, y: 150 },
          data: {
            title: t(
              "aigcStudio.templateNodes.characterSource.title",
              "角色图",
            ),
            text: "",
            previewKind: "characterPortrait",
          },
        },
        {
          id: targetId,
          type: "image_generate",
          position: { x: 460, y: 150 },
          data: {
            title: t(
              "aigcStudio.templateNodes.characterTarget.title",
              "角色三视图",
            ),
            text: t(
              "aigcStudio.templateNodes.characterTarget.text",
              "根据角色参考图生成正面、侧面、背面三视图",
            ),
            previewKind: "turnaround",
          },
        },
      ],
      edges: [edge(sourceId, targetId)],
    };
  }

  if (variant === "keyframe") {
    const sourceId = `keyframe-source-${seed}`;
    const targetId = `keyframe-video-${seed}`;
    return {
      selectedNodeId: targetId,
      nodes: [
        {
          id: sourceId,
          type: "reference_asset",
          position: { x: 140, y: 145 },
          data: {
            title: t("aigcStudio.templateNodes.keyframeSource.title", "首帧"),
            text: "",
            previewKind: "keyframe",
          },
        },
        {
          id: targetId,
          type: "video_generate",
          position: { x: 520, y: 150 },
          data: {
            title: t("aigcStudio.templateNodes.keyframeTarget.title", "视频"),
            text: t(
              "aigcStudio.templateNodes.keyframeTarget.text",
              "根据首帧图片生成对应动态视频",
            ),
          },
        },
      ],
      edges: [edge(sourceId, targetId)],
    };
  }

  const audioId = `audio-source-${seed}`;
  const imageId = `audio-image-${seed}`;
  const targetId = `audio-video-${seed}`;
  return {
    selectedNodeId: targetId,
    nodes: [
      {
        id: audioId,
        type: "audio_generate",
        position: { x: 130, y: 120 },
        data: {
          title: t("aigcStudio.templateNodes.audioSource.title", "音频"),
          text: "00:00 / 00:03",
          previewKind: "audioWave",
        },
      },
      {
        id: imageId,
        type: "reference_asset",
        position: { x: 130, y: 360 },
        data: {
          title: t("aigcStudio.templateNodes.audioImage.title", "图片"),
          text: "",
          previewKind: "portrait",
        },
      },
      {
        id: targetId,
        type: "video_generate",
        position: { x: 520, y: 210 },
        data: {
          title: t("aigcStudio.templateNodes.audioVideo.title", "视频"),
          text: t(
            "aigcStudio.templateNodes.audioVideo.text",
            "根据上传的音频生成对应场景画面，镜头语言、节奏、音乐匹配情绪变化，电影级质感。",
          ),
        },
      },
    ],
    edges: [edge(audioId, targetId), edge(imageId, targetId)],
  };
}
