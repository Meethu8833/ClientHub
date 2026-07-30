import { useQuery } from "@tanstack/react-query";

import { getTaskTimeEntries } from "../../../api/endpoints/projects";

// A task's logged hours (the Time tab of the task modal). STAFF get only
// their own rows back — that filtering is server-side, so the same call is
// correct for every role.
export function useTaskTimeEntries(taskId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["tasks", taskId, "time-entries"],
    queryFn: () => getTaskTimeEntries(taskId),
    enabled: enabled && taskId != null,
  });
}
