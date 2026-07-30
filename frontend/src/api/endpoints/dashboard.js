import { api } from "../client";

export async function getSummary() {
  const { data } = await api.get("/dashboard/summary/");
  // { clients, projects, tasks, tickets, quotations, billing?, as_of }
  // `billing` is ABSENT (not zeroed) for staff — the backend never sends
  // numbers a role couldn't reach through the underlying list endpoints.
  return data;
}

export async function getCharts() {
  const { data } = await api.get("/dashboard/charts/");
  // { project_status, tickets_by_month, revenue_by_month?, invoice_aging?, as_of }
  // Same rule as the summary: `revenue_by_month` and `invoice_aging` are
  // omitted for staff rather than zeroed, so the UI renders whichever blocks
  // arrive instead of role-checking client-side.
  return data;
}
