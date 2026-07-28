import { api } from "../client";

// GET /users/assignable/ → [{id, name, email, role}]
// The one users endpoint managers can hit — the option list for user pickers
// (client account manager now, task assignee later). Unpaginated by design.
export async function getAssignableUsers() {
  const { data } = await api.get("/users/assignable/");
  return data;
}
