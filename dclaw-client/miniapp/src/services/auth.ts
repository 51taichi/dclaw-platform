import Taro from "@tarojs/taro";

import { shouldRedirectToLogin } from "./authGuard";

const TOKEN_KEY = "qwenpaw_auth_token";
const USERNAME_KEY = "qwenpaw_username";

export interface LoginResponse {
  token: string;
  username: string;
}

export function getAuthToken(): string {
  return Taro.getStorageSync(TOKEN_KEY) || "";
}

export function getStoredUsername(): string {
  return String(Taro.getStorageSync(USERNAME_KEY) || "").trim();
}

export function setAuthToken(token: string): void {
  Taro.setStorageSync(TOKEN_KEY, token);
}

export function setAuthSession(response: LoginResponse): void {
  setAuthToken(response.token);
  const username = response.username.trim();
  if (username) {
    Taro.setStorageSync(USERNAME_KEY, username);
    return;
  }
  Taro.removeStorageSync(USERNAME_KEY);
}

export function clearAuthToken(): void {
  Taro.removeStorageSync(TOKEN_KEY);
  Taro.removeStorageSync(USERNAME_KEY);
}

export function requireAuth(): boolean {
  if (!shouldRedirectToLogin(getAuthToken())) {
    return true;
  }
  Taro.reLaunch({ url: "/pages/login/index" });
  return false;
}
