type ErrorRecord = Record<string, unknown>;

function isRecord(value: unknown): value is ErrorRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function textFromValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }

  if (Array.isArray(value)) {
    return value
      .map(textFromValue)
      .filter(Boolean)
      .join("；");
  }

  if (isRecord(value)) {
    return (
      textFromValue(value.msg) ||
      textFromValue(value.message) ||
      textFromValue(value.detail) ||
      textFromValue(value.error)
    );
  }

  return "";
}

function localizeBackendMessage(message: string, statusCode: number): string {
  if (statusCode === 401 && message === "Invalid username or password") {
    return "账户或密码错误";
  }
  return message;
}

export function getResponseErrorMessage(
  data: unknown,
  statusCode: number,
): string {
  const directMessage = textFromValue(data);
  if (directMessage) {
    return localizeBackendMessage(directMessage, statusCode);
  }
  return `Request failed: ${statusCode}`;
}

export function getRequestFailureMessage(error: unknown): string {
  const message =
    error instanceof Error
      ? error.message
      : isRecord(error)
        ? textFromValue(error.errMsg) || textFromValue(error.message)
        : "";

  if (message.includes("timeout")) {
    return "请求超时，请确认 DClaw 后端已启动并可访问";
  }

  return message || "网络请求失败";
}
