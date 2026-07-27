/// <reference types="@tarojs/taro" />

declare const __DCLAW_API_BASE__: string;

declare namespace NodeJS {
  interface ProcessEnv {
    QWENPAW_SAAS_HOST_PORT?: string;
    TARO_APP_API_BASE?: string;
    TARO_APP_API_HOST?: string;
    TARO_APP_API_PORT?: string;
  }
}
