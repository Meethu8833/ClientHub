import { useQuery } from "@tanstack/react-query";

import { getProject } from "../../../api/endpoints/projects";

// Detail query, key ['projects', id] (ARCHITECTURE §10: keys mirror API paths).
//
// `enabled` exists because the cross-project task list loads a project's
// detail only when the edit modal opens — the pickers on the task form need
// that project's members and milestones.
export function useProject(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["projects", id],
    queryFn: () => getProject(id),
    enabled: enabled && id != null,
    // For STAFF, a project they are not a member of 404s (§8 scoping never
    // leaks existence) — that is a final answer, not a blip. Retrying only
    // delays the "not found" screen.
    retry: (failureCount, error) => error?.response?.status !== 404 && failureCount < 1,
  });
}
