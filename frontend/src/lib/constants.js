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
