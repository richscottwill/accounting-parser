/**
 * SPA smoke tests.
 *
 * These run against jsdom with a mocked fetch. Real end-to-end
 * validation runs via Playwright against the live backend (wired in
 * P1.6 / P2). The tests here catch the "did I break the router or
 * the auth gate" class of regression fast.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { setSessionToken } from "./api/client";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  setSessionToken(null);
  // Default: every /auth/me call 401s (not logged in).
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/auth/me")) {
      return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("not found", { status: 404 });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  setSessionToken(null);
});

describe("App router", () => {
  it("shows signup page on /signup without auth", async () => {
    render(
      <MemoryRouter initialEntries={["/signup"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("heading", { name: /create your firm/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("firm-name")).toBeInTheDocument();
  });

  it("shows login page on /login without auth", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("heading", { name: /sign in/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("session-token")).toBeInTheDocument();
  });

  it("redirects unauth'd access to /login", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /sign in/i }),
      ).toBeInTheDocument(),
    );
  });

  it("renders dashboard for authenticated user", async () => {
    setSessionToken("fake-token");
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/me")) {
        return new Response(
          JSON.stringify({
            user_id: "u1",
            tenant_id: "t1",
            firm_id: "f1",
            email: "admin@firm.test",
            role: "firm_administrator",
            session_expires_at: "2030-01-01T00:00:00Z",
          }),
          {
            status: 200,
            headers: { "content-type": "application/json" },
          },
        );
      }
      return new Response("not found", { status: 404 });
    }) as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      await screen.findByTestId("current-user-email"),
    ).toHaveTextContent("admin@firm.test");
    expect(screen.getByText(/firm_administrator/i)).toBeInTheDocument();
  });
});
