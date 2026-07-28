import { api } from "../client";

// One file per backend app (ARCHITECTURE §3). Thin functions only — no
// caching, no state: that's TanStack Query's job in the feature hooks.

// GET /clients/?search&status&industry&page&ordering
// → { count, next, previous, results } (DRF pagination envelope)
export async function getClients(params) {
  const { data } = await api.get("/clients/", { params });
  return data;
}

// GET /clients/{id}/ → full detail incl. embedded account_manager + contacts
export async function getClient(id) {
  const { data } = await api.get(`/clients/${id}/`);
  return data;
}

// Writes answer with the FULL detail shape (the backend re-serializes after
// saving), so callers can prime the detail cache straight from the response.
export async function createClient(payload) {
  const { data } = await api.post("/clients/", payload);
  return data;
}

export async function updateClient(id, payload) {
  const { data } = await api.patch(`/clients/${id}/`, payload);
  return data;
}

// Soft delete server-side: the row survives for audit, the API hides it.
export async function deleteClient(id) {
  await api.delete(`/clients/${id}/`);
}

// Contacts follow the §6 nesting rule: CREATE under the client (the parent
// comes from the URL, not the body), update/delete on the flat resource.
export async function createContact(clientId, payload) {
  const { data } = await api.post(`/clients/${clientId}/contacts/`, payload);
  return data;
}

export async function updateContact(contactId, payload) {
  const { data } = await api.patch(`/contacts/${contactId}/`, payload);
  return data;
}

export async function deleteContact(contactId) {
  await api.delete(`/contacts/${contactId}/`);
}
