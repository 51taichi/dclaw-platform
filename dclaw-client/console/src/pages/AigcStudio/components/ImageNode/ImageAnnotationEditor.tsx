import {
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { ArrowLeft, RotateCcw, Save, Trash2 } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import {
  imageAnnotationPathD,
  imageAnnotationViewBoxForNode,
  type ImageAnnotationPath,
  type ImageAnnotationViewBox,
} from "../../canvasAnnotationActions";
import styles from "../../index.module.less";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import type { Translate } from "./types";

type ImageAnnotationEditorProps = {
  node: AigcCanvasNode;
  sourcePreviewUrl: string;
  t: Translate;
  onCancel: () => void;
  onSave: (annotation: {
    annotationPreviewUrl: string;
    annotationPaths: ImageAnnotationPath[];
    annotationViewBox: ImageAnnotationViewBox;
    instruction: string;
    sourcePreviewUrl: string;
  }) => void;
};

const STROKE_COLOR = "#ff2424";
const STROKE_WIDTH = 18;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const escapeAttribute = (value: string) =>
  value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

const absoluteSvgImageUrl = (source: string) => {
  try {
    return new URL(
      source,
      typeof window === "undefined" ? "http://localhost" : window.location.href,
    ).toString();
  } catch {
    return source;
  }
};

const annotationSvgDataUrl = ({
  sourcePreviewUrl,
  paths,
  viewBox,
}: {
  sourcePreviewUrl: string;
  paths: ImageAnnotationPath[];
  viewBox: ImageAnnotationViewBox;
}) => {
  const safeSource = escapeAttribute(absoluteSvgImageUrl(sourcePreviewUrl));
  const pathMarkup = paths
    .filter((path) => path.points.length > 0)
    .map(
      (path) =>
        `<path d="${escapeAttribute(
          imageAnnotationPathD(path),
        )}" fill="none" stroke="${STROKE_COLOR}" stroke-width="${STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round" />`,
    )
    .join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${viewBox.width}" height="${viewBox.height}" viewBox="0 0 ${viewBox.width} ${viewBox.height}"><image href="${safeSource}" x="0" y="0" width="${viewBox.width}" height="${viewBox.height}" preserveAspectRatio="xMidYMid meet" />${pathMarkup}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
};

export function ImageAnnotationEditor({
  node,
  sourcePreviewUrl,
  t,
  onCancel,
  onSave,
}: ImageAnnotationEditorProps) {
  const [paths, setPaths] = useState<ImageAnnotationPath[]>([]);
  const viewBox = useMemo(() => imageAnnotationViewBoxForNode(node), [node]);
  const [instruction, setInstruction] = useState(
    t(
      "aigcStudio.imageNode.annotation.defaultInstruction",
      "按红色标注区域局部编辑。",
    ),
  );
  const activePathIdRef = useRef<string | null>(null);
  const nextPathIdRef = useRef(1);
  const sourceName = String(
    node.data.assetName ??
      node.data.referenceAssetName ??
      node.data.title ??
      t("aigcStudio.imageNode.generated", "生成结果"),
  );

  const pathElements = useMemo(
    () =>
      paths
        .filter((path) => path.points.length > 0)
        .map((path) => (
          <path
            d={imageAnnotationPathD(path)}
            fill="none"
            key={path.id}
            stroke={STROKE_COLOR}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={STROKE_WIDTH}
          />
        )),
    [paths],
  );

  const pointFromEvent = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = rect.width || 1;
    const height = rect.height || 1;
    return {
      x: Math.round(
        clamp(
          ((event.clientX - rect.left) / width) * viewBox.width,
          0,
          viewBox.width,
        ),
      ),
      y: Math.round(
        clamp(
          ((event.clientY - rect.top) / height) * viewBox.height,
          0,
          viewBox.height,
        ),
      ),
    };
  };

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const pathId = `annotation-path-${nextPathIdRef.current}`;
    nextPathIdRef.current += 1;
    activePathIdRef.current = pathId;
    const point = pointFromEvent(event);
    setPaths((current) => [...current, { id: pathId, points: [point] }]);
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!activePathIdRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const point = pointFromEvent(event);
    setPaths((current) =>
      current.map((path) =>
        path.id === activePathIdRef.current
          ? { ...path, points: [...path.points, point] }
          : path,
      ),
    );
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    event.preventDefault();
    event.stopPropagation();
    activePathIdRef.current = null;
  };

  const handleSave = () => {
    onSave({
      annotationPreviewUrl: annotationSvgDataUrl({
        sourcePreviewUrl,
        paths,
        viewBox,
      }),
      annotationPaths: paths,
      annotationViewBox: viewBox,
      instruction,
      sourcePreviewUrl,
    });
  };

  return (
    <div
      className={styles.annotationEditor}
      data-aigc-floating-panel
      data-testid="aigc-image-annotation-editor"
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className={styles.annotationToolbar}>
        <button
          type="button"
          aria-label={t("aigcStudio.imageNode.annotation.cancel", "退出标注")}
          onClick={onCancel}
        >
          <ArrowLeft size={16} />
        </button>
        <strong>{t("aigcStudio.imageNode.annotation.title", "标注")}</strong>
        <button
          type="button"
          aria-label={t("aigcStudio.imageNode.annotation.undo", "撤销")}
          onClick={() => setPaths((current) => current.slice(0, -1))}
        >
          <RotateCcw size={16} />
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.imageNode.annotation.clear", "清除标注")}
          onClick={() => setPaths([])}
        >
          <Trash2 size={16} />
        </button>
        <button
          type="button"
          className={styles.annotationSave}
          aria-label={t("aigcStudio.imageNode.annotation.save", "保存标注")}
          onClick={handleSave}
        >
          <Save size={16} />
          {t("aigcStudio.imageNode.annotation.save", "保存标注")}
        </button>
      </div>
      <div
        className={styles.annotationStage}
        data-testid="aigc-image-annotation-surface"
        style={{ aspectRatio: `${viewBox.width} / ${viewBox.height}` }}
      >
        <AuthenticatedAssetImage src={sourcePreviewUrl} alt={sourceName} />
        <svg
          className={styles.annotationDrawingLayer}
          data-testid="aigc-image-annotation-stage"
          viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {pathElements}
        </svg>
      </div>
      <input
        className={styles.annotationInstruction}
        aria-label={t(
          "aigcStudio.imageNode.annotation.instruction",
          "标注说明",
        )}
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder={t(
          "aigcStudio.imageNode.annotation.instructionPlaceholder",
          "这块要怎么改",
        )}
      />
    </div>
  );
}
