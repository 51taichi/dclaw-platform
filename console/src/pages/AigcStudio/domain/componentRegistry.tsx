import type { ReactNode } from "react";
import {
  AudioLines,
  Boxes,
  FileText,
  Film,
  Image,
  Layers,
  Link2,
  Newspaper,
  Scissors,
  Type,
  Upload,
} from "lucide-react";

import type { AigcCanvasNode } from "../../../api/modules/aigcStudio";

export type PortSide = "left" | "right";

export type NodeDefinition = {
  type: string;
  titleKey: string;
  titleFallback: string;
  descriptionKey: string;
  descriptionFallback: string;
  capability: string;
  icon: ReactNode;
  menuDescription?: string;
  tag?: string;
  size?: "compact" | "wide" | "tall";
};

export type TemplateVariant = "story" | "character" | "keyframe" | "audioVideo";

type TemplateCardDefinition = {
  titleKey: string;
  titleFallback: string;
  type: string;
  icon: ReactNode;
  variant: TemplateVariant;
};

const SIDEBAR_NODE_TYPES = [
  "prompt",
  "reference_asset",
  "image_generate",
  "video_generate",
  "output",
];

const CONTEXT_MENU_NODE_TYPES = [
  "prompt",
  "image_generate",
  "video_generate",
  "audio_generate",
  "script_generate",
];

const ADD_MENU_NODE_TYPES = [
  "prompt",
  "image_generate",
  "video_generate",
  "long_image_export",
  "video_compose",
  "director_stage",
  "audio_generate",
  "script_generate",
  "reference_asset",
  "reference_note",
];

const PORT_MENU_NODE_TYPES = [
  "prompt",
  "image_generate",
  "video_generate",
  "long_image_export",
  "video_compose",
  "director_stage",
  "audio_generate",
  "script_generate",
  "reference_note",
];

const WORKFLOW_ONLY_NODE_TYPES = ["long_image_export"];

export const NODE_DEFINITIONS: NodeDefinition[] = [
  {
    type: "prompt",
    titleKey: "aigcStudio.nodeLibrary.prompt.title",
    titleFallback: "文本",
    descriptionKey: "aigcStudio.nodeLibrary.prompt.description",
    descriptionFallback: "剧本、广告词、品牌文案",
    capability: "storyboard",
    icon: <Type size={16} />,
    size: "compact",
  },
  {
    type: "image_generate",
    titleKey: "aigcStudio.nodeLibrary.image.title",
    titleFallback: "图片",
    descriptionKey: "aigcStudio.nodeLibrary.image.description",
    descriptionFallback: "文生图、图生图、参考图",
    capability: "text_to_image",
    icon: <Image size={16} />,
    size: "wide",
  },
  {
    type: "video_generate",
    titleKey: "aigcStudio.nodeLibrary.video.title",
    titleFallback: "视频",
    descriptionKey: "aigcStudio.nodeLibrary.video.description",
    descriptionFallback: "文生视频、图生视频、首尾帧",
    capability: "text_to_video",
    icon: <Film size={16} />,
    size: "wide",
  },
  {
    type: "long_image_export",
    titleKey: "aigcStudio.nodeLibrary.longImage.title",
    titleFallback: "公众号长图",
    descriptionKey: "aigcStudio.nodeLibrary.longImage.description",
    descriptionFallback: "小说推文排版、长图切片",
    capability: "long_image_export",
    icon: <Newspaper size={16} />,
    tag: "NEW",
    size: "wide",
  },
  {
    type: "video_compose",
    titleKey: "aigcStudio.nodeLibrary.videoCompose.title",
    titleFallback: "视频合成",
    descriptionKey: "aigcStudio.nodeLibrary.videoCompose.description",
    descriptionFallback: "片段拼接、成片导出",
    capability: "image_to_video",
    icon: <Scissors size={16} />,
    tag: "Beta",
    size: "wide",
  },
  {
    type: "director_stage",
    titleKey: "aigcStudio.nodeLibrary.directorStage.title",
    titleFallback: "导演台",
    descriptionKey: "aigcStudio.nodeLibrary.directorStage.description",
    descriptionFallback: "3D 场景、机位、角色调度",
    capability: "storyboard",
    icon: <Boxes size={16} />,
    tag: "NEW",
    size: "compact",
  },
  {
    type: "audio_generate",
    titleKey: "aigcStudio.nodeLibrary.audio.title",
    titleFallback: "音频",
    descriptionKey: "aigcStudio.nodeLibrary.audio.description",
    descriptionFallback: "配音、音效、音乐",
    capability: "text_to_audio",
    icon: <AudioLines size={16} />,
    size: "compact",
  },
  {
    type: "script_generate",
    titleKey: "aigcStudio.nodeLibrary.script.title",
    titleFallback: "脚本",
    descriptionKey: "aigcStudio.nodeLibrary.script.description",
    descriptionFallback: "剧情分镜、角色分镜",
    capability: "storyboard",
    icon: <FileText size={16} />,
    tag: "NEW",
    size: "compact",
  },
  {
    type: "reference_asset",
    titleKey: "aigcStudio.nodeLibrary.reference.title",
    titleFallback: "参考素材",
    descriptionKey: "aigcStudio.nodeLibrary.reference.description",
    descriptionFallback: "角色图、商品图、风格图",
    capability: "reference_image",
    icon: <Upload size={16} />,
    size: "wide",
  },
  {
    type: "reference_note",
    titleKey: "aigcStudio.nodeLibrary.referenceNode.title",
    titleFallback: "参考节点",
    descriptionKey: "aigcStudio.nodeLibrary.referenceNode.description",
    descriptionFallback: "参考说明，不参与生成",
    capability: "storyboard",
    icon: <Link2 size={16} />,
    size: "wide",
  },
  {
    type: "output",
    titleKey: "aigcStudio.nodeLibrary.output.title",
    titleFallback: "输出/导出",
    descriptionKey: "aigcStudio.nodeLibrary.output.description",
    descriptionFallback: "图片组、视频片段、成片",
    capability: "storyboard",
    icon: <Layers size={16} />,
    size: "compact",
  },
];

export const TEMPLATE_CARDS: TemplateCardDefinition[] = [
  {
    titleKey: "aigcStudio.templates.story.title",
    titleFallback: "故事脚本生成",
    type: "script_generate",
    icon: <FileText size={18} />,
    variant: "story",
  },
  {
    titleKey: "aigcStudio.templates.character.title",
    titleFallback: "角色三视图",
    type: "image_generate",
    icon: <Image size={18} />,
    variant: "character",
  },
  {
    titleKey: "aigcStudio.templates.keyframe.title",
    titleFallback: "首帧图生视频",
    type: "video_generate",
    icon: <Film size={18} />,
    variant: "keyframe",
  },
  {
    titleKey: "aigcStudio.templates.audioVideo.title",
    titleFallback: "音频生视频",
    type: "audio_generate",
    icon: <AudioLines size={18} />,
    variant: "audioVideo",
  },
];

export function nodeDefinition(type: string) {
  return NODE_DEFINITIONS.find((definition) => definition.type === type);
}

export function capabilityForNode(type: string) {
  return nodeDefinition(type)?.capability ?? "storyboard";
}

export function isWorkflowOnlyNodeType(type: string) {
  return WORKFLOW_ONLY_NODE_TYPES.includes(type);
}

export function nodeIcon(type: string) {
  const definition = nodeDefinition(type);
  if (definition) return definition.icon;
  if (type === "image_generate") return <Image size={14} />;
  if (type === "video_generate") return <Film size={14} />;
  if (type === "long_image_export") return <Newspaper size={14} />;
  if (type === "reference_asset") return <Upload size={14} />;
  if (type === "reference_note") return <Link2 size={14} />;
  if (type === "output") return <Layers size={14} />;
  return <Type size={14} />;
}

export function isSidebarNodeType(type: string) {
  return SIDEBAR_NODE_TYPES.includes(type);
}

export function isContextMenuNodeType(type: string) {
  return CONTEXT_MENU_NODE_TYPES.includes(type);
}

export function isAddMenuNodeType(type: string) {
  return ADD_MENU_NODE_TYPES.includes(type);
}

export function isImageLikeNode(node: AigcCanvasNode) {
  return (
    node.type === "image_generate" ||
    (node.type === "reference_asset" &&
      String(node.data.assetKind ?? "image") === "image")
  );
}

export function isVideoLikeNode(node: AigcCanvasNode) {
  return (
    node.type === "video_generate" ||
    (node.type === "reference_asset" &&
      String(node.data.assetKind ?? "") === "video")
  );
}

export function isAudioLikeNode(node: AigcCanvasNode) {
  return (
    node.type === "audio_generate" ||
    (node.type === "reference_asset" &&
      String(node.data.assetKind ?? "") === "audio")
  );
}

export function portMenuDefinitions() {
  return NODE_DEFINITIONS.filter((definition) =>
    PORT_MENU_NODE_TYPES.includes(definition.type),
  );
}

export function enabledPortTypesForNode(node: AigcCanvasNode, side: PortSide) {
  if (side === "left") {
    if (node.type === "prompt") {
      return ["prompt", "image_generate", "video_generate", "reference_note"];
    }
    if (isImageLikeNode(node)) {
      return ["prompt", "image_generate", "reference_note"];
    }
    if (isVideoLikeNode(node)) {
      return [
        "prompt",
        "image_generate",
        "video_generate",
        "video_compose",
        "audio_generate",
        "reference_note",
      ];
    }
    if (isAudioLikeNode(node)) {
      return ["prompt", "reference_note"];
    }
    return ["prompt", "image_generate", "reference_note"];
  }

  const assetKind = String(node.data.assetKind ?? "");
  if (node.type === "reference_note") {
    return ["prompt", "image_generate", "video_generate"];
  }
  if (node.type === "prompt") {
    return [
      "prompt",
      "image_generate",
      "video_generate",
      "script_generate",
      "long_image_export",
    ];
  }
  if (assetKind === "audio" || node.type === "audio_generate") {
    return ["video_generate", "video_compose"];
  }
  if (isImageLikeNode(node)) {
    return [
      "prompt",
      "image_generate",
      "video_generate",
      "director_stage",
      "script_generate",
      "long_image_export",
    ];
  }
  if (isVideoLikeNode(node)) {
    return ["prompt", "video_generate", "video_compose", "script_generate"];
  }
  return ["image_generate", "video_generate"];
}
