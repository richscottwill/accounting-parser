import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * Dashboard — the authenticated landing page.
 *
 * P1.5 scope: show who's signed in + a clear entry point to the
 * engagement view. Rich dashboard widgets (metering, recent
 * workflows, outstanding PBCs) land in Phase 2 once the
 * supporting data exists.
 */
export function Dashboard() {
  const { user, logout } = useAuth();
  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <h1>accounting-parser</h1>
        <div className="user-menu">
          <span data-testid="current-user-email">{user?.email}</span>
          <span className="muted"> ({user?.role})</span>
          <button
            onClick={() => void logout()}
            data-testid="logout-button"
          >
            Sign out
          </button>
        </div>
      </header>
      <section>
        <h2>Quick actions</h2>
        <p>
          Open an engagement to upload documents and run workflows. The
          engagement list UI ships later; for now you can navigate
          directly to an engagement you know the id of.
        </p>
        <nav aria-label="quick navigation">
          <ul>
            <li>
              <Link to="/engagement/lookup">Open engagement by id</Link>
            </li>
          </ul>
        </nav>
      </section>
    </main>
  );
}
