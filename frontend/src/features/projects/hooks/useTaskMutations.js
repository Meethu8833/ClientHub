import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createTask, deleteTask, logTime, updateTask } from "../../../api/endpoints/projects";
import { useToast } from "../../../components/ui/useToast";

// Pulls the readable half out of a DRF 400. The task API refuses moves with
// messages the user can act on ("Blocked by unfinished task(s): …", "You may
// only change the status of your tasks") — swallowing those behind a generic
// failure toast would leave people stuck with no idea why the card sprang back.
function serverMessage(error, fallback) {
  const data = error?.response?.data;
  if (!data || typeof data !== "object") return fallback;
  const first = data.detail ?? data.status ?? Object.values(data)[0];
  if (!first) return fallback;
  return Array.isArray(first) ? first[0] : String(first);
}

// All task writes. `projectId` is only needed for create (the parent comes
// from the URL, §6) — the cross-project task page passes it per-call instead.
export function useTaskMutations(projectId) {
  const queryClient = useQueryClient();
  const toast = useToast();

  // Tasks show up in three places: the flat lists, the board's per-status
  // columns, and the project detail. All of them are ['tasks'] or ['projects']
  // prefixed, so two invalidations cover every view.
  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    queryClient.invalidateQueries({ queryKey: ["projects"] });
  }

  const create = useMutation({
    mutationFn: ({ project, ...payload }) => createTask(project ?? projectId, payload),
    onSuccess: (task) => {
      queryClient.setQueryData(["tasks", String(task.id)], task);
      refresh();
      toast.success(`Task "${task.title}" created.`);
    },
    // No error toast — the form maps 400s onto its fields.
  });

  const update = useMutation({
    mutationFn: ({ id, ...payload }) => updateTask(id, payload),
    onSuccess: (task) => {
      queryClient.setQueryData(["tasks", String(task.id)], task);
      refresh();
      toast.success("Task updated.");
    },
  });

  // Status-only change: the board's drag-drop and the card menu.
  //
  // Deliberately NOT optimistic. A move can be legitimately refused — the
  // dependency gate keeps a blocked task in To do, and staff may only move
  // their own cards — so an optimistic card would jump to the new column and
  // then snap back, which reads as a glitch rather than as a rule. Waiting for
  // the server means the card moves once, and only when it really moved.
  const move = useMutation({
    mutationFn: ({ id, status }) => updateTask(id, { status }),
    onSuccess: (task) => {
      queryClient.setQueryData(["tasks", String(task.id)], task);
      refresh();
    },
    onError: (error) => toast.error(serverMessage(error, "Could not move this task.")),
  });

  const remove = useMutation({
    mutationFn: deleteTask,
    onSuccess: () => {
      refresh();
      toast.success("Task deleted.");
    },
    onError: (error) => toast.error(serverMessage(error, "Could not delete the task.")),
  });

  const log = useMutation({
    mutationFn: ({ taskId, ...payload }) => logTime(taskId, payload),
    onSuccess: (entry) => {
      // The task's own time list plus every row showing logged_hours.
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast.success(`Logged ${entry.hours} h.`);
    },
  });

  return { create, update, move, remove, log };
}
