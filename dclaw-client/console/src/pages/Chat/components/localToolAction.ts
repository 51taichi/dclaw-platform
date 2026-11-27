export function isTrustedLocalToolActionUrl(value: string): boolean {
  try {
    const url = new URL(value);
    const trustedHost =
      url.hostname === window.location.hostname ||
      url.hostname === "dclaw.deepmega.cn" ||
      url.hostname.endsWith(".dclaw.deepmega.cn");
    return (
      url.protocol === "https:" &&
      trustedHost &&
      /^\/api\/bootstrap\/[^/]+\/connect$/.test(url.pathname) &&
      !url.username &&
      !url.password &&
      !url.hash
    );
  } catch {
    return false;
  }
}
