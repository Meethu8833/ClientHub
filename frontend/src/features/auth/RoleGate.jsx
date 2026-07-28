import { useAuth } from "./useAuth";

// Hides UI from roles that can't use it. This is UX only — never security:
// the backend enforces every permission again on each request (ARCHITECTURE §8).
export function RoleGate({ roles, children, fallback = null }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return fallback;
  return children;
}
