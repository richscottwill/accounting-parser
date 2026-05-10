import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { signup } from "../api/endpoints";

/**
 * Signup — Firm_Administrator bootstrap (R25.1).
 *
 * Single-firm install: second signup attempt returns 409, rendered
 * here as a friendly "already provisioned" state with a link to
 * /login. No passkey enrollment UI at P1.5 — that lands in P2
 * alongside the WebAuthn ceremony wiring. For now the signup
 * produces the tenant/firm/user rows and hands off to /login.
 */
export function Signup() {
  const [firmName, setFirmName] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [alreadyProvisioned, setAlreadyProvisioned] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signup({
        firm_name: firmName,
        principal_email: email,
        principal_display_name: name,
      });
      navigate("/login");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setAlreadyProvisioned(true);
        } else {
          setError(
            typeof err.detail === "string" ? err.detail : "Signup failed.",
          );
        }
      } else {
        setError("Unexpected error. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (alreadyProvisioned) {
    return (
      <main className="signup">
        <h1>Firm already provisioned</h1>
        <p>
          This installation already has a firm registered. Self-hosted
          accounting-parser supports exactly one firm per installation.
        </p>
        <p>
          If you are the firm administrator, <Link to="/login">log in</Link>{" "}
          with your existing passkey.
        </p>
      </main>
    );
  }

  return (
    <main className="signup">
      <h1>Create your firm</h1>
      <p className="muted">
        First-time setup. Creates the Firm_Administrator account for this
        installation.
      </p>
      <form onSubmit={handleSubmit} aria-label="signup form">
        <label>
          Firm name
          <input
            type="text"
            required
            value={firmName}
            onChange={(e) => setFirmName(e.target.value)}
            data-testid="firm-name"
          />
        </label>
        <label>
          Your email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-testid="principal-email"
          />
        </label>
        <label>
          Your display name
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="display-name"
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting} data-testid="signup-submit">
          {submitting ? "Creating firm..." : "Create firm"}
        </button>
      </form>
    </main>
  );
}
