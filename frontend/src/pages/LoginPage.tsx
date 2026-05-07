import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { performLogin } from "../api/auth";
import { useAuth } from "../auth/AuthContext";

/**
 * Returning-user login. Single input (email) + passkey assertion.
 *
 * WebAuthn is phishing-resistant by design, so a username-only form is the
 * expected shape — the browser finds the passkey scoped to the RP ID and
 * prompts the user through the authenticator's UI.
 */
export function LoginPage(): JSX.Element {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setStatus("submitting");
    setError(null);
    try {
      const me = await performLogin(email);
      setUser(me);
      navigate("/dashboard", { replace: true });
    } catch (e: unknown) {
      setError(extractErrorMessage(e));
      setStatus("error");
    }
  }

  return (
    <main className="page page-login" data-testid="login-page">
      <h1>Log in</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            data-testid="login-email"
          />
        </label>
        <button
          type="submit"
          disabled={status === "submitting"}
          data-testid="login-submit"
        >
          {status === "submitting" ? "Verifying passkey…" : "Continue with passkey"}
        </button>
      </form>
      {error && (
        <p className="error" data-testid="login-error">
          {error}
        </p>
      )}
      <p>
        New firm? <Link to="/signup">Create an account</Link>.
      </p>
    </main>
  );
}

function extractErrorMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "response" in e) {
    const resp = (e as { response?: { data?: { detail?: { message?: string } } } })
      .response;
    if (resp?.data?.detail?.message) return resp.data.detail.message;
  }
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}
