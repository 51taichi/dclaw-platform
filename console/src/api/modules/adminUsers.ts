import { getApiUrl, getApiToken } from "../config";

export interface AdminUser {
  id: number;
  username: string;
  display_name?: string | null;
  phone_number?: string | null;
  ai_customer_service_url?: string | null;
  scene_tabs?: SceneTabInput[];
  role: string;
  created_at: string;
}

export interface SceneTabInput {
  title: string;
  url: string;
  icon?: string;
}

export interface CreateAdminUserInput {
  username: string;
  display_name?: string;
  phone_number?: string;
  ai_customer_service_url?: string;
  scene_tabs?: SceneTabInput[];
  password: string;
  role: "admin" | "user";
}

export const adminUsersApi = {
  async listUsers(): Promise<AdminUser[]> {
    const res = await fetch(getApiUrl("/admin/users"), {
      headers: {
        Authorization: `Bearer ${getApiToken()}`,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to list users");
    }
    return res.json();
  },

  async createUser(data: CreateAdminUserInput): Promise<AdminUser> {
    const res = await fetch(getApiUrl("/admin/users"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getApiToken()}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to create user");
    }
    return res.json();
  },

  async resetPassword(userId: number, new_password: string): Promise<void> {
    const res = await fetch(getApiUrl(`/admin/users/${userId}/password`), {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getApiToken()}`,
      },
      body: JSON.stringify({ new_password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to reset password");
    }
  },

  async updateSceneTabs(
    userId: number,
    scene_tabs: SceneTabInput[],
  ): Promise<AdminUser> {
    const res = await fetch(getApiUrl(`/admin/users/${userId}/scene-tabs`), {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getApiToken()}`,
      },
      body: JSON.stringify({ scene_tabs }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to update scene tabs");
    }
    return res.json();
  },

  async deleteUser(userId: number): Promise<void> {
    const res = await fetch(getApiUrl(`/admin/users/${userId}`), {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${getApiToken()}`,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to delete user");
    }
  },
};
