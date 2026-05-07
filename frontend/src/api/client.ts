/**
 * Thin Axios client for the accounting-parser API.
 *
 * All calls go through Vite's `/api/*` proxy in dev; in prod the same prefix
 * is mapped by the ingress. A bearer-token interceptor reads the session JWT
 * from localStorage and attaches it to every request; a 401 response clears
 * the stored token and notifies subscribers (via the `onUnauthorized` hook).
 */
import axios, { AxiosInstance } from "axios";

const SESSION_TOKEN_KEY = "accounting_parser_session_token";

let unauthorizedCallback: (() => void) | null = null;

export function onUnauthorized(cb: () => void): void {
  unauthorizedCallback = cb;
}

export function setSessionToken(token: string | null): void {
  if (token) {
    localStorage.setItem(SESSION_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(SESSION_TOKEN_KEY);
  }
}

export function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_TOKEN_KEY);
}

export function createClient(): AxiosInstance {
  const instance = axios.create({
    baseURL: "/api",
    timeout: 30_000,
  });

  instance.interceptors.request.use((config) => {
    const token = getSessionToken();
    if (token) {
      config.headers = config.headers ?? {};
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  });

  instance.interceptors.response.use(
    (r) => r,
    (error) => {
      if (error.response?.status === 401) {
        setSessionToken(null);
        unauthorizedCallback?.();
      }
      return Promise.reject(error);
    }
  );

  return instance;
}

export const api = createClient();
