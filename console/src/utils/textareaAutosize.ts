export function resizeTextareaToContent(
  textarea: HTMLTextAreaElement | null,
  maxHeight = 220,
): void {
  if (!textarea) return;

  textarea.style.height = "auto";

  const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
  if (nextHeight > 0) {
    textarea.style.height = `${nextHeight}px`;
  }
  textarea.style.overflowY =
    textarea.scrollHeight > maxHeight ? "auto" : "hidden";
}
