import { createContext, useContext, useState, useEffect } from "react";
import { authApi } from "../api/modules/auth";
import type { ClientScene } from "../api/modules/auth";
import { getApiToken, getApiUrl, clearAuthToken } from "../api/config";

interface AuthContextType {
  username: string | null;
  role: string | null;
  scenes: ClientScene[];
  status: "loading" | "auth-required" | "ok";
  setRole: (role: string | null) => void;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  username: null,
  role: null,
  scenes: [],
  status: "loading",
  setRole: () => {},
  logout: () => {},
  checkAuth: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRoleState] = useState<string | null>(() =>
    localStorage.getItem("qwenpaw_user_role"),
  );
  const [scenes, setScenes] = useState<ClientScene[]>([]);
  const [status, setStatus] = useState<"loading" | "auth-required" | "ok">(
    "loading",
  );

  const setRole = (newRole: string | null) => {
    setRoleState(newRole);
    if (newRole) {
      localStorage.setItem("qwenpaw_user_role", newRole);
    } else {
      localStorage.removeItem("qwenpaw_user_role");
    }
  };

  const logout = () => {
    clearAuthToken();
    setUsername(null);
    setRole(null);
    setScenes([]);
    setStatus("auth-required");
  };

  const checkAuth = async () => {
    setStatus("loading");
    try {
      const res = await authApi.getStatus();
      if (!res.enabled) {
        setUsername(null);
        setRole("admin");
        setScenes([]);
        setStatus("ok");
        return;
      }
      const token = getApiToken();
      if (!token) {
        setUsername(null);
        setRole(null);
        setScenes([]);
        setStatus("auth-required");
        return;
      }
      try {
        const r = await fetch(getApiUrl("/auth/verify"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (r.ok) {
          const data = await r.json();
          setUsername(
            typeof data.username === "string" && data.username
              ? data.username
              : null,
          );
          if (data.role) {
            setRole(data.role);
          }
          setScenes(Array.isArray(data.scenes) ? data.scenes : []);
          setStatus("ok");
        } else {
          logout();
        }
      } catch {
        logout();
      }
    } catch {
      clearAuthToken();
      setUsername(null);
      setRole(null);
      setScenes([]);
      setStatus("auth-required");
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  return (
    <AuthContext.Provider
      value={{ username, role, scenes, status, setRole, logout, checkAuth }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
