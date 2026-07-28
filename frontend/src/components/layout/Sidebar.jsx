import { NavLink } from "react-router-dom";

import { RoleGate } from "../../features/auth/RoleGate";
import { ROLES } from "../../lib/constants";

// Live routes use NavLink; not-yet-built modules render as muted placeholders
// so the sidebar shows the product's shape without dead links.
const linkClasses = ({ isActive }) =>
  `block rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "bg-indigo-700 text-white" : "text-indigo-100 hover:bg-indigo-700/60"
  }`;

function ComingSoon({ label }) {
  return (
    <span className="flex items-center justify-between rounded-md px-3 py-2 text-sm text-indigo-300/70">
      {label}
      <span className="rounded-full bg-indigo-800 px-2 py-0.5 text-[10px] uppercase">soon</span>
    </span>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col bg-indigo-900 md:flex">
      <div className="flex h-16 items-center px-4 text-lg font-bold text-white">
        Client<span className="text-indigo-300">Hub</span>
      </div>

      <nav className="flex-1 space-y-1 px-2 py-2" aria-label="Main">
        <NavLink to="/" end className={linkClasses}>
          Dashboard
        </NavLink>

        <NavLink to="/clients" className={linkClasses}>
          Clients
        </NavLink>

        <ComingSoon label="Projects" />
        <ComingSoon label="Tasks" />
        <ComingSoon label="Tickets" />
        <ComingSoon label="Quotations" />

        {/* Staff never see billing — matches the API, which omits it for them */}
        <RoleGate roles={[ROLES.ADMIN, ROLES.MANAGER]}>
          <ComingSoon label="Billing" />
        </RoleGate>
        <RoleGate roles={[ROLES.ADMIN]}>
          <ComingSoon label="Users" />
        </RoleGate>
      </nav>
    </aside>
  );
}
