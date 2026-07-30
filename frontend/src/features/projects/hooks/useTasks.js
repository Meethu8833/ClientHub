import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getTasks } from "../../../api/endpoints/projects";

// Task list query — the cross-project table AND each kanban column use it.
// The key embeds the params, so a column (['tasks', {project, status}]) is its
// own cache entry and only that column refetches when a card lands in it.
export function useTasks(params, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["tasks", params],
    queryFn: () => getTasks(params),
    enabled,
    placeholderData: keepPreviousData,
  });
}
