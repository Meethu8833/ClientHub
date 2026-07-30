import { api } from "../client";

// GET /users/assignable/ → [{id, name, email, role}]
// The one users endpoint managers can hit — the option list for user pickers
// (client account manager now, task assignee later). Unpaginated by design.
export async function getAssignableUsers() {
  const { data } = await api.get("/users/assignable/");
  return data;
}

// ---------------------------------------------------------------------------
// Admin user management (/users/ — every call below is IsAdmin server-side).
// ---------------------------------------------------------------------------

// GET /users/?search&role&is_active&page&ordering
// → { count, next, previous, results } (DRF pagination envelope)
export async function getUsers(params) {
  const { data } = await api.get("/users/", { params });
  return data;
}

export async function getUser(id) {
  const { data } = await api.get(`/users/${id}/`);
  return data;
}

// POST /users/ — {email, first_name, last_name, role, password?}.
// Omitting `password` is meaningful: the account gets an unusable password
// and the server emails an invite link instead (docs/user-management.md).
// Answers with the full detail shape, like every other write here.
export async function createUser(payload) {
  const { data } = await api.post("/users/", payload);
  return data;
}

// PATCH only — the API 405s on PUT. Names + weekly capacity; role and
// active state have their own endpoints below.
export async function updateUser(id, payload) {
  const { data } = await api.patch(`/users/${id}/`, payload);
  return data;
}

// Reversible block: keeps the row visible in lists, revokes refresh tokens.
export async function deactivateUser(id) {
  const { data } = await api.post(`/users/${id}/deactivate/`);
  return data;
}

export async function activateUser(id) {
  const { data } = await api.post(`/users/${id}/activate/`);
  return data;
}

// Role changes are a deliberate, guarded action of their own — never a PATCH.
export async function assignUserRole(id, role) {
  const { data } = await api.post(`/users/${id}/assign-role/`, { role });
  return data;
}
