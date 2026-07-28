import { api } from "../client";

export async function getSummary() {
  const { data } = await api.get("/dashboard/summary/");
  // { clients, projects, tasks, tickets, quotations, billing?, as_of }
  // `billing` is ABSENT (not zeroed) for staff — the backend never sends
  // numbers a role couldn't reach through the underlying list endpoints.
  return data;
}
