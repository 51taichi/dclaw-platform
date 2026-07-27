import Taro from "@tarojs/taro";

import { clearAuthToken, getAuthToken } from "./auth";
import {
  getRequestFailureMessage,
  getResponseErrorMessage,
} from "./apiError";

const API_BASE =
  typeof __DCLAW_API_BASE__ === "string" ? __DCLAW_API_BASE__ : "";
const DEFAULT_REQUEST_TIMEOUT_MS = 8000;

function joinUrl(prefix: string, path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${prefix}${normalized}`;
}

export function buildRequestUrl(prefix: string, path: string): string {
  return joinUrl(prefix, path);
}

function buildHeader(extra?: TaroGeneral.IAnyObject): TaroGeneral.IAnyObject {
  const token = getAuthToken();
  const header: TaroGeneral.IAnyObject = {
    ...(extra || {}),
  };
  if (token) {
    header.Authorization = `Bearer ${token}`;
  }
  return header;
}

async function requestWithPrefix<T>(
  prefix: string,
  path: string,
  options: Omit<Taro.request.Option, "url"> = {},
): Promise<T> {
  let response: Awaited<ReturnType<typeof Taro.request<T>>>;
  try {
    response = await Taro.request<T>({
      ...options,
      url: joinUrl(prefix, path),
      header: buildHeader(options.header),
      timeout: options.timeout || DEFAULT_REQUEST_TIMEOUT_MS,
    });
  } catch (error) {
    throw new Error(getRequestFailureMessage(error));
  }

  if (response.statusCode === 401) {
    clearAuthToken();
    Taro.reLaunch({ url: "/pages/login/index" });
    throw new Error("请先登录");
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(
      getResponseErrorMessage(response.data, response.statusCode),
    );
  }

  return response.data as T;
}

export function request<T>(
  path: string,
  options: Omit<Taro.request.Option, "url"> = {},
): Promise<T> {
  return requestWithPrefix<T>("/api/user", path, options);
}

export function requestRoot<T>(
  path: string,
  options: Omit<Taro.request.Option, "url"> = {},
): Promise<T> {
  return requestWithPrefix<T>("/api", path, options);
}
