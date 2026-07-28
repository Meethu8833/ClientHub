import axios from "axios";

import { getAccessToken, setAccessToken } from "./tokenStore";

// In dev "/api/v1" hits the Vite proxy (vite.config.js) → Django :8000.
// In prod Nginx serves the same path — the bundle needs no code change.
const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export const api = axios.create({
  baseURL,
  // Send/receive cookies — required for the HttpOnly refresh cookie.
  withCredentials: true,
});

// ---------------------------------------------------------------------------
// Request interceptor: attach the access token to every outgoing request.
// ---------------------------------------------------------------------------
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ---------------------------------------------------------------------------
// Refresh machinery.
// All concurrent 401s share ONE in-flight refresh call — otherwise each would
// rotate the cookie and blacklist the others' token (refresh rotation is on).
// ---------------------------------------------------------------------------
let refreshPromise = null;

export function refreshAccessToken() {
  refreshPromise ??= api
    .post("/auth/refresh/") // empty body — the browser attaches the cookie
    .then((res) => {
      setAccessToken(res.data.access);
      return res.data.access;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

// AuthProvider registers a handler so a dead session clears React state
// (which makes ProtectedRoute redirect to /login) instead of a hard reload.
let onSessionExpired = null;

export function setOnSessionExpired(handler) {
  onSessionExpired = handler;
}

// Endpoints where a 401 is a real answer, not "access token expired":
// retrying them through refresh would loop or mask the actual error.
const NO_REFRESH_URLS = ["/auth/login/", "/auth/refresh/", "/auth/logout/"];

// ---------------------------------------------------------------------------
// Response interceptor: on 401 → refresh once → replay the failed request.
// If the refresh itself fails, the session is over.
// ---------------------------------------------------------------------------
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const skip = NO_REFRESH_URLS.some((url) => config?.url?.includes(url));

    if (response?.status !== 401 || config?._retry || skip) {
      throw error;
    }

    try {
      await refreshAccessToken();
    } catch {
      setAccessToken(null);
      onSessionExpired?.();
      throw error;
    }

    config._retry = true; // one replay max — never an infinite loop
    return api(config);
  }
);
