// Mirrors accounts.User.Role (TextChoices) on the backend — stored values
// are lowercase strings. Single source of truth for role checks in the UI.
export const ROLES = {
  ADMIN: "admin",
  MANAGER: "manager",
  STAFF: "staff",
};

export const ROLE_LABELS = {
  [ROLES.ADMIN]: "Admin",
  [ROLES.MANAGER]: "Manager",
  [ROLES.STAFF]: "Staff",
};

// Mirrors clients.Client.Status. Shape is { value: {label, color} } for
// <StatusBadge> (design doc §1.2: prospect → amber, active → green,
// inactive → gray). The label always accompanies the color — color is
// never the only signal.
export const CLIENT_STATUS = {
  prospect: { label: "Prospect", color: "amber" },
  active: { label: "Active", color: "green" },
  inactive: { label: "Inactive", color: "gray" },
};

// The same enum as <Select> options (for filters and the form).
export const CLIENT_STATUS_OPTIONS = Object.entries(CLIENT_STATUS).map(([value, { label }]) => ({
  value,
  label,
}));
