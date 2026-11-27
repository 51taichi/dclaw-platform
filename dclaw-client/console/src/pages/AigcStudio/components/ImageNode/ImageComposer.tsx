import {
  AlertCircle,
  Camera,
  FileText,
  Focus,
  Image,
  Maximize2,
  MousePointer2,
  Pencil,
  Play,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";

import {
  aigcStudioApi,
  type AigcCapabilityInfo,
  type AigcStyleTemplate,
  type AigcStyleTemplateType,
  type VisualDnaDimension,
  type VisualDnaDimensionInfo,
  type VisualDnaElement,
  type VisualDnaSelection,
} from "../../../../api/modules/aigcStudio";
import { useAuth } from "../../../../contexts/AuthContext";
import { assetPreviewSource } from "../../canvasNodeUtils";
import styles from "../../index.module.less";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import { PromptFullscreenEditor } from "../PromptFullscreenEditor";
import {
  AIGC_REFERENCE_ASSET_MIME,
  insertReferenceAlias,
  readReferenceAssetDragData,
  writeReferenceAssetDragData,
} from "../referenceAssetDrag";
import { useAutoGrowTextarea } from "../useAutoGrowTextarea";
import {
  DEFAULT_IMAGE_ASPECT_RATIO,
  DEFAULT_IMAGE_CAMERA_PRESET,
  IMAGE_FOCUS_OPTIONS,
  IMAGE_MARK_OPTIONS,
  IMAGE_QUALITY_OPTIONS,
  IMAGE_SLASH_COMMANDS,
  IMAGE_STYLE_OPTIONS,
  PANORAMA_IMAGE_ASPECT_RATIO,
  imageModelForNode,
  imageModelOptionsFrom,
  imageModelDisplayName,
  imageNodeStateFromNode,
  isPanoramaImageNode,
} from "./imageNodeState";
import {
  imageModelParameterProfileFor,
  imageGenerationParametersForProfile,
  imageSizeParameterSummary,
  normalizedImageParameterSelection,
} from "./imageModelParameterProfile";
import { estimatedImageGenerationSecondsLabel } from "../../generationProgress";
import type { ImagePromptToolKey } from "./imageModelParameterProfile";
import { imageStyleTemplateData } from "./imageStyleTemplates";
import type { ImageComposerProps } from "./types";

type ImageToolKey = ImagePromptToolKey;
type ImageToolDataKey = "stylePreset" | "markPreset" | "focusPreset";
type StyleGalleryMode = "all" | "favorites" | "recent";
type StyleGalleryTemplateKind = AigcStyleTemplateType;
type ReferenceAsset = NonNullable<
  ImageComposerProps["referenceAssets"]
>[number];
type ReferenceMentionState = {
  query: string;
  start: number;
  end: number;
};

const ASPECT_RATIO_PREVIEW_MAX_WIDTH = 18;
const ASPECT_RATIO_PREVIEW_MAX_HEIGHT = 12;
const ASPECT_RATIO_PREVIEW_MIN_EDGE = 4;
const STYLE_GALLERY_CATEGORIES = [
  "推荐",
  "我的风格",
  "海报场景",
  "摄影写真",
  "电商营销",
  "动漫游戏",
  "风格插画",
  "平面设计",
  "建筑及室内设计",
  "文创周边",
  "小说推文",
];
const CREATION_TEMPLATE_CATEGORIES = [
  "推荐",
  "海报场景",
  "电商营销",
  "文创周边",
  "小说推文",
];
const AESTHETIC_PROFILE_DIMENSIONS = new Set<VisualDnaDimension>([
  "art_direction",
  "lighting",
  "color",
  "material",
  "emotion",
  "environment",
]);
const VISUAL_DNA_INTENSITIES = [
  { label: "弱", weight: 0.35 },
  { label: "中", weight: 0.65 },
  { label: "强", weight: 0.9 },
] as const;
const visualDnaIntensityLabel = (weight: number) =>
  weight >= 0.85 ? "强" : weight >= 0.5 ? "中" : "弱";

const aspectRatioPreviewStyle = (ratio: string): CSSProperties => {
  const [width, height] = ratio.split(":").map((part) => Number(part));
  if (!Number.isFinite(width) || !Number.isFinite(height)) {
    return { width: 10, height: 10 };
  }
  if (width <= 0 || height <= 0) {
    return { width: 10, height: 10 };
  }

  const scale = Math.min(
    ASPECT_RATIO_PREVIEW_MAX_WIDTH / width,
    ASPECT_RATIO_PREVIEW_MAX_HEIGHT / height,
  );
  return {
    width: Math.max(ASPECT_RATIO_PREVIEW_MIN_EDGE, Math.round(width * scale)),
    height: Math.max(ASPECT_RATIO_PREVIEW_MIN_EDGE, Math.round(height * scale)),
  };
};

const styleTemplateModelFamilyFor = (model?: AigcCapabilityInfo | null) => {
  const modelKey = `${model?.model_id ?? ""} ${
    model?.model_name ?? ""
  }`.toLowerCase();
  if (
    (modelKey.includes("seedream") && modelKey.includes("4-5")) ||
    (modelKey.includes("seedream") && modelKey.includes("4.5"))
  ) {
    return "seedream-4.5";
  }
  if (modelKey.includes("lib image")) {
    return "lib-image";
  }
  return undefined;
};

const stylePromptTemplateFrom = (template: AigcStyleTemplate) =>
  template.type === "play" ? String(template.prompt_template ?? "").trim() : "";

const isTextReferenceAsset = (asset: ReferenceAsset) => {
  const kind = String(asset.kind ?? "")
    .trim()
    .toLowerCase();
  const previewUrl = String(asset.previewUrl ?? "")
    .trim()
    .toLowerCase();
  const sourceId = String(asset.sourceNodeId ?? asset.id ?? "")
    .trim()
    .toLowerCase();
  return (
    kind === "text" ||
    kind === "prompt" ||
    previewUrl === "prompt" ||
    sourceId.startsWith("prompt-")
  );
};

const hasImageReferencePreview = (asset: ReferenceAsset) => {
  const previewUrl = String(asset.previewUrl ?? "").trim();
  if (!previewUrl || isTextReferenceAsset(asset)) return false;
  return (
    /^(blob:|data:image\/|https?:\/\/|\/|\.\/|\.\.\/)/i.test(previewUrl) ||
    /[/.]/.test(previewUrl)
  );
};

const referenceAssetPreview = (asset: ReferenceAsset, size = 18) => {
  if (hasImageReferencePreview(asset)) {
    return <AuthenticatedAssetImage src={asset.previewUrl} alt={asset.name} />;
  }
  if (isTextReferenceAsset(asset)) {
    return <FileText size={size} data-testid="aigc-text-reference-icon" />;
  }
  return <Image size={size} />;
};

const referenceAssetBadgeNumber = (
  alias: ReferenceAsset["alias"],
  fallback: number,
) => {
  const match = String(alias ?? "").match(/\d+/);
  return match?.[0] ?? String(fallback);
};

const shouldShowImageSlashMenu = (input: unknown) => {
  const text = String(input ?? "");
  const lines = text.split(/\r?\n/);
  const currentLine = lines[lines.length - 1]?.trimStart() ?? "";
  return currentLine.startsWith("/");
};

const referenceMentionStateFromText = (
  text: string,
  cursorPosition: number,
): ReferenceMentionState | null => {
  const beforeCursor = text.slice(0, cursorPosition);
  const mentionStart = beforeCursor.lastIndexOf("@");
  if (mentionStart < 0) return null;
  const query = beforeCursor.slice(mentionStart + 1);
  if (/[\s@]/.test(query)) return null;
  return {
    query,
    start: mentionStart,
    end: cursorPosition,
  };
};

const existingReferencedAssets = (value: unknown) =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object",
      )
    : [];

const referenceAssetIdentity = (asset: ReferenceAsset) =>
  String(asset.sourceNodeId ?? asset.id ?? asset.previewUrl ?? "").trim();

const referencedAssetIdentity = (asset: Record<string, unknown>) =>
  String(
    asset.sourceNodeId ??
      asset.id ??
      asset.previewUrl ??
      asset.url ??
      asset.assetPreviewUrl ??
      "",
  ).trim();

const canUserEditStyleTemplate = (template: AigcStyleTemplate) =>
  template.type === "style" &&
  template.provider === "internal" &&
  template.runtime_mode === "prompt_style" &&
  template.category === "我的风格" &&
  !template.effect_template_uuid &&
  template.effect_id == null;

const canEditStyleTemplate = (template: AigcStyleTemplate, isAdmin: boolean) =>
  isAdmin || canUserEditStyleTemplate(template);

const styleTemplateCoverUrl = (source: string | null | undefined) => {
  const trimmed = String(source ?? "").trim();
  if (!trimmed) return "";
  if (/\/aigc-studio\/assets\/[^/?#]+\/file(?:[?#].*)?$/i.test(trimmed)) {
    return trimmed;
  }
  return trimmed.replace(
    /(\/aigc-studio\/assets\/[^/?#]+)([?#].*)?$/i,
    "$1/file$2",
  );
};

const firstGeneratedImageCoverUrl = (node: ImageComposerProps["node"]) => {
  const outputs = Array.isArray(node.data.outputs) ? node.data.outputs : [];
  const [firstOutput] = outputs;
  if (!firstOutput || typeof firstOutput !== "object") return "";
  return styleTemplateCoverUrl(assetPreviewSource(firstOutput) ?? "");
};

const styleTemplateMatchesFilters = (
  template: AigcStyleTemplate,
  filters: {
    templateKind: StyleGalleryTemplateKind;
    modelFamily: string | undefined;
    category: string;
    query: string;
  },
) => {
  const { templateKind, modelFamily, category, query } = filters;
  if (template.type !== templateKind) return false;
  if (
    modelFamily &&
    template.model_family &&
    template.model_family !== modelFamily
  ) {
    return false;
  }
  if (category && category !== "推荐") {
    const categoryText = [
      template.category,
      template.keywords,
      ...template.tags,
    ].join(" ");
    if (!categoryText.includes(category)) return false;
  }
  if (query) {
    const haystack = [
      template.title,
      template.category,
      template.keywords,
      template.description,
      template.prompt_template ?? "",
      ...template.tags,
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(query.toLowerCase())) return false;
  }
  return true;
};

export function ImageComposer({
  node,
  imageComposerMenu,
  currentModel,
  modelOptions,
  currentModelKey,
  referenceAssets = [],
  t,
  workflow,
  disabled,
  onUpdateNodeData,
  onRunNode,
  onToggleMenu,
  onSelectModel,
  onCloseMenu,
}: ImageComposerProps) {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [styleGalleryOpen, setStyleGalleryOpen] = useState(false);
  const [styleGalleryMode, setStyleGalleryMode] =
    useState<StyleGalleryMode>("all");
  const [styleGalleryTemplateKind, setStyleGalleryTemplateKind] =
    useState<StyleGalleryTemplateKind>("style");
  const [styleGalleryQuery, setStyleGalleryQuery] = useState("");
  const [styleGalleryCategory, setStyleGalleryCategory] = useState("推荐");
  const [styleGalleryTemplates, setStyleGalleryTemplates] = useState<
    AigcStyleTemplate[]
  >([]);
  const [styleGalleryLoading, setStyleGalleryLoading] = useState(false);
  const [styleGalleryError, setStyleGalleryError] = useState<string | null>(
    null,
  );
  const [styleCreateOpen, setStyleCreateOpen] = useState(false);
  const [editingStyleTemplate, setEditingStyleTemplate] =
    useState<AigcStyleTemplate | null>(null);
  const [styleCreateTitle, setStyleCreateTitle] = useState("");
  const [styleCreatePrompt, setStyleCreatePrompt] = useState("");
  const [styleCreateCategory, setStyleCreateCategory] = useState("我的风格");
  const [styleCreateVisualDna, setStyleCreateVisualDna] = useState<
    VisualDnaSelection[]
  >([]);
  const [visualDnaDimensions, setVisualDnaDimensions] = useState<
    VisualDnaDimensionInfo[]
  >([]);
  const [visualDnaElements, setVisualDnaElements] = useState<
    VisualDnaElement[]
  >([]);
  const [visualDnaDimension, setVisualDnaDimension] =
    useState<VisualDnaDimension>("lighting");
  const [visualDnaQuery, setVisualDnaQuery] = useState("");
  const [visualDnaLoading, setVisualDnaLoading] = useState(false);
  const [visualDnaError, setVisualDnaError] = useState<string | null>(null);
  const [pendingStylePromptTemplate, setPendingStylePromptTemplate] = useState<{
    template: AigcStyleTemplate;
    promptTemplate: string;
  } | null>(null);
  const [styleUploadedCoverUrl, setStyleUploadedCoverUrl] = useState("");
  const [styleCoverUploading, setStyleCoverUploading] = useState(false);
  const [styleReferenceImageUrls, setStyleReferenceImageUrls] = useState<
    string[]
  >([]);
  const [styleReferenceUploading, setStyleReferenceUploading] = useState(false);
  const [styleCreateSaving, setStyleCreateSaving] = useState(false);
  const [styleCreateError, setStyleCreateError] = useState<string | null>(null);
  const [useCurrentImageAsStyleCover, setUseCurrentImageAsStyleCover] =
    useState(true);
  const [composerFullscreenOpen, setComposerFullscreenOpen] = useState(false);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const draggedReferenceAssetRef = useRef<ReferenceAsset | null>(null);
  const [referenceMention, setReferenceMention] =
    useState<ReferenceMentionState | null>(null);
  const composerTextValue = String(
    node.data.composerText ?? node.data.text ?? "",
  );
  const [composerDraftText, setComposerDraftText] = useState(composerTextValue);
  useAutoGrowTextarea(composerDraftText, composerInputRef);
  const composerNodeIdRef = useRef(node.id);
  const composerTextValueRef = useRef(composerTextValue);
  const imageState = imageNodeStateFromNode(node);
  const imageModelOptions = imageModelOptionsFrom(modelOptions);
  const selectedImageModel = imageModelForNode(
    node,
    currentModel,
    modelOptions,
  );
  const parameterProfile = imageModelParameterProfileFor(selectedImageModel);
  const styleGalleryModelFamily = useMemo(
    () => styleTemplateModelFamilyFor(selectedImageModel),
    [selectedImageModel],
  );
  const activeStyleGalleryCategories =
    styleGalleryTemplateKind === "style"
      ? STYLE_GALLERY_CATEGORIES
      : CREATION_TEMPLATE_CATEGORIES;
  const styleCreateCoverUrl = useMemo(
    () => firstGeneratedImageCoverUrl(node),
    [node],
  );
  const inheritedStyleCoverUrl =
    styleCreateCoverUrl ||
    styleTemplateCoverUrl(editingStyleTemplate?.cover_url) ||
    "";
  const styleFormCoverUrl =
    styleUploadedCoverUrl ||
    (useCurrentImageAsStyleCover ? inheritedStyleCoverUrl : "");
  const styleVisibleCoverUrl = styleFormCoverUrl || inheritedStyleCoverUrl;
  const parameterSelection = normalizedImageParameterSelection(
    parameterProfile,
    node.data,
  );
  const imageModelLabel =
    imageModelDisplayName(selectedImageModel?.model_name) ||
    String(
      selectedImageModel?.model_id ?? node.data.modelLabel ?? "Lib Navo Pro",
    );
  const isPanorama = parameterProfile.showPanorama && isPanoramaImageNode(node);
  const hasCameraSettings = Boolean(
    parameterProfile.showCamera &&
      (node.data.cameraBody ||
        node.data.lens ||
        node.data.focal ||
        node.data.aperture ||
        node.data.cameraProfile),
  );
  const hasAdvancedSettings =
    parameterProfile.showAdvanced && node.data.webSearch === true;
  const hasCustomCount = Number(node.data.imageCount ?? 1) !== 1;
  const activeImageQuality = parameterSelection.imageQuality;
  const activeResolution = parameterSelection.resolution;
  const activeAspectRatio = isPanorama
    ? PANORAMA_IMAGE_ASPECT_RATIO
    : parameterSelection.aspectRatio;
  const sizeSummary = imageSizeParameterSummary(
    parameterProfile,
    parameterSelection,
  );
  const cameraSummary = `${String(
    node.data.focal ?? DEFAULT_IMAGE_CAMERA_PRESET.focal,
  )} · ${String(node.data.aperture ?? DEFAULT_IMAGE_CAMERA_PRESET.aperture)}`;
  const activeImageTool = String(node.data.activeTool ?? "");
  const imageComposerPlaceholder = String(
    node.data.composerPlaceholder ??
      t(
        "aigcStudio.promptPlaceholder",
        "描述你想要生成的画面内容，按呼出指令，@引用素材",
      ),
  );
  const runtimeLabelForModel = (model: AigcCapabilityInfo) => {
    const modelProfile = imageModelParameterProfileFor(model);
    return estimatedImageGenerationSecondsLabel({
      providerId: model.provider_id,
      modelId: model.model_id,
      parameters: imageGenerationParametersForProfile(modelProfile, node.data),
    });
  };
  const imageToolConfigs: Array<{
    key: ImageToolKey;
    label: string;
    icon: JSX.Element;
    dataKey: ImageToolDataKey;
    options: string[];
  }> = [
    {
      key: "style",
      label: t("aigcStudio.style", "风格"),
      icon: <Sparkles size={15} />,
      dataKey: "stylePreset",
      options: IMAGE_STYLE_OPTIONS,
    },
    {
      key: "mark",
      label: t("aigcStudio.mark", "标记"),
      icon: <MousePointer2 size={15} />,
      dataKey: "markPreset",
      options: IMAGE_MARK_OPTIONS,
    },
    {
      key: "focus",
      label: t("aigcStudio.focus", "聚焦"),
      icon: <Focus size={15} />,
      dataKey: "focusPreset",
      options: IMAGE_FOCUS_OPTIONS,
    },
  ];
  const enabledImageToolConfigs = imageToolConfigs.filter((tool) =>
    parameterProfile.promptTools.includes(tool.key),
  );
  const selectedImageTool = enabledImageToolConfigs.find(
    (tool) => tool.key === activeImageTool,
  );
  const inlineImageTool =
    selectedImageTool?.key === "style" ? undefined : selectedImageTool;
  const inlineImageToolValue = inlineImageTool
    ? String(node.data[inlineImageTool.dataKey] ?? "")
    : "";
  const isStyleGalleryOpen = styleGalleryOpen || activeImageTool === "style";
  useEffect(() => {
    if (composerNodeIdRef.current !== node.id) {
      composerNodeIdRef.current = node.id;
      composerTextValueRef.current = composerTextValue;
      setComposerDraftText(composerTextValue);
      return;
    }
    if (composerTextValue !== composerTextValueRef.current) {
      composerTextValueRef.current = composerTextValue;
      setComposerDraftText(composerTextValue);
    }
  }, [composerTextValue, node.id]);
  const visibleReferenceAssets = useMemo<ReferenceAsset[]>(() => {
    if (referenceAssets.length > 0) return referenceAssets;
    const previewUrl = String(node.data.referencePreviewUrl ?? "").trim();
    if (node.data.referenceThumb === true && previewUrl) {
      return [
        {
          id: String(node.data.referenceAssetId ?? previewUrl),
          alias: "图片1",
          name: String(node.data.referenceAssetName ?? "参考素材"),
          previewUrl,
          sourceNodeId:
            typeof node.data.referenceSourceNodeId === "string"
              ? node.data.referenceSourceNodeId
              : undefined,
        },
      ];
    }
    return [];
  }, [
    node.data.referenceAssetId,
    node.data.referenceAssetName,
    node.data.referencePreviewUrl,
    node.data.referenceSourceNodeId,
    node.data.referenceThumb,
    referenceAssets,
  ]);
  const referenceMentionOptions = useMemo(() => {
    const query = (referenceMention?.query ?? "").toLowerCase();
    return visibleReferenceAssets.filter((asset) => {
      if (!query) return true;
      return [asset.alias, asset.name, asset.id]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [referenceMention, visibleReferenceAssets]);
  const selectedVisualDnaById = useMemo(
    () =>
      new Map(
        styleCreateVisualDna.map((selection) => [
          selection.element_id,
          selection,
        ]),
      ),
    [styleCreateVisualDna],
  );
  const profileVisualDnaDimensions = useMemo(
    () =>
      visualDnaDimensions.filter(
        (dimension) =>
          dimension.scope === "aesthetic_profile" ||
          AESTHETIC_PROFILE_DIMENSIONS.has(dimension.id),
      ),
    [visualDnaDimensions],
  );
  const profileVisualDnaSelections = useMemo(() => {
    const dimensionByElementId = new Map(
      visualDnaElements.map((element) => [element.id, element.dimension]),
    );
    return styleCreateVisualDna.filter((selection) => {
      const dimension =
        dimensionByElementId.get(selection.element_id) ??
        (selection.element_id.split(".", 1)[0] as VisualDnaDimension);
      return AESTHETIC_PROFILE_DIMENSIONS.has(dimension);
    });
  }, [styleCreateVisualDna, visualDnaElements]);
  const visibleVisualDnaElements = useMemo(() => {
    const query = visualDnaQuery.trim().toLowerCase();
    return visualDnaElements.filter((element) => {
      if (element.dimension !== visualDnaDimension) return false;
      if (!query) return true;
      return [
        element.id,
        element.name,
        element.definition,
        element.visual_effect,
        ...element.aliases,
        ...element.tags,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [visualDnaDimension, visualDnaElements, visualDnaQuery]);
  const visualDnaConflicts = useMemo(() => {
    const selectedIds = new Set(
      profileVisualDnaSelections.map((selection) => selection.element_id),
    );
    const elementsById = new Map(
      visualDnaElements.map((element) => [element.id, element]),
    );
    const pairs = new Set<string>();
    const messages: string[] = [];
    profileVisualDnaSelections.forEach((selection) => {
      const element = elementsById.get(selection.element_id);
      element?.conflicts_with.forEach((conflictId) => {
        if (!selectedIds.has(conflictId)) return;
        const pair = [selection.element_id, conflictId].sort();
        const key = pair.join("|");
        if (pairs.has(key)) return;
        pairs.add(key);
        messages.push(
          `${elementsById.get(pair[0])?.name ?? pair[0]} 与 ${
            elementsById.get(pair[1])?.name ?? pair[1]
          } 不建议同时使用`,
        );
      });
    });
    return messages;
  }, [profileVisualDnaSelections, visualDnaElements]);
  const applyReferenceMentionText = (
    value: string,
    cursorPosition = value.length,
  ) => {
    setReferenceMention(referenceMentionStateFromText(value, cursorPosition));
  };
  const updateComposerText = (value: string, cursorPosition = value.length) => {
    setComposerDraftText(value);
    applyReferenceMentionText(value, cursorPosition);
    onUpdateNodeData(node.id, {
      composerText: value,
      text: value,
    });
  };
  const currentComposerText = () => {
    const refValue = composerInputRef.current?.value;
    const nodeValue = String(node.data.composerText ?? node.data.text ?? "");
    if (typeof refValue === "string" && refValue.trim()) return refValue;
    if (composerDraftText.trim()) return composerDraftText;
    if (nodeValue.trim()) return nodeValue;
    if (typeof refValue === "string") return refValue;
    return nodeValue;
  };
  const selectReferenceMention = (asset: ReferenceAsset) => {
    const text = currentComposerText();
    const mention =
      referenceMention ?? referenceMentionStateFromText(text, text.length);
    if (!mention) return;
    const nextText = `${text.slice(0, mention.start)}@${
      asset.alias
    } ${text.slice(mention.end)}`;
    const existing = existingReferencedAssets(node.data.referencedAssets);
    const assetKey = referenceAssetIdentity(asset);
    const nextReferencedAssets = [
      ...existing.filter((item) => referencedAssetIdentity(item) !== assetKey),
      asset,
    ];
    setReferenceMention(null);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      composerText: nextText,
      text: nextText,
      referencedAssets: nextReferencedAssets,
      inputUpdated: true,
    });
  };
  const commitDraggedReferenceAsset = (
    asset: ReferenceAsset,
    nextText: string,
    cursor?: number,
  ) => {
    const existing = existingReferencedAssets(node.data.referencedAssets);
    const assetKey = referenceAssetIdentity(asset);
    const nextReferencedAssets = [
      ...existing.filter((item) => referencedAssetIdentity(item) !== assetKey),
      asset,
    ];
    setReferenceMention(null);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      composerText: nextText,
      text: nextText,
      referencedAssets: nextReferencedAssets,
      inputUpdated: true,
    });
    if (cursor !== undefined) {
      window.requestAnimationFrame(() => {
        composerInputRef.current?.focus();
        composerInputRef.current?.setSelectionRange(cursor, cursor);
      });
    }
  };
  const insertDraggedReferenceAsset = (
    asset: ReferenceAsset,
    text: string,
    selectionStart: number,
    selectionEnd: number,
  ) => {
    const insertion = insertReferenceAlias(
      text,
      asset.alias,
      selectionStart,
      selectionEnd,
    );
    commitDraggedReferenceAsset(asset, insertion.value, insertion.cursor);
  };
  useEffect(() => {
    if (!isStyleGalleryOpen) return;
    let cancelled = false;
    const query = styleGalleryQuery.trim();
    const request =
      styleGalleryMode === "favorites"
        ? aigcStudioApi.listFavoriteStyleTemplates()
        : styleGalleryMode === "recent"
        ? aigcStudioApi.listRecentStyleTemplates()
        : aigcStudioApi.listStyleTemplates({
            type: styleGalleryTemplateKind,
            model_family: styleGalleryModelFamily,
            category: styleGalleryCategory,
            q: query,
          });
    setStyleGalleryLoading(true);
    setStyleGalleryError(null);
    request
      .then((result) => {
        if (cancelled) return;
        const templates =
          styleGalleryMode === "all"
            ? result.templates
            : result.templates.filter((template) =>
                styleTemplateMatchesFilters(template, {
                  templateKind: styleGalleryTemplateKind,
                  modelFamily: styleGalleryModelFamily,
                  category: styleGalleryCategory,
                  query,
                }),
              );
        setStyleGalleryTemplates(templates);
      })
      .catch((error) => {
        if (cancelled) return;
        setStyleGalleryTemplates([]);
        setStyleGalleryError(
          error instanceof Error ? error.message : String(error),
        );
      })
      .finally(() => {
        if (!cancelled) setStyleGalleryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    isStyleGalleryOpen,
    styleGalleryCategory,
    styleGalleryMode,
    styleGalleryModelFamily,
    styleGalleryQuery,
    styleGalleryTemplateKind,
  ]);
  useEffect(() => {
    if (!styleCreateOpen) return;
    let cancelled = false;
    setVisualDnaLoading(true);
    setVisualDnaError(null);
    Promise.all([
      aigcStudioApi.listVisualDnaDimensions(),
      aigcStudioApi.listVisualDnaElements({ limit: 500 }),
    ])
      .then(([dimensionResult, elementResult]) => {
        if (cancelled) return;
        const profileDimensions = dimensionResult.dimensions.filter(
          (dimension) =>
            dimension.scope === "aesthetic_profile" ||
            AESTHETIC_PROFILE_DIMENSIONS.has(dimension.id),
        );
        setVisualDnaDimensions(dimensionResult.dimensions);
        setVisualDnaElements(elementResult.elements);
        if (profileDimensions.length > 0) {
          setVisualDnaDimension((current) =>
            profileDimensions.some((dimension) => dimension.id === current)
              ? current
              : profileDimensions[0].id,
          );
        }
      })
      .catch((error) => {
        if (cancelled) return;
        setVisualDnaDimensions([]);
        setVisualDnaElements([]);
        setVisualDnaError(
          error instanceof Error ? error.message : String(error),
        );
      })
      .finally(() => {
        if (!cancelled) setVisualDnaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [styleCreateOpen]);
  const resetStyleCreateForm = () => {
    setEditingStyleTemplate(null);
    setStyleCreateTitle("");
    setStyleCreatePrompt("");
    setStyleCreateCategory("我的风格");
    setStyleCreateVisualDna([]);
    setVisualDnaDimension("lighting");
    setVisualDnaQuery("");
    setStyleUploadedCoverUrl("");
    setStyleCoverUploading(false);
    setStyleReferenceImageUrls([]);
    setStyleReferenceUploading(false);
    setStyleCreateError(null);
    setUseCurrentImageAsStyleCover(true);
  };
  const openStyleCreateForm = () => {
    setStyleCreateOpen((open) => {
      if (!open || editingStyleTemplate) {
        resetStyleCreateForm();
        return true;
      }
      return false;
    });
  };
  const selectStyleGalleryTemplateKind = (
    templateKind: StyleGalleryTemplateKind,
  ) => {
    setStyleGalleryTemplateKind(templateKind);
    setStyleGalleryCategory("推荐");
    setStyleCreateOpen(false);
    resetStyleCreateForm();
  };
  const startEditingStyleTemplate = (template: AigcStyleTemplate) => {
    if (!canEditStyleTemplate(template, isAdmin)) return;
    setEditingStyleTemplate(template);
    setStyleCreateTitle(template.title);
    setStyleCreatePrompt(template.supplemental_prompt ?? "");
    setStyleCreateCategory(template.category || "我的风格");
    setStyleCreateVisualDna(template.visual_dna ?? []);
    setStyleUploadedCoverUrl("");
    setStyleReferenceImageUrls(template.reference_image_urls ?? []);
    setUseCurrentImageAsStyleCover(Boolean(template.cover_url));
    setStyleCreateError(null);
    setStyleCreateOpen(true);
  };
  const toggleVisualDnaElement = (element: VisualDnaElement) => {
    setStyleCreateVisualDna((selections) => {
      if (selections.some((item) => item.element_id === element.id)) {
        return selections.filter((item) => item.element_id !== element.id);
      }
      return [...selections, { element_id: element.id, weight: 0.65 }];
    });
  };
  const updateVisualDnaWeight = (elementId: string, weight: number) => {
    setStyleCreateVisualDna((selections) =>
      selections.map((selection) =>
        selection.element_id === elementId
          ? { ...selection, weight }
          : selection,
      ),
    );
  };
  const closeStyleGallery = () => {
    setStyleGalleryOpen(false);
    setPendingStylePromptTemplate(null);
    if (activeImageTool === "style") {
      onUpdateNodeData(node.id, { activeTool: null });
    }
  };
  const applyStyleTemplateSelection = (template: AigcStyleTemplate) => {
    setStyleGalleryOpen(false);
    setStyleCreateOpen(false);
    setEditingStyleTemplate(null);
    setPendingStylePromptTemplate(null);
    void aigcStudioApi
      .markStyleTemplateUsed(template.id)
      .catch(() => undefined);
    onUpdateNodeData(node.id, {
      ...imageStyleTemplateData(template),
      activeTool: null,
    });
  };
  const applyCreationTemplateSelection = (
    template: AigcStyleTemplate,
    promptTemplate: string,
  ) => {
    setStyleGalleryOpen(false);
    setStyleCreateOpen(false);
    setEditingStyleTemplate(null);
    setPendingStylePromptTemplate(null);
    void aigcStudioApi
      .markStyleTemplateUsed(template.id)
      .catch(() => undefined);
    onUpdateNodeData(node.id, {
      composerText: promptTemplate,
      creationTemplateId: template.id,
      creationTemplateName: template.title,
      activeTool: null,
      inputUpdated: true,
    });
  };
  const selectStyleTemplate = (template: AigcStyleTemplate) => {
    const promptTemplate = stylePromptTemplateFrom(template);
    if (template.type === "play" && promptTemplate) {
      setStyleGalleryOpen(false);
      setStyleCreateOpen(false);
      setEditingStyleTemplate(null);
      setPendingStylePromptTemplate({ template, promptTemplate });
      onUpdateNodeData(node.id, { activeTool: null });
      return;
    }
    if (template.type === "style") {
      applyStyleTemplateSelection(template);
    }
  };
  const savePromptStyleTemplate = async () => {
    const supplementalPrompt = styleCreatePrompt.trim();
    const title = styleCreateTitle.trim();
    if (
      !title ||
      (!supplementalPrompt && profileVisualDnaSelections.length === 0) ||
      styleCreateSaving
    ) {
      return;
    }
    const profileElementNames = profileVisualDnaSelections
      .map(
        (selection) =>
          visualDnaElements.find(
            (element) => element.id === selection.element_id,
          )?.name,
      )
      .filter((name): name is string => Boolean(name));
    const description =
      supplementalPrompt || profileElementNames.join("、") || "自定义审美档案";
    const selectedCategory = styleCreateCategory.trim() || "我的风格";
    const inheritedCoverUrl =
      styleCreateCoverUrl ||
      styleTemplateCoverUrl(editingStyleTemplate?.cover_url) ||
      "";
    const coverUrl =
      styleUploadedCoverUrl ||
      (useCurrentImageAsStyleCover ? inheritedCoverUrl : "");

    setStyleCreateSaving(true);
    setStyleCreateError(null);
    try {
      if (editingStyleTemplate) {
        const preserveTemplateMetadata =
          isAdmin && !canUserEditStyleTemplate(editingStyleTemplate);
        const template = await aigcStudioApi.updateStyleTemplate(
          editingStyleTemplate.id,
          {
            title,
            type: preserveTemplateMetadata
              ? editingStyleTemplate.type
              : "style",
            provider: preserveTemplateMetadata
              ? editingStyleTemplate.provider
              : "internal",
            model_family: preserveTemplateMetadata
              ? editingStyleTemplate.model_family ?? null
              : null,
            category: preserveTemplateMetadata
              ? editingStyleTemplate.category
              : selectedCategory,
            tags: preserveTemplateMetadata
              ? editingStyleTemplate.tags
              : [selectedCategory],
            keywords: preserveTemplateMetadata
              ? editingStyleTemplate.keywords
              : "",
            description,
            supplemental_prompt: supplementalPrompt,
            visual_dna: profileVisualDnaSelections,
            reference_image_urls: styleReferenceImageUrls,
            profile_version: editingStyleTemplate.profile_version ?? "1.0",
            cover_url: coverUrl || null,
            commercial: preserveTemplateMetadata
              ? editingStyleTemplate.commercial
              : false,
            runtime_mode: preserveTemplateMetadata
              ? editingStyleTemplate.runtime_mode
              : "prompt_style",
            status: editingStyleTemplate.status ?? "enabled",
          },
        );
        setStyleGalleryTemplates((templates) =>
          templates.map((item) => (item.id === template.id ? template : item)),
        );
        resetStyleCreateForm();
        selectStyleTemplate(template);
        return;
      }
      const template = await aigcStudioApi.createStyleTemplate({
        title,
        type: "style",
        provider: "internal",
        model_family: null,
        category: selectedCategory,
        tags: [selectedCategory],
        keywords: "",
        description,
        supplemental_prompt: supplementalPrompt,
        prompt_template: "",
        visual_dna: profileVisualDnaSelections,
        reference_image_urls: styleReferenceImageUrls,
        profile_version: "1.0",
        cover_url: coverUrl || null,
        commercial: false,
        runtime_mode: "prompt_style",
        status: "enabled",
      });
      setStyleGalleryTemplates((templates) => [
        template,
        ...templates.filter((item) => item.id !== template.id),
      ]);
      resetStyleCreateForm();
      selectStyleTemplate(template);
    } catch (error) {
      setStyleCreateError(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setStyleCreateSaving(false);
    }
  };
  const uploadStyleCover = async (file: File | undefined) => {
    if (!file || styleCoverUploading) return;
    setStyleCoverUploading(true);
    setStyleCreateError(null);
    try {
      const asset = await aigcStudioApi.uploadAsset(file);
      const uploadedUrl = styleTemplateCoverUrl(asset.url || asset.path || "");
      setStyleUploadedCoverUrl(uploadedUrl);
      setUseCurrentImageAsStyleCover(false);
    } catch (error) {
      setStyleCreateError(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setStyleCoverUploading(false);
    }
  };
  const uploadStyleReferenceImages = async (files: FileList | null) => {
    if (!files?.length || styleReferenceUploading) return;
    const availableSlots = Math.max(0, 3 - styleReferenceImageUrls.length);
    const selectedFiles = Array.from(files).slice(0, availableSlots);
    if (selectedFiles.length === 0) return;
    setStyleReferenceUploading(true);
    setStyleCreateError(null);
    try {
      const assets = await Promise.all(
        selectedFiles.map((file) => aigcStudioApi.uploadAsset(file)),
      );
      const uploadedUrls = assets
        .map((asset) => styleTemplateCoverUrl(asset.url || asset.path || ""))
        .filter(Boolean);
      setStyleReferenceImageUrls((current) =>
        Array.from(new Set([...current, ...uploadedUrls])).slice(0, 3),
      );
    } catch (error) {
      setStyleCreateError(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setStyleReferenceUploading(false);
    }
  };
  const deletePromptStyleTemplate = async (template: AigcStyleTemplate) => {
    if (!canEditStyleTemplate(template, isAdmin)) return;
    try {
      await aigcStudioApi.deleteStyleTemplate(template.id);
      setStyleGalleryTemplates((templates) =>
        templates.filter((item) => item.id !== template.id),
      );
      if (editingStyleTemplate?.id === template.id) {
        setStyleCreateOpen(false);
        resetStyleCreateForm();
      }
      const isCurrentTemplate =
        String(node.data.styleTemplateId ?? "") === template.id ||
        String(node.data.stylePreset ?? "") === template.title;
      if (isCurrentTemplate) {
        onUpdateNodeData(node.id, {
          activeTool: null,
          stylePreset: "",
          styleTemplateId: null,
          styleRuntimeMode: null,
          styleReferenceThumb: false,
          styleReferenceName: null,
          styleTemplateUuid: null,
          effectTemplateUuids: [],
          effectId: null,
          effects: [],
          styleKeywords: null,
          styleDescription: null,
          styleSupplementalPrompt: null,
          stylePromptTemplate: null,
          visualDna: null,
          styleReferenceImages: null,
          aestheticProfileSnapshot: null,
          inputUpdated: true,
        });
      }
    } catch (error) {
      setStyleCreateError(
        error instanceof Error ? error.message : String(error),
      );
      setStyleCreateOpen(true);
    }
  };
  const toggleStyleTemplateFavorite = async (template: AigcStyleTemplate) => {
    try {
      const updated = await aigcStudioApi.updateStyleTemplateFavorite(
        template.id,
        !template.favorite,
      );
      setStyleGalleryTemplates((templates) => {
        const nextTemplates = templates.map((item) =>
          item.id === updated.id ? updated : item,
        );
        if (styleGalleryMode === "favorites" && !updated.favorite) {
          return nextTemplates.filter((item) => item.id !== updated.id);
        }
        return nextTemplates;
      });
    } catch (error) {
      setStyleCreateError(
        error instanceof Error ? error.message : String(error),
      );
      setStyleCreateOpen(true);
    }
  };
  const selectedImageToolSummaries = enabledImageToolConfigs
    .map((tool) => ({
      key: tool.key,
      label: tool.label,
      dataKey: tool.dataKey,
      value: String(node.data[tool.dataKey] ?? "").trim(),
    }))
    .filter((tool) => tool.value);
  const clearImageToolSummary = (dataKey: ImageToolDataKey) => {
    const styleReset =
      dataKey === "stylePreset"
        ? {
            styleReferenceThumb: null,
            styleReferenceName: null,
            styleReferencePreviewUrl: null,
            styleTemplateId: null,
            styleTemplateUuid: null,
            effectTemplateUuids: null,
            effectId: null,
            effects: null,
            styleRuntimeMode: null,
            styleKeywords: null,
            styleDescription: null,
            styleSupplementalPrompt: null,
            stylePromptTemplate: null,
            visualDna: null,
            styleReferenceImages: null,
            aestheticProfileSnapshot: null,
          }
        : {};
    onUpdateNodeData(node.id, {
      [dataKey]: null,
      ...styleReset,
      imageProgress: null,
      inputUpdated: true,
    });
  };
  const imageModeAfterPanoramaOff = () => {
    const imageMode = String(node.data.imageMode ?? "");
    if (imageMode && imageMode !== "panorama") return imageMode;
    if (
      node.data.referenceThumb === true ||
      node.data.referenceAssetName ||
      node.data.referencePreviewUrl ||
      node.data.assetName ||
      node.data.assetPreviewUrl
    ) {
      return "image_to_image";
    }
    return "blank";
  };
  const togglePanoramaMode = () => {
    if (isPanorama) {
      onUpdateNodeData(node.id, {
        panoramaMode: false,
        imageMode: imageModeAfterPanoramaOff(),
        aspectRatio: DEFAULT_IMAGE_ASPECT_RATIO,
      });
      return;
    }
    onUpdateNodeData(node.id, {
      panoramaMode: true,
      imageMode: "panorama",
      aspectRatio: PANORAMA_IMAGE_ASPECT_RATIO,
      imageQuality: activeImageQuality,
      resolution: activeResolution,
      imageState: "editing",
      imageProgress: null,
      showTryOptions: false,
      inputUpdated: true,
      job_status: null,
      outputs: [],
    });
  };
  const applyDefaultCameraPreset = () => {
    onUpdateNodeData(node.id, {
      ...DEFAULT_IMAGE_CAMERA_PRESET,
      imageState: "editing",
      imageProgress: null,
      inputUpdated: true,
      job_status: null,
      outputs: [],
    });
  };
  const styleGalleryDialog =
    isStyleGalleryOpen && typeof document !== "undefined"
      ? createPortal(
          <div
            className={`nodrag nopan ${styles.imageStyleGalleryBackdrop}`}
            data-testid="aigc-image-style-gallery-backdrop"
            onMouseDown={(event) => {
              event.stopPropagation();
              if (event.target === event.currentTarget) {
                closeStyleGallery();
              }
            }}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <section
              className={styles.imageStyleGalleryDialog}
              role="dialog"
              aria-modal="true"
              aria-label={t("aigcStudio.imageNode.styleGallery", "风格广场")}
              data-testid="aigc-image-style-gallery-dialog"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header className={styles.imageStyleGalleryHeader}>
                <div className={styles.imageStyleGalleryModeTabs}>
                  {[
                    ["all", "风格广场"],
                    ["favorites", "我的收藏"],
                    ["recent", "最近使用"],
                  ].map(([mode, label]) => (
                    <button
                      type="button"
                      key={mode}
                      className={
                        styleGalleryMode === mode
                          ? styles.imageOptionActive
                          : ""
                      }
                      onClick={() =>
                        setStyleGalleryMode(mode as StyleGalleryMode)
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <label className={styles.imageStyleGallerySearch}>
                  <Search size={16} />
                  <input
                    value={styleGalleryQuery}
                    placeholder={t(
                      "aigcStudio.imageNode.searchStyle",
                      styleGalleryTemplateKind === "style"
                        ? "搜索风格名称、作者"
                        : "搜索创作模板",
                    )}
                    onChange={(event) =>
                      setStyleGalleryQuery(event.target.value)
                    }
                  />
                </label>
                <div className={styles.imageStyleGalleryActions}>
                  {styleGalleryTemplateKind === "style" && (
                    <button
                      type="button"
                      className={styles.imageStyleCreateButton}
                      onClick={openStyleCreateForm}
                    >
                      <Plus size={14} />
                      {t("aigcStudio.imageNode.createStyle", "创建风格")}
                    </button>
                  )}
                  <span>
                    当前模型：{styleGalleryModelFamily ?? imageModelLabel} ·
                    自动适配
                  </span>
                  <button
                    type="button"
                    aria-label={t("aigcStudio.close", "关闭")}
                    onClick={closeStyleGallery}
                  >
                    <X size={18} />
                  </button>
                </div>
              </header>
              <nav className={styles.imageStyleGalleryKindTabs}>
                <button
                  type="button"
                  className={
                    styleGalleryTemplateKind === "style"
                      ? styles.imageOptionActive
                      : ""
                  }
                  onClick={() => selectStyleGalleryTemplateKind("style")}
                >
                  审美风格
                  <small>控制整体视觉气质</small>
                </button>
                <button
                  type="button"
                  className={
                    styleGalleryTemplateKind === "play"
                      ? styles.imageOptionActive
                      : ""
                  }
                  onClick={() => selectStyleGalleryTemplateKind("play")}
                >
                  创作模板
                  <small>回填主体、场景和文案结构</small>
                </button>
              </nav>
              <nav className={styles.imageStyleGalleryCategories}>
                {activeStyleGalleryCategories.map((category) => (
                  <button
                    type="button"
                    key={category}
                    className={
                      styleGalleryCategory === category
                        ? styles.imageOptionActive
                        : ""
                    }
                    onClick={() => setStyleGalleryCategory(category)}
                  >
                    {category}
                  </button>
                ))}
              </nav>
              <div className={styles.imageStyleGalleryGrid}>
                {styleCreateOpen && styleGalleryTemplateKind === "style" && (
                  <form
                    className={styles.imageStyleCreateForm}
                    onSubmit={(event) => {
                      event.preventDefault();
                      void savePromptStyleTemplate();
                    }}
                  >
                    <header className={styles.aestheticProfileEditorHeader}>
                      <strong>
                        {editingStyleTemplate ? "编辑审美档案" : "创建审美档案"}
                      </strong>
                      <span>
                        定义可跨图片和视频复用的整体审美；镜头、构图、叙事和素材约束在具体创作节点设置。
                      </span>
                    </header>
                    <label>
                      {t("aigcStudio.imageNode.styleName", "风格名称")}
                      <input
                        value={styleCreateTitle}
                        placeholder="例如：冷峻电影写实"
                        onChange={(event) =>
                          setStyleCreateTitle(event.target.value)
                        }
                      />
                    </label>
                    <label>
                      {t("aigcStudio.imageNode.styleCategory", "应用场景")}
                      <select
                        value={styleCreateCategory}
                        onChange={(event) =>
                          setStyleCreateCategory(event.target.value)
                        }
                      >
                        {STYLE_GALLERY_CATEGORIES.filter(
                          (category) => category !== "推荐",
                        ).map((category) => (
                          <option key={category} value={category}>
                            {category}
                          </option>
                        ))}
                      </select>
                    </label>
                    <section
                      className={styles.visualDnaBuilder}
                      aria-label={t(
                        "aigcStudio.imageNode.visualDnaBuilder",
                        "审美 DNA",
                      )}
                    >
                      <header className={styles.visualDnaBuilderHeader}>
                        <div>
                          <strong>
                            {t(
                              "aigcStudio.imageNode.visualDnaBuilder",
                              "审美 DNA",
                            )}
                          </strong>
                          <span>
                            {t(
                              "aigcStudio.imageNode.visualDnaSelectedCount",
                              "已选 {{count}} 个审美元素",
                              { count: profileVisualDnaSelections.length },
                            )}
                          </span>
                          <span>
                            只控制艺术方向、光影、色彩、材质和整体氛围。
                          </span>
                        </div>
                        <label className={styles.visualDnaSearch}>
                          <Search size={14} />
                          <input
                            value={visualDnaQuery}
                            placeholder={t(
                              "aigcStudio.imageNode.visualDnaSearch",
                              "搜索审美元素",
                            )}
                            onChange={(event) =>
                              setVisualDnaQuery(event.target.value)
                            }
                          />
                        </label>
                      </header>
                      <nav className={styles.visualDnaDimensions}>
                        {profileVisualDnaDimensions.map((dimension) => (
                          <button
                            type="button"
                            key={dimension.id}
                            className={
                              visualDnaDimension === dimension.id
                                ? styles.imageOptionActive
                                : ""
                            }
                            onClick={() => {
                              setVisualDnaDimension(dimension.id);
                              setVisualDnaQuery("");
                            }}
                          >
                            {dimension.name}
                            <small>{dimension.element_count}</small>
                          </button>
                        ))}
                      </nav>
                      {visualDnaLoading && (
                        <p className={styles.visualDnaState}>
                          {t(
                            "aigcStudio.imageNode.visualDnaLoading",
                            "正在加载审美元素...",
                          )}
                        </p>
                      )}
                      {!visualDnaLoading && visualDnaError && (
                        <p className={styles.visualDnaState} role="alert">
                          {t(
                            "aigcStudio.imageNode.visualDnaLoadFailed",
                            "审美元素加载失败",
                          )}
                        </p>
                      )}
                      {!visualDnaLoading && !visualDnaError && (
                        <div className={styles.visualDnaElements}>
                          {visibleVisualDnaElements.map((element) => {
                            const selection = selectedVisualDnaById.get(
                              element.id,
                            );
                            return (
                              <article
                                key={element.id}
                                className={
                                  selection
                                    ? styles.visualDnaElementSelected
                                    : ""
                                }
                              >
                                <button
                                  type="button"
                                  aria-label={
                                    selection
                                      ? `取消审美元素 ${element.name}`
                                      : `选择审美元素 ${element.name}`
                                  }
                                  aria-pressed={Boolean(selection)}
                                  onClick={() =>
                                    toggleVisualDnaElement(element)
                                  }
                                >
                                  <span>
                                    <strong>{element.name}</strong>
                                    <small>{element.visual_effect}</small>
                                  </span>
                                  <em>{selection ? "✓" : "+"}</em>
                                </button>
                                {selection && (
                                  <div className={styles.visualDnaIntensity}>
                                    <span>影响强度</span>
                                    <div>
                                      {VISUAL_DNA_INTENSITIES.map(
                                        (intensity) => (
                                          <button
                                            type="button"
                                            key={intensity.label}
                                            className={
                                              visualDnaIntensityLabel(
                                                selection.weight,
                                              ) === intensity.label
                                                ? styles.imageOptionActive
                                                : ""
                                            }
                                            aria-label={`${element.name}影响强度：${intensity.label}`}
                                            onClick={() =>
                                              updateVisualDnaWeight(
                                                element.id,
                                                intensity.weight,
                                              )
                                            }
                                          >
                                            {intensity.label}
                                          </button>
                                        ),
                                      )}
                                    </div>
                                  </div>
                                )}
                              </article>
                            );
                          })}
                          {visibleVisualDnaElements.length === 0 && (
                            <p className={styles.visualDnaState}>
                              {t(
                                "aigcStudio.imageNode.visualDnaEmpty",
                                "当前维度没有匹配的审美元素",
                              )}
                            </p>
                          )}
                        </div>
                      )}
                      {visualDnaConflicts.length > 0 && (
                        <div className={styles.visualDnaConflict} role="alert">
                          <AlertCircle size={14} />
                          <div>
                            <strong>
                              {t(
                                "aigcStudio.imageNode.visualDnaConflict",
                                "发现审美冲突",
                              )}
                            </strong>
                            {visualDnaConflicts.map((message) => (
                              <span key={message}>{message}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </section>
                    <label className={styles.imageStyleCreateWideField}>
                      {t(
                        "aigcStudio.imageNode.styleSupplementalPrompt",
                        "风格补充说明（可选）",
                      )}
                      <textarea
                        rows={3}
                        value={styleCreatePrompt}
                        placeholder={t(
                          "aigcStudio.imageNode.styleSupplementalPromptPlaceholder",
                          "只填写审美 DNA 尚未覆盖的特殊视觉规则；不要填写主体、镜头、构图或文案。",
                        )}
                        onChange={(event) =>
                          setStyleCreatePrompt(event.target.value)
                        }
                      />
                    </label>
                    <div className={styles.aestheticProfileAssetHeading}>
                      <strong>卡片封面</strong>
                      <span>只用于风格广场展示，不参与生成。</span>
                    </div>
                    <div className={styles.imageStyleCoverControls}>
                      <label className={styles.imageStyleCoverUpload}>
                        <Upload size={14} />
                        {styleCoverUploading
                          ? t("aigcStudio.imageNode.uploadingCover", "上传中")
                          : t(
                              "aigcStudio.imageNode.uploadCover",
                              "上传卡片封面",
                            )}
                        <input
                          type="file"
                          accept="image/*"
                          aria-label={t(
                            "aigcStudio.imageNode.uploadCover",
                            "上传卡片封面",
                          )}
                          onChange={(event) => {
                            void uploadStyleCover(event.target.files?.[0]);
                            event.target.value = "";
                          }}
                        />
                      </label>
                      {(styleUploadedCoverUrl ||
                        (!styleCreateCoverUrl && styleVisibleCoverUrl)) && (
                        <span className={styles.imageStyleCoverThumb}>
                          <AuthenticatedAssetImage
                            src={styleVisibleCoverUrl}
                            alt={t(
                              "aigcStudio.imageNode.styleCover",
                              "风格封面",
                            )}
                          />
                        </span>
                      )}
                    </div>
                    {styleCreateCoverUrl && !styleUploadedCoverUrl && (
                      <label className={styles.imageStyleCoverOption}>
                        <input
                          type="checkbox"
                          checked={useCurrentImageAsStyleCover}
                          onChange={(event) =>
                            setUseCurrentImageAsStyleCover(event.target.checked)
                          }
                        />
                        <span>
                          {t(
                            "aigcStudio.imageNode.useCurrentImageAsCover",
                            "使用当前图作封面",
                          )}
                        </span>
                        <span className={styles.imageStyleCoverThumb}>
                          <AuthenticatedAssetImage
                            src={styleCreateCoverUrl}
                            alt={t(
                              "aigcStudio.imageNode.styleCover",
                              "风格封面",
                            )}
                          />
                        </span>
                      </label>
                    )}
                    <div className={styles.aestheticProfileAssetHeading}>
                      <strong>风格参考图</strong>
                      <span>
                        参与生成，只传递审美特征，不复制主体和构图；最多 3 张。
                      </span>
                    </div>
                    <div className={styles.imageStyleCoverControls}>
                      <label className={styles.imageStyleCoverUpload}>
                        <Upload size={14} />
                        {styleReferenceUploading
                          ? "上传中"
                          : styleReferenceImageUrls.length >= 3
                          ? "已达 3 张"
                          : "上传风格参考图"}
                        <input
                          type="file"
                          accept="image/*"
                          multiple
                          disabled={
                            styleReferenceUploading ||
                            styleReferenceImageUrls.length >= 3
                          }
                          aria-label="上传风格参考图"
                          onChange={(event) => {
                            void uploadStyleReferenceImages(event.target.files);
                            event.target.value = "";
                          }}
                        />
                      </label>
                      <div className={styles.aestheticProfileReferenceList}>
                        {styleReferenceImageUrls.map((referenceUrl, index) => (
                          <span
                            className={styles.aestheticProfileReferenceThumb}
                            key={referenceUrl}
                          >
                            <AuthenticatedAssetImage
                              src={referenceUrl}
                              alt={`风格参考图 ${index + 1}`}
                            />
                            <button
                              type="button"
                              aria-label={`移除风格参考图 ${index + 1}`}
                              onClick={() =>
                                setStyleReferenceImageUrls((current) =>
                                  current.filter(
                                    (item) => item !== referenceUrl,
                                  ),
                                )
                              }
                            >
                              <X size={11} />
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                    {styleCreateError && (
                      <p className={styles.imageStyleCreateError}>
                        {styleCreateError}
                      </p>
                    )}
                    <div className={styles.imageStyleCreateActions}>
                      <button
                        type="button"
                        onClick={() => {
                          setStyleCreateOpen(false);
                          resetStyleCreateForm();
                        }}
                      >
                        {t("aigcStudio.cancel", "取消")}
                      </button>
                      <button
                        type="submit"
                        disabled={
                          !styleCreateTitle.trim() ||
                          (!styleCreatePrompt.trim() &&
                            profileVisualDnaSelections.length === 0) ||
                          styleCreateSaving ||
                          styleCoverUploading ||
                          styleReferenceUploading
                        }
                      >
                        {styleCreateSaving
                          ? t("aigcStudio.saving", "保存中")
                          : editingStyleTemplate
                          ? t("aigcStudio.imageNode.updateStyle", "保存修改")
                          : t("aigcStudio.imageNode.saveStyle", "保存风格")}
                      </button>
                    </div>
                  </form>
                )}
                {styleGalleryLoading && (
                  <p className={styles.imageStyleGalleryState}>
                    {styleGalleryTemplateKind === "style"
                      ? t(
                          "aigcStudio.imageNode.loadingStyles",
                          "正在加载风格...",
                        )
                      : "正在加载创作模板..."}
                  </p>
                )}
                {!styleGalleryLoading && styleGalleryError && (
                  <p className={styles.imageStyleGalleryState}>
                    {styleGalleryTemplateKind === "style"
                      ? t(
                          "aigcStudio.imageNode.loadStylesFailed",
                          "风格加载失败",
                        )
                      : "创作模板加载失败"}
                  </p>
                )}
                {!styleGalleryLoading &&
                  !styleGalleryError &&
                  styleGalleryTemplates.length === 0 && (
                    <p className={styles.imageStyleGalleryState}>
                      {styleGalleryTemplateKind === "style"
                        ? t("aigcStudio.imageNode.noStyles", "暂无可用风格")
                        : "暂无可用创作模板"}
                    </p>
                  )}
                {styleGalleryTemplates.map((template) => {
                  const isSelected =
                    styleGalleryOpen &&
                    (template.type === "style"
                      ? String(node.data.stylePreset ?? "") ===
                          template.title ||
                        String(node.data.styleTemplateId ?? "") ===
                          template.id ||
                        String(node.data.styleTemplateUuid ?? "") ===
                          template.effect_template_uuid
                      : String(node.data.creationTemplateId ?? "") ===
                        template.id);
                  const isEditable =
                    template.type === "style" &&
                    canEditStyleTemplate(template, isAdmin);
                  const coverUrl = styleTemplateCoverUrl(template.cover_url);
                  return (
                    <article
                      key={template.id}
                      aria-label={t(
                        "aigcStudio.imageNode.styleTemplateCard",
                        `${
                          template.type === "style" ? "风格" : "创作模板"
                        }卡片 ${template.title}`,
                      )}
                      className={
                        isSelected ? styles.imageStyleTemplateActive : undefined
                      }
                    >
                      <span className={styles.imageStyleTemplateActions}>
                        <button
                          type="button"
                          className={
                            template.favorite
                              ? styles.imageStyleTemplateFavoriteActive
                              : undefined
                          }
                          aria-label={t(
                            "aigcStudio.imageNode.favoriteStyleTemplate",
                            template.favorite
                              ? `取消收藏风格 ${template.title}`
                              : `收藏风格 ${template.title}`,
                          )}
                          onClick={(event) => {
                            event.stopPropagation();
                            void toggleStyleTemplateFavorite(template);
                          }}
                        >
                          <Star size={13} />
                        </button>
                        {isEditable && (
                          <>
                            <button
                              type="button"
                              aria-label={t(
                                "aigcStudio.imageNode.editStyleTemplate",
                                `编辑风格 ${template.title}`,
                              )}
                              onClick={(event) => {
                                event.stopPropagation();
                                startEditingStyleTemplate(template);
                              }}
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              type="button"
                              aria-label={t(
                                "aigcStudio.imageNode.deleteStyleTemplate",
                                `删除风格 ${template.title}`,
                              )}
                              onClick={(event) => {
                                event.stopPropagation();
                                void deletePromptStyleTemplate(template);
                              }}
                            >
                              <Trash2 size={13} />
                            </button>
                          </>
                        )}
                      </span>
                      <button
                        type="button"
                        className={styles.imageStyleTemplateSelect}
                        aria-label={template.title}
                        onClick={() => selectStyleTemplate(template)}
                      >
                        <span className={styles.imageStyleTemplatePreview}>
                          {coverUrl ? (
                            <AuthenticatedAssetImage
                              src={coverUrl}
                              alt={template.title}
                            />
                          ) : (
                            <Sparkles size={18} />
                          )}
                          {isSelected && (
                            <em
                              className={styles.imageStyleTemplateSelectedBadge}
                            >
                              {t(
                                "aigcStudio.imageNode.currentStyle",
                                "当前使用",
                              )}
                            </em>
                          )}
                          {(template.visual_dna?.length ?? 0) > 0 && (
                            <em className={styles.imageStyleVisualDnaBadge}>
                              审美 DNA · {template.visual_dna?.length ?? 0}
                            </em>
                          )}
                          {template.type === "play" && (
                            <em className={styles.imageStyleVisualDnaBadge}>
                              创作模板
                            </em>
                          )}
                        </span>
                        <strong>{template.title}</strong>
                        <small>{template.description}</small>
                        <span className={styles.imageStyleTemplateMeta}>
                          <em>{template.tags[0] ?? "商用"}</em>
                          <span>{template.use_count}</span>
                        </span>
                      </button>
                    </article>
                  );
                })}
              </div>
            </section>
          </div>,
          document.body,
        )
      : null;
  const stylePromptTemplateDialog =
    pendingStylePromptTemplate && typeof document !== "undefined"
      ? createPortal(
          <div
            className={`nodrag nopan ${styles.imageStylePromptTemplateBackdrop}`}
            data-testid="aigc-image-style-prompt-template-backdrop"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <section
              className={styles.imageStylePromptTemplateDialog}
              role="dialog"
              aria-modal="true"
              aria-label={t(
                "aigcStudio.imageNode.usePromptTemplate",
                "使用创作模板？",
              )}
              data-testid="aigc-image-style-prompt-template-dialog"
            >
              <strong>
                {t("aigcStudio.imageNode.usePromptTemplate", "使用创作模板？")}
              </strong>
              <p>
                {t(
                  "aigcStudio.imageNode.usePromptTemplateHint",
                  "将「{{style}}」的画面内容模板回填到输入框，之后可以继续修改主体、场景和文案。它不会改变当前审美风格。",
                  { style: pendingStylePromptTemplate.template.title },
                )}
              </p>
              <pre>{pendingStylePromptTemplate.promptTemplate}</pre>
              <div className={styles.imageStylePromptTemplateActions}>
                <button
                  type="button"
                  onClick={() => setPendingStylePromptTemplate(null)}
                >
                  {t("aigcStudio.cancel", "取消")}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    applyCreationTemplateSelection(
                      pendingStylePromptTemplate.template,
                      pendingStylePromptTemplate.promptTemplate,
                    )
                  }
                >
                  {t("aigcStudio.imageNode.fillPromptTemplate", "回填模板")}
                </button>
              </div>
            </section>
          </div>,
          document.body,
        )
      : null;

  return (
    <div
      className={`nodrag nopan ${styles.imageComposer} ${
        imageState === "generating" ? styles.imageComposerGenerating : ""
      } ${imageState === "generated" ? styles.imageComposerGenerated : ""}`}
      data-testid="aigc-image-composer"
      data-image-flow={imageState}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.composerExpand}
        aria-label={t("aigcStudio.composer.fullscreen.open", "全屏编辑输入")}
        onClick={(event) => {
          event.stopPropagation();
          setComposerFullscreenOpen(true);
        }}
      >
        <Maximize2 size={15} />
      </button>
      {node.data.imageMode === "upscale" ? (
        <div className={styles.upscaleComposer}>
          <strong>{t("aigcStudio.imageNode.upscale.panel", "高清放大")}</strong>
          <label>
            {t("aigcStudio.imageNode.upscale.provider", "模型选择")}
            <select
              value={String(node.data.upscaleProvider ?? "Topazlabs")}
              onChange={(event) =>
                onUpdateNodeData(node.id, {
                  upscaleProvider: event.target.value,
                })
              }
            >
              <option>Topazlabs</option>
              <option>Real-ESRGAN</option>
              <option>Magnific</option>
            </select>
          </label>
          <label>
            {t("aigcStudio.imageNode.upscale.modelLabel", "模型")}
            <select
              value={String(node.data.upscaleModel ?? "通用")}
              onChange={(event) =>
                onUpdateNodeData(node.id, {
                  upscaleModel: event.target.value,
                })
              }
            >
              <option>{t("aigcStudio.imageNode.upscale.model", "通用")}</option>
              <option>
                {t("aigcStudio.imageNode.upscale.portrait", "人像")}
              </option>
              <option>
                {t("aigcStudio.imageNode.upscale.product", "商品")}
              </option>
            </select>
          </label>
          <div className={styles.upscaleFactors}>
            <span>{t("aigcStudio.imageNode.upscale.factor", "放大倍数")}</span>
            {[2, 4, 6].map((factor) => (
              <button
                type="button"
                key={factor}
                className={
                  node.data.upscaleFactor === factor
                    ? styles.imageOptionActive
                    : ""
                }
                onClick={() =>
                  onUpdateNodeData(node.id, {
                    upscaleFactor: factor,
                  })
                }
              >
                {factor}
              </button>
            ))}
          </div>
          <div className={styles.upscaleRunRow}>
            <button
              type="button"
              data-platform-control-id="aigc.image.generate-submit"
              className={styles.runCircle}
              aria-label={t(
                "aigcStudio.imageNode.submitComposer",
                "提交图片节点输入",
              )}
              onClick={(event) => {
                event.stopPropagation();
                const submittedText = currentComposerText();
                const nextNode = workflow.handleImageComposerSubmit({
                  ...node,
                  data: {
                    ...node.data,
                    composerText: submittedText,
                    text: submittedText,
                  },
                });
                onRunNode(nextNode);
              }}
              disabled={disabled}
            >
              <Play size={15} />
            </button>
          </div>
        </div>
      ) : (
        <>
          {(enabledImageToolConfigs.length > 0 ||
            node.data.styleReferenceThumb === true ||
            visibleReferenceAssets.length > 0) && (
            <div
              className={styles.composerTools}
              data-testid="aigc-image-composer-tools"
            >
              {node.data.styleReferenceThumb === true && (
                <span
                  className={`${styles.imageReferenceThumb} ${styles.imageStyleReferenceThumb}`}
                  data-testid="aigc-image-style-thumb"
                  title={String(node.data.styleReferenceName ?? "")}
                >
                  {String(node.data.styleReferencePreviewUrl ?? "") ? (
                    <AuthenticatedAssetImage
                      src={String(node.data.styleReferencePreviewUrl)}
                      alt={String(node.data.styleReferenceName ?? "")}
                    />
                  ) : (
                    <Sparkles size={18} />
                  )}
                  <em>{t("aigcStudio.style", "风格")}</em>
                </span>
              )}
              {enabledImageToolConfigs.map((tool) => {
                const hasToolValue = Boolean(node.data[tool.dataKey]);
                const isActive = activeImageTool === tool.key;
                return (
                  <button
                    type="button"
                    key={tool.key}
                    className={
                      isActive || hasToolValue ? styles.imageToolActive : ""
                    }
                    aria-pressed={isActive || hasToolValue}
                    onClick={() => {
                      if (tool.key === "style") {
                        setStyleGalleryOpen(true);
                        onUpdateNodeData(node.id, {
                          activeTool: "style",
                        });
                        return;
                      }
                      onUpdateNodeData(node.id, {
                        activeTool: isActive ? null : tool.key,
                      });
                    }}
                  >
                    {tool.icon}
                    {tool.label}
                  </button>
                );
              })}
              {visibleReferenceAssets.map((asset, index) => (
                <span
                  className={styles.imageReferenceThumb}
                  data-testid="aigc-image-reference-thumb"
                  data-reference-alias={asset.alias}
                  title={asset.name}
                  key={`${asset.id}-${asset.previewUrl}`}
                  draggable
                  onDragStart={(event) => {
                    event.stopPropagation();
                    draggedReferenceAssetRef.current = asset;
                    writeReferenceAssetDragData(event.dataTransfer, asset);
                  }}
                  onDragEnd={(event) => {
                    event.stopPropagation();
                    draggedReferenceAssetRef.current = null;
                  }}
                >
                  {referenceAssetPreview(asset)}
                  <em>{referenceAssetBadgeNumber(asset.alias, index + 1)}</em>
                </span>
              ))}
            </div>
          )}
          {selectedImageToolSummaries.length > 0 && (
            <div
              className={styles.imageToolSummary}
              data-testid="aigc-image-tool-summary"
            >
              {selectedImageToolSummaries.map((tool) => (
                <span key={tool.key}>
                  <small>{tool.label}</small>
                  {tool.value}
                  <button
                    type="button"
                    aria-label={t(
                      "aigcStudio.imageNode.clearToolPreset",
                      "清除{{label}}",
                      { label: tool.label },
                    )}
                    onClick={() => clearImageToolSummary(tool.dataKey)}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          {inlineImageTool && (
            <div
              className={styles.imageToolPanel}
              data-testid={`aigc-image-${inlineImageTool.key}-panel`}
            >
              <div className={styles.imageToolPanelHeader}>
                <strong>{inlineImageTool.label}</strong>
                {inlineImageToolValue && <span>{inlineImageToolValue}</span>}
              </div>
              <div className={styles.imageToolOptions}>
                {inlineImageTool.options.map((option) => (
                  <button
                    type="button"
                    key={option}
                    className={
                      inlineImageToolValue === option
                        ? styles.imageOptionActive
                        : ""
                    }
                    onClick={() =>
                      onUpdateNodeData(node.id, {
                        [inlineImageTool.dataKey]: option,
                        activeTool: inlineImageTool.key,
                        imageState: "editing",
                        imageProgress: null,
                        inputUpdated: true,
                        job_status: null,
                        outputs: [],
                      })
                    }
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
          )}
          <textarea
            ref={composerInputRef}
            className={`${styles.promptPlaceholder} ${styles.textComposerInput}`}
            rows={4}
            value={composerDraftText}
            placeholder={imageComposerPlaceholder}
            aria-label={t("aigcStudio.imageNode.composerLabel", "图片节点输入")}
            onMouseDown={onCloseMenu}
            onFocus={onCloseMenu}
            onDragOver={(event) => {
              const carriesReference =
                draggedReferenceAssetRef.current !== null ||
                Array.from(event.dataTransfer.types).includes(
                  AIGC_REFERENCE_ASSET_MIME,
                );
              if (!carriesReference) return;
              event.preventDefault();
              event.stopPropagation();
              event.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(event) => {
              const asset =
                readReferenceAssetDragData(event.dataTransfer) ??
                draggedReferenceAssetRef.current;
              if (!asset) return;
              event.stopPropagation();
              draggedReferenceAssetRef.current = null;
              const textBeforeDrop = event.currentTarget.value;
              const fallbackStart =
                event.currentTarget.selectionStart ?? textBeforeDrop.length;
              const fallbackEnd =
                event.currentTarget.selectionEnd ?? fallbackStart;
              window.requestAnimationFrame(() => {
                const nativeDropText = composerInputRef.current?.value;
                if (
                  typeof nativeDropText === "string" &&
                  nativeDropText !== textBeforeDrop
                ) {
                  commitDraggedReferenceAsset(asset, nativeDropText);
                  return;
                }
                insertDraggedReferenceAsset(
                  asset,
                  textBeforeDrop,
                  fallbackStart,
                  fallbackEnd,
                );
              });
            }}
            onChange={(event) => {
              updateComposerText(
                event.target.value,
                event.target.selectionStart ?? event.target.value.length,
              );
            }}
            onKeyUp={(event) =>
              applyReferenceMentionText(
                event.currentTarget.value,
                event.currentTarget.selectionStart ??
                  event.currentTarget.value.length,
              )
            }
          />
          {referenceMention && referenceMentionOptions.length > 0 && (
            <div
              className={styles.referenceMentionMenu}
              data-testid="aigc-reference-mention-menu"
            >
              {referenceMentionOptions.map((asset) => (
                <button
                  type="button"
                  key={`${asset.id}-${asset.alias}`}
                  aria-label={`${asset.alias} ${asset.name}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectReferenceMention(asset)}
                >
                  <span className={styles.referenceMentionThumb}>
                    {referenceAssetPreview(asset, 16)}
                  </span>
                  <span>
                    <strong>{asset.alias}</strong>
                    <small>{asset.name}</small>
                  </span>
                </button>
              ))}
            </div>
          )}
          {shouldShowImageSlashMenu(composerDraftText) && (
            <div
              className={styles.slashMenu}
              data-testid="aigc-image-slash-menu"
            >
              {IMAGE_SLASH_COMMANDS.map((command) => (
                <button
                  type="button"
                  key={command.title}
                  onClick={() =>
                    workflow.handleImageSlashCommand(node, command)
                  }
                >
                  <strong>{command.title}</strong>
                  <small>{command.description}</small>
                </button>
              ))}
            </div>
          )}
          {node.data.slashReferenceError && (
            <div className={styles.composerError}>
              <AlertCircle size={14} />
              {String(node.data.slashReferenceError)}
            </div>
          )}
        </>
      )}
      {node.data.imageMode !== "upscale" && (
        <div className={styles.parameterBar}>
          <button
            type="button"
            className={styles.textModelButton}
            onClick={() => onToggleMenu(node.id, "model")}
          >
            {imageModelLabel}
            <span>⌃</span>
          </button>
          {parameterProfile.showPanorama && (
            <button
              type="button"
              className={`${styles.imageParamButton} ${
                isPanorama ? styles.imageParamActive : ""
              }`}
              aria-label={t("aigcStudio.imageNode.panorama", "720全景")}
              aria-pressed={isPanorama}
              onClick={togglePanoramaMode}
            >
              <span className={styles.panoramaBadge}>720</span>
              {t("aigcStudio.imageNode.panoramaLabel", "全景")}
            </button>
          )}
          <button
            type="button"
            className={styles.imageParamButton}
            onClick={() => onToggleMenu(node.id, "size")}
          >
            {sizeSummary}
            <span>⌃</span>
          </button>
          {parameterProfile.showCamera && (
            <button
              type="button"
              className={`${styles.imageParamButton} ${
                hasCameraSettings ? styles.imageParamActive : ""
              }`}
              aria-pressed={hasCameraSettings}
              onClick={() => onToggleMenu(node.id, "camera")}
            >
              <Camera size={15} />
              {t("aigcStudio.camera", "镜头")}
              {hasCameraSettings && <small>{cameraSummary}</small>}
            </button>
          )}
          {parameterProfile.showAdvanced && (
            <button
              type="button"
              className={`${styles.iconParamButton} ${
                hasAdvancedSettings ? styles.imageParamActive : ""
              }`}
              aria-label={t("aigcStudio.imageNode.advanced", "高级设置")}
              aria-pressed={hasAdvancedSettings}
              onClick={() => onToggleMenu(node.id, "advanced")}
            >
              <SlidersHorizontal size={15} />
            </button>
          )}
          <button
            type="button"
            className={`${styles.imageParamButton} ${
              hasCustomCount ? styles.imageParamActive : ""
            }`}
            onClick={() => onToggleMenu(node.id, "count")}
          >
            {t("aigcStudio.imageNode.countValue", "{{count}}张", {
              count: Number(node.data.imageCount ?? 1),
            })}
            <span>⌃</span>
          </button>
          <button
            type="button"
            data-platform-control-id="aigc.image.generate-submit"
            className={styles.runCircle}
            aria-label={t(
              "aigcStudio.imageNode.submitComposer",
              "提交图片节点输入",
            )}
            onClick={(event) => {
              event.stopPropagation();
              const submittedText = currentComposerText();
              const nextNode = workflow.handleImageComposerSubmit({
                ...node,
                data: {
                  ...node.data,
                  composerText: submittedText,
                  text: submittedText,
                },
              });
              onRunNode(nextNode);
            }}
            disabled={disabled}
          >
            <Play size={15} />
          </button>
        </div>
      )}
      {imageComposerMenu?.nodeId === node.id &&
        imageComposerMenu.menu === "model" && (
          <div
            className={styles.imageModelMenu}
            data-testid="aigc-image-model-menu"
          >
            {imageModelOptions.map((model, index) => (
              <button
                type="button"
                key={`${model.provider_id}:${model.model_id}`}
                className={
                  currentModelKey === `${model.provider_id}:${model.model_id}`
                    ? styles.textModelActive
                    : ""
                }
                onClick={() => onSelectModel(model)}
              >
                <span className={styles.imageModelIcon}>
                  {index % 2 === 0 ? <Sparkles size={16} /> : "▧"}
                </span>
                <span>
                  <strong>
                    {imageModelDisplayName(model.model_name) || model.model_id}
                  </strong>
                  {index === 0 && (
                    <small>
                      {t(
                        "aigcStudio.imageNode.modelHint",
                        "照强图片编辑模型，一致性好",
                      )}
                    </small>
                  )}
                </span>
                <em>{runtimeLabelForModel(model)}</em>
              </button>
            ))}
          </div>
        )}
      {imageComposerMenu?.nodeId === node.id &&
        imageComposerMenu.menu === "size" && (
          <div
            className={styles.imageSizeMenu}
            data-testid="aigc-image-size-menu"
            data-image-size-mode={isPanorama ? "panorama" : "standard"}
          >
            {parameterProfile.showQuality && (
              <>
                <div className={styles.imageMenuTitle}>
                  {t("aigcStudio.imageNode.quality", "画质")}
                </div>
                <div className={styles.segmentGrid}>
                  {IMAGE_QUALITY_OPTIONS.map((imageQuality) => (
                    <button
                      type="button"
                      key={imageQuality}
                      className={
                        activeImageQuality === imageQuality
                          ? styles.imageOptionActive
                          : ""
                      }
                      onClick={() => {
                        onUpdateNodeData(node.id, { imageQuality });
                      }}
                    >
                      {imageQuality}
                    </button>
                  ))}
                </div>
              </>
            )}
            <div className={styles.imageMenuTitle}>
              {t("aigcStudio.imageNode.resolution", "分辨率")}
            </div>
            <div className={styles.segmentGrid}>
              {parameterProfile.resolutions.map((resolution) => (
                <button
                  type="button"
                  key={resolution}
                  className={
                    activeResolution === resolution
                      ? styles.imageOptionActive
                      : ""
                  }
                  onClick={() => {
                    onUpdateNodeData(node.id, { resolution });
                  }}
                >
                  {resolution}
                </button>
              ))}
            </div>
            <div className={styles.imageMenuTitle}>
              {t("aigcStudio.imageNode.aspectRatio", "比例")}
            </div>
            <div className={styles.ratioGrid}>
              {parameterProfile.aspectRatios.map((ratio) => {
                const disabled =
                  isPanorama && ratio !== PANORAMA_IMAGE_ASPECT_RATIO;
                return (
                  <button
                    type="button"
                    key={ratio}
                    className={
                      activeAspectRatio === ratio
                        ? styles.imageOptionActive
                        : ""
                    }
                    disabled={disabled}
                    onClick={() => {
                      onUpdateNodeData(node.id, {
                        aspectRatio: ratio,
                      });
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={aspectRatioPreviewStyle(ratio)}
                    />
                    {ratio}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      {imageComposerMenu?.nodeId === node.id &&
        imageComposerMenu.menu === "camera" &&
        parameterProfile.showCamera && (
          <div
            className={styles.cameraPanel}
            data-testid="aigc-image-camera-menu"
          >
            <div className={styles.cameraPanelHeader}>
              <strong>{t("aigcStudio.camera", "镜头")}</strong>
              <button type="button" onClick={onCloseMenu}>
                ×
              </button>
            </div>
            <div className={styles.cameraColumns}>
              {[
                ["cameraBody", "相机", DEFAULT_IMAGE_CAMERA_PRESET.cameraBody],
                ["lens", "镜头", DEFAULT_IMAGE_CAMERA_PRESET.lens],
                ["focal", "焦距", DEFAULT_IMAGE_CAMERA_PRESET.focal],
                ["aperture", "光圈", DEFAULT_IMAGE_CAMERA_PRESET.aperture],
              ].map(([key, title, value]) => (
                <button
                  type="button"
                  key={key}
                  onClick={() => onUpdateNodeData(node.id, { [key]: value })}
                >
                  <span>{title}</span>
                  <strong>{value}</strong>
                </button>
              ))}
            </div>
            <button
              type="button"
              className={styles.cameraUseButton}
              onClick={applyDefaultCameraPreset}
            >
              {t("aigcStudio.imageNode.use", "使用")}
            </button>
          </div>
        )}
      {imageComposerMenu?.nodeId === node.id &&
        imageComposerMenu.menu === "advanced" &&
        parameterProfile.showAdvanced && (
          <div
            className={styles.advancedPanel}
            data-testid="aigc-image-advanced-menu"
          >
            <small>{t("aigcStudio.imageNode.advanced", "高级设置")}</small>
            <label>
              {t("aigcStudio.imageNode.webSearch", "联网搜索")}
              <input
                type="checkbox"
                checked={node.data.webSearch === true}
                onChange={(event) => {
                  onUpdateNodeData(node.id, {
                    webSearch: event.target.checked,
                  });
                }}
              />
            </label>
          </div>
        )}
      {imageComposerMenu?.nodeId === node.id &&
        imageComposerMenu.menu === "count" && (
          <div className={styles.countMenu} data-testid="aigc-image-count-menu">
            {[1, 2, 4].map((count) => (
              <button
                type="button"
                key={count}
                className={
                  Number(node.data.imageCount ?? 1) === count
                    ? styles.textModelActive
                    : ""
                }
                onClick={() => {
                  onUpdateNodeData(node.id, { imageCount: count });
                }}
              >
                {t("aigcStudio.imageNode.countValue", "{{count}}张", {
                  count,
                })}
              </button>
            ))}
          </div>
        )}
      <PromptFullscreenEditor
        open={composerFullscreenOpen}
        title={t(
          "aigcStudio.imageNode.composerFullscreenTitle",
          "图片节点输入全屏编辑",
        )}
        label={t(
          "aigcStudio.imageNode.composerFullscreenLabel",
          "图片节点输入全屏编辑",
        )}
        value={composerDraftText}
        placeholder={imageComposerPlaceholder}
        closeLabel={t("aigcStudio.composer.fullscreen.close", "关闭全屏编辑")}
        meta={t("aigcStudio.composer.fullscreen.meta", "{{count}} 字", {
          count: composerDraftText.length,
        })}
        onChange={updateComposerText}
        onClose={() => setComposerFullscreenOpen(false)}
      />
      {styleGalleryDialog}
      {stylePromptTemplateDialog}
    </div>
  );
}
