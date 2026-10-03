import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { apiRequest } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // Deliberately React state, not localStorage/sessionStorage: the spec
  // asks for the JWT to live only in memory, so a page refresh logs the
  // user out. Persistent sessions / refresh tokens are a later concern.
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);

  const register = useCallback(async (email, username, password) => {
    await apiRequest("/auth/register", { method: "POST", json: { email, username, password } });
  }, []);

  const _finishLogin = useCallback(async (accessToken) => {
    setToken(accessToken);
    const me = await apiRequest("/auth/me", { token: accessToken });
    setUser(me);
  }, []);

  /**
   * Returns { requiresTwoFactor: true, pendingToken } if the account has
   * 2FA enabled (nothing is logged in yet -- call verifyTwoFactor next), or
   * { requiresTwoFactor: false } once actually logged in.
   */
  const login = useCallback(
    async (email, password) => {
      const data = await apiRequest("/auth/login", { method: "POST", json: { email, password } });
      if (data.requires_2fa) {
        return { requiresTwoFactor: true, pendingToken: data.pending_token };
      }
      await _finishLogin(data.access_token);
      return { requiresTwoFactor: false };
    },
    [_finishLogin]
  );

  const verifyTwoFactor = useCallback(
    async (pendingToken, code) => {
      const { access_token } = await apiRequest("/auth/2fa/verify", {
        method: "POST",
        json: { pending_token: pendingToken, code },
      });
      await _finishLogin(access_token);
    },
    [_finishLogin]
  );

  const refreshUser = useCallback(async () => {
    setUser(await apiRequest("/auth/me", { token }));
  }, [token]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ token, user, register, login, verifyTwoFactor, refreshUser, logout }),
    [token, user, register, login, verifyTwoFactor, refreshUser, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
