import { AuthApiError, AuthNetworkError } from "../../api/modules/auth";

type Translate = (key: string, options?: { seconds: number }) => string;

export function getLoginErrorMessage(
  error: unknown,
  translate: Translate,
): string {
  if (error instanceof AuthNetworkError) {
    return translate("login.networkError");
  }

  if (error instanceof AuthApiError) {
    if (error.status === 401) {
      return translate("login.invalidCredentials");
    }
    if (error.status === 429) {
      return error.retryAfterSeconds
        ? translate("login.tooManyAttemptsWithRetry", {
            seconds: error.retryAfterSeconds,
          })
        : translate("login.tooManyAttempts");
    }
    if (error.status >= 500) {
      return translate("login.serviceUnavailable");
    }
  }

  return translate("login.failed");
}
