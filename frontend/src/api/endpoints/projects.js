import { api } from "../client";

// One file per backend app (ARCHITECTURE §3). Tasks, sprints, milestones and
// time entries all live in the Django `projects` app, so they live here too —
// there is no separate tasks app to mirror.
//
// The §6 nesting rule shows up all over this file: CREATE happens under the
// parent (the parent comes from the URL, never the body), every other write
// goes to the flat resource.

// ---------------------------------------------------------------- projects

// GET /projects/?search&status&priority&client&member&technology&page&ordering
// → { count, next, previous, results }
export async function getProjects(params) {
  const { data } = await api.get("/projects/", { params });
  return data;
}

// GET /projects/{id}/ → detail incl. embedded client, members, milestones,
// technologies and progress. `budget` is absent for STAFF — the server strips
// it, so the UI must treat "missing" as normal, not as an error.
export async function getProject(id) {
  const { data } = await api.get(`/projects/${id}/`);
  return data;
}

// Writes answer with the FULL detail shape, so callers can prime the detail
// cache straight from the response (same contract as clients).
export async function createProject(payload) {
  const { data } = await api.post("/projects/", payload);
  return data;
}

export async function updateProject(id, payload) {
  const { data } = await api.patch(`/projects/${id}/`, payload);
  return data;
}

// Soft delete server-side: the row survives for audit, the API hides it.
export async function deleteProject(id) {
  await api.delete(`/projects/${id}/`);
}

// ------------------------------------------------------------- memberships

// POST /projects/{id}/members/ — {user_id, role}. Answers with the membership
// row, not the project, so the caller invalidates rather than primes.
export async function addProjectMember(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/members/`, payload);
  return data;
}

// Role is the only mutable field on a membership.
export async function updateProjectMember(membershipId, payload) {
  const { data } = await api.patch(`/project-memberships/${membershipId}/`, payload);
  return data;
}

// 400s (not 403) when removing the last manager — the message is meant to be
// shown to the user.
export async function removeProjectMember(membershipId) {
  await api.delete(`/project-memberships/${membershipId}/`);
}

// -------------------------------------------------------------- milestones

// GET /milestones/?project&is_completed&due_before&due_after
export async function getMilestones(params) {
  const { data } = await api.get("/milestones/", { params });
  return data;
}

export async function createMilestone(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/milestones/`, payload);
  return data;
}

export async function updateMilestone(milestoneId, payload) {
  const { data } = await api.patch(`/milestones/${milestoneId}/`, payload);
  return data;
}

export async function deleteMilestone(milestoneId) {
  await api.delete(`/milestones/${milestoneId}/`);
}

// ----------------------------------------------------------------- sprints

// GET /sprints/?project&status
export async function getSprints(params) {
  const { data } = await api.get("/sprints/", { params });
  return data;
}

export async function createSprint(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/sprints/`, payload);
  return data;
}

export async function updateSprint(sprintId, payload) {
  const { data } = await api.patch(`/sprints/${sprintId}/`, payload);
  return data;
}

// PLANNED sprints only — active/completed ones are velocity history and 400.
export async function deleteSprint(sprintId) {
  await api.delete(`/sprints/${sprintId}/`);
}

// The lifecycle is a state machine, not a PATCH: these two POSTs are the only
// way status moves, because completion also freezes the velocity snapshot.
export async function startSprint(sprintId) {
  const { data } = await api.post(`/sprints/${sprintId}/start/`);
  return data;
}

export async function completeSprint(sprintId) {
  const { data } = await api.post(`/sprints/${sprintId}/complete/`);
  return data;
}

// GET /sprints/{id}/burndown/ → {days: [{date, ideal, remaining}], …}
// `remaining` is null for days still in the future, so the actual line stops
// at today while the ideal line runs the full timebox.
export async function getSprintBurndown(sprintId) {
  const { data } = await api.get(`/sprints/${sprintId}/burndown/`);
  return data;
}

// GET /projects/{id}/velocity/ → {velocity, sprints: [...]}
export async function getProjectVelocity(projectId) {
  const { data } = await api.get(`/projects/${projectId}/velocity/`);
  return data;
}

// ------------------------------------------------------------------- tasks

// GET /tasks/?project&sprint&backlog&status&priority&assignee&unassigned
//           &due_before&due_after&search&page&ordering
// The board reads this flat list one column at a time; "my tasks" filters by
// assignee. Rows carry logged_hours / open_blockers / is_overdue computed
// server-side — never recompute them here.
export async function getTasks(params) {
  const { data } = await api.get("/tasks/", { params });
  return data;
}

export async function getTask(id) {
  const { data } = await api.get(`/tasks/${id}/`);
  return data;
}

// Create is nested (§6): the project comes from the URL. There is no flat
// POST /tasks/ — it 405s.
export async function createTask(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/tasks/`, payload);
  return data;
}

// PATCH is role-shaped server-side: managers/admins may send any field,
// STAFF may send ONLY {status} and only on their own tasks (403 otherwise).
export async function updateTask(id, payload) {
  const { data } = await api.patch(`/tasks/${id}/`, payload);
  return data;
}

export async function deleteTask(id) {
  await api.delete(`/tasks/${id}/`);
}

// -------------------------------------------------------------- time entries

// GET /tasks/{id}/time-entries/ — staff see only their own rows.
export async function getTaskTimeEntries(taskId, params) {
  const { data } = await api.get(`/tasks/${taskId}/time-entries/`, { params });
  return data;
}

// POST — {hours, worked_on, description?}. The row is ALWAYS logged against
// the current user; there is no user_id to send.
export async function logTime(taskId, payload) {
  const { data } = await api.post(`/tasks/${taskId}/time-entries/`, payload);
  return data;
}

// GET /time-entries/?project&task&user&worked_from&worked_to — the timesheet.
export async function getTimeEntries(params) {
  const { data } = await api.get("/time-entries/", { params });
  return data;
}

export async function updateTimeEntry(id, payload) {
  const { data } = await api.patch(`/time-entries/${id}/`, payload);
  return data;
}

export async function deleteTimeEntry(id) {
  await api.delete(`/time-entries/${id}/`);
}

// ------------------------------------------------------------ technologies

// GET /technologies/?search → the tag picker. Unpaginated in practice but the
// API still answers with the DRF envelope, so callers read `.results`.
export async function getTechnologies(params) {
  const { data } = await api.get("/technologies/", { params });
  return data;
}

export async function createTechnology(payload) {
  const { data } = await api.post("/technologies/", payload);
  return data;
}
