import { invoke } from "@tauri-apps/api/core";
import { Alert, Spin } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ClientScene } from "../../api/modules/auth";
import styles from "../index.module.less";

interface SceneWebviewBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

function measureHost(element: HTMLElement): SceneWebviewBounds | null {
  const rect = element.getBoundingClientRect();
  const borderInset = 1;
  const width = Math.floor(rect.width - borderInset * 2);
  const height = Math.floor(rect.height - borderInset * 2);
  if (width < 1 || height < 1) return null;

  return {
    x: Math.floor(rect.left + borderInset),
    y: Math.floor(rect.top + borderInset),
    width,
    height,
  };
}

export default function SceneWebviewHost({ scene }: { scene: ClientScene }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let disposed = false;
    let resizeFrame = 0;
    const commandPayload = {
      sceneKey: scene.key,
      url: scene.url,
    };
    const initialBounds = measureHost(host);
    if (initialBounds) {
      void invoke("show_scene_webview", {
        ...commandPayload,
        bounds: initialBounds,
      })
        .then(() => {
          if (!disposed) setError(null);
        })
        .catch((reason: unknown) => {
          if (!disposed) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        });
    }

    const syncBounds = () => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        const bounds = measureHost(host);
        if (!disposed && bounds) {
          void invoke("resize_scene_webview", {
            ...commandPayload,
            bounds,
          });
        }
      });
    };
    const observer = new ResizeObserver(syncBounds);
    observer.observe(host);
    window.addEventListener("resize", syncBounds);
    window.visualViewport?.addEventListener("resize", syncBounds);

    return () => {
      disposed = true;
      cancelAnimationFrame(resizeFrame);
      observer.disconnect();
      window.removeEventListener("resize", syncBounds);
      window.visualViewport?.removeEventListener("resize", syncBounds);
    };
  }, [scene.key, scene.url]);

  useEffect(
    () => () => {
      void invoke("hide_scene_webviews");
    },
    [],
  );

  return (
    <div
      ref={hostRef}
      className={styles.sceneWebviewHost}
      data-scene-webview={scene.key}
    >
      {error ? (
        <Alert
          type="error"
          showIcon
          message="场景加载失败"
          description={error}
        />
      ) : (
        <Spin tip="加载中" />
      )}
    </div>
  );
}
