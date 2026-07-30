import { useQuery } from "@tanstack/react-query";

import { getSprints } from "../../../api/endpoints/projects";

// A project's sprints, newest first (the API's default ordering).
// Used by the sprint picker on the task form and the project's Sprints tab.
export function useSprints(projectId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["sprints", { project: projectId }],
    queryFn: () => getSprints({ project: projectId, page_size: 100 }),
    enabled: enabled && projectId != null,
    select: (data) => data.results ?? data,
  });
}
