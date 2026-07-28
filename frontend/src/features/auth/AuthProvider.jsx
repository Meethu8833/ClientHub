import { useCallback, useEffect, useMemo, useState } from "react";

import { refreshAccessToken, setOnSessionExpired } from "../../api/client";
import * as authApi from "../../api/endpoints/auth";
import { setAccessToken } from "../../api/tokenStore";
import { AuthContext } from "./AuthContext";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // true until the boot refresh settles — ProtectedRoute must not redirect
  // to /login while we still don't know whether the session is alive.
  const [isBooting, setIsBooting] = useState(true);

  useEffect(() => {
    // If a refresh ever fails mid-session, the interceptor clears the token
    // and calls this — dropping `user` sends ProtectedRoute to /login.
    setOnSessionExpired(() => setUser(null));

    // Silent session restore (ARCHITECTURE §7): the access token lives only
    // in JS memory, so F5 wipes it. If the HttpOnly refresh cookie is still
    // valid this brings the session back without showing the login screen.
    let cancelled = false;
    async function boot() {
      try {
        await refreshAccessToken();
        const me = await authApi.fetchMe();
        if (!cancelled) setUser(me);
      } catch {
        // No/expired cookie — the user is simply logged out. Not an error.
      } finally {
        if (!cancelled) setIsBooting(false);
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const { access, user: me } = await authApi.login(email, password);
    setAccessToken(access);
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Even if the server call fails, finish logging out locally.
    }
    setAccessToken(null);
    setUser(null);
  }, []);

  // useMemo keeps the context value referentially stable, so consumers only
  // re-render when user/isBooting actually change — not on every render here.
  const value = useMemo(
    () => ({ user, isBooting, login, logout }),
    [user, isBooting, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
