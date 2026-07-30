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

// <StatusBadge> map for User.role (design doc §1.2: admin → indigo,
// manager → sky, staff → gray). Same {value: {label, color}} shape as
// CLIENT_STATUS so both feed the same component.
export const USER_ROLE = {
  [ROLES.ADMIN]: { label: ROLE_LABELS[ROLES.ADMIN], color: "indigo" },
  [ROLES.MANAGER]: { label: ROLE_LABELS[ROLES.MANAGER], color: "sky" },
  [ROLES.STAFF]: { label: ROLE_LABELS[ROLES.STAFF], color: "gray" },
};

// Role options for the user form and the role filter. Order is least → most
// privilege, so the safest choice sits at the top of the list.
export const ROLE_OPTIONS = [ROLES.STAFF, ROLES.MANAGER, ROLES.ADMIN].map((value) => ({
  value,
  label: ROLE_LABELS[value],
}));

// is_active as a badge. Not a status enum on the model — a boolean — so the
// keys are the strings the filter/select use ("true"/"false").
export const USER_ACTIVE_STATUS = {
  true: { label: "Active", color: "green" },
  false: { label: "Deactivated", color: "gray" },
};

export const USER_ACTIVE_OPTIONS = [
  { value: "true", label: "Active" },
  { value: "false", label: "Deactivated" },
];

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

// ---------------------------------------------------------------------------
// Projects app (projects.models — Project, Task, Sprint, ProjectMembership).
// Same { value: {label, color} } shape as CLIENT_STATUS so everything feeds
// <StatusBadge>, and the label always rides along with the colour.
// ---------------------------------------------------------------------------

// Mirrors Project.Status. Colour follows the design doc's semantic scale:
// neutral for "not started", sky for "running", amber for "stalled",
// green for "shipped", red for "stopped".
export const PROJECT_STATUS = {
  planned: { label: "Planned", color: "gray" },
  in_progress: { label: "In progress", color: "sky" },
  on_hold: { label: "On hold", color: "amber" },
  completed: { label: "Completed", color: "green" },
  cancelled: { label: "Cancelled", color: "red" },
};

// Mirrors Task.Status. `todo → done` here IS the kanban column order —
// Object.keys order is the board's left-to-right, so the board never needs
// its own list that could drift from this one.
export const TASK_STATUS = {
  todo: { label: "To do", color: "gray" },
  in_progress: { label: "In progress", color: "sky" },
  review: { label: "Review", color: "indigo" },
  done: { label: "Done", color: "green" },
};

// Project.Priority and Task.Priority are the same four values on the backend,
// so one map serves both — a single place to restyle "urgent".
export const PRIORITY = {
  low: { label: "Low", color: "gray" },
  medium: { label: "Medium", color: "sky" },
  high: { label: "High", color: "amber" },
  urgent: { label: "Urgent", color: "red" },
};

// Mirrors Sprint.Status. The lifecycle is start/complete actions server-side,
// never a PATCH — this map is read-only decoration.
export const SPRINT_STATUS = {
  planned: { label: "Planned", color: "gray" },
  active: { label: "Active", color: "sky" },
  completed: { label: "Completed", color: "green" },
};

// Mirrors ProjectMembership.Role — a per-project role, NOT the account-wide
// ROLES above. Someone can be project manager here and a staff user globally.
export const MEMBER_ROLE = {
  manager: { label: "Manager", color: "indigo" },
  developer: { label: "Developer", color: "gray" },
};

// Every map above as <Select> options, in declaration order.
const toOptions = (map) => Object.entries(map).map(([value, { label }]) => ({ value, label }));

export const PROJECT_STATUS_OPTIONS = toOptions(PROJECT_STATUS);
export const TASK_STATUS_OPTIONS = toOptions(TASK_STATUS);
export const PRIORITY_OPTIONS = toOptions(PRIORITY);
export const MEMBER_ROLE_OPTIONS = toOptions(MEMBER_ROLE);

// The kanban's columns, left to right. Derived from TASK_STATUS so adding a
// status to the enum adds a column — the two can never disagree.
export const TASK_STATUS_ORDER = Object.keys(TASK_STATUS);

// Country ↔ dial-code pairs for the client form: the Country select's
// options AND the source of the phone prefix auto-selection. Curated to the
// markets the business actually deals with — extend as new ones appear
// (the backend stores country as free text, so adding a row here is enough).
export const PHONE_COUNTRIES = [
  { name: "India", code: "+91" },
  { name: "United Arab Emirates", code: "+971" },
  { name: "Saudi Arabia", code: "+966" },
  { name: "Qatar", code: "+974" },
  { name: "Oman", code: "+968" },
  { name: "Kuwait", code: "+965" },
  { name: "Bahrain", code: "+973" },
  { name: "Singapore", code: "+65" },
  { name: "Malaysia", code: "+60" },
  { name: "Sri Lanka", code: "+94" },
  { name: "Bangladesh", code: "+880" },
  { name: "Nepal", code: "+977" },
  { name: "United States", code: "+1" },
  { name: "Canada", code: "+1" },
  { name: "United Kingdom", code: "+44" },
  { name: "Australia", code: "+61" },
  { name: "Germany", code: "+49" },
  { name: "France", code: "+33" },
  { name: "Japan", code: "+81" },
  { name: "China", code: "+86" },
];

export const COUNTRY_OPTIONS = PHONE_COUNTRIES.map(({ name }) => ({ value: name, label: name }));

// Unique codes only (US and Canada share +1); label is the bare code so the
// narrow prefix select stays compact — the Country field carries the context.
export const PHONE_PREFIX_OPTIONS = [...new Set(PHONE_COUNTRIES.map(({ code }) => code))].map(
  (code) => ({ value: code, label: code })
);

// Lowercased country name → dial code, for syncing the prefix when the
// Country field changes.
export const COUNTRY_DIAL_CODE = Object.fromEntries(
  PHONE_COUNTRIES.map(({ name, code }) => [name.toLowerCase(), code])
);
