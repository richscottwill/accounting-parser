import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * Login — token-based entry point for P1.5.
 *
 * WebAuthn passkey ceremony lands in P2 (needs the browser's
 * navigator.credentials API wired to the /auth/login/{begin,complete}
 * endpoints). At P1.5 we accept a session token directly for
 * Playwright validation: the test mints a token against the memory
 * adapter and pastes it in. Real users never see this form on a
 * production deployment — it's behind a VITE_DEV_LOGIN flag.
 *
 * Structural decision: the login UI still lives at /login so the
 * P2 WebAuthn ceremony drops into the same route when it replaces
 * this form. Keeps bookmarks, docs, tests stable.
 */
export function Login() {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(token.trim());
      navigate("/");
    } catch {
      setError("Invalid session token.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <h1>Sign in</h1>
      <p className="muted">
        Passkey login lands in a subsequent release. For development
        validation, paste a session token minted by the backend.
      </p>
      <form onSubmit={handleSubmit} aria-label="login form">
        <label>
          Session token
          <input
            type="text"
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
            data-testid="session-token"
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting} data-testid="login-submit">
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
