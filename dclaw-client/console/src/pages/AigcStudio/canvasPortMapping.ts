import type { AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  annotationInputFromNode,
  isImageAnnotationNode,
  isStyleTemplateNode,
  nodeReferenceName,
  nodeReferencePreviewSource,
  type Translate,
} from "./canvasNodeUtils";

export function nodeDataForContextTarget(t: Translate, contextType: string) {
  if (contextType === "prompt") {
    return {
      text: t(
        "aigcStudio.port.contextPrompt",
        "为当前节点补充提示词、镜头、风格或角色设定。",
      ),
      showTryOptions: false,
    };
  }
  if (contextType === "reference_note") {
    return {
      title: t("aigcStudio.nodeLibrary.referenceNode.title", "参考节点"),
      text: "",
      placeholder: t(
        "aigcStudio.referenceNode.hint",
        "双击输入参考说明（不参与生成）",
      ),
      participatesInGeneration: false,
      showTryOptions: false,
    };
  }
  return {
    showTryOptions: false,
    inputUpdated: true,
  };
}

export function edgeRoleForSource(node: AigcCanvasNode) {
  if (node.type === "prompt") return "prompt";
  if (node.type === "reference_note") return "reference_note";
  if (isImageAnnotationNode(node)) return "image_annotation";
  if (isStyleTemplateNode(node)) return "style_template";
  if (String(node.data.assetKind ?? "") === "audio") return "audio";
  if (
    node.type === "video_generate" ||
    String(node.data.assetKind ?? "") === "video"
  ) {
    return "reference_video";
  }
  return "reference_image";
}

const sourceReferenceName = (node: AigcCanvasNode) => {
  return nodeReferenceName(node) ?? "";
};

const sourceReferencePreviewUrl = (node: AigcCanvasNode) => {
  return nodeReferencePreviewSource(node) ?? "";
};

function targetReferenceModeData(
  t: Translate,
  sourceNode: AigcCanvasNode,
  targetType: string,
) {
  const sourceKind = String(
    sourceNode.data.assetKind ??
      (sourceNode.type === "video_generate"
        ? "video"
        : sourceNode.type === "audio_generate"
        ? "audio"
        : "image"),
  );
  if (targetType === "video_generate") {
    const usesReferenceMode = sourceKind === "audio" || sourceKind === "video";
    return {
      activeVideoTab: usesReferenceMode ? "all_reference" : "image_to_video",
      videoMode: usesReferenceMode ? "reference" : "image_to_video",
      composerPlaceholder:
        sourceKind === "audio"
          ? t(
              "aigcStudio.videoNode.composer.audioReference",
              "根据音频节奏与描述生成视频。",
            )
          : sourceKind === "video"
          ? t(
              "aigcStudio.videoNode.composer.videoReference",
              "参考当前视频与描述生成视频。",
            )
          : t(
              "aigcStudio.videoNode.composer.firstFrame",
              "以当前图为首帧生成视频。",
            ),
    };
  }
  if (targetType === "image_generate") {
    return {
      imageMode: "image_to_image",
      composerPlaceholder: t(
        "aigcStudio.imageNode.composer.imageToImage",
        "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
      ),
    };
  }
  return {};
}

function annotationReferenceData(
  t: Translate,
  sourceNode: AigcCanvasNode,
  targetType: string,
) {
  const annotation = annotationInputFromNode(sourceNode);
  const referenceName = String(
    annotation.asset_name || sourceReferenceName(sourceNode),
  );
  const sourcePreviewUrl = String(
    annotation.source_preview_url || annotation.preview_url || "",
  );
  const annotatedPreviewUrl = String(
    annotation.annotated_preview_url || annotation.preview_url || "",
  );

  return {
    showTryOptions: false,
    inputUpdated: true,
    referenceThumb: true,
    referenceAssetName: referenceName,
    referencePreviewUrl: sourcePreviewUrl || annotatedPreviewUrl,
    annotationThumb: true,
    annotationAssetName: referenceName,
    annotationPreviewUrl: annotatedPreviewUrl,
    annotationSourcePreviewUrl: sourcePreviewUrl || annotatedPreviewUrl,
    annotationInstruction: annotation.instruction,
    annotationMode: "region_edit",
    imageEditScope: "annotated_region",
    ...targetReferenceModeData(t, sourceNode, targetType),
  };
}

export function downstreamDataFromSource(
  t: Translate,
  sourceNode: AigcCanvasNode,
  targetType: string,
) {
  if (targetType === "long_image_export") {
    return {
      showTryOptions: false,
      inputUpdated: true,
    };
  }

  const sourceText = String(sourceNode.data.text ?? "").trim();
  if (sourceNode.type === "prompt") {
    if (targetType === "image_generate") {
      return {
        showTryOptions: false,
        inputUpdated: true,
      };
    }
    return {
      text: sourceText,
      composerText: sourceText,
      showTryOptions: false,
      inputUpdated: true,
    };
  }
  if (sourceNode.type === "reference_note") {
    return {
      showTryOptions: false,
      inputUpdated: false,
    };
  }
  if (isImageAnnotationNode(sourceNode)) {
    return annotationReferenceData(t, sourceNode, targetType);
  }
  if (sourceNode.type === "reference_asset") {
    const referenceName = sourceReferenceName(sourceNode);
    const referencePreviewUrl = sourceReferencePreviewUrl(sourceNode);
    if (isStyleTemplateNode(sourceNode)) {
      const styleTemplateUuid = String(
        sourceNode.data.styleTemplateUuid ??
          sourceNode.data.effectTemplateUuid ??
          "",
      );
      const effectId = sourceNode.data.effectId;
      return {
        showTryOptions: false,
        inputUpdated: true,
        styleReferenceThumb: true,
        styleReferenceName: referenceName,
        styleReferencePreviewUrl: referencePreviewUrl,
        stylePreset: referenceName,
        styleTemplateUuid,
        ...(styleTemplateUuid
          ? { effectTemplateUuids: [styleTemplateUuid] }
          : {}),
        ...(typeof effectId === "number" || typeof effectId === "string"
          ? { effectId, effects: [effectId] }
          : {}),
        ...(sourceNode.data.styleKeywords
          ? { styleKeywords: sourceNode.data.styleKeywords }
          : {}),
        ...(sourceNode.data.styleDescription
          ? { styleDescription: sourceNode.data.styleDescription }
          : {}),
        ...(sourceNode.data.styleSupplementalPrompt
          ? {
              styleSupplementalPrompt: sourceNode.data.styleSupplementalPrompt,
            }
          : {}),
        ...(Array.isArray(sourceNode.data.visualDna)
          ? { visualDna: sourceNode.data.visualDna }
          : {}),
        ...(Array.isArray(sourceNode.data.styleReferenceImages)
          ? { styleReferenceImages: sourceNode.data.styleReferenceImages }
          : {}),
        ...(sourceNode.data.aestheticProfileSnapshot &&
        typeof sourceNode.data.aestheticProfileSnapshot === "object"
          ? {
              aestheticProfileSnapshot:
                sourceNode.data.aestheticProfileSnapshot,
            }
          : {}),
      };
    }
    return {
      showTryOptions: false,
      inputUpdated: true,
      referenceThumb: true,
      referenceAssetName: referenceName,
      referencePreviewUrl,
      ...targetReferenceModeData(t, sourceNode, targetType),
    };
  }
  return {
    showTryOptions: false,
    inputUpdated: true,
    referenceThumb: true,
    referenceAssetName: sourceReferenceName(sourceNode),
    referencePreviewUrl: sourceReferencePreviewUrl(sourceNode),
    ...targetReferenceModeData(t, sourceNode, targetType),
  };
}
