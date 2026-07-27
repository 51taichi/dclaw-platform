import { useLayoutEffect, type RefObject } from "react";

import { resizeTextareaToContent } from "../../../utils/textareaAutosize";

export function useAutoGrowTextarea(
  value: string,
  textareaRef: RefObject<HTMLTextAreaElement | null>,
) {
  useLayoutEffect(() => {
    resizeTextareaToContent(textareaRef.current, Number.POSITIVE_INFINITY);
  }, [textareaRef, value]);
}
