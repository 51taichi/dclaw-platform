import { createContext, useContext, useState, useEffect } from "react";
import { authApi } from "../api/modules/auth";
import { getApiToken, getApiUrl, clearAuthToken } from "../api/config";

interface AuthContextType {
  role: string | null;
  status: "loading" | "auth-required" | "ok";
  setRole: (role: string | null) => void;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  role: null,
  status: "loading",
  setRole: () => {},
  logout: () => {},
  checkAuth: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [role, setRoleState] = useState<string | null>(() => localStorage.getItem("qwenpaw_user_role"));
  const [status, setStatus] = useState<"loading" | "auth-required" | "ok">("loading");

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
    setRole(null);
    setStatus("auth-required");
  };

  const checkAuth = async () => {
    setStatus("loading");
    try {
      const res = await authApi.getStatus();
      if (!res.enabled) {
        setRole("admin");
        setStatus("ok");
        return;
      }
      const token = getApiToken();
      if (!token) {
        setStatus("auth-required");
        return;
      }
      try {
        const r = await fetch(getApiUrl("/auth/verify"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (r.ok) {
          const data = await r.json();
          if (data.role) {
            setRole(data.role);
          }
          setStatus("ok");
        } else {
          logout();
        }
      } catch {
        logout();
      }
    } catch {
      clearAuthToken();
      setRole(null);
      setStatus("auth-required");
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  return (
    <AuthContext.Provider value={{ role, status, setRole, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
