import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";

/**
 * Root router.
 *
 * Unauthenticated users land on /signup; authenticated users land on /dashboard.
 * An explicit /login route exists for returning users — signup already covers
 * first-time firm bootstrap.
 */
export function App(): JSX.Element {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <main className="page page-loading" data-testid="app-loading">
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <Routes>
      <Route
        path="/signup"
        element={user ? <Navigate to="/dashboard" replace /> : <SignupPage />}
      />
      <Route
        path="/login"
        element={user ? <Navigate to="/dashboard" replace /> : <LoginPage />}
      />
      <Route
        path="/dashboard"
        element={user ? <DashboardPage /> : <Navigate to="/signup" replace />}
      />
      <Route
        path="*"
        element={<Navigate to={user ? "/dashboard" : "/signup"} replace />}
      />
    </Routes>
  );
}
