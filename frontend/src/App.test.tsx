/**
 * Component-level tests. End-to-end auth validation is Playwright's job
 * (see tests/playwright/task-5-auth.spec.ts) because WebAuthn ceremonies
 * require a real browser + virtual authenticator.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";

// Mock the auth API module so tests don't need a live backend.
vi.mock("./api/auth", () => ({
  fetchMe: vi.fn().mockRejectedValue(new Error("no session")),
  performSignup: vi.fn(),
  performLogin: vi.fn(),
  logout: vi.fn(),
}));

afterEach(() => {
  localStorage.clear();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("App routing (unauthenticated)", () => {
  it("shows the signup page at /signup", async () => {
    renderAt("/signup");
    await waitFor(() => {
      expect(screen.getByTestId("signup-page")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", { name: /sign up your firm/i })
    ).toBeInTheDocument();
  });

  it("shows the login page at /login", async () => {
    renderAt("/login");
    await waitFor(() => {
      expect(screen.getByTestId("login-page")).toBeInTheDocument();
    });
  });

  it("redirects / to /signup when no session", async () => {
    renderAt("/");
    await waitFor(() => {
      expect(screen.getByTestId("signup-page")).toBeInTheDocument();
    });
  });

  it("redirects /dashboard to /signup when no session", async () => {
    renderAt("/dashboard");
    await waitFor(() => {
      expect(screen.getByTestId("signup-page")).toBeInTheDocument();
    });
  });
});
