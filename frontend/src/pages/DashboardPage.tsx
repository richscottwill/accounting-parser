import { useAuth } from "../auth/AuthContext";

/**
 * Minimal firm dashboard — proves the session works end-to-end. Real panels
 * (Clients, Engagements, Documents, Workflow, Audit) arrive with Tasks 6+.
 */
export function DashboardPage(): JSX.Element {
  const { user, logout } = useAuth();

  if (!user) {
    // Router guard already enforces this; belt-and-suspenders so tests don't flake.
    return <p>Not signed in.</p>;
  }

  return (
    <main className="page page-dashboard" data-testid="dashboard-page">
      <header className="dashboard-header">
        <h1>accounting-parser</h1>
        <div className="user-menu" data-testid="user-menu">
          <span data-testid="user-email">{user.email}</span>
          <span className="role-chip" data-testid="user-role">
            {user.role}
          </span>
          <button type="button" onClick={logout} data-testid="logout-button">
            Log out
          </button>
        </div>
      </header>
      <section>
        <h2>Welcome to your firm dashboard</h2>
        <dl className="identity-block">
          <dt>Tenant ID</dt>
          <dd data-testid="tenant-id">{user.tenant_id}</dd>
          <dt>Firm ID</dt>
          <dd data-testid="firm-id">{user.firm_id ?? "—"}</dd>
          <dt>User ID</dt>
          <dd data-testid="user-id">{user.user_id}</dd>
        </dl>
        <p className="empty-hint">
          Next: create a client, kick off an engagement, upload documents.
          Those panels arrive in the next tasks.
        </p>
      </section>
    </main>
  );
}
