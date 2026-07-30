import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  completeSprint,
  createSprint,
  deleteSprint,
  startSprint,
  updateSprint,
} from "../../../api/endpoints/projects";
import { useToast } from "../../../components/ui/useToast";

function serverMessage(error, fallback) {
  const data = error?.response?.data;
  if (!data || typeof data !== "object") return fallback;
  const first = data.detail ?? Object.values(data)[0];
  if (!first) return fallback;
  return Array.isArray(first) ? first[0] : String(first);
}

// Sprint writes. The lifecycle deliberately does NOT go through `update`:
// start/complete are POST ceremonies because completing a sprint also freezes
// its velocity snapshot and returns unfinished tasks to the backlog.
export function useSprintMutations(projectId) {
  const queryClient = useQueryClient();
  const toast = useToast();

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["sprints"] });
    // Completion moves unfinished tasks back to the backlog, so every task
    // view can be stale after a ceremony.
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
  }

  const create = useMutation({
    mutationFn: (payload) => createSprint(projectId, payload),
    onSuccess: (sprint) => {
      refresh();
      toast.success(`Sprint "${sprint.name}" created.`);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateSprint(id, payload),
    onSuccess: () => {
      refresh();
      toast.success("Sprint updated.");
    },
  });

  const start = useMutation({
    mutationFn: startSprint,
    onSuccess: (sprint) => {
      refresh();
      toast.success(`"${sprint.name}" started.`);
    },
    onError: (error) => toast.error(serverMessage(error, "Could not start the sprint.")),
  });

  const complete = useMutation({
    mutationFn: completeSprint,
    onSuccess: (sprint) => {
      refresh();
      toast.success(
        `"${sprint.name}" completed — ${sprint.completed_points}/${sprint.total_points} points done.`
      );
    },
    onError: (error) => toast.error(serverMessage(error, "Could not complete the sprint.")),
  });

  const remove = useMutation({
    mutationFn: deleteSprint,
    onSuccess: () => {
      refresh();
      toast.success("Sprint deleted.");
    },
    // Active/completed sprints refuse deletion with an explanation worth showing.
    onError: (error) => toast.error(serverMessage(error, "Could not delete the sprint.")),
  });

  return { create, update, start, complete, remove };
}
