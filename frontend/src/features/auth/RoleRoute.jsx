import { Outlet, useNavigate } from "react-router-dom";

import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAuth } from "./useAuth";

// Layout-route guard for whole sections that belong to specific roles
// (design doc §7.11's 403 state). Nests INSIDE ProtectedRoute, which has
// already settled the session — so reaching here with no user means the role
// simply doesn't qualify, not "not logged in yet".
//
// This is UX, not security: the API re-checks every request (IsAdmin & co.).
// Its job is to explain the wall instead of rendering a page that 403s.
export function RoleRoute({ roles }) {
  const { user } = useAuth();
  const navigate = useNavigate();

  if (!user || !roles.includes(user.role)) {
    return (
      <EmptyState
        icon="🔒"
        title="You don't have access to this page"
        message="Ask an administrator if you think you should."
        action={
          <Button variant="secondary" onClick={() => navigate("/")}>
            Go to dashboard
          </Button>
        }
      />
    );
  }

  return <Outlet />;
}
