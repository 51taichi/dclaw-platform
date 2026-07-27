import { Image, Upload } from "lucide-react";
import type { SyntheticEvent } from "react";

import {
  imageAnnotationSourceSize,
  imageAnnotationPathD,
  imageAnnotationViewBoxForNode,
  type ImageAnnotationPath,
} from "../../canvasAnnotationActions";
import styles from "../../index.module.less";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import type { UploadedAssetNodeProps } from "./types";

const annotationPathsFromNode = (value: unknown): ImageAnnotationPath[] => {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (path): path is ImageAnnotationPath =>
      path &&
      typeof path === "object" &&
      "id" in path &&
      "points" in path &&
      Array.isArray((path as ImageAnnotationPath).points),
  );
};

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const imageSizeFromNode = (node: UploadedAssetNodeProps["node"]) => {
  const width =
    numberValue(node.data.assetWidth) ??
    numberValue(node.data.sourceImageWidth);
  const height =
    numberValue(node.data.assetHeight) ??
    numberValue(node.data.sourceImageHeight);
  return width && height ? { width, height } : null;
};

export function UploadedAssetNode({
  node,
  t,
  onReplace,
  onUpdateNodeData,
}: UploadedAssetNodeProps) {
  const isAnnotation =
    node.data.isAnnotation === true ||
    String(node.data.assetRole ?? "") === "image_annotation";
  const previewUrl = String(
    node.data.assetPreviewUrl ?? node.data.annotationSourcePreviewUrl ?? "",
  );
  const annotationPaths = isAnnotation
    ? annotationPathsFromNode(node.data.annotationPaths)
    : [];
  const annotationSourceSize = imageAnnotationSourceSize(node);
  const annotationViewBox = imageAnnotationViewBoxForNode(node);
  const imageSize = imageSizeFromNode(node);
  const cardAspectRatio = isAnnotation
    ? `${annotationSourceSize.width} / ${annotationSourceSize.height}`
    : imageSize
    ? `${imageSize.width} / ${imageSize.height}`
    : undefined;
  const handlePreviewLoad = (event: SyntheticEvent<HTMLImageElement>) => {
    if (isAnnotation) return;
    const { naturalWidth, naturalHeight } = event.currentTarget;
    if (!naturalWidth || !naturalHeight) return;
    if (
      numberValue(node.data.assetWidth) === naturalWidth &&
      numberValue(node.data.assetHeight) === naturalHeight
    ) {
      return;
    }
    onUpdateNodeData?.(node.id, {
      assetWidth: naturalWidth,
      assetHeight: naturalHeight,
    });
  };

  return (
    <>
      <div className={styles.uploadedAssetLabel}>
        <span>
          <Image size={15} />
          {String(
            node.data.title ??
              t("aigcStudio.imageNode.sources.image", "图片节点"),
          )}
        </span>
      </div>
      <div
        className={`${styles.uploadedAssetCard} ${
          isAnnotation ? styles.uploadedAssetCardAnnotation : ""
        }`}
        data-testid="aigc-uploaded-asset-card"
        style={cardAspectRatio ? { aspectRatio: cardAspectRatio } : undefined}
      >
        {previewUrl ? (
          <AuthenticatedAssetImage
            src={previewUrl}
            alt={String(node.data.assetName ?? "")}
            onLoad={handlePreviewLoad}
          />
        ) : (
          <div className={styles.uploadedAssetFallback}>
            <Image size={42} />
            <span>{String(node.data.assetName ?? "")}</span>
          </div>
        )}
        {annotationPaths.length > 0 && (
          <svg
            className={styles.uploadedAssetAnnotationLayer}
            data-testid="aigc-uploaded-asset-annotation"
            viewBox={`0 0 ${annotationViewBox.width} ${annotationViewBox.height}`}
            aria-hidden="true"
          >
            {annotationPaths.map((path) => (
              <path
                d={imageAnnotationPathD(path)}
                fill="none"
                key={path.id}
                stroke="#ff2424"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={18}
              />
            ))}
          </svg>
        )}
        {!isAnnotation && (
          <label
            className={styles.uploadedAssetReplace}
            onClick={(event) => event.stopPropagation()}
          >
            <Upload size={14} />
            <input
              type="file"
              accept="image/*"
              aria-label={t("aigcStudio.imageNode.replaceSource", "替换参考图")}
              onChange={(event) => {
                void onReplace(node, event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
        )}
      </div>
    </>
  );
}
