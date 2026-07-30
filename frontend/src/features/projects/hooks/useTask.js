import { useQuery } from "@tanstack/react-query";

import { getTask } from "../../../api/endpoints/projects";

// Detail query for the task modal. Only the detail shape carries the
// dependency graph (blocked_by / blocks) and the description — list rows
// deliberately omit both.
export function useTask(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["tasks", id],
    queryFn: () => getTask(id),
    enabled: enabled && id != null,
    retry: (failureCount, error) => error?.response?.status !== 404 && failureCount < 1,
  });
}
