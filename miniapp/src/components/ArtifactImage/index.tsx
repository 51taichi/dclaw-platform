import { Image, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useEffect, useState } from "react";

import { downloadArtifactFile } from "../../services/mobile";

import "./index.scss";

interface ArtifactImageProps {
  chatId: string;
  path: string;
  className?: string;
  interactive?: boolean;
}

function isDirectImageSource(path: string): boolean {
  return /^(?:https?:|data:image\/|wxfile:|blob:)/i.test(path);
}

export default function ArtifactImage({
  chatId,
  path,
  className = "",
  interactive = true,
}: ArtifactImageProps) {
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    if (isDirectImageSource(path)) {
      setSrc(path);
      return () => {
        cancelled = true;
      };
    }
    setSrc("");
    void downloadArtifactFile(chatId, path)
      .then((tempFilePath) => {
        if (!cancelled) {
          setSrc(tempFilePath);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [chatId, path]);

  const preview = () => {
    if (!interactive || !src) {
      return;
    }
    void Taro.previewImage({ current: src, urls: [src] });
  };

  return (
    <View
      className={`artifact-image ${interactive ? "artifact-image--interactive" : ""} ${className}`}
      onClick={(event) => {
        if (interactive) {
          event.stopPropagation();
        }
        preview();
      }}
    >
      {src ? (
        <Image
          className="artifact-image__img"
          src={src}
          mode="aspectFill"
          onError={() => {
            setSrc("");
            setFailed(true);
          }}
        />
      ) : (
        <Text className="artifact-image__state">
          {failed ? "图片加载失败" : "图片加载中"}
        </Text>
      )}
    </View>
  );
}
