import { request } from "../request";

export type DesktopUpdatePlatform = "win" | "mac";

export interface DesktopUpdateResponse {
  has_update: boolean;
  version: string;
  platform: DesktopUpdatePlatform;
  download_url: string;
  sha256: string;
  size_bytes: number;
  release_notes: string;
  force: boolean;
}

export const desktopUpdateApi = {
  checkUpdate: (platform: DesktopUpdatePlatform, version: string) =>
    request<DesktopUpdateResponse>(
      `/desktop/update?platform=${platform}&version=${encodeURIComponent(
        version,
      )}`,
    ),
};
