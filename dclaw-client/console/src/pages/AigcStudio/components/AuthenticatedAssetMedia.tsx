import { forwardRef, useEffect, useState } from "react";
import type { ImgHTMLAttributes, VideoHTMLAttributes } from "react";

import { buildAuthHeaders } from "../../../api/authHeaders";

const TRANSPARENT_IMAGE =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
const SIGNED_URL_CACHE_PREFIX = "aigc.authenticatedAsset.signedUrl:";
const SIGNED_URL_MIN_REMAINING_MS = 5_000;

type SignedUrlCacheEntry = {
  url: string;
  expiresAt: number;
};

const signedUrlCache = new Map<string, SignedUrlCacheEntry>();

export function clearAuthenticatedAssetMediaCache() {
  signedUrlCache.clear();
  if (typeof window === "undefined") return;
  try {
    const keysToRemove: string[] = [];
    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index);
      if (key?.startsWith(SIGNED_URL_CACHE_PREFIX)) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach((key) => window.sessionStorage.removeItem(key));
  } catch {
    // Ignore storage access errors in private browsing or locked-down contexts.
  }
}

export function shouldFetchAuthenticatedAsset(source: string): boolean {
  const trimmed = source.trim();
  if (!trimmed || /^(blob:|data:)/i.test(trimmed)) return false;

  try {
    const url = new URL(
      trimmed,
      typeof window === "undefined" ? "http://localhost" : window.location.href,
    );
    return (
      url.pathname.startsWith("/api/user/") ||
      url.pathname.startsWith("/api/admin/")
    );
  } catch {
    return (
      trimmed.startsWith("/api/user/") || trimmed.startsWith("/api/admin/")
    );
  }
}

function normalizeSameHostApiUrl(url: URL): URL {
  if (typeof window === "undefined") return url;
  const currentLocation = window.location;
  if (
    currentLocation.protocol === "https:" &&
    url.protocol === "http:" &&
    url.hostname === currentLocation.hostname
  ) {
    url.protocol = currentLocation.protocol;
    url.host = currentLocation.host;
  }
  return url;
}

export function absoluteAuthenticatedAssetFetchUrl(source: string): string {
  try {
    return normalizeSameHostApiUrl(
      new URL(
        source,
        typeof window === "undefined"
          ? "http://localhost"
          : window.location.href,
      ),
    ).toString();
  } catch {
    return source;
  }
}

function assetSignedUrlSource(source: string): string | null {
  try {
    const url = normalizeSameHostApiUrl(
      new URL(
        source,
        typeof window === "undefined"
          ? "http://localhost"
          : window.location.href,
      ),
    );
    if (!url.pathname.match(/\/aigc-studio\/assets\/[^/]+\/file$/)) {
      return null;
    }
    url.pathname = url.pathname.replace(/\/file$/, "/signed-url");
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    if (!source.match(/\/aigc-studio\/assets\/[^/]+\/file$/)) {
      return null;
    }
    return source.replace(/\/file$/, "/signed-url");
  }
}

function sessionStorageKey(source: string): string {
  return `${SIGNED_URL_CACHE_PREFIX}${source}`;
}

function usableCachedSignedUrl(
  entry: SignedUrlCacheEntry | null,
): string | null {
  if (!entry?.url) return null;
  if (entry.expiresAt <= Date.now() + SIGNED_URL_MIN_REMAINING_MS) return null;
  return entry.url;
}

function cachedSignedUrl(source: string): string | null {
  const memoryValue = usableCachedSignedUrl(signedUrlCache.get(source) ?? null);
  if (memoryValue) return memoryValue;
  signedUrlCache.delete(source);

  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(sessionStorageKey(source));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SignedUrlCacheEntry>;
    const entry =
      typeof parsed.url === "string" && typeof parsed.expiresAt === "number"
        ? { url: parsed.url, expiresAt: parsed.expiresAt }
        : null;
    const storedValue = usableCachedSignedUrl(entry);
    if (storedValue && entry) {
      signedUrlCache.set(source, entry);
      return storedValue;
    }
    window.sessionStorage.removeItem(sessionStorageKey(source));
  } catch {
    return null;
  }
  return null;
}

function cacheSignedUrl(source: string, url: string, expiresIn: unknown): void {
  const seconds = Number(expiresIn);
  const ttlMs =
    Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 60_000;
  const safetyMs = Math.min(60_000, Math.max(5_000, ttlMs * 0.1));
  const entry = {
    url,
    expiresAt: Date.now() + Math.max(0, ttlMs - safetyMs),
  };
  if (!usableCachedSignedUrl(entry)) return;
  signedUrlCache.set(source, entry);
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      sessionStorageKey(source),
      JSON.stringify(entry),
    );
  } catch {
    // Memory cache is enough when session storage is unavailable or full.
  }
}

type AuthenticatedAssetSourceOptions = {
  preferProxy?: boolean;
};

export function useAuthenticatedAssetSource(
  src: string,
  { preferProxy = false }: AuthenticatedAssetSourceOptions = {},
) {
  const normalizedSrc = src.trim();
  const needsAuthenticatedFetch = shouldFetchAuthenticatedAsset(normalizedSrc);
  const [objectSource, setObjectSource] = useState("");
  const [objectUrl, setObjectUrl] = useState("");
  const [loadState, setLoadState] = useState<
    "idle" | "loading" | "loaded" | "failed"
  >("idle");

  useEffect(() => {
    if (!needsAuthenticatedFetch || !normalizedSrc) {
      setObjectSource("");
      setObjectUrl("");
      setLoadState("idle");
      return;
    }

    let cancelled = false;
    let nextObjectUrl = "";
    const headers = buildAuthHeaders();
    if (!headers.Authorization) {
      setObjectSource(normalizedSrc);
      setObjectUrl("");
      setLoadState("failed");
      return;
    }

    setObjectSource(normalizedSrc);
    setObjectUrl("");
    setLoadState("loading");

    const loadViaProxy = () =>
      fetch(absoluteAuthenticatedAssetFetchUrl(normalizedSrc), {
        credentials: "include",
        headers,
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Asset media request failed: ${response.status}`);
          }
          return response.blob();
        })
        .then((blob) => URL.createObjectURL(blob));

    const signedUrlSource = preferProxy
      ? null
      : assetSignedUrlSource(normalizedSrc);
    const cachedDirectSource = signedUrlSource
      ? cachedSignedUrl(signedUrlSource)
      : null;
    const loadDirectSource = cachedDirectSource
      ? Promise.resolve(cachedDirectSource)
      : signedUrlSource
      ? fetch(signedUrlSource, {
          credentials: "include",
          headers,
        })
          .then((response) => {
            if (!response.ok) {
              throw new Error(
                `Asset signed URL request failed: ${response.status}`,
              );
            }
            return response.json() as Promise<{
              url?: unknown;
              expires_in?: unknown;
            }>;
          })
          .then((payload) => {
            const directUrl = String(payload.url || "").trim();
            if (!directUrl) {
              throw new Error(
                "Asset signed URL response did not include a URL",
              );
            }
            cacheSignedUrl(signedUrlSource, directUrl, payload.expires_in);
            return directUrl;
          })
          .catch(() => loadViaProxy())
      : loadViaProxy();

    loadDirectSource
      .then((resolvedUrl) => {
        if (cancelled) return;
        nextObjectUrl = resolvedUrl;
        setObjectUrl(nextObjectUrl);
        setLoadState("loaded");
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn("Failed to load authenticated asset media:", error);
        setLoadState("failed");
      });

    return () => {
      cancelled = true;
      if (nextObjectUrl.startsWith("blob:")) {
        URL.revokeObjectURL(nextObjectUrl);
      }
    };
  }, [needsAuthenticatedFetch, normalizedSrc, preferProxy]);

  const resolvedSrc =
    needsAuthenticatedFetch && objectSource === normalizedSrc && objectUrl
      ? objectUrl
      : needsAuthenticatedFetch
      ? TRANSPARENT_IMAGE
      : normalizedSrc;

  return {
    loadState,
    needsAuthenticatedFetch,
    resolvedSrc,
  };
}

type AuthenticatedAssetImageProps = Omit<
  ImgHTMLAttributes<HTMLImageElement>,
  "src"
> & {
  src: string;
};

export function AuthenticatedAssetImage({
  src,
  ...imageProps
}: AuthenticatedAssetImageProps) {
  const { loadState, needsAuthenticatedFetch, resolvedSrc } =
    useAuthenticatedAssetSource(src);

  return (
    <img
      {...imageProps}
      src={resolvedSrc}
      data-authenticated-asset={needsAuthenticatedFetch ? "true" : undefined}
      data-authenticated-asset-state={
        needsAuthenticatedFetch ? loadState : undefined
      }
    />
  );
}

type AuthenticatedAssetVideoProps = Omit<
  VideoHTMLAttributes<HTMLVideoElement>,
  "src"
> & {
  src: string;
};

export const AuthenticatedAssetVideo = forwardRef<
  HTMLVideoElement,
  AuthenticatedAssetVideoProps
>(function AuthenticatedAssetVideo({ src, ...videoProps }, ref) {
  const { loadState, needsAuthenticatedFetch, resolvedSrc } =
    useAuthenticatedAssetSource(src);
  const videoSrc =
    needsAuthenticatedFetch && resolvedSrc === TRANSPARENT_IMAGE
      ? undefined
      : resolvedSrc;

  return (
    <video
      {...videoProps}
      ref={ref}
      src={videoSrc}
      data-authenticated-asset={needsAuthenticatedFetch ? "true" : undefined}
      data-authenticated-asset-state={
        needsAuthenticatedFetch ? loadState : undefined
      }
    />
  );
});
