import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    // One-shot migration: if a legacy localStorage token is around, hand it to
    // the server which will mint cookies for us, then drop it from storage.
    try {
      const legacy = localStorage.getItem("af_token");
      if (legacy) {
        try {
          await api.post(
            "/auth/migrate-token",
            {},
            { headers: { Authorization: `Bearer ${legacy}` } },
          );
        } catch {
          /* ignore — token may have expired; we'll fall through to /me */
        } finally {
          localStorage.removeItem("af_token");
        }
      }
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const login = async (email, password) => {
    // Server sets HttpOnly auth cookie + csrf cookie. We only need the user.
    const { data } = await api.post("/auth/login", { email, password });
    setUser(data.user);
    return data.user;
  };

  const register = async (email, name, password) => {
    const { data } = await api.post("/auth/register", { email, name, password });
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch { /* ignore — clear local state regardless */ }
    setUser(null);
    try { localStorage.removeItem("af_token"); } catch { /* ignore */ }
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
