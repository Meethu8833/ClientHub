import { useNavigate } from "react-router-dom";

import { useAuth } from "../../features/auth/useAuth";
import { ThemeToggle } from "../../features/theme/ThemeToggle";
import { ROLE_LABELS } from "../../lib/constants";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

const ROLE_COLORS = { admin: "red", manager: "indigo", staff: "gray" };

export function Topbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const displayName = [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email;

  return (
    <header
      className="flex h-16 items-center justify-between border-b border-gray-200 bg-white
        px-4 sm:px-6 dark:border-gray-800 dark:bg-gray-900"
    >
      {/* Brand shows here on small screens where the sidebar is hidden */}
      <div className="font-bold text-indigo-900 md:hidden dark:text-indigo-200">
        Client<span className="text-indigo-400">Hub</span>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span className="hidden text-sm font-medium text-gray-700 sm:block dark:text-gray-200">
          {displayName}
        </span>
        <Badge color={ROLE_COLORS[user.role] ?? "gray"}>
          {ROLE_LABELS[user.role] ?? user.role}
        </Badge>
        <ThemeToggle />
        <Button variant="secondary" onClick={handleLogout}>
          Log out
        </Button>
      </div>
    </header>
  );
}
