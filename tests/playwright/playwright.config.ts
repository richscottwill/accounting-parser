import { defineConfig, devices } from "@playwright/test";

/**
 * Task 5 "[Validate] Playwright" uses a virtual authenticator (CDP's
 * WebAuthn domain) so the SPA's passkey ceremonies complete without a
 * physical device. Tests assume the dev stack is up:
 *
 *   1. docker compose up -d                    # postgres + redis + localstack
 *   2. cd backend && poetry run uvicorn ...    # API on :8000
 *   3. cd frontend && pnpm dev                 # SPA on :3000 proxying /api → :8000
 *
 * The webServer config below can boot 2 + 3 automatically when running
 * `pnpm test` locally; for now we assume they're already running in CI.
 */
export default defineConfig({
  testDir: ".",
  fullyParallel: false, // WebAuthn virtual authenticators are per-context; keep deterministic.
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
