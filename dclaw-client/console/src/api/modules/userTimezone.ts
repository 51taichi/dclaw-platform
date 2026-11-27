import { request } from "../request";

export interface UserTimezoneConfig {
  timezone: string;
}

function configBasePath(): string {
  if (
    typeof window !== "undefined" &&
    window.location.pathname.startsWith("/admin")
  ) {
    return "/admin/config";
  }
  return "/user/config";
}

export const userTimezoneApi = {
  getUserTimezone: () =>
    request<UserTimezoneConfig>(`${configBasePath()}/user-timezone`),

  updateUserTimezone: (timezone: string) =>
    request<UserTimezoneConfig>(`${configBasePath()}/user-timezone`, {
      method: "PUT",
      body: JSON.stringify({ timezone }),
    }),
};
