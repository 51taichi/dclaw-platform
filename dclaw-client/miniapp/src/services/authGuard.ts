export function normalizeAuthToken(token: string | null | undefined): string {
  return (token || "").trim();
}

export function shouldRedirectToLogin(token: string | null | undefined): boolean {
  return normalizeAuthToken(token).length === 0;
}
