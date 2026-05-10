/**
 * Backend API client.
 *
 * One HTTP client shared by every feature module. Handles:
 * - Base URL resolution (VITE_API_BASE_URL env var, defaults to
 *   same-origin for production where Caddy proxies /api to the app).
 * - Bearer token injection from the auth store.
 * - JSON request/response shaping.
 * - Generic error type mapped from the backend's HTTPException
 *   payloads so feature code doesn't repeat try/catch plumbing.
 *
 * Not a heavy framework — wraps fetch directly. If we need retries or
 * backoff we add them here, not in callers.
 */

const BASE_URL =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? "";

let sessionToken: string | null = null;

export function setSessionToken(token: string | null): void {
  sessionToken = token;
  if (token) {
    localStorage.setItem("session_token", token);
  } else {
    localStorage.removeItem("session_token");
  }
}

export function restoreSessionToken(): string | null {
  if (sessionToken !== null) return sessionToken;
  sessionToken = localStorage.getItem("session_token");
  return sessionToken;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API error ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  formData?: FormData;
  auth?: boolean;
}

export async function apiFetch<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = restoreSessionToken();
  if (opts.auth !== false && token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const response = await fetch(`${BASE_URL}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body,
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, detail);
  }
  // 204 or empty bodies.
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}
