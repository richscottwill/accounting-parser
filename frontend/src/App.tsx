import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Dashboard } from "./routes/Dashboard";
import { Engagement } from "./routes/Engagement";
import { EngagementLookup } from "./routes/EngagementLookup";
import { Login } from "./routes/Login";
import { Signup } from "./routes/Signup";
import { WorkflowDetail } from "./routes/WorkflowDetail";

/**
 * App — SPA shell.
 *
 * Routing decisions:
 * - /signup + /login are public. Everything else requires auth.
 * - RequireAuth wraps protected routes and redirects to /login on
 *   missing / invalid session; keeps per-route boilerplate out.
 * - While AuthProvider is hydrating the current user (fetch /auth/
 *   me on boot), we render a loading state instead of flashing the
 *   signup page.
 */
export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/signup" element={<Signup />} />
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Dashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/engagement/lookup"
          element={
            <RequireAuth>
              <EngagementLookup />
            </RequireAuth>
          }
        />
        <Route
          path="/engagement/:engagementId"
          element={
            <RequireAuth>
              <Engagement />
            </RequireAuth>
          }
        />
        <Route
          path="/workflow/:runId"
          element={
            <RequireAuth>
              <WorkflowDetail />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <main aria-busy="true">Loading...</main>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
