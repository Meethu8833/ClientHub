import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Spinner } from "../../components/ui/Spinner";
import { useAuth } from "./useAuth";

// Layout-route guard: wraps every authenticated route once in App.jsx.
// <Outlet /> renders whatever child route matched.
export function ProtectedRoute() {
  const { user, isBooting } = useAuth();
  const location = useLocation();

  // Don't decide while the silent refresh is in flight — redirecting now
  // would bounce a logged-in user to /login on every F5.
  if (isBooting) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <Spinner size="lg" className="text-indigo-600" />
      </div>
    );
  }

  if (!user) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
