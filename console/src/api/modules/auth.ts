import { getApiUrl } from "../config";

export interface LoginResponse {
  token: string;
  username: string;
  message?: string;
}

export interface AuthStatusResponse {
  enabled: boolean;
  has_users: boolean;
}

export class AuthApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(
    message: string,
    status: number,
    retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export class AuthNetworkError extends Error {
  constructor() {
    super("Unable to reach the authentication service");
    this.name = "AuthNetworkError";
  }
}

function getRetryAfterSeconds(response: Response): number | null {
  const raw = response.headers?.get("Retry-After");
  if (!raw) return null;

  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

export const authApi = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    let res: Response;
    try {
      res = await fetch(getApiUrl("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    } catch {
      throw new AuthNetworkError();
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new AuthApiError(
        err.detail || "Login failed",
        res.status,
        getRetryAfterSeconds(res),
      );
    }
    return res.json();
  },

  register: async (
    username: string,
    password: string,
  ): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Registration failed");
    }
    return res.json();
  },

  getStatus: async (): Promise<AuthStatusResponse> => {
    const res = await fetch(getApiUrl("/auth/status"));
    if (!res.ok) throw new Error("Failed to check auth status");
    return res.json();
  },

  updateProfile: async (
    currentPassword: string,
    newUsername?: string,
    newPassword?: string,
  ): Promise<LoginResponse> => {
    const token = localStorage.getItem("qwenpaw_auth_token") || "";
    const res = await fetch(getApiUrl("/auth/update-profile"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_username: newUsername || null,
        new_password: newPassword || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Update failed");
    }
    return res.json();
  },
};
