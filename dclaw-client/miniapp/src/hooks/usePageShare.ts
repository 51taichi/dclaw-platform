import { useShareAppMessage, useShareTimeline } from "@tarojs/taro";

type PageShareOptions = {
  title: string;
  path: string;
};

export function getShareQuery(path: string): string {
  const queryStart = path.indexOf("?");
  return queryStart >= 0 ? path.slice(queryStart + 1) : "";
}

export default function usePageShare({ title, path }: PageShareOptions) {
  useShareAppMessage(() => ({
    title,
    path,
  }));

  useShareTimeline(() => ({
    title,
    query: getShareQuery(path),
  }));
}
