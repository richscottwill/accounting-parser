import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { performSignup } from "../api/auth";
import { useAuth } from "../auth/AuthContext";

/**
 * Firm signup: creates a new Tenant + Firm + admin user in one flow and
 * enrolls the admin's first passkey via navigator.credentials.create.
 */
export function SignupPage(): JSX.Element {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [firmName, setFirmName] = useState("");
  const [email, setEmail] = useState("");
  const [ptin, setPtin] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setStatus("submitting");
    setError(null);
    try {
      const me = await performSignup({
        firm_name: firmName,
        admin_email: email,
        admin_ptin: ptin.trim() ? ptin.trim() : null,
      });
      setUser(me);
      navigate("/dashboard", { replace: true });
    } catch (e: unknown) {
      const msg = extractErrorMessage(e);
      setError(msg);
      setStatus("error");
    }
  }

  return (
    <main className="page page-signup" data-testid="signup-page">
      <h1>Sign up your firm</h1>
      <p className="lede">
        Multi-tenant accounting document parser for solo CPA practices.
        Signup creates your firm, provisions encrypted storage keys, and
        enrolls your first passkey — no passwords.
      </p>
      <form onSubmit={handleSubmit}>
        <label>
          Firm name
          <input
            name="firm_name"
            value={firmName}
            onChange={(e) => setFirmName(e.target.value)}
            required
            minLength={2}
            data-testid="signup-firm-name"
          />
        </label>
        <label>
          Admin email
          <input
            name="admin_email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            data-testid="signup-email"
          />
        </label>
        <label>
          PTIN (optional)
          <input
            name="admin_ptin"
            pattern="P\d{8}"
            placeholder="P12345678"
            value={ptin}
            onChange={(e) => setPtin(e.target.value)}
            data-testid="signup-ptin"
          />
        </label>
        <button
          type="submit"
          disabled={status === "submitting"}
          data-testid="signup-submit"
        >
          {status === "submitting" ? "Enrolling passkey…" : "Create firm"}
        </button>
      </form>
      {error && (
        <p className="error" data-testid="signup-error">
          {error}
        </p>
      )}
    </main>
  );
}

function extractErrorMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "response" in e) {
    // AxiosError
    const resp = (e as { response?: { data?: { detail?: { message?: string } } } })
      .response;
    if (resp?.data?.detail?.message) return resp.data.detail.message;
  }
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}
