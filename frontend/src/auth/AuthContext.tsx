/**
 * AuthContext — the single source of truth for the currently-signed-in
 * principal in the SPA.
 *
 * Wraps React Context with the three operations the rest of the app
 * needs: login, logout, and "refresh current user from the session
 * token". On app boot we read the persisted token from localStorage
 * and hit /auth/me to hydrate the user state. If the token is invalid
 * /auth/me 401s and we treat the session as logged out.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { setSessionToken, restoreSessionToken, ApiError } from "../api/client";
import { getCurrentUser, logout as apiLogout } from "../api/endpoints";
import type { MeResponse } from "../api/types";

interface AuthState {
  user: MeResponse | null;
  loading: boolean;
  login: (token: string) => Promise<MeResponse>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!restoreSessionToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await getCurrentUser();
      setUser(me);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setSessionToken(null);
        setUser(null);
      } else {
        throw e;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(
    async (token: string) => {
      setSessionToken(token);
      const me = await getCurrentUser();
      setUser(me);
      return me;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Revocation is best-effort server-side; clearing the token
      // client-side is what actually ends the session for this SPA.
    }
    setSessionToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be called inside AuthProvider");
  }
  return ctx;
}
