export const DEFAULT_MINIAPP_API_BASE = "https://dclaw.deepmega.cn";
export const DEFAULT_LOCAL_DOCKER_API_HOST = "127.0.0.1";
export const DEFAULT_LOCAL_DOCKER_API_PORT = "18088";
export const DEFAULT_LOCAL_DOCKER_API_BASE = `http://${DEFAULT_LOCAL_DOCKER_API_HOST}:${DEFAULT_LOCAL_DOCKER_API_PORT}`;

type ApiBaseEnv = {
  QWENPAW_SAAS_HOST_PORT?: string;
  TARO_APP_API_BASE?: string;
  TARO_APP_API_HOST?: string;
  TARO_APP_API_PORT?: string;
};

export function resolveMiniappApiBase(env: ApiBaseEnv): string {
  if (env.TARO_APP_API_BASE) {
    return env.TARO_APP_API_BASE;
  }

  if (
    env.TARO_APP_API_HOST ||
    env.TARO_APP_API_PORT ||
    env.QWENPAW_SAAS_HOST_PORT
  ) {
    const host = env.TARO_APP_API_HOST || DEFAULT_LOCAL_DOCKER_API_HOST;
    const port =
      env.TARO_APP_API_PORT ||
      env.QWENPAW_SAAS_HOST_PORT ||
      DEFAULT_LOCAL_DOCKER_API_PORT;
    return `http://${host}:${port}`;
  }

  return DEFAULT_MINIAPP_API_BASE;
}
